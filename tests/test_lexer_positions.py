import pytest

from sparq.lexer import Lexer


@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"])
def test_line_breaks_count_once(newline):
    tokens = Lexer("x" + newline + "y").tokenize()
    assert (tokens[1].line, tokens[1].column) == (2, 1)
    assert (tokens[0].end_line, tokens[0].end_column) == (1, 2)


def test_tabs_and_unicode_columns():
    tokens = Lexer('"\u03bb\U0001f642"\tX').tokenize()
    assert (tokens[0].line, tokens[0].column, tokens[0].end_column) == (1, 1, 5)
    assert (tokens[1].line, tokens[1].column) == (1, 6)


def test_operator_and_comment_positions():
    tokens = Lexer("x>=2/*a\nb*/SHOW").tokenize()
    assert (tokens[1].column, tokens[1].end_column) == (2, 4)
    assert (tokens[3].line, tokens[3].column) == (2, 4)


def test_eof_position_after_crlf():
    eof = Lexer("x\r\n").tokenize()[-1]
    assert (eof.line, eof.column, eof.end_line, eof.end_column) == (2, 1, 2, 1)
