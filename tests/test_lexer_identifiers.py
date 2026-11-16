import pytest

from sparq.errors import LexicalError
from sparq.lexer import Lexer
from sparq.token import TokenType


@pytest.mark.parametrize("word", ["age", "student_name", "_total", "abc123", "_"])
def test_valid_identifier(word):
    token = Lexer(word).tokenize()[0]
    assert token.type is TokenType.IDENTIFIER
    assert token.lexeme == word


def test_leading_digit_is_malformed_number():
    with pytest.raises(LexicalError, match="MALFORMED_NUMBER") as caught:
        Lexer("2age").tokenize()
    assert caught.value.offending_text == "2age"


def test_unicode_letter_is_not_identifier_character():
    with pytest.raises(LexicalError) as caught:
        Lexer("nameé").tokenize()
    assert caught.value.category == "INVALID_CHARACTER"
    assert (caught.value.line, caught.value.column) == (1, 5)
