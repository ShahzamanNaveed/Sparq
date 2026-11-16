from pathlib import Path
import subprocess
import sys

from sparq.lexer import Lexer, main
from sparq.token import TokenType


ROOT = Path(__file__).resolve().parents[1]


def test_hello_example():
    tokens = Lexer.from_file(ROOT / "examples" / "hello.spq").tokenize()
    assert [t.type for t in tokens] == [
        TokenType.START, TokenType.LBRACE, TokenType.SHOW,
        TokenType.LPAREN, TokenType.STRING_LITERAL, TokenType.RPAREN,
        TokenType.SEMICOLON, TokenType.RBRACE, TokenType.EOF,
    ]
    assert (tokens[0].line, tokens[0].column) == (1, 1)
    assert (tokens[4].line, tokens[4].column) == (2, 10)
    assert tokens[4].literal == "Hello from Sparq!"


def test_representative_constructs_tokenize_only():
    source = """
FUNC add(INT x, INT y) -> INT { RETURN x+y; }
START {
  INT a[2] = {1, 2};
  WHEN (a[0] < 2 AND TRUE) { SHOW(add(a[0], a[1])); }
  SELECT (a[0]) { CASE 1: { READ(a[1]); } DEFAULT: {} }
  REPEAT (INT i=0; i<2; i=i+1) { SHOW(i); }
  WHILE (FALSE) {}
  DO {} WHILE (FALSE);
}
"""
    tokens = Lexer(source).tokenize()
    assert tokens[0].type is TokenType.FUNC
    assert tokens[-1].type is TokenType.EOF
    assert {TokenType.SELECT, TokenType.REPEAT, TokenType.WHILE, TokenType.DO} <= {
        t.type for t in tokens
    }


def test_lexer_accepts_valid_tokens_with_bad_syntax_or_semantics():
    assert Lexer("INT = 10; SHOW(unknown);").tokenize()[-1].type is TokenType.EOF


def test_cli_prints_tokens_without_compiling(capsys):
    status = main([str(ROOT / "examples" / "hello.spq")])
    captured = capsys.readouterr()
    assert status == 0
    assert "STRING_LITERAL" in captured.out
    assert "EOF" in captured.out
    assert captured.err == ""


def test_cli_displays_ordinary_integer(tmp_path, capsys):
    path = tmp_path / "ordinary.spq"
    path.write_text("START { SHOW(42); }", encoding="utf-8")
    assert main([str(path)]) == 0
    output = capsys.readouterr().out
    assert "INT_LITERAL '42' 42" in output


def test_cli_displays_large_integer_without_host_error(tmp_path):
    digits = "9" * 5000
    path = tmp_path / "large.spq"
    path.write_text(f"START {{ SHOW({digits}); }}", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "sparq.lexer", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if "INT_LITERAL" in line)
    assert "5000 digits" in line
    assert "<INT from 5000 source digits>" in line
    assert len(line) < 200
    assert digits not in result.stdout


def test_cli_invalid_source_exits_with_diagnostic(tmp_path):
    path = tmp_path / "invalid.spq"
    path.write_text("START { SHOW(12abc); }", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "sparq.lexer", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "MALFORMED_NUMBER" in result.stderr
    assert "12abc" in result.stderr
