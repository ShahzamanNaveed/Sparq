from sparq.lexer import Lexer
from sparq.parser import Parser


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def bounds(node):
    span = node.span
    return span.start_line, span.start_column, span.end_line, span.end_column


def test_program_function_and_crlf_block_spans():
    source = (
        "FUNC f(INT x) -> INT {\r\n"
        "  RETURN x;\r\n"
        "}\r\n"
        "START {\r\n"
        "  SHOW(1);\r\n"
        "}"
    )
    program = parse(source)
    function, = program.functions
    assert bounds(function) == (1, 1, 3, 2)
    assert bounds(function.params[0]) == (1, 8, 1, 13)
    assert bounds(function.body) == (1, 22, 3, 2)
    assert bounds(program.main) == (4, 7, 6, 2)
    assert bounds(program) == (1, 1, 6, 2)
    assert bounds(program.main.statements[0]) == (5, 3, 5, 11)


def test_declaration_assignment_call_and_nested_block_spans():
    source = "START { INT x = 1; INT a[2] = {1, 2}; x = 3; f(x); { SHOW(x); } }"
    program = parse(source)
    scalar, array, assignment, call, nested = program.main.statements
    assert bounds(scalar) == (1, 9, 1, 19)
    assert bounds(array) == (1, 20, 1, 38)
    assert bounds(assignment) == (1, 39, 1, 45)
    assert bounds(call) == (1, 46, 1, 51)
    assert bounds(call.call) == (1, 46, 1, 50)
    assert bounds(nested) == (1, 52, 1, 64)
    assert bounds(program) == (1, 1, 1, 66)


def test_when_select_repeat_and_do_while_spans_include_full_syntax():
    source = (
        "START {\n"
        " WHEN (x) { SHOW(1); } OTHERWISE { SHOW(2); }\n"
        " SELECT (x) { CASE -1: {} DEFAULT: {} }\n"
        " REPEAT (INT i = 0; i < 2; i = i + 1) {}\n"
        " DO {} WHILE (x);\n"
        "}"
    )
    program = parse(source)
    when, select, repeat, do_while = program.main.statements
    assert bounds(when) == (2, 2, 2, 46)
    assert bounds(when.then_block) == (2, 11, 2, 23)
    assert bounds(when.else_block) == (2, 34, 2, 46)
    assert bounds(select) == (3, 2, 3, 40)
    assert bounds(select.cases[0]) == (3, 15, 3, 26)
    assert bounds(select.cases[0].label) == (3, 20, 3, 22)
    assert bounds(repeat) == (4, 2, 4, 41)
    assert bounds(repeat.initializer) == (4, 10, 4, 19)
    assert bounds(repeat.update) == (4, 28, 4, 37)
    assert bounds(do_while) == (5, 2, 5, 18)
