from itertools import product

import pytest

from sparq.ast_nodes import (
    ArrayAccess, ArrayDecl, AssignStmt, BinaryExpr, Block, CallExpr,
    CallStmt, DoWhileStmt, ForStmt, LiteralExpr, ReadStmt, ReturnStmt,
    ScalarDecl, SelectStmt, ShowStmt, UnaryExpr, VarRef, WhenStmt, WhileStmt,
)
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.token import TokenType


def statements(source):
    return Parser(Lexer("START { " + source + " }").tokenize()).parse().main.statements


@pytest.mark.parametrize(("source", "kind", "name", "value"), [
    ("INT age;", TokenType.INT, "age", None),
    ("INT age = 20;", TokenType.INT, "age", 20),
    ("FLOAT value = 3.5;", TokenType.FLOAT, "value", 3.5),
    ("CHAR initial = 'A';", TokenType.CHAR, "initial", "A"),
    ('STRING name = "Sparq";', TokenType.STRING, "name", "Sparq"),
    ("BOOL active = TRUE;", TokenType.BOOL, "active", True),
])
def test_scalar_declarations(source, kind, name, value):
    declaration, = statements(source)
    assert isinstance(declaration, ScalarDecl)
    assert (declaration.type_name, declaration.name) == (kind, name)
    if value is None:
        assert declaration.initializer is None
    else:
        assert isinstance(declaration.initializer, LiteralExpr)
        assert declaration.initializer.value == value


def test_array_declarations_and_initializer_order():
    plain, initialized = statements(
        "INT plain[03]; INT numbers[3] = {1, add(2, 3), 4 + 5};"
    )
    assert isinstance(plain, ArrayDecl)
    assert plain.element_type is TokenType.INT and plain.name == "plain"
    assert (plain.size.lexeme, plain.size.value) == ("03", 3)
    assert plain.initializers is None
    assert isinstance(initialized, ArrayDecl)
    assert initialized.size.value == 3
    assert isinstance(initialized.initializers, tuple)
    assert [type(expr) for expr in initialized.initializers] == [
        LiteralExpr, CallExpr, BinaryExpr,
    ]
    assert initialized.initializers[1].callee == "add"
    assert initialized.initializers[2].operator is TokenType.PLUS


def test_scalar_indexed_assignments_and_calls():
    scalar, indexed, call = statements(
        "x = 10; values[i + 1] = f(20); showResult(f(1), values[0]);"
    )
    assert isinstance(scalar, AssignStmt) and isinstance(scalar.target, VarRef)
    assert scalar.target.name == "x" and scalar.value.value == 10
    assert isinstance(indexed, AssignStmt)
    assert isinstance(indexed.target, ArrayAccess)
    assert indexed.target.name == "values"
    assert indexed.target.index.operator is TokenType.PLUS
    assert isinstance(indexed.value, CallExpr) and indexed.value.callee == "f"
    assert isinstance(call, CallStmt) and call.call.callee == "showResult"
    assert isinstance(call.call.args, tuple)
    assert [type(arg) for arg in call.call.args] == [CallExpr, ArrayAccess]


def test_when_otherwise_and_nested_when():
    outer, = statements("WHEN (x) { WHEN (y) {} } OTHERWISE { SHOW(1); }")
    assert isinstance(outer, WhenStmt)
    assert isinstance(outer.condition, VarRef)
    assert isinstance(outer.then_block.statements[0], WhenStmt)
    assert outer.then_block.statements[0].else_block is None
    assert isinstance(outer.else_block, Block)
    assert isinstance(outer.else_block.statements[0], ShowStmt)


