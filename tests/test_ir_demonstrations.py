"""Derived educational IR views never alter the canonical instruction stream."""

from dataclasses import FrozenInstanceError

import pytest

from sparq.ir import Binary, Constant, RoutineId, Show
from sparq.ir_builder import IRBuilder
from sparq.ast_nodes import SourceSpan
from sparq.symbols import ScalarType
from sparq.token import TokenType
from tools.ir_demonstrations import (
    IndirectTriples, PositionRef, UnsupportedIRView, demonstrate,
    indirect_triples, quadruples, triples,
)


SPAN = SourceSpan(1, 1, 1, 1)


def _fragment():
    builder = IRBuilder(RoutineId.start(), 1)
    left = builder.temp(ScalarType.INT)
    builder.emit(Binary(builder.owner, SPAN, TokenType.STAR,
                        Constant(ScalarType.INT, 2), Constant(ScalarType.INT, 3), left))
    right = builder.temp(ScalarType.INT)
    builder.emit(Binary(builder.owner, SPAN, TokenType.PLUS,
                        Constant(ScalarType.INT, 1), left, right))
    return builder, builder.snapshot()


def test_quadruple_fields_and_triple_dependency_positions():
    _, items = _fragment()
    quads = quadruples(items)
    rows = triples(items)
    assert len(quads) == len(rows) == 2
    assert (quads[0].operator, quads[0].arg1.value, quads[0].arg2.value,
            quads[0].result) == ("STAR", 2, 3, items[0].result)
    assert quads[1].arg2 is items[0].result and quads[1].result is items[1].result
    assert rows[0].operator == "STAR" and rows[1].operator == "PLUS"
    assert rows[1].arg2 == PositionRef(0) and rows[1].arg1.value == 1


def test_empty_input_and_indirect_pointer_order():
    assert quadruples(()) == triples(()) == ()
    assert indirect_triples(()).order == ()
    _, items = _fragment()
    rows = triples(items)
    indirect = indirect_triples(rows, (1, 0))
    assert isinstance(indirect, IndirectTriples)
    assert indirect.triples == rows and indirect.order == (1, 0)
    assert indirect.triples[1].arg2 == PositionRef(0)
    with pytest.raises(ValueError):
        indirect_triples(rows, (0, 0))


def test_unsupported_instructions_and_missing_dependencies_fail_explicitly():
    builder, items = _fragment()
    show = Show(builder.owner, SPAN, items[-1].result)
    with pytest.raises(UnsupportedIRView, match="Show"):
        quadruples(items + (show,))
    with pytest.raises(UnsupportedIRView, match="Show"):
        triples(items + (show,))
    with pytest.raises(UnsupportedIRView, match="prior arithmetic"):
        triples((items[1],))


def test_derived_tables_are_frozen_and_do_not_mutate_source():
    builder, items = _fragment()
    before = builder.snapshot()
    quads, rows = quadruples(items), triples(items)
    assert before == builder.snapshot() == items
    with pytest.raises(FrozenInstanceError):
        quads[0].operator = "OTHER"
    with pytest.raises(FrozenInstanceError):
        rows[0].operator = "OTHER"


def test_demonstration_is_source_backed_and_deterministic():
    first = demonstrate()
    assert first == demonstrate()
    assert "START { SHOW(1 + 2 * 3); }" in first
    assert "Canonical typed TAC:" in first
    assert "Quadruples:" in first and "Triples:" in first
    assert "Indirect triples: pointer order (0, 1)" in first
    assert "Alternative pointer order (display only; no execution or optimization): (1, 0)" in first
    assert "(0)" in first
