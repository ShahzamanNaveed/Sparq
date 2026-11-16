from dataclasses import FrozenInstanceError

import pytest

from sparq.lexer import Lexer
from sparq.token import TokenType


def test_literal_values_lexemes_and_eof():
    tokens = Lexer('name 001 3.25 "hi" \'x\' TRUE FALSE').tokenize()
    assert [t.type for t in tokens] == [
        TokenType.IDENTIFIER, TokenType.INT_LITERAL, TokenType.FLOAT_LITERAL,
        TokenType.STRING_LITERAL, TokenType.CHAR_LITERAL, TokenType.TRUE,
        TokenType.FALSE, TokenType.EOF,
    ]
    assert [t.literal for t in tokens] == [None, 1, 3.25, "hi", "x", True, False, None]
    assert [t.lexeme for t in tokens[:-1]] == [
        "name", "001", "3.25", '"hi"', "'x'", "TRUE", "FALSE",
    ]
    assert len([t for t in tokens if t.type is TokenType.EOF]) == 1


def test_token_is_immutable_and_end_is_exclusive():
    token = Lexer("START").tokenize()[0]
    assert (token.line, token.column, token.end_line, token.end_column) == (1, 1, 1, 6)
    with pytest.raises(FrozenInstanceError):
        token.column = 4
