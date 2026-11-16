import pytest

from sparq.lexer import Lexer
from sparq.token import TokenType


@pytest.mark.parametrize(("source", "kind"), [
    ("+", TokenType.PLUS), ("-", TokenType.MINUS), ("*", TokenType.STAR),
    ("/", TokenType.SLASH), ("%", TokenType.PERCENT),
    (">", TokenType.GREATER), ("<", TokenType.LESS),
    (">=", TokenType.GREATER_EQUAL), ("<=", TokenType.LESS_EQUAL),
    ("==", TokenType.EQUAL_EQUAL), ("!=", TokenType.BANG_EQUAL),
    ("=", TokenType.EQUAL), ("->", TokenType.ARROW),
    ("(", TokenType.LPAREN), (")", TokenType.RPAREN),
    ("{", TokenType.LBRACE), ("}", TokenType.RBRACE),
    ("[", TokenType.LBRACKET), ("]", TokenType.RBRACKET),
    (";", TokenType.SEMICOLON), (",", TokenType.COMMA),
    (":", TokenType.COLON),
])
def test_operator_or_delimiter(source, kind):
    assert Lexer(source).tokenize()[0].type is kind


def test_longest_match_and_arrow():
    tokens = Lexer(">= > <= < == = != -> -").tokenize()
    assert [t.type for t in tokens[:-1]] == [
        TokenType.GREATER_EQUAL, TokenType.GREATER,
        TokenType.LESS_EQUAL, TokenType.LESS,
        TokenType.EQUAL_EQUAL, TokenType.EQUAL,
        TokenType.BANG_EQUAL, TokenType.ARROW, TokenType.MINUS,
    ]