def test_select_empty_cases_labels_and_default():
    empty, populated = statements(
        "SELECT (x) {} "
        "SELECT (x) { CASE 01: {} CASE -2: {} CASE 'a': {} "
        'CASE "s": {} DEFAULT: { SHOW(0); } }'
    )
    assert isinstance(empty, SelectStmt)
    assert empty.cases == () and empty.default is None
    assert isinstance(populated.cases, tuple) and len(populated.cases) == 4
    labels = [case.label for case in populated.cases]
    assert isinstance(labels[0], LiteralExpr)
    assert (labels[0].lexeme, labels[0].value) == ("01", 1)
    assert isinstance(labels[1], UnaryExpr)
    assert labels[1].operator is TokenType.MINUS
    assert labels[1].operand.value == 2
    assert [label.value for label in (labels[2], labels[3])] == ["a", "s"]
    assert isinstance(populated.default.statements[0], ShowStmt)


def test_select_default_without_cases():
    select, = statements("SELECT (value) { DEFAULT: { SHOW(value); } }")
    assert select.cases == ()
    assert isinstance(select.default.statements[0], ShowStmt)


def test_repeat_header_all_forms_and_no_extra_semicolon():
    declared, assigned, empty = statements(
        "REPEAT (INT i = 0; i < 5; i = i + 1) { SHOW(i); } "
        "REPEAT (a[0] = 1; ; a[1] = 2) {} "
        "REPEAT (; ; ) {}"
    )
    assert isinstance(declared, ForStmt)
    assert isinstance(declared.initializer, ScalarDecl)
    assert declared.initializer.name == "i"
    assert isinstance(declared.condition, BinaryExpr)
    assert isinstance(declared.update, AssignStmt)
    assert isinstance(declared.body.statements[0], ShowStmt)
    assert isinstance(assigned.initializer, AssignStmt)
    assert isinstance(assigned.initializer.target, ArrayAccess)
    assert assigned.condition is None
    assert isinstance(assigned.update.target, ArrayAccess)
    assert isinstance(empty, ForStmt)
    assert (empty.initializer, empty.condition, empty.update) == (None, None, None)


def test_repeat_header_components_can_be_present_independently():
    init_only, condition_only, update_only = statements(
        "REPEAT (x = 1; ; ) {} "
        "REPEAT (; x < 3; ) {} "
        "REPEAT (; ; x = 2) {}"
    )
    assert isinstance(init_only.initializer, AssignStmt)
    assert init_only.condition is None and init_only.update is None
    assert condition_only.initializer is None
    assert condition_only.condition.operator is TokenType.LESS
    assert condition_only.update is None
    assert update_only.initializer is None and update_only.condition is None
    assert isinstance(update_only.update, AssignStmt)


@pytest.mark.parametrize(("has_init", "has_condition", "has_update"), [
    combination for combination in product((False, True), repeat=3)
])
def test_all_repeat_optional_header_combinations(has_init, has_condition, has_update):
    header = "; ".join((
        "i = 0" if has_init else "",
        "i < 5" if has_condition else "",
        "i = i + 1" if has_update else "",
    ))
    loop, = statements(f"REPEAT ({header}) {{}}")
    assert isinstance(loop, ForStmt)
    assert (
        loop.initializer is not None,
        loop.condition is not None,
        loop.update is not None,
    ) == (has_init, has_condition, has_update)


def test_while_do_while_and_nested_blocks():
    loop, do_loop, block = statements(
        "WHILE (x) { SHOW(x); } DO { x = 1; } WHILE (x); { { SHOW(1); } }"
    )
    assert isinstance(loop, WhileStmt)
    assert isinstance(loop.body.statements[0], ShowStmt)
    assert isinstance(do_loop, DoWhileStmt)
    assert isinstance(do_loop.body.statements[0], AssignStmt)
    assert isinstance(block, Block)
    assert isinstance(block.statements[0], Block)


def test_return_read_and_show_forms():
    bare, valued, scalar, indexed, output = statements(
        "RETURN; RETURN 1 + 2; READ(x); READ(items[i]); SHOW(f(1));"
    )
    assert isinstance(bare, ReturnStmt) and bare.value is None
    assert isinstance(valued.value, BinaryExpr)
    assert isinstance(scalar, ReadStmt) and isinstance(scalar.target, VarRef)
    assert isinstance(indexed.target, ArrayAccess)
    assert isinstance(output, ShowStmt) and isinstance(output.value, CallExpr)
