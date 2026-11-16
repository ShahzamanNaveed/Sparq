import pytest

from sparq.lexer import Lexer
from sparq.parser import ParseError, Parser
from sparq.token import Token, TokenType


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


@pytest.mark.parametrize(("source", "category"), [
    ("", "EXPECTED_TOKEN"),
    ("FUNC f() -> VOID {}", "EXPECTED_TOKEN"),
    ("INT x; START {}", "EXPECTED_TOKEN"),
    ("START {} START {}", "EXPECTED_TOKEN"),
    ("START {} FUNC f() -> VOID {}", "EXPECTED_TOKEN"),
    ("START {", "EXPECTED_TOKEN"),
    ("FUNC () -> VOID {} START {}", "EXPECTED_TOKEN"),
    ("FUNC f(INT) -> VOID {} START {}", "EXPECTED_TOKEN"),
    ("FUNC f(INT x,) -> VOID {} START {}", "EXPECTED_TOKEN"),
    ("FUNC f() VOID {} START {}", "EXPECTED_TOKEN"),
    ("FUNC f() -> INT START {}", "EXPECTED_TOKEN"),
    ("START { INT x }", "EXPECTED_TOKEN"),
    ("START { INT a[1+2]; }", "EXPECTED_TOKEN"),
    ("START { INT a[-1]; }", "EXPECTED_TOKEN"),
    ("START { INT a[1] = {}; }", "EXPECTED_EXPRESSION"),
    ("START { INT a[1] = {1,}; }", "EXPECTED_EXPRESSION"),
    ("START { x + 1; }", "EXPECTED_TOKEN"),
    ("START { x = 1 }", "EXPECTED_TOKEN"),
    ("START { a[1 = 2; }", "EXPECTED_TOKEN"),
    ("START { f(1) + 2; }", "EXPECTED_TOKEN"),
    ("START { WHEN x {} }", "EXPECTED_TOKEN"),
    ("START { WHEN (x) SHOW(x); }", "EXPECTED_TOKEN"),
    ("START { SELECT (x) { CASE TRUE: {} } }", "EXPECTED_CASE_LABEL"),
    ("START { SELECT (x) { CASE -'a': {} } }", "EXPECTED_TOKEN"),
    ("START { SELECT (x) { CASE 1 {} } }", "EXPECTED_TOKEN"),
    ("START { SELECT (x) { DEFAULT: {} CASE 1: {} } }", "EXPECTED_TOKEN"),
    ("START { SELECT (x) { DEFAULT: {} DEFAULT: {} } }", "EXPECTED_TOKEN"),
    ("START { REPEAT (INT i; ; ) {} }", "EXPECTED_TOKEN"),
    ("START { REPEAT (f(); ; ) {} }", "EXPECTED_TOKEN"),
    ("START { REPEAT (; ; f()) {} }", "EXPECTED_TOKEN"),
    ("START { REPEAT (; x) {} }", "EXPECTED_TOKEN"),
    ("START { WHILE () {} }", "EXPECTED_EXPRESSION"),
    ("START { DO {} WHILE (x) }", "EXPECTED_TOKEN"),
    ("START { READ(1 + 2); }", "EXPECTED_TOKEN"),
    ("START { READ(x + 1); }", "EXPECTED_TOKEN"),
    ("START { SHOW(); }", "EXPECTED_EXPRESSION"),
    ("START { CASE 1: {} }", "EXPECTED_STATEMENT"),
])
def test_invalid_programs_fail_with_controlled_diagnostic(source, category):
    with pytest.raises(ParseError) as caught:
        parse(source)
    error = caught.value
    assert error.category == category
    assert error.line >= 1 and error.column >= 1
    assert category in str(error)


def test_missing_closing_brace_reports_eof_position():
    with pytest.raises(ParseError) as caught:
        parse("START {\n SHOW(1);\n")
    error = caught.value
    assert error.category == "EXPECTED_TOKEN"
    assert error.expected == "RBRACE"
    assert error.actual.type is TokenType.EOF
    assert (error.line, error.column) == (3, 1)


def test_malformed_token_stream_still_fails_before_program_parsing():
    bad = Token(TokenType.INT_LITERAL, "1", None, 1, 1, 1, 2)
    eof = Token(TokenType.EOF, "", None, 1, 2, 1, 2)
    with pytest.raises(ParseError) as caught:
        Parser([bad, eof]).parse()
    assert caught.value.category == "INVALID_TOKEN_STREAM"


@pytest.mark.parametrize(("entry", "prefix"), [
    ("parse", "START "), ("parse_block", ""), ("parse_statement", ""),
])
def test_deeply_nested_blocks_have_controlled_resource_diagnostic(entry, prefix):
    source = prefix + "{" * 1500 + "}" * 1500
    with pytest.raises(ParseError) as caught:
        getattr(Parser(Lexer(source).tokenize()), entry)()
    error = caught.value
    assert error.category == "RESOURCE_LIMIT"
    assert error.line >= 1 and error.column >= 1
    assert error.actual.type is TokenType.LBRACE
    assert "RESOURCE_LIMIT" in str(error)


def test_exact_reversed_program_token_positions_are_controlled():
    tokens = [
        Token(TokenType.START, "START", None, 2, 1, 2, 6),
        Token(TokenType.LBRACE, "{", None, 1, 7, 1, 8),
        Token(TokenType.RBRACE, "}", None, 1, 8, 1, 9),
        Token(TokenType.EOF, "", None, 1, 9, 1, 9),
    ]
    with pytest.raises(ParseError) as caught:
        Parser(tokens).parse()
    error = caught.value
    assert error.category == "INVALID_TOKEN_STREAM"
    assert error.expected == "token start at or after previous token end"
    assert error.actual.type is TokenType.LBRACE
    assert (error.line, error.column) == (1, 7)


def test_ordinary_public_block_statement_and_expression_entries_still_work():
    block = Parser(Lexer("{{}} ").tokenize()).parse_block()
    statement = Parser(Lexer("{{}} ").tokenize()).parse_statement()
    expression = Parser(Lexer("1 + 2").tokenize()).parse_expression_only()
    assert len(block.statements) == 1 and block.statements[0].statements == ()
    assert statement == block
    assert expression.left.value == 1 and expression.right.value == 2


def test_missing_semicolon_exposes_expected_and_actual_tokens():
    with pytest.raises(ParseError) as caught:
        parse("START { SHOW(1) }")
    error = caught.value
    assert error.category == "EXPECTED_TOKEN"
    assert error.expected == "SEMICOLON"
    assert error.actual.type is TokenType.RBRACE
    assert (error.line, error.column) == (1, 17)
