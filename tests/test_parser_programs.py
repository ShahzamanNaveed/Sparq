from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sparq.ast_nodes import (
    AssignStmt, BinaryExpr, Block, CallExpr, FunctionDecl, LiteralExpr,
    Program, ReturnStmt, ScalarDecl, ShowStmt, WhenStmt,
)
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.token import TokenType


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def test_empty_start_is_a_complete_program():
    program = parse("START {}   \n")
    assert isinstance(program, Program)
    assert program.functions == ()
    assert isinstance(program.main, Block)
    assert program.main.statements == ()
    assert (program.span.start_column, program.span.end_column) == (1, 9)
    with pytest.raises(FrozenInstanceError):
        program.functions = ()


@pytest.mark.parametrize("return_type", [
    TokenType.INT, TokenType.FLOAT, TokenType.CHAR, TokenType.STRING,
    TokenType.BOOL, TokenType.VOID,
])
def test_all_function_return_types_parse_without_semantic_checks(return_type):
    program = parse(f"FUNC f() -> {return_type.name} {{ RETURN; }} START {{}}")
    assert program.functions[0].return_type is return_type


def test_multiple_functions_and_all_parameter_types_preserve_order():
    source = (
        "FUNC first() -> VOID { RETURN; }\n"
        "FUNC second(INT i, FLOAT f, CHAR c, STRING s, BOOL b) -> INT {"
        " RETURN i; }\n"
        "START { SHOW(second(1, 2.0, 'x', \"s\", TRUE)); }"
    )
    program = parse(source)
    assert isinstance(program.functions, tuple)
    assert [function.name for function in program.functions] == ["first", "second"]
    first, second = program.functions
    assert isinstance(first, FunctionDecl)
    assert first.params == () and first.return_type is TokenType.VOID
    assert [param.type_name for param in second.params] == [
        TokenType.INT, TokenType.FLOAT, TokenType.CHAR, TokenType.STRING,
        TokenType.BOOL,
    ]
    assert [param.name for param in second.params] == ["i", "f", "c", "s", "b"]
    assert isinstance(second.params, tuple)
    assert second.return_type is TokenType.INT
    assert isinstance(first.body.statements[0], ReturnStmt)
    assert isinstance(second.body.statements[0], ReturnStmt)
    assert isinstance(program.main.statements[0].value, CallExpr)
    assert len(program.main.statements[0].value.args) == 5
    assert program.span.start_line == 1
    assert program.span.end_line == 3


def test_hello_example_has_expected_ast():
    path = Path(__file__).resolve().parents[1] / "examples" / "hello.spq"
    program = parse(path.read_text(encoding="utf-8"))
    assert program.functions == ()
    assert len(program.main.statements) == 1
    statement = program.main.statements[0]
    assert isinstance(statement, ShowStmt)
    assert isinstance(statement.value, LiteralExpr)
    assert statement.value.kind is TokenType.STRING_LITERAL
    assert statement.value.value == "Hello from Sparq!"


def test_representative_program_preserves_statement_order_and_expression_shapes():
    source = """FUNC add(INT a, INT b) -> INT { RETURN a + b; }
START {
    INT total = add(1, 2);
    WHEN (total >= 3) { SHOW("ok"); } OTHERWISE { SHOW("low"); }
    total = total + 1;
    SHOW(total);
}"""
    program = parse(source)
    assert [type(stmt) for stmt in program.main.statements] == [
        ScalarDecl, WhenStmt, AssignStmt, ShowStmt,
    ]
    assert isinstance(program.functions[0].body.statements[0].value, BinaryExpr)
    assert isinstance(program.main.statements[0].initializer, CallExpr)
    assert program.main.statements[0].initializer.callee == "add"
    assert program.main.statements[0].initializer.args[0].value == 1
    assert program.main.statements[0].initializer.args[1].value == 2


def test_syntactically_valid_semantic_errors_remain_for_later_phase():
    program = parse("""START {
        RETURN;
        INT missing = unknown;
        FLOAT wrong = TRUE;
        INT zero[0] = {1, 2};
        SHOW(doesNotExist());
    }""")
    assert len(program.main.statements) == 5
    assert program.main.statements[3].size.value == 0
    assert len(program.main.statements[3].initializers) == 2
