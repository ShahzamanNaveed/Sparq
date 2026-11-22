"""Source-backed structural checks for the first finite-register target layer."""

from dataclasses import FrozenInstanceError, replace

import pytest

from sparq.ir import FunctionRef, IRProgram, LabelRef
from sparq.lexer import Lexer
from sparq.optimization import optimize_program
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.tac import generate_tac
from sparq.target import (
    FrameSlot, Op, Register, SlotKind, TargetInstruction, TargetProgram,
    TargetRoutine, format_target, instruction_cost,
)
from sparq.target_codegen import CodeGenerationError, generate_target, main


def compile_target(source, *, optimized=False):
    program = Parser(Lexer(source).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    ir = generate_tac(program, analysis)
    if optimized:
        ir = optimize_program(ir, analysis)
    return ir, generate_target(ir)


def ops(routine):
    return [item.opcode for item in routine.instructions]


def test_hello_and_immutable_deterministic_records():
    source = 'START { SHOW("Hello from Sparq!"); }'
    ir, target = compile_target(source)
    assert target.source_ir is ir
    assert ops(target.entry) == [Op.CONST, Op.SHOW, Op.HALT]
    assert all(item.owner is ir.entry.owner and item.span is not None
               for item in target.entry.instructions)
    assert format_target(target) == format_target(compile_target(source)[1])
    with pytest.raises(FrozenInstanceError):
        target.entry.instructions[0].opcode = Op.HALT
    with pytest.raises(FrozenInstanceError):
        target.entry.slots = ()
    with pytest.raises(TypeError):
        target.entry.instructions[0].operands[0] = Register.R2


def test_all_scalar_operations_conversions_and_branch_destinations():
    source = (
        "START { INT x = 7; FLOAT f = x + 2.0; BOOL b = TRUE; "
        "BOOL c = b AND x < 9; "
        "WHEN (c) { x = -x; SHOW(f); } OTHERWISE { SHOW(x % 2); } "
        "WHILE (FALSE) { x = x + 1; } }"
    )
    _, target = compile_target(source)
    found = set(ops(target.entry))
    assert {Op.CONST, Op.LOAD, Op.STORE, Op.INIT_SCALAR, Op.UNARY, Op.BINARY,
            Op.COMPARE, Op.TO_FLOAT, Op.BRANCH_BOOL, Op.JUMP, Op.LABEL,
            Op.SHOW, Op.HALT} <= found
    labels = {item.operands[0] for item in target.entry.instructions if item.opcode is Op.LABEL}
    for item in target.entry.instructions:
        if item.opcode is Op.JUMP:
            assert item.operands[0] in labels
        elif item.opcode is Op.BRANCH_BOOL:
            assert set(item.operands[1:]) <= labels
    assert {slot.kind for slot in target.entry.slots} >= {
        SlotKind.VARIABLE, SlotKind.TEMP, SlotKind.MERGE
    }
    assert {value for item in target.entry.instructions for value in item.operands
            if isinstance(value, Register)} <= set(Register)


def test_arrays_guard_order_and_io():
    source = (
        "START { INT a[2] = {1, 2}; INT i = 0; "
        "a[i] = a[1] + 1; READ(a[0]); READ(i); SHOW(a[i]); }"
    )
    _, target = compile_target(source)
    sequence = ops(target.entry)
    assert {Op.ALLOC_ARRAY, Op.INIT_ELEMENT, Op.CHECK_BOUNDS,
            Op.LOAD_ELEMENT, Op.STORE_ELEMENT, Op.READ_ELEMENT,
            Op.READ_SCALAR, Op.SHOW} <= set(sequence)
    assert sequence.index(Op.ALLOC_ARRAY) < sequence.index(Op.INIT_ELEMENT)
    assert sequence.index(Op.CHECK_BOUNDS) < sequence.index(Op.STORE_ELEMENT)
    assert sequence.index(Op.CHECK_BOUNDS) < sequence.index(Op.READ_ELEMENT)
    assert SlotKind.ARRAY in {slot.kind for slot in target.entry.slots}
    assert SlotKind.GUARD in {slot.kind for slot in target.entry.slots}


def test_calls_parameter_identity_recursion_and_return():
    source = (
        "FUNC fib(INT n) -> INT { WHEN (n < 2) { RETURN n; } "
        "OTHERWISE { RETURN fib(n - 1) + fib(n - 2); } } "
        "FUNC echo(FLOAT v) -> FLOAT { RETURN v; } "
        "FUNC quiet() -> VOID { RETURN; } "
        "START { SHOW(echo(fib(3))); quiet(); }"
    )
    ir, target = compile_target(source)
    assert len(target.functions) == 3
    assert [routine.owner for routine in target.functions] == [
        item.body.owner for item in ir.functions
    ]
    for routine, function in zip(target.functions, ir.functions):
        assert all(slot.symbol is parameter.symbol
                   for slot, parameter in zip(routine.parameters, function.parameters))
    recursive = [item for item in target.functions[0].instructions if item.opcode is Op.CALL]
    assert len(recursive) == 2
    assert all(item.operands[0].symbol is ir.semantic_owner.signatures[0]
               for item in recursive)
    assert Op.RETURN in ops(target.functions[0])
    assert Op.RETURN_VOID in ops(target.functions[2])
    assert ops(target.entry)[-1] is Op.HALT
    assert len([item for item in target.entry.instructions if item.opcode is Op.CALL]) == 3


@pytest.mark.parametrize("source", [
    "START { CHAR c = 'a'; STRING s = \"z\"; BOOL b = FALSE; SHOW(c); SHOW(s); SHOW(b); }",
    "START { INT x = 1; SELECT (x) { CASE -1: { SHOW(1); } "
    "CASE 1: { SHOW(2); } DEFAULT: { SHOW(3); } } }",
    "START { INT x = 0; DO { x = x + 1; } WHILE (x < 2); "
    "REPEAT (INT i = 0; i < 2; i = i + 1) { SHOW(i); } }",
    "FUNC f(INT x) -> INT { RETURN x; } START { INT a[1]; "
    "a[0] = f(2); SHOW(a[0]); }",
])
def test_additional_complete_source_forms(source):
    ir, target = compile_target(source)
    assert len(target.functions) == len(ir.functions)
    assert all(routine.instructions for routine in (*target.functions, target.entry))
    assert target.entry.instructions[-1].opcode is Op.HALT


def test_every_canonical_ir_family_is_exercised():
    sources = [
        "START { INT x = 1; FLOAT f = x + 1.0; BOOL b = TRUE; "
        "BOOL c = b AND x < 3; WHEN (c) { x = -x; } "
        "OTHERWISE { SHOW(x % 2); } }",
        "START { INT a[2] = {1, 2}; INT i = 0; a[i] = a[1]; "
        "READ(a[0]); READ(i); SHOW(a[i]); }",
        "FUNC f(INT x) -> INT { RETURN x; } "
        "FUNC g() -> VOID { RETURN; } START { SHOW(f(1)); g(); }",
    ]
    encountered = set()
    for source in sources:
        ir, _ = compile_target(source)
        encountered.update(type(item).__name__ for routine in (
            *(function.body for function in ir.functions), ir.entry
        ) for item in routine.instructions)
    assert encountered == {
        "InitScalar", "Move", "Load", "Unary", "Binary", "Compare", "Convert",
        "InitArray", "InitElement", "CheckBounds", "LoadElement", "StoreElement",
        "Label", "Jump", "BranchBool", "Call", "Return", "ReadScalar",
        "ReadElement", "Show", "HaltStart",
    }


def test_optimized_and_unoptimized_programs_and_cost():
    source = "START { INT x = 2 + 3 * 4; SHOW(x); }"
    original_ir, original = compile_target(source)
    optimized_ir, optimized = compile_target(source, optimized=True)
    assert isinstance(original_ir, IRProgram) and isinstance(optimized_ir, IRProgram)
    assert Op.BINARY in ops(original.entry)
    assert Op.HALT in ops(optimized.entry)
    assert Op.BINARY not in ops(optimized.entry)
    assert all(instruction_cost(item) >= 0 for item in original.entry.instructions)
    assert sum(map(instruction_cost, optimized.entry.instructions)) < sum(
        map(instruction_cost, original.entry.instructions)
    )


def test_large_integer_display_preserves_complete_payload():
    digits = "9" * 5000
    ir, target = compile_target(f"START {{ SHOW({digits}); }}")
    constant = target.entry.instructions[0].operands[1]
    assert constant.value == int(digits[:2500]) * 10**2500 + int(digits[2500:])
    rendered = format_target(target)
    assert len(rendered) < 2000
    assert "CONST R0" in rendered
    assert target.source_ir is ir


def test_invalid_input_and_target_record_construction():
    ir, target = compile_target("START { SHOW(1); }")
    with pytest.raises(CodeGenerationError):
        generate_target(None)
    item = target.entry.instructions[0]
    with pytest.raises(ValueError):
        replace(item, operands=(Register.R0,))
    with pytest.raises(ValueError):
        replace(item, opcode=Op.STORE, operands=(
            FrameSlot(ir.entry.owner, SlotKind.GUARD, 1, None), Register.R0
        ))


def test_target_cli_success_optimized_and_controlled_failure(tmp_path, capsys):
    good = tmp_path / "good.spq"
    good.write_text("START { SHOW(2 + 3); }", encoding="utf-8")
    assert main([str(good)]) == 0
    assert "BINARY" in capsys.readouterr().out
    assert main([str(good), "--optimize"]) == 0
    assert "BINARY" not in capsys.readouterr().out
    bad = tmp_path / "bad.spq"
    bad.write_text("START { SHOW(@); }", encoding="utf-8")
    assert main([str(bad)]) == 1
    assert "target compilation failed" in capsys.readouterr().err


def test_indexed_assignment_guard_precedes_call_and_read_guard_precedes_input():
    source = (
        "FUNC f() -> INT { RETURN 2; } "
        "START { INT a[1]; a[0] = f(); READ(a[0]); }"
    )
    _, target = compile_target(source)
    start = ops(target.entry)
    assert start.index(Op.CHECK_BOUNDS) < start.index(Op.CALL)
    assert start.index(Op.CALL) < start.index(Op.STORE_ELEMENT)
    assert max(i for i, op in enumerate(start) if op is Op.CHECK_BOUNDS) < start.index(
        Op.READ_ELEMENT
    )


def test_direct_records_reject_bad_branch_and_argument_types():
    _, target = compile_target("FUNC f(INT x) -> INT { RETURN x; } START { SHOW(f(1)); }")
    routine = target.entry
    call_index = next(i for i, item in enumerate(routine.instructions)
                      if item.opcode is Op.CALL)
    push_index = next(i for i, item in enumerate(routine.instructions)
                      if item.opcode is Op.PUSH_ARG)
    changed = list(routine.instructions)
    from sparq.symbols import ScalarType
    changed[push_index] = replace(changed[push_index], operands=(Register.R0, ScalarType.FLOAT))
    with pytest.raises(ValueError, match="argument types"):
        replace(routine, instructions=tuple(changed))
    assert call_index > push_index
    bad_jump = TargetInstruction(routine.owner, Op.JUMP, (LabelRef(routine.owner, 999),),
                                 routine.instructions[-1].span)
    with pytest.raises(ValueError, match="undefined label"):
        replace(routine, instructions=(*routine.instructions, bad_jump))


def test_immediate_conversion_before_later_argument_call():
    source = (
        "FUNC later() -> INT { SHOW(9); RETURN 2; } "
        "FUNC f(FLOAT a, INT b) -> FLOAT { RETURN a; } "
        "START { SHOW(f(1, later())); }"
    )
    _, target = compile_target(source)
    items = target.entry.instructions
    conversion = next(i for i, item in enumerate(items) if item.opcode is Op.TO_FLOAT)
    later_call = next(i for i, item in enumerate(items) if item.opcode is Op.CALL
                      and item.operands[0].symbol.name == "later")
    outer_call = next(i for i, item in enumerate(items) if item.opcode is Op.CALL
                      and item.operands[0].symbol.name == "f")
    assert conversion < later_call < outer_call
    pushes = [item.operands[1] for item in items if item.opcode is Op.PUSH_ARG]
    from sparq.symbols import ScalarType
    assert pushes == [ScalarType.FLOAT, ScalarType.INT]


def test_source_spans_are_retained_from_verified_ir():
    ir, target = compile_target("START { INT x = 1 + 2; SHOW(x); }")
    source_spans = {id(item.span) for item in ir.entry.instructions}
    assert all(id(item.span) in source_spans for item in target.entry.instructions)
    assert any(item.span is ir.entry.instructions[0].span
               for item in target.entry.instructions)


def test_foreign_equal_call_symbol_is_rejected_before_translation():
    ir, _ = compile_target(
        "FUNC f() -> INT { RETURN 1; } START { SHOW(f()); }"
    )
    from sparq.ir import Call
    call = next(item for item in ir.entry.instructions if isinstance(item, Call))
    foreign = replace(ir.semantic_owner.signatures[0])
    assert foreign == ir.semantic_owner.signatures[0]
    assert foreign is not ir.semantic_owner.signatures[0]
    modified = replace(call, function=FunctionRef(foreign))
    bad_entry = replace(ir.entry, instructions=tuple(
        modified if item is call else item for item in ir.entry.instructions
    ))
    with pytest.raises(CodeGenerationError):
        generate_target(replace(ir, entry=bad_entry))

