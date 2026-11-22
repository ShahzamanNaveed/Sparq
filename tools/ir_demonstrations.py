"""Derived teaching views of a restricted canonical Sparq TAC fragment.

These tables do not execute, reorder, replace, or verify production IR.
"""

from __future__ import annotations

from dataclasses import dataclass

from sparq.ir import (
    Binary, Compare, Constant, Convert, InitScalar, Load, Move, RoutineId,
    Temporary, Unary,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.statement_lowering import StatementLowerer


class UnsupportedIRView(ValueError):
    """An instruction or dependency is outside the stated teaching subset."""


@dataclass(frozen=True, slots=True)
class Quadruple:
    operator: str
    arg1: object | None
    arg2: object | None
    result: object


@dataclass(frozen=True, slots=True)
class PositionRef:
    position: int

    def __post_init__(self) -> None:
        if type(self.position) is not int or self.position < 0:
            raise ValueError("triple position must be nonnegative")

    def __repr__(self) -> str:
        return f"({self.position})"


@dataclass(frozen=True, slots=True)
class Triple:
    operator: str
    arg1: Constant | PositionRef
    arg2: Constant | PositionRef


@dataclass(frozen=True, slots=True)
class IndirectTriples:
    triples: tuple[Triple, ...]
    order: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "triples", tuple(self.triples))
        object.__setattr__(self, "order", tuple(self.order))
        if any(not isinstance(item, Triple) for item in self.triples):
            raise TypeError("indirect triples require Triple records")
        if (any(type(position) is not int for position in self.order)
                or sorted(self.order) != list(range(len(self.triples)))):
            raise ValueError("indirect order must reference every triple once")


def quadruples(instructions) -> tuple[Quadruple, ...]:
    """Display scalar data operations as four-field records; reject other opcodes."""
    output = []
    for instruction in instructions:
        if isinstance(instruction, (Binary, Compare)):
            row = Quadruple(instruction.operator.name, instruction.left,
                            instruction.right, instruction.result)
        elif isinstance(instruction, Unary):
            row = Quadruple(instruction.operator.name, instruction.operand,
                            None, instruction.result)
        elif isinstance(instruction, Convert):
            row = Quadruple("INT_TO_FLOAT", instruction.operand, None,
                            instruction.result)
        elif isinstance(instruction, Load):
            row = Quadruple("LOAD", instruction.source, None, instruction.result)
        elif isinstance(instruction, InitScalar):
            row = Quadruple("INIT_SCALAR", instruction.value, None,
                            instruction.target)
        elif isinstance(instruction, Move):
            row = Quadruple("MOVE", instruction.value, None, instruction.target)
        else:
            raise UnsupportedIRView(f"{type(instruction).__name__} has no four-field teaching view")
        output.append(row)
    return tuple(output)


def triples(instructions) -> tuple[Triple, ...]:
    """Translate a straight-line Binary-only fragment with prior temp definitions."""
    output = []
    definitions: dict[Temporary, int] = {}
    owner = None
    for instruction in instructions:
        if not isinstance(instruction, Binary):
            raise UnsupportedIRView(f"{type(instruction).__name__} is outside arithmetic triples")
        if owner is None:
            owner = instruction.owner
        elif instruction.owner is not owner:
            raise UnsupportedIRView("triple fragment crosses routine owners")
        args = []
        for operand in (instruction.left, instruction.right):
            if isinstance(operand, Constant):
                args.append(operand)
            elif isinstance(operand, Temporary) and operand in definitions:
                args.append(PositionRef(definitions[operand]))
            else:
                raise UnsupportedIRView("triple operand needs a prior arithmetic definition")
        if instruction.result in definitions:
            raise UnsupportedIRView("triple result has multiple definitions")
        definitions[instruction.result] = len(output)
        output.append(Triple(instruction.operator.name, args[0], args[1]))
    return tuple(output)


def indirect_triples(table, order=None) -> IndirectTriples:
    """Attach a pointer order; this does not validate reordered execution safety."""
    rows = tuple(table)
    return IndirectTriples(rows, tuple(range(len(rows))) if order is None else tuple(order))


def demonstrate() -> str:
    """Derive all teaching views from one source-backed generated TAC fragment."""
    source = "START { SHOW(1 + 2 * 3); }"
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    builder = IRBuilder(RoutineId.start(), semantic.start_scope.id)
    StatementLowerer(builder).lower_block(semantic.start)
    canonical = builder.snapshot()
    arithmetic = tuple(item for item in canonical if isinstance(item, Binary))
    quads = quadruples(arithmetic)
    triples_table = triples(arithmetic)
    pointers = indirect_triples(triples_table)
    lines = ["Source: " + source, "Canonical typed TAC:"]
    lines.extend(f"  {position}: {item!r}" for position, item in enumerate(canonical))
    lines.append("Derived arithmetic subset: positions " +
                 repr(tuple(i for i, item in enumerate(canonical) if isinstance(item, Binary))))
    lines.append("Quadruples:")
    lines.extend(f"  {position}: {row!r}" for position, row in enumerate(quads))
    lines.append("Triples:")
    lines.extend(f"  {position}: {row!r}" for position, row in enumerate(triples_table))
    lines.append("Indirect triples: pointer order " + repr(pointers.order))
    independent_source = "START { SHOW(1 + 2); SHOW(3 + 4); }"
    independent_program = Parser(Lexer(independent_source).tokenize()).parse()
    independent_semantic = SemanticAnalyzer(independent_program).analyze()
    independent_builder = IRBuilder(RoutineId.start(), independent_semantic.start_scope.id)
    StatementLowerer(independent_builder).lower_block(independent_semantic.start)
    independent_rows = triples(tuple(
        item for item in independent_builder.snapshot() if isinstance(item, Binary)
    ))
    alternative = indirect_triples(independent_rows, (1, 0))
    lines.append("Independent source: " + independent_source)
    lines.append("Alternative pointer order (display only; no execution or optimization): " +
                 repr(alternative.order))
    return "\n".join(lines)


if __name__ == "__main__":
    print(demonstrate())
