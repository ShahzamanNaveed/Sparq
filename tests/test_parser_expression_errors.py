import pytest

from sparq.lexer import Lexer
from sparq.parser import ParseError, Parser
from sparq.token import Token, TokenType


@pytest.mark.parametrize("source", [
    "", "10 +", "(10 + 2", "10 20", "a + * b", "f(1,)",
    "a[]", "a[1", "a < b < c", "a == b == c", "f()[0]",
    "a = 1", "f(,1)", "NOT", "-",
])
def test_invalid_expression_fails_with_parse_error(source):
    with pytest.raises(ParseError):
        Parser(Lexer(source).tokenize()).parse_expression_only()


def test_error_exposes_actual_token_expected_and_location():
    with pytest.raises(ParseError) as caught:
        Parser(Lexer("10 +").tokenize()).parse_expression_only()
    error = caught.value
    assert error.category == "EXPECTED_EXPRESSION"
    assert error.expected == "an expression"
    assert error.actual.type is TokenType.EOF
    assert (error.line, error.column) == (1, 5)
    assert "1:5" in str(error)


def test_trailing_token_reports_expected_eof():
    with pytest.raises(ParseError) as caught:
        Parser(Lexer("10 20").tokenize()).parse_expression_only()
    assert caught.value.expected == "EOF"
    assert caught.value.actual.type is TokenType.INT_LITERAL


def test_malformed_manual_token_streams_are_controlled():
    eof = Token(TokenType.EOF, "", None, 1, 2, 1, 2)
    identifier = Token(TokenType.IDENTIFIER, "x", None, 1, 1, 1, 2)
    bad_streams = [
        [], [identifier], [eof, eof], [identifier, eof, identifier],
        [object(), eof], [Token("BAD", "x", None, 1, 1, 1, 2), eof],
        [identifier, Token(TokenType.EOF, "x", None, 1, 2, 1, 3)],
    ]
    for stream in bad_streams:
        with pytest.raises(ParseError) as caught:
            Parser(stream)
        assert caught.value.category == "INVALID_TOKEN_STREAM"


def test_input_token_list_is_not_mutated():
    tokens = Lexer("x + 1").tokenize()
    before = tuple(tokens)
    Parser(tokens).parse_expression_only()
    assert tuple(tokens) == before


@pytest.mark.parametrize("source", [
    "-" * 100 + "1", "(" * 100 + "1" + ")" * 100,
])
def test_excessive_nesting_has_controlled_diagnostic(source):
    with pytest.raises(ParseError) as caught:
        Parser(Lexer(source).tokenize()).parse_expression_only()
    assert caught.value.category == "RESOURCE_LIMIT"


@pytest.mark.parametrize("bad", [
    Token(TokenType.INT_LITERAL, "1", None, 1, 1, 1, 2),
    Token(TokenType.INT_LITERAL, "1", True, 1, 1, 1, 2),
    Token(TokenType.FLOAT_LITERAL, "1.0", 1, 1, 1, 1, 4),
    Token(TokenType.FLOAT_LITERAL, "1.0", float("inf"), 1, 1, 1, 4),
    Token(TokenType.FLOAT_LITERAL, "1.0", float("nan"), 1, 1, 1, 4),
    Token(TokenType.CHAR_LITERAL, "'a'", "ab", 1, 1, 1, 4),
    Token(TokenType.CHAR_LITERAL, "'x'", "\ud800", 1, 1, 1, 4),
    Token(TokenType.STRING_LITERAL, '"a"', 1, 1, 1, 1, 4),
    Token(TokenType.TRUE, "TRUE", False, 1, 1, 1, 5),
    Token(TokenType.FALSE, "FALSE", True, 1, 1, 1, 6),
    Token(TokenType.IDENTIFIER, "1x", None, 1, 1, 1, 3),
    Token(TokenType.IDENTIFIER, "name", "name", 1, 1, 1, 5),
    Token(TokenType.PLUS, None, None, 1, 1, 1, 2),
    Token("BAD", "x", None, 1, 1, 1, 2),
])
def test_malformed_token_payload_has_controlled_diagnostic(bad):
    eof = Token(TokenType.EOF, "", None, 1, 6, 1, 6)
    with pytest.raises(ParseError) as caught:
        Parser([bad, eof]).parse_expression_only()
    error = caught.value
    assert error.category == "INVALID_TOKEN_STREAM"
    assert (error.line, error.column) == (1, 1)
    assert "INVALID_TOKEN_STREAM at 1:1" in str(error)


