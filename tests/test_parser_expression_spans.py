from sparq.ast_nodes import ArrayAccess, BinaryExpr, CallExpr, LiteralExpr, UnaryExpr
from sparq.lexer import Lexer
from sparq.parser import Parser


def parse(source):
    return Parser(Lexer(source).tokenize()).parse_expression_only()


def bounds(node):
    span = node.span
    return (span.start_line, span.start_column, span.end_line, span.end_column)


def test_literal_variable_and_unary_spans():
    assert bounds(parse("42")) == (1, 1, 1, 3)
    assert bounds(parse("name")) == (1, 1, 1, 5)
    node = parse("- (x)")
    assert isinstance(node, UnaryExpr)
    assert bounds(node) == (1, 1, 1, 6)
    assert bounds(node.operand) == (1, 4, 1, 5)


def test_grouped_inner_span_and_outer_binary_span():
    inner = parse("(10 + 20)")
    assert isinstance(inner, BinaryExpr)
    assert bounds(inner) == (1, 2, 1, 9)
    outer = parse("(10 + 20) * 3")
    assert bounds(outer) == (1, 1, 1, 14)
    assert bounds(outer.left) == (1, 2, 1, 9)
    assert bounds(outer.right) == (1, 13, 1, 14)


def test_call_and_array_access_include_closing_delimiter():
    call = parse("foo(1,\n 2)")
    assert isinstance(call, CallExpr)
    assert bounds(call) == (1, 1, 2, 4)
    assert [bounds(arg) for arg in call.args] == [
        (1, 5, 1, 6), (2, 2, 2, 3),
    ]
    array = parse("arr[1+2]")
    assert isinstance(array, ArrayAccess)
    assert bounds(array) == (1, 1, 1, 9)
    assert bounds(array.index) == (1, 5, 1, 8)


def test_multiline_binary_span_and_no_semicolon_in_expression():
    node = parse("a +\n b")
    assert bounds(node) == (1, 1, 2, 3)
    assert isinstance(node.left, type(parse("a")))
    assert isinstance(parse("7"), LiteralExpr)
