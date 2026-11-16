import pytest

from sparq.errors import LexicalError
from sparq.lexer import Lexer
from sparq.token import TokenType


@pytest.mark.parametrize(("source", "value"), [
    ('""', ""), ('"Hello"', "Hello"), ('"λ🙂"', "λ🙂"),
    (r'"a\n\t\r\\\"\'\0"', "a\n\t\r\\\"'\0"),
])
def test_strings(source, value):
    token = Lexer(source).tokenize()[0]
    assert (token.type, token.lexeme, token.literal) == (TokenType.STRING_LITERAL, source, value)


@pytest.mark.parametrize(("source", "value"), [
    ("'A'", "A"), ("'7'", "7"), (r"'\n'", "\n"), (r"'\\'", "\\"),
    ("'🙂'", "🙂"),
])
def test_characters(source, value):
    token = Lexer(source).tokenize()[0]
    assert (token.type, token.lexeme, token.literal) == (TokenType.CHAR_LITERAL, source, value)


@pytest.mark.parametrize(("source", "category"), [
    ("''", "INVALID_CHAR_LENGTH"), ("'AB'", "INVALID_CHAR_LENGTH"),
    ("'abc'", "INVALID_CHAR_LENGTH"), ("'a", "UNTERMINATED_CHAR"),
    ('"a', "UNTERMINATED_STRING"), (r'"\q"', "INVALID_ESCAPE"),
    (r"'\x'", "INVALID_ESCAPE"), ('"a\nb"', "UNTERMINATED_STRING"),
    ("'a\r\nb'", "UNTERMINATED_CHAR"),
    ('"a\tb"', "INVALID_LITERAL_CHARACTER"),
    ('"\u0085"', "INVALID_LITERAL_CHARACTER"),
    ('"\ud800"', "INVALID_LITERAL_CHARACTER"),
])
def test_invalid_literals(source, category):
    with pytest.raises(LexicalError) as caught:
        Lexer(source).tokenize()
    assert caught.value.category == category
