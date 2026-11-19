"""WHILE, DO-WHILE, and REPEAT scopes and component metadata."""

from dataclasses import replace

import pytest

from sparq.errors import SemanticError
from sparq.function_semantic import FunctionAnalyzer
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import StatementAnalyzer
from sparq.symbols import ScalarType


def parsed(source):
    return Parser(Lexer(source).tokenize()).parse()


def start(body):
    program = parsed(f"START {{ {body} }}")
    context = SemanticContext(); context.begin_start()
    return program, context, StatementAnalyzer(context).analyze_block(program.main)


def error(body, category):
    with pytest.raises(SemanticError) as caught:
        start(body)
    assert caught.value.category == category


def test_while_condition_and_body_scope():
    program, context, result = start("INT x; WHILE (x < 2) { INT y; x = x + 1; }")
    loop = program.main.statements[1]
    assert result.condition_of(loop).type is ScalarType.BOOL
    assert result.scope_of(loop.body).parent is context.current_scope
    assert context.current_scope.lookup_local("y") is None
    error("WHILE (1) {}", "CONDITION_TYPE")
    error("WHILE (TRUE) { INT y; } SHOW(y);", "UNDECLARED_NAME")


def test_do_condition_uses_enclosing_scope_and_is_checked_after_body():
    program, context, result = start("INT x; DO { INT y; x = 1; } WHILE (x < 2);")
    loop = program.main.statements[1]
    assert result.condition_of(loop).type is ScalarType.BOOL
    assert result.scope_of(loop.body).parent is context.current_scope
    error("DO { INT y; } WHILE (y < 2);", "UNDECLARED_NAME")
    error("DO { SHOW(missing); } WHILE (1);", "UNDECLARED_NAME")


def test_repeat_header_and_body_have_distinct_nested_scopes():
    program, context, result = start(
        "INT i = 9; REPEAT (INT i = 0; i < 3; i = i + 1) { INT j = i; INT i = 4; } "
        "SHOW(i);"
    )
    loop = program.main.statements[1]
    header = result.repeat_scope_of(loop)
    body = result.scope_of(loop.body)
    assert header.parent is context.current_scope and body.parent is header
    assert result.declaration_of(loop.initializer) is header.lookup_local("i")
    assert body.lookup_local("i") is not header.lookup_local("i")
    assert result.target_of(loop.update).symbol is header.lookup_local("i")
    assert result.condition_of(loop).type is ScalarType.BOOL
    assert context.current_scope.lookup_local("j") is None
    assert result.show_of(program.main.statements[2]).annotations.binding_of(
        program.main.statements[2].value
    ) is result.declaration_of(program.main.statements[0])
    with pytest.raises(ValueError, match="REPEAT scope coverage"):
        replace(result, repeat_scopes=())


def test_repeat_initializer_assignment_omissions_and_conversions():
    program, _, result = start(
        "FLOAT f; INT i; REPEAT (f = 1; ; i = i + 1) { SHOW(f); } REPEAT (;; ) {}"
    )
    first, second = program.main.statements[2:]
    assert result.target_of(first.initializer).symbol.name == "f"
    assert result.condition_of(first) is None
    assert result.condition_of(second) is None
    assert len([site for site in result.conversions if site.parent is first.initializer]) == 1
    assert result.repeat_scope_of(first) is not result.repeat_scope_of(second)
    error("REPEAT (INT i = i; TRUE; i = i + 1) {}", "READ_BEFORE_INITIALIZATION")
    error("INT i; REPEAT (; TRUE; i = TRUE) {}", "TYPE_MISMATCH")
    error("REPEAT (; 1; ) {}", "CONDITION_TYPE")


def test_repeat_visibility_and_scope_restoration():
    error("REPEAT (INT i = 0; TRUE; i = i + 1) {} SHOW(i);", "UNDECLARED_NAME")
    error("REPEAT (INT i = 0; TRUE; i = body) { INT body; }", "UNDECLARED_NAME")
    error("REPEAT (INT i = 0; body < 2; i = i + 1) { INT body; }", "UNDECLARED_NAME")
    program, context, result = start(
        "REPEAT (INT i = 0; i < 2; i = i + 1) { "
        "REPEAT (INT i = 0; i < 1; i = i + 1) { SHOW(i); } } "
        "REPEAT (INT i = 0; i < 1; i = i + 1) {}"
    )
    assert len(result.repeat_scopes) == 3
    assert len({scope.id for _, scope in result.repeat_scopes}) == 3
    assert context.current_scope.lookup_local("i") is None


def test_repeat_failure_exits_header_and_body_scopes():
    program = parsed("START { INT outer; REPEAT (INT i = 0; TRUE; i = i + 1) { SHOW(missing); } }")
    context = SemanticContext(); context.begin_start(); analyzer = StatementAnalyzer(context)
    completed = analyzer.analyze_statement(program.main.statements[0])
    with pytest.raises(SemanticError) as caught:
        analyzer.analyze_statement(program.main.statements[1])
    assert caught.value.category == "UNDECLARED_NAME"
    assert context.current_scope.parent is None
    assert context.current_scope.lookup_local("i") is None
    assert not context._initializing and context._statement_invalid
    assert completed.declaration_of(program.main.statements[0]).name == "outer"


def test_loop_return_guarantees_remain_conservative_and_conditions_checked():
    cases = [
        ("DO { RETURN 1; } WHILE (TRUE);", True),
        ("WHILE (TRUE) { RETURN 1; }", False),
        ("REPEAT (;; ) { RETURN 1; }", False),
    ]
    for body, expected in cases:
        program = parsed(f"FUNC f() -> INT {{ {body} }} START {{}}")
        context = SemanticContext(); context.collect_signatures(program)
        if expected:
            assert FunctionAnalyzer(context).analyze_function(program.functions[0]).guarantees_return
        else:
            with pytest.raises(SemanticError) as caught:
                FunctionAnalyzer(context).analyze_function(program.functions[0])
            assert caught.value.category == "MISSING_RETURN"
    program = parsed("FUNC f() -> INT { DO { RETURN 1; } WHILE (1); } START {}")
    context = SemanticContext(); context.collect_signatures(program)
    with pytest.raises(SemanticError) as caught:
        FunctionAnalyzer(context).analyze_function(program.functions[0])
    assert caught.value.category == "CONDITION_TYPE"
