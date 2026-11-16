import math

import pytest

from sparq.errors import LexicalError
from sparq.lexer import Lexer
from sparq.token import TokenType


@pytest.mark.parametrize(("source", "value"), [("0", 0), ("10", 10), ("123", 123), ("001", 1)])
def test_integer_literals(source, value):
    token = Lexer(source).tokenize()[0]
    assert (token.type, token.literal, token.lexeme) == (TokenType.INT_LITERAL, value, source)


def test_integer_exceeds_host_string_conversion_limit():
    source = "9" * 5000
    token = Lexer(source).tokenize()[0]
    assert token.type is TokenType.INT_LITERAL
    assert token.literal == 10**5000 - 1
    assert token.lexeme == source


@pytest.mark.parametrize(("source", "value"), [("3.14", 3.14), ("0.5", 0.5), ("100.25", 100.25)])
def test_float_literals(source, value):
    token = Lexer(source).tokenize()[0]
    assert token.type is TokenType.FLOAT_LITERAL
    assert token.literal == value
    assert math.isfinite(token.literal)


@pytest.mark.parametrize("source", ["12abc", "12_abc", "2age", "2e10"])
def test_malformed_integer_like(source):
    with pytest.raises(LexicalError) as caught:
        Lexer(source).tokenize()
    assert caught.value.category == "MALFORMED_NUMBER"
    assert caught.value.offending_text == source


@pytest.mark.parametrize("source", ["5.", ".5", "1.2.3", "3.5abc"])
def test_malformed_float_like(source):
    with pytest.raises(LexicalError) as caught:
        Lexer(source).tokenize()
    assert caught.value.category == "MALFORMED_FLOAT"
    assert caught.value.offending_text == source


def test_nonfinite_float_literal():
    source = "9" * 400 + ".0"
    with pytest.raises(LexicalError) as caught:
        Lexer(source).tokenize()
    assert caught.value.category == "NONFINITE_FLOAT"


def test_minus_is_separate_and_operator_after_number_is_preserved():
    tokens = Lexer("-12+3.5").tokenize()
    assert [t.type for t in tokens] == [
        TokenType.MINUS, TokenType.INT_LITERAL, TokenType.PLUS,
        TokenType.FLOAT_LITERAL, TokenType.EOF,
    ]
