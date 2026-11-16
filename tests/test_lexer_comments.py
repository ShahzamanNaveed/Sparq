import pytest

from sparq.errors import LexicalError
from sparq.lexer import Lexer
from sparq.token import TokenType


def test_line_comment_to_eof():
    assert [t.type for t in Lexer("INT // comment").tokenize()] == [
        TokenType.INT, TokenType.EOF,
    ]


def test_block_comment_first_closing_marker_and_adjacency():
    tokens = Lexer("a/* x */b").tokenize()
    assert [t.lexeme for t in tokens] == ["a", "b", ""]


def test_multiline_comment_positions():
    tokens = Lexer("a/* x\r\ny */b").tokenize()
    assert (tokens[1].line, tokens[1].column) == (2, 5)


def test_nested_comments_are_not_supported():
    tokens = Lexer("/* outer /* inner */ */").tokenize()
    assert [token.type for token in tokens] == [
        TokenType.STAR, TokenType.SLASH, TokenType.EOF,
    ]


def test_unterminated_comment():
    with pytest.raises(LexicalError) as caught:
        Lexer("x /* no end").tokenize()
    assert caught.value.category == "UNTERMINATED_COMMENT"
    assert (caught.value.line, caught.value.column) == (1, 3)


def test_comment_markers_inside_string():
    tokens = Lexer('"hello // world" "/* not a comment */"').tokenize()
    assert [t.type for t in tokens[:-1]] == [
        TokenType.STRING_LITERAL, TokenType.STRING_LITERAL,
    ]
