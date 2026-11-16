from dataclasses import FrozenInstanceError

import pytest

from sparq.ast_nodes import (
    ArrayDecl, Block, CallExpr, CaseClause, FunctionDecl, LiteralExpr,
    Parameter, Program, SelectStmt, ShowStmt, SourceSpan,
)
from sparq.token import TokenType


def test_source_span_validation_and_immutability():
    span = SourceSpan(1, 2, 3, 4)
    assert (span.start_line, span.end_column) == (1, 4)
    with pytest.raises(FrozenInstanceError):
        span.end_column = 9
    with pytest.raises(ValueError):
        SourceSpan(0, 1, 1, 2)
    with pytest.raises(ValueError):
        SourceSpan(2, 4, 2, 3)


def test_program_and_declarations_keep_immutable_collections():
    span = SourceSpan(1, 1, 1, 3)
    param = Parameter(TokenType.INT, "x", span)
    body = Block((), span)
    function = FunctionDecl("f", (param,), TokenType.VOID, body, span)
    program = Program((function,), body, span)
    size = LiteralExpr(TokenType.INT_LITERAL, 2, "02", span)
    array = ArrayDecl(TokenType.INT, "a", size, (size, size), span)
    assert program.functions == (function,)
    assert function.params == (param,)
    assert array.initializers == (size, size)
    assert array.size.lexeme == "02"
    with pytest.raises(FrozenInstanceError):
        program.main = body
    with pytest.raises(AttributeError):
        body.statements.append(array)


def _collection_node(field, values):
    span = SourceSpan(1, 1, 1, 2)
    body = Block((), span)
    literal = LiteralExpr(TokenType.INT_LITERAL, 1, "1", span)
    if field == "functions":
        item = FunctionDecl("f", (), TokenType.VOID, body, span)
        return Program([item] if values is None else values, body, span), item
    if field == "params":
        item = Parameter(TokenType.INT, "x", span)
        return FunctionDecl("f", [item] if values is None else values, TokenType.VOID, body, span), item
    if field == "statements":
        item = ShowStmt(literal, span)
        return Block([item] if values is None else values, span), item
    if field == "initializers":
        return ArrayDecl(TokenType.INT, "a", literal, [literal] if values is None else values, span), literal
    if field == "cases":
        item = CaseClause(literal, body, span)
        return SelectStmt(literal, [item] if values is None else values, None, span), item
    return CallExpr("f", [literal] if values is None else values, span), literal


@pytest.mark.parametrize("field", [
    "functions", "params", "statements", "initializers", "cases", "args",
])
def test_collection_inputs_are_snapshotted_and_frozen(field):
    _, item = _collection_node(field, None)
    original = [item]
    node, _ = _collection_node(field, original)
    assert getattr(node, field) == (item,)
    assert isinstance(getattr(node, field), tuple)
    original.append(item)
    assert getattr(node, field) == (item,)
    with pytest.raises(FrozenInstanceError):
        setattr(node, field, ())


@pytest.mark.parametrize("field", [
    "functions", "params", "statements", "initializers", "cases", "args",
])
def test_collection_fields_accept_tuples_and_reject_invalid_inputs(field):
    _, item = _collection_node(field, None)
    node, _ = _collection_node(field, (item,))
    assert getattr(node, field) == (item,)
    for invalid in ("text", {"item": item}, 7):
        with pytest.raises(TypeError, match=field):
            _collection_node(field, invalid)


def test_optional_array_initializers_still_accept_none():
    span = SourceSpan(1, 1, 1, 2)
    size = LiteralExpr(TokenType.INT_LITERAL, 1, "1", span)
    assert ArrayDecl(TokenType.INT, "a", size, None, span).initializers is None
