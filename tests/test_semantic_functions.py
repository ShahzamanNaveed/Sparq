"""Supported function-body analysis and parameter scope integration."""

from dataclasses import FrozenInstanceError, replace

import pytest

from sparq.ast_nodes import Block, SourceSpan
from sparq.errors import SemanticError
from sparq.function_semantic import FunctionAnalysis, FunctionAnalyzer, check_guaranteed_return
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import StatementAnalyzer
from sparq.symbols import ScalarType as T, SymbolKind


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def analyze(source):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    results = tuple(FunctionAnalyzer(context).analyze_function(fn) for fn in program.functions)
    return program, context, results


def rejected(source, category):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    with pytest.raises(SemanticError) as caught:
        FunctionAnalyzer(context).analyze_function(program.functions[0])
    assert caught.value.category == category
    assert caught.value.line >= 1 and caught.value.column >= 1
    assert context.current_scope is None and context.active_function is None
    return caught.value, context


def test_parameter_scope_shared_with_outer_body_and_nested_shadow_allowed():
    program, context, results = analyze(
        "FUNC f(FLOAT p) -> FLOAT { p = 1; { INT p = 2; INT x = p; } RETURN p; } START {}"
    )
    result, = results
    assignment, nested, returned = program.functions[0].body.statements
    assert result.scope is result.body.scope_of(program.functions[0].body)
    parameter, = result.parameters
    assert parameter.kind is SymbolKind.PARAMETER
    assert result.body.target_of(assignment).symbol is parameter
    assert result.body.declaration_of(nested.statements[0]).id != parameter.id
    assert result.body.return_of(returned).value.annotations.binding_of(returned.value) is parameter
    assert context.current_scope is None and context.active_function is None


def test_outer_body_cannot_redeclare_parameter():
    error, _ = rejected("FUNC f(INT p) -> VOID { INT p; } START {}", "REDECLARATION")
    assert error.name == "p"


def test_separate_function_and_start_scopes_are_isolated():
    program, context, results = analyze(
        "FUNC first(INT p) -> INT { INT local = p; RETURN local; } "
        "FUNC second() -> VOID { INT own; } START { INT main; }"
    )
    first, second = results
    assert first.scope.resolve("local") is first.body.declaration_of(program.functions[0].body.statements[0])
    assert second.scope.resolve("local") is None
    assert second.scope.resolve("p") is None
    assert first.scope.resolve("own") is None
    start_scope = context.begin_start()
    StatementAnalyzer(context).analyze_block(program.main)
    assert start_scope.resolve("p") is None and start_scope.resolve("local") is None
    assert start_scope.resolve("main") is not None


def test_forward_direct_and_mutually_recursive_calls_use_precollected_signatures():
    program, context, results = analyze(
        "FUNC first(INT n) -> INT { RETURN second(n); } "
        "FUNC second(INT n) -> INT { RETURN first(n); } "
        "FUNC self(INT n) -> INT { RETURN self(n); } START {}"
    )
    assert len(results) == 3
    for declaration, result in zip(program.functions, results):
        returned = declaration.body.statements[0]
        value = result.body.return_of(returned).value
        callee = value.annotations.function_of(returned.value)
        assert callee is context.functions.resolve(returned.value.callee)
        assert result.guarantees_return
    assert context.current_scope is None


def test_recursive_call_still_checks_argument_type():
    error, _ = rejected("FUNC f(INT x) -> INT { RETURN f(TRUE); } START {}", "ARGUMENT_TYPE_MISMATCH")
    assert (error.expected, error.actual) == ("INT", "BOOL")


def test_void_function_fallthrough_and_bare_return_are_valid():
    _, _, results = analyze("FUNC a() -> VOID {} FUNC b() -> VOID { RETURN; } START {}")
    assert [result.guarantees_return for result in results] == [False, True]


def test_nonvoid_function_missing_return_is_controlled_and_invalidates_context():
    error, context = rejected("FUNC f() -> INT { INT x; } START {}", "MISSING_RETURN")
    assert error.name == "f" and error.expected == "INT"
    with pytest.raises(ValueError, match="invalid after failed"):
        context.begin_start()


def test_control_flow_requires_validated_branches_before_function_success():
    program = parse(
        "FUNC f() -> INT { WHEN (TRUE) { RETURN 1; } OTHERWISE { RETURN 2; } } START {}"
    )
    assert check_guaranteed_return(program.functions[0].body)
    context = SemanticContext()
    context.collect_signatures(program)
    result = FunctionAnalyzer(context).analyze_function(program.functions[0])
    assert result.guarantees_return
    branch = program.functions[0].body.statements[0]
    assert result.body.condition_of(branch).type.name == "BOOL"
    assert len(result.body.returns) == 2
    assert context.current_scope is None and context.active_function is None


def test_function_result_records_snapshot_parameters_and_reject_false_success():
    program, _, results = analyze("FUNC f(INT p) -> INT { RETURN p; } START {}")
    result, = results
    params = list(result.parameters)
    copied = FunctionAnalysis(
        result.declaration, result.function, result.scope, params,
        result.body, result.guarantees_return,
    )
    params.clear()
    assert copied.parameters == result.parameters
    with pytest.raises(FrozenInstanceError):
        copied.guarantees_return = False
    with pytest.raises(ValueError):
        FunctionAnalysis(result.declaration, result.function, result.scope, (), result.body, True)
    with pytest.raises(ValueError):
        FunctionAnalysis(result.declaration, result.function, result.scope, result.parameters, result.body, False)
    assert result.body.return_of(program.functions[0].body.statements[0]).function is result.function


def test_failed_function_does_not_invalidate_previously_completed_result():
    program = parse(
        "FUNC good() -> INT { RETURN 1; } FUNC bad() -> INT {} START {}"
    )
    context = SemanticContext(); context.collect_signatures(program)
    analyzer = FunctionAnalyzer(context)
    good = analyzer.analyze_function(program.functions[0])
    with pytest.raises(SemanticError) as caught:
        analyzer.analyze_function(program.functions[1])
    assert caught.value.category == "MISSING_RETURN"
    assert good.guarantees_return and good.body.return_of(program.functions[0].body.statements[0])
    with pytest.raises(ValueError, match="invalid after failed"):
        FunctionAnalyzer(context).analyze_function(program.functions[0])


def test_supported_statement_after_return_is_still_validated():
    _, _, results = analyze("FUNC f() -> INT { RETURN 1; SHOW(2); } START {}")
    assert results[0].body.shows
    rejected("FUNC f() -> INT { RETURN 1; SHOW(missing); } START {}", "UNDECLARED_NAME")


def test_deep_function_body_reports_resource_limit_and_clears_context():
    original = parse("FUNC f() -> VOID {} START {}")
    span = SourceSpan(1, 1, 1, 2)
    body = Block((), span)
    for _ in range(1200):
        body = Block((body,), span)
    declaration = replace(original.functions[0], body=body)
    program = replace(original, functions=(declaration,))
    context = SemanticContext(); context.collect_signatures(program)
    with pytest.raises(SemanticError) as caught:
        FunctionAnalyzer(context).analyze_function(declaration)
    assert caught.value.category == "RESOURCE_LIMIT"
    assert context.current_scope is None and context.active_function is None
    with pytest.raises(ValueError, match="invalid after failed"):
        context.begin_start()