@pytest.mark.parametrize("coordinates", [
    (0, 1, 1, 2), (True, 1, 1, 2), (1, 1, 1, False),
    (2, 5, 2, 4), (2, 1, 1, 8), ("1", 1, 1, 2),
])
def test_invalid_token_coordinates_are_controlled(coordinates):
    bad = Token(TokenType.INT_LITERAL, "1", 1, *coordinates)
    eof = Token(TokenType.EOF, "", None, 1, 2, 1, 2)
    with pytest.raises(ParseError) as caught:
        Parser([bad, eof])
    assert caught.value.category == "INVALID_TOKEN_STREAM"
    assert "INVALID_TOKEN_STREAM" in str(caught.value)


def test_valid_lexer_tokens_and_large_integer_keep_exact_values():
    source = "9" * 5000
    tokens = Lexer(source).tokenize()
    node = Parser(tokens).parse_expression_only()
    assert node.lexeme == source
    assert node.value == 10**5000 - 1
    assert tokens[0].literal is node.value
    assert Parser(Lexer("f(1, TRUE, 'a', \"x\")").tokenize()).parse_expression_only()


def test_non_iterable_stream_is_controlled():
    with pytest.raises(ParseError) as caught:
        Parser(None)
    assert caught.value.category == "INVALID_TOKEN_STREAM"
    assert "1:1" in str(caught.value)


def test_enormous_manual_coordinate_cannot_break_error_formatting():
    enormous = 10**5000
    bad = Token(TokenType.PLUS, None, None, enormous, 1, enormous, 2)
    eof = Token(TokenType.EOF, "", None, 1, 1, 1, 1)
    with pytest.raises(ParseError) as caught:
        Parser([bad, eof])
    assert caught.value.category == "INVALID_TOKEN_STREAM"
    assert "<invalid position>" in str(caught.value)


@pytest.mark.parametrize(("tokens", "kind", "location"), [
    (
        [Token(TokenType.INT_LITERAL, "1", 1, 2, 1, 2, 2),
         Token(TokenType.PLUS, "+", None, 1, 3, 1, 4),
         Token(TokenType.INT_LITERAL, "2", 2, 1, 5, 1, 6),
         Token(TokenType.EOF, "", None, 1, 6, 1, 6)],
        TokenType.PLUS, (1, 3),
    ),
    (
        [Token(TokenType.INT_LITERAL, "12", 12, 1, 1, 1, 3),
         Token(TokenType.PLUS, "+", None, 1, 2, 1, 3),
         Token(TokenType.INT_LITERAL, "2", 2, 1, 3, 1, 4),
         Token(TokenType.EOF, "", None, 1, 4, 1, 4)],
        TokenType.PLUS, (1, 2),
    ),
    (
        [Token(TokenType.INT_LITERAL, "1", 1, 1, 1, 1, 2),
         Token(TokenType.EOF, "", None, 1, 1, 1, 1)],
        TokenType.EOF, (1, 1),
    ),
])
def test_reversed_or_overlapping_manual_token_positions_are_controlled(tokens, kind, location):
    with pytest.raises(ParseError) as caught:
        Parser(tokens).parse_expression_only()
    error = caught.value
    assert error.category == "INVALID_TOKEN_STREAM"
    assert error.expected == "token start at or after previous token end"
    assert error.actual.type is kind
    assert (error.line, error.column) == location
    assert "INVALID_TOKEN_STREAM" in str(error)


@pytest.mark.parametrize("source", [
    "1+2", "1  +    2  ", "1/* comment */+2", "1\n +\n2\n", "1\r\n  +\r\n 2\r\n",
])
def test_adjacent_gapped_and_multiline_lexer_tokens_remain_valid(source):
    tokens = Lexer(source).tokenize()
    node = Parser(tokens).parse_expression_only()
    assert node.operator is TokenType.PLUS
    assert node.left.value == 1 and node.right.value == 2
    assert (tokens[-1].line, tokens[-1].column) >= (
        tokens[-2].end_line, tokens[-2].end_column
    )


def test_ordered_manual_tokens_with_multiline_gap_and_eof_are_valid():
    tokens = [
        Token(TokenType.INT_LITERAL, "1", 1, 1, 1, 1, 2),
        Token(TokenType.PLUS, "+", None, 2, 2, 2, 3),
        Token(TokenType.INT_LITERAL, "2", 2, 3, 1, 3, 2),
        Token(TokenType.EOF, "", None, 4, 1, 4, 1),
    ]
    node = Parser(tokens).parse_expression_only()
    assert (node.span.start_line, node.span.end_line) == (1, 3)
