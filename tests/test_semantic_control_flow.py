"""Parsed control-flow statements and completed semantic records."""

from dataclasses import FrozenInstanceError, replace

import pytest

from sparq.ast_nodes import Block, LiteralExpr, SourceSpan, WhenStmt
from sparq.errors import SemanticError
from sparq.function_semantic import FunctionAnalyzer
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import ConditionUse, StatementAnalyzer
from sparq.symbols import ScalarType
from sparq.token import TokenType


def parsed(source):
    return Parser(Lexer(source).tokenize()).parse()


def start(body, functions=""):
    program = parsed(f"{functions} START {{ {body} }}")
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    return program, context, StatementAnalyzer(context).analyze_block(program.main)


def fails(body, category, functions=""):
    program = parsed(f"{functions} START {{ {body} }}")
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert caught.value.category == category
    assert context._statement_invalid
    return caught.value


@pytest.mark.parametrize("condition", ["TRUE", "FALSE", "1 < 2", "NOT FALSE", "b()"])
def test_boolean_conditions_keep_intrinsic_annotations(condition):
    program, context, result = start(
        f"WHEN ({condition}) {{ SHOW(1); }}",
        "FUNC b() -> BOOL { RETURN TRUE; }",
    )
    branch = program.main.statements[0]
    analysis = result.condition_of(branch)
    assert analysis.root is branch.condition and analysis.type is ScalarType.BOOL
    if condition == "b()":
        assert analysis.annotations.function_of(branch.condition) is context.functions.resolve("b")


@pytest.mark.parametrize("condition, category", [
    ("1", "CONDITION_TYPE"), ("1.5", "CONDITION_TYPE"),
    ("'a'", "CONDITION_TYPE"), ('"a"', "CONDITION_TYPE"),
    ("v()", "VOID_VALUE"), ("a", "ARRAY_AS_SCALAR"),
    ("missing", "UNDECLARED_NAME"),
])
def test_invalid_when_conditions(condition, category):
    fails(f"INT a[1]; WHEN ({condition}) {{}}",
          category, "FUNC v() -> VOID {}")


def test_when_branches_are_sibling_scopes_and_both_checked():
    program, context, result = start(
        "INT x = 1; WHEN (TRUE) { INT x = 2; INT y; } "
        "OTHERWISE { INT x = 3; INT y; } SHOW(x);"
    )
    branch = program.main.statements[1]
    then_scope = result.scope_of(branch.then_block)
    else_scope = result.scope_of(branch.else_block)
    assert then_scope.parent is else_scope.parent is context.current_scope
    assert then_scope.lookup_local("x") is not else_scope.lookup_local("x")
    assert context.current_scope.lookup_local("y") is None
    assert result.show_of(program.main.statements[2]).annotations.binding_of(
        program.main.statements[2].value
    ) is result.declaration_of(program.main.statements[0])
    fails("WHEN (TRUE) {} OTHERWISE { SHOW(missing); }", "UNDECLARED_NAME")


def test_nested_when_and_return_validation_inside_branches():
    program = parsed(
        "FUNC f(FLOAT x) -> FLOAT { WHEN (TRUE) { WHEN (FALSE) { RETURN 1; } "
        "OTHERWISE { RETURN x; } } OTHERWISE { RETURN 2; } } START {}"
    )
    context = SemanticContext(); context.collect_signatures(program)
    result = FunctionAnalyzer(context).analyze_function(program.functions[0])
    assert result.guarantees_return and len(result.body.returns) == 3
    assert sum(record.conversion is not None for record in result.body.returns) == 2
    assert context.active_function is None and context.current_scope is None


@pytest.mark.parametrize("statement", [
    "WHEN (TRUE) { RETURN; }",
    "WHILE (FALSE) { RETURN 1; }",
    "DO { RETURN; } WHILE (FALSE);",
    "REPEAT (;; ) { RETURN; }",
])
def test_return_remains_prohibited_in_start_control_flow(statement):
    fails(statement, "RETURN_OUTSIDE_FUNCTION")


def test_completed_records_require_condition_and_snapshot_collections():
    program, _, result = start("WHEN (TRUE) { INT x; }")
    with pytest.raises(ValueError, match="condition analysis coverage"):
        replace(result, conditions=())
    conditions = list(result.conditions)
    copied = replace(result, conditions=conditions)
    conditions.clear()
    assert copied.conditions == result.conditions
    with pytest.raises(FrozenInstanceError):
        copied.conditions = ()
    assert result.scope_of(program.main.statements[0].then_block) is not None
    with pytest.raises(ValueError, match="block scope record"):
        replace(result, scopes=(result.scopes[0], (result.scopes[1][0], result.scopes[0][1])))
    other = parsed("START { WHEN (FALSE) {} }").main.statements[0]
    with pytest.raises(ValueError):
        ConditionUse(other, result.conditions[0].analysis)


def test_condition_conversions_and_nested_results_keep_owners():
    program, context, result = start(
        "FLOAT x = 1; WHEN (x < 2) { FLOAT y = f(1); SHOW(y); }",
        "FUNC f(FLOAT p) -> INT { RETURN 1; }",
    )
    branch = program.main.statements[1]
    condition = result.condition_of(branch)
    assert condition.annotations.type_of(branch.condition.right) is ScalarType.INT
    assert len(condition.annotations.all_conversions()) == 1
    nested_declaration = branch.then_block.statements[0]
    binding = result.expressions[1].analysis.annotations.call_binding_of(nested_declaration.initializer)
    assert binding.function is context.functions.resolve("f")
    assert len(binding.conversions) == 1
    assert len(result.all_conversions()) == 4  # initializer, condition, argument, nested initializer


def test_failed_nested_branch_cleans_scopes_and_preserves_prior_result():
    program = parsed("START { INT ok = 1; WHEN (TRUE) { INT x; SHOW(missing); } }")
    context = SemanticContext(); context.begin_start(); analyzer = StatementAnalyzer(context)
    prior = analyzer.analyze_statement(program.main.statements[0])
    with pytest.raises(SemanticError) as caught:
        analyzer.analyze_statement(program.main.statements[1])
    assert caught.value.category == "UNDECLARED_NAME"
    assert context.current_scope.parent is None and context.current_scope.lookup_local("x") is None
    assert not context._initializing and context._statement_invalid
    assert prior.declaration_of(program.main.statements[0]).name == "ok"


def test_deep_nested_control_flow_has_controlled_resource_diagnostic():
    span = SourceSpan(1, 1, 1, 2)
    root = Block((), span)
    for _ in range(1200):
        root = Block((WhenStmt(LiteralExpr(TokenType.TRUE, True, "TRUE", span), root, None, span),), span)
    context = SemanticContext(); context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(root)
    assert caught.value.category == "RESOURCE_LIMIT"
