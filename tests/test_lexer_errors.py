from pathlib import Path

import pytest

from sparq.errors import LexicalError
from sparq.lexer import Lexer


def test_invalid_character_location_and_text():
    with pytest.raises(LexicalError) as caught:
        Lexer("a\n@").tokenize()
    err = caught.value
    assert (err.category, err.line, err.column, err.offending_text) == (
        "INVALID_CHARACTER", 2, 1, "@",
    )
    assert "2:1" in str(err)


def test_fail_fast_does_not_skip_first_error():
    with pytest.raises(LexicalError) as caught:
        Lexer("@ #").tokenize()
    assert caught.value.offending_text == "@"


def test_invalid_utf8_is_controlled(tmp_path: Path):
    path = tmp_path / "bad.spq"
    path.write_bytes(b"START\r\n\xff")
    with pytest.raises(LexicalError) as caught:
        Lexer.from_file(path)
    assert (caught.value.category, caught.value.line, caught.value.column) == (
        "INVALID_ENCODING", 2, 1,
    )


def test_missing_file_is_not_silently_ignored(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        Lexer.from_file(tmp_path / "missing.spq")
