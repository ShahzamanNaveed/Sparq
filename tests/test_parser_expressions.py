import pytest

from sparq.ast_nodes import (
    ArrayAccess, BinaryExpr, CallExpr, LiteralExpr, UnaryExpr, VarRef,
)
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.token import TokenType


def parse(source):
    return Parser(Lexer(source).tokenize()).parse_expression_only()


@pytest.mark.parametrize(("source", "kind", "value"), [
    ("001", TokenType.INT_LITERAL, 1),
    ("3.25", TokenType.FLOAT_LITERAL, 3.25),
    ("'λ'", TokenType.CHAR_LITERAL, "λ"),
    ('"hi\\n"', TokenType.STRING_LITERAL, "hi\n"),
    ("TRUE", TokenType.TRUE, True),
    ("FALSE", TokenType.FALSE, False),
])
def test_literal_kind_value_and_original_spelling(source, kind, value):
    node = parse(source)
    assert isinstance(node, LiteralExpr)
    assert (node.kind, node.value, node.lexeme) == (kind, value, source)


def test_arbitrary_precision_int_is_not_reparsed_or_truncated():
    source = "9" * 5000
    node = parse(source)
    assert node.lexeme == source
    assert node.value == 10**5000 - 1


def test_variable_call_array_and_argument_order():
    assert parse("x") == VarRef("x", parse("x").span)
    empty = parse("f()")
    assert isinstance(empty, CallExpr) and empty.callee == "f" and empty.args == ()
    call = parse("f(10, x, a[1])")
    assert isinstance(call, CallExpr)
    assert isinstance(call.args, tuple)
    assert [type(arg) for arg in call.args] == [LiteralExpr, VarRef, ArrayAccess]
    access = parse("numbers[i + 1]")
    assert isinstance(access, ArrayAccess) and access.name == "numbers"
    assert isinstance(access.index, BinaryExpr)
    assert access.index.operator is TokenType.PLUS


@pytest.mark.parametrize(("source", "kind"), [
    ("-10", TokenType.MINUS), ("NOT TRUE", TokenType.NOT),
])
def test_unary(source, kind):
    node = parse(source)
    assert isinstance(node, UnaryExpr)
    assert node.operator is kind


def test_nested_unary_is_right_associated():
    node = parse("NOT -x")
    assert isinstance(node, UnaryExpr) and node.operator is TokenType.NOT
    assert isinstance(node.operand, UnaryExpr)
    assert node.operand.operator is TokenType.MINUS


@pytest.mark.parametrize(("source", "kind"), [
    ("a+b", TokenType.PLUS), ("a-b", TokenType.MINUS),
    ("a*b", TokenType.STAR), ("a/b", TokenType.SLASH),
    ("a%b", TokenType.PERCENT), ("a<b", TokenType.LESS),
    ("a>b", TokenType.GREATER), ("a<=b", TokenType.LESS_EQUAL),
    ("a>=b", TokenType.GREATER_EQUAL), ("a==b", TokenType.EQUAL_EQUAL),
    ("a!=b", TokenType.BANG_EQUAL), ("a AND b", TokenType.AND),
    ("a OR b", TokenType.OR),
])
def test_binary_operators(source, kind):
    node = parse(source)
    assert isinstance(node, BinaryExpr)
    assert node.operator is kind
    assert isinstance(node.left, VarRef) and isinstance(node.right, VarRef)


def test_precedence_shapes():
    node = parse("10 + 5 * 2")
    assert node.operator is TokenType.PLUS
    assert node.left.value == 10
    assert node.right.operator is TokenType.STAR
    assert (node.right.left.value, node.right.right.value) == (5, 2)
    node = parse("a OR b AND c == d + e * f")
    assert node.operator is TokenType.OR
    assert node.right.operator is TokenType.AND
    assert node.right.right.operator is TokenType.EQUAL_EQUAL
    assert node.right.right.right.operator is TokenType.PLUS
    assert node.right.right.right.right.operator is TokenType.STAR


@pytest.mark.parametrize(("source", "kind"), [
    ("a-b-c", TokenType.MINUS), ("a/b/c", TokenType.SLASH),
    ("a AND b AND c", TokenType.AND), ("a OR b OR c", TokenType.OR),
])
def test_repeated_binary_operators_associate_left(source, kind):
    node = parse(source)
    assert node.operator is kind
    assert isinstance(node.left, BinaryExpr)
    assert node.left.operator is kind
    assert isinstance(node.left.left, VarRef)
    assert isinstance(node.right, VarRef)


def test_parentheses_override_precedence_without_group_node():
    node = parse("(10 + 20) * 3")
    assert node.operator is TokenType.STAR
    assert node.left.operator is TokenType.PLUS
    assert node.right.value == 3


def test_syntax_parser_leaves_type_and_name_checks_for_later():
    assert parse("unknown + TRUE").operator is TokenType.PLUS
    assert parse("f(1, FALSE)").callee == "f"
