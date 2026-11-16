import pytest

from sparq.lexer import KEYWORDS, Lexer
from sparq.token import TokenType


@pytest.mark.parametrize("word", list(KEYWORDS))
def test_every_keyword(word):
    token = Lexer(word).tokenize()[0]
    assert token.type is TokenType[word]
    assert token.lexeme == word
    if word in ("TRUE", "FALSE"):
        assert token.literal is (word == "TRUE")
    else:
        assert token.literal is None


@pytest.mark.parametrize("word", ["when", "When", "STARTER", "FLOATING", "AND_2"])
def test_keyword_requires_exact_case_sensitive_match(word):
    assert Lexer(word).tokenize()[0].type is TokenType.IDENTIFIER
