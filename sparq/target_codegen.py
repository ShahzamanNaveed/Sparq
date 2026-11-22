"""Lower complete verified typed TAC to immutable three-register VM instructions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sparq.errors import LexicalError, SemanticError
from sparq.ir import (
    ArrayRef, Binary, BoolMergeTemp, BranchBool, Call, CheckBounds,
    CheckedElement, Compare, Constant, Convert, HaltStart, IRProgram,
    InitArray, InitElement, InitScalar, Jump, Label, Load, LoadElement,
    Move, ParameterRef, ReadElement, ReadScalar, Return, Show, StoreElement,
    Temporary, Unary, VariableRef, instruction_operands,
)
from sparq.ir_verify import verify_program
from sparq.lexer import Lexer
from sparq.optimization import optimize_program
from sparq.parser import ParseError, Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.tac import generate_tac
from sparq.target import (
    FrameSlot, Op, Register as R, SlotKind, TargetInstruction,
    TargetProgram, TargetRoutine, format_target,
)


class CodeGenerationError(ValueError):
    """No partial target program is published after a translation failure."""


def _category(value):
    if isinstance(value, ParameterRef):
        return SlotKind.PARAMETER
    if isinstance(value, VariableRef):
        return SlotKind.VARIABLE
    if isinstance(value, ArrayRef):
        return SlotKind.ARRAY
    if isinstance(value, Temporary):
        return SlotKind.TEMP
    if isinstance(value, BoolMergeTemp):
        return SlotKind.MERGE
    if isinstance(value, CheckedElement):
        return SlotKind.GUARD
    raise CodeGenerationError("unsupported compiler operand category")


def _frame_slot(value):
    kind = _category(value)
    symbol = value.symbol if kind in (SlotKind.PARAMETER, SlotKind.VARIABLE, SlotKind.ARRAY) else None
    return FrameSlot(value.owner, kind, symbol.id if symbol else value.number,
                     None if kind is SlotKind.GUARD else value.type if kind is not SlotKind.ARRAY
                     else value.element_type, symbol)


def _inventory(routine):
    slots = {}
    def add(value):
        if not isinstance(value, (ParameterRef, VariableRef, ArrayRef,
                                  Temporary, BoolMergeTemp, CheckedElement)):
            return
        slot = _frame_slot(value)
        key = (slot.kind, slot.number)
        previous = slots.setdefault(key, slot)
        if previous.type is not slot.type or previous.symbol is not slot.symbol:
            raise CodeGenerationError("conflicting target frame slot metadata")
        if isinstance(value, CheckedElement) and isinstance(value.index, Temporary):
            add(value.index)
    for value in routine.local_symbols:
        add(value)
    for instruction in routine.instructions:
        for value in instruction_operands(instruction):
            add(value)
    ordered = tuple(slots[key] for key in sorted(slots, key=lambda key: (key[0].value, key[1])))
    return ordered, slots


def _lower_routine(routine):
    inventory, slots = _inventory(routine)
    owner = routine.owner
    output = []

    def slot(value):
        return slots[(_category(value), value.symbol.id if hasattr(value, "symbol") else value.number)]

    def emit(opcode, span, *operands):
        output.append(TargetInstruction(owner, opcode, operands, span))

    def value(operand, register, span):
        if isinstance(operand, Constant):
            emit(Op.CONST, span, register, operand)
        else:
            emit(Op.LOAD, span, register, slot(operand))

    for item in routine.instructions:
        span = item.span
        if isinstance(item, InitScalar):
            value(item.value, R.R0, span)
            emit(Op.INIT_SCALAR, span, slot(item.target), R.R0)
        elif isinstance(item, Move):
            value(item.value, R.R0, span)
            emit(Op.STORE, span, slot(item.target), R.R0)
        elif isinstance(item, Load):
            value(item.source, R.R0, span)
            emit(Op.STORE, span, slot(item.result), R.R0)
        elif isinstance(item, Unary):
            value(item.operand, R.R0, span)
            emit(Op.UNARY, span, R.R1, item.operator, R.R0, item.result.type)
            emit(Op.STORE, span, slot(item.result), R.R1)
        elif isinstance(item, Binary):
            value(item.left, R.R0, span)
            value(item.right, R.R1, span)
            emit(Op.BINARY, span, R.R2, item.operator, R.R0, R.R1, item.result.type)
            emit(Op.STORE, span, slot(item.result), R.R2)
        elif isinstance(item, Compare):
            value(item.left, R.R0, span)
            value(item.right, R.R1, span)
            emit(Op.COMPARE, span, R.R2, item.operator, R.R0, R.R1, item.left.type)
            emit(Op.STORE, span, slot(item.result), R.R2)
        elif isinstance(item, Convert):
            value(item.operand, R.R0, span)
            emit(Op.TO_FLOAT, span, R.R1, R.R0)
            emit(Op.STORE, span, slot(item.result), R.R1)
        elif isinstance(item, InitArray):
            emit(Op.ALLOC_ARRAY, span, slot(item.target), item.length, item.default)
        elif isinstance(item, InitElement):
            value(item.value, R.R0, span)
            emit(Op.INIT_ELEMENT, span, slot(item.array), item.index, R.R0)
        elif isinstance(item, CheckBounds):
            value(item.index, R.R0, span)
            emit(Op.CHECK_BOUNDS, span, slot(item.result), slot(item.array), R.R0)
        elif isinstance(item, LoadElement):
            emit(Op.LOAD_ELEMENT, span, R.R0, slot(item.checked))
            emit(Op.STORE, span, slot(item.result), R.R0)
        elif isinstance(item, StoreElement):
            value(item.value, R.R0, span)
            emit(Op.STORE_ELEMENT, span, slot(item.checked), R.R0)
        elif isinstance(item, Label):
            emit(Op.LABEL, span, item.target)
        elif isinstance(item, Jump):
            emit(Op.JUMP, span, item.target)
        elif isinstance(item, BranchBool):
            value(item.condition, R.R0, span)
            emit(Op.BRANCH_BOOL, span, R.R0, item.true_target, item.false_target)
        elif isinstance(item, Call):
            for argument in item.arguments:
                value(argument, R.R0, span)
                emit(Op.PUSH_ARG, span, R.R0, argument.type)
            emit(Op.CALL, span, item.function, len(item.arguments))
            if item.result is not None:
                emit(Op.STORE, span, slot(item.result), R.R0)
        elif isinstance(item, Return):
            if item.value is None:
                emit(Op.RETURN_VOID, span)
            else:
                value(item.value, R.R0, span)
                emit(Op.RETURN, span, R.R0)
        elif isinstance(item, ReadScalar):
            emit(Op.READ_SCALAR, span, slot(item.target))
        elif isinstance(item, ReadElement):
            emit(Op.READ_ELEMENT, span, slot(item.checked))
        elif isinstance(item, Show):
            value(item.value, R.R0, span)
            emit(Op.SHOW, span, R.R0)
        elif isinstance(item, HaltStart):
            emit(Op.HALT, span)
        else:
            raise CodeGenerationError("unsupported canonical IR instruction")
    parameters = tuple(slot(parameter) for parameter in routine.parameters)
    return TargetRoutine(owner, inventory, parameters, tuple(output))


def generate_target(ir_program: IRProgram) -> TargetProgram:
    """Translate one verified IRProgram without executing or mutating it."""
    try:
        verify_program(ir_program)
        functions = tuple(_lower_routine(item.body) for item in ir_program.functions)
        entry = _lower_routine(ir_program.entry)
        return TargetProgram(ir_program, functions, entry)
    except (TypeError, ValueError, KeyError, RecursionError) as exc:
        raise CodeGenerationError("cannot generate a complete target program") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile Sparq source to target VM listing")
    parser.add_argument("source", help=".spq source file")
    parser.add_argument("--optimize", action="store_true", help="translate optimized verified TAC")
    parser.add_argument("--target-optimize", action="store_true",
                        help="apply machine-dependent target optimization")
    parser.add_argument("--compare-target", action="store_true",
                        help="show ordinary, target-optimized, and combined target listings")
    args = parser.parse_args(argv)
    if args.compare_target and (args.optimize or args.target_optimize):
        parser.error("--compare-target already includes both optimization paths")
    try:
        source = Path(args.source).read_text(encoding="utf-8")
        program = Parser(Lexer(source).tokenize()).parse()
        analysis = SemanticAnalyzer(program).analyze()
        ir = generate_tac(program, analysis)
        if args.compare_target:
            from sparq.target_optimization import optimize_target_with_report
            ordinary = generate_target(ir)
            machine, machine_report = optimize_target_with_report(ordinary)
            combined_ir = optimize_program(ir, analysis)
            combined, combined_report = optimize_target_with_report(generate_target(combined_ir))
            for title, target, report in (
                ("A: ordinary target", ordinary, machine_report.stages[0]),
                ("B: machine-dependent target", machine, machine_report.stages[-1]),
                ("C: optimized TAC and machine-dependent target", combined,
                 combined_report.stages[-1]),
            ):
                print(f"{title} | instructions={report.instructions} "
                      f"estimated_cost={report.estimated_cost}")
                print(format_target(target))
            return 0
        if args.optimize:
            ir = optimize_program(ir, analysis)
        target = generate_target(ir)
        if args.target_optimize:
            from sparq.target_optimization import optimize_target
            target = optimize_target(target)
        print(format_target(target))
        return 0
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError,
            LexicalError, ParseError, SemanticError) as exc:
        print(f"target compilation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
