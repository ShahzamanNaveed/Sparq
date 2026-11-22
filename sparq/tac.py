"""Complete Sparq source-to-verified-TAC entry point and readable listing."""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields
from pathlib import Path

from sparq.ast_nodes import Program
from sparq.function_lowering import lower_function
from sparq.ir import (
    ArrayRef, BranchBool, Constant, HaltStart, IRProgram, Jump, Label,
    RoutineId, VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.ir_verify import verify_program
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import AnalysisResult, SemanticAnalyzer
from sparq.statement_lowering import StatementLowerer
from sparq.symbols import ScalarType, SymbolKind


class TACGenerationError(ValueError):
    """A whole-program TAC generation session could not publish verified IR."""


class TACGenerator:
    """Generate one complete, verified IRProgram from an exact semantic owner."""

    def __init__(self, program: Program, analysis: AnalysisResult) -> None:
        if (not isinstance(program, Program) or not isinstance(analysis, AnalysisResult)
                or analysis.program is not program):
            raise TACGenerationError("Program and AnalysisResult must share exact identity")
        self.program = program
        self.analysis = analysis
        self._failed = False
        self._complete: IRProgram | None = None

    def generate(self) -> IRProgram:
        if self._complete is not None:
            return self._complete
        if self._failed:
            raise TACGenerationError("failed TAC generator must be discarded")
        try:
            functions = tuple(lower_function(item) for item in self.analysis.functions)
            owner = RoutineId.start()
            locals_ = tuple(
                ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
                else VariableRef(owner, symbol)
                for _, symbol in self.analysis.start.declarations
            )
            builder = IRBuilder(owner, self.analysis.start_scope.id, local_symbols=locals_)
            StatementLowerer(builder).lower_block(self.analysis.start)
            builder.emit(HaltStart(owner, self.program.main.span))
            candidate = IRProgram(self.program, self.analysis, functions, builder.finish())
            self._complete = verify_program(candidate)
            return self._complete
        except (TypeError, ValueError, RecursionError) as exc:
            self._failed = True
            raise TACGenerationError("cannot generate a complete verified TAC program") from exc


def generate_tac(program: Program, analysis: AnalysisResult) -> IRProgram:
    """Convenience one-shot complete generation API."""
    return TACGenerator(program, analysis).generate()


def _display(value) -> str:
    if type(value) is int and value.bit_length() > 4096:
        return repr(Constant(ScalarType.INT, value))
    if isinstance(value, tuple):
        return "(" + ", ".join(_display(item) for item in value) + ")"
    if hasattr(value, "name") and type(value).__module__ == "sparq.token":
        return value.name
    return repr(value)


def _listing(routine) -> list[str]:
    lines = []
    for number, instruction in enumerate(routine.instructions):
        if isinstance(instruction, Label):
            body = f"L{instruction.target.number}:"
        elif isinstance(instruction, Jump):
            body = f"JUMP L{instruction.target.number}"
        elif isinstance(instruction, BranchBool):
            body = (f"BRANCH {_display(instruction.condition)} "
                    f"? L{instruction.true_target.number} : L{instruction.false_target.number}")
        else:
            members = ", ".join(
                f"{field.name}={_display(getattr(instruction, field.name))}"
                for field in fields(instruction) if field.name not in ("owner", "span")
            )
            body = f"{type(instruction).__name__.upper()} {members}".rstrip()
        lines.append(f"  {number:04d} {body}")
    return lines


def format_tac(program: IRProgram) -> str:
    """Render only a complete verified canonical IRProgram, deterministically."""
    verify_program(program)
    lines = []
    for item in program.functions:
        signature = item.function.symbol
        parameters = ", ".join(
            f"{parameter.symbol.name}#{parameter.symbol.id}:{parameter.type.name}"
            for parameter in item.parameters
        )
        lines.append(f"FUNC {signature.name}#{signature.id}({parameters}) -> {signature.return_type.name}")
        lines.extend(_listing(item.body))
    lines.append("START")
    lines.extend(_listing(program.entry))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile Sparq source to verified typed TAC")
    parser.add_argument("source", help=".spq source file")
    args = parser.parse_args(argv)
    try:
        source = Path(args.source).read_text(encoding="utf-8")
        program = Parser(Lexer(source).tokenize()).parse()
        analysis = SemanticAnalyzer(program).analyze()
        output = format_tac(generate_tac(program, analysis))
    except Exception as exc:
        message = str(exc)
        if len(message) > 240:
            message = message[:237] + "..."
        print(f"TAC compilation failed: {type(exc).__name__}: {message}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
