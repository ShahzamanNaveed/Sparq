"""Function-call semantics through lexer, parser, and semantic analysis."""

from dataclasses import FrozenInstanceError

import pytest

from sparq.ast_nodes import CallExpr, SourceSpan
from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import (
    ArgumentConversionSite, CallAnalysis, CallBinding, ExpressionAnalyzer,
    ExpressionAnnotations, SemanticContext,
)
from sparq.statement_semantic import StatementAnalysis, StatementAnalyzer
from sparq.symbols import ScalarType as T


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def start(source):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    return program, context, StatementAnalyzer(context).analyze_block(program.main)


def failed(source, category):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert caught.value.category == category
    assert caught.value.line >= 1 and caught.value.column >= 1
    return caught.value


def test_zero_argument_call_expression_and_discarded_nonvoid_statement():
    program, context, result = start(
        "FUNC f() -> INT { RETURN 1; } START { INT x = f(); f(); }"
    )
    declaration, call_statement = program.main.statements
    call = declaration.initializer
    use = result.expressions[0]
    binding = use.analysis.annotations.call_binding_of(call)
    assert use.analysis.type is T.INT
    assert binding.function is context.functions.resolve("f")
    assert binding.argument_types == binding.conversions == ()
    discarded = result.call_of(call_statement)
    assert discarded.binding.function is binding.function
    assert discarded.binding.return_type is T.INT
    assert discarded.annotations.call_binding_of(call_statement.call) is discarded.binding


def test_void_standalone_call_and_multiple_argument_conversions():
    program, _, result = start(
        "FUNC f(FLOAT a, INT b, FLOAT c) -> VOID { RETURN; } "
        "START { f(1, 2, 3); }"
    )
    call_statement = program.main.statements[0]
    analysis = result.call_of(call_statement)
    assert [kind.name for kind in analysis.binding.argument_types] == ["INT", "INT", "INT"]
    assert [site.index for site in analysis.binding.conversions] == [0, 2]
    assert all(site.function is analysis.binding.function for site in analysis.binding.conversions)
    assert [analysis.annotations.type_of(arg) for arg in call_statement.call.args] == [T.INT] * 3
    assert result.all_conversions() == analysis.binding.conversions


@pytest.mark.parametrize("args, category, expected, actual", [
    ("", "ARGUMENT_COUNT", "1", "0"),
    ("1, missing", "ARGUMENT_COUNT", "1", "2"),
])
def test_argument_count_precedes_argument_expression_errors(args, category, expected, actual):
    error = failed(
        f"FUNC f(INT x) -> INT {{ RETURN x; }} START {{ INT y = f({args}); }}",
        category,
    )
    assert (error.name, error.expected, error.actual) == ("f", expected, actual)


def test_unknown_function_and_variable_namespace_are_separate():
    error = failed("START { INT missing; missing(); }", "UNKNOWN_FUNCTION")
    assert error.name == "missing"
    program, context, result = start(
        "FUNC f() -> INT { RETURN 1; } START { INT f = 2; INT x = f + f(); { INT f = 3; f(); } }"
    )
    outer, x, nested = program.main.statements
    use = next(use for use in result.expressions if use.parent is x)
    assert use.analysis.annotations.binding_of(x.initializer.left) is result.declaration_of(outer)
    assert use.analysis.annotations.function_of(x.initializer.right) is context.functions.resolve("f")
    assert result.call_of(nested.statements[1]).binding.function is context.functions.resolve("f")


_LITERALS = {
    "INT": "1", "FLOAT": "2.5", "CHAR": "'a'", "STRING": '"a"', "BOOL": "TRUE",
}


@pytest.mark.parametrize("destination", _LITERALS)
@pytest.mark.parametrize("source", _LITERALS)
def test_all_ordered_parameter_argument_type_pairs(destination, source):
    source_text = (
        f"FUNC f({destination} p) -> INT {{ RETURN 1; }} "
        f"START {{ INT x = f({_LITERALS[source]}); }}"
    )
    expected_conversion = (destination, source) == ("FLOAT", "INT")
    if destination != source and not expected_conversion:
        error = failed(source_text, "ARGUMENT_TYPE_MISMATCH")
        assert (error.expected, error.actual) == (destination, source)
    else:
        program, _, result = start(source_text)
        call = program.main.statements[0].initializer
        binding = result.expressions[0].analysis.annotations.call_binding_of(call)
        assert binding.argument_types[0].name == source
        assert len(binding.conversions) == int(expected_conversion)


def test_nested_calls_and_operator_conversions_keep_distinct_owners():
    program, context, result = start(
        "FUNC inner(INT x) -> INT { RETURN x; } "
        "FUNC outer(FLOAT x) -> FLOAT { RETURN x; } "
        "START { FLOAT y = outer(inner(1) + 2); }"
    )
    expression = program.main.statements[0].initializer
    use = result.expressions[0]
    outer = use.analysis.annotations.call_binding_of(expression)
    inner_call = expression.args[0].left
    inner = use.analysis.annotations.call_binding_of(inner_call)
    assert outer.function is context.functions.resolve("outer")
    assert inner.function is context.functions.resolve("inner")
    assert len(outer.conversions) == 1 and outer.conversions[0].index == 0
    assert use.analysis.annotations.type_of(expression.args[0]) is T.INT
    assert use.analysis.annotations.type_of(inner_call) is T.INT
    assert result.conversions == ()


def test_float_valued_argument_retains_only_binary_operand_conversion():
    program, _, result = start(
        "FUNC f(FLOAT x) -> INT { RETURN 1; } START { INT y = f(1 + 2.5); }"
    )
    call = program.main.statements[0].initializer
    use = result.expressions[0]
    assert use.analysis.annotations.call_binding_of(call).conversions == ()
    operator_sites = use.analysis.annotations.conversions_for(call.args[0])
    assert len(operator_sites) == 1
    assert operator_sites[0].operand is call.args[0].left
    assert result.all_conversions() == operator_sites


def test_arguments_are_checked_left_to_right_after_count_validation():
    error = failed(
        "FUNC f(INT a, INT b) -> INT { RETURN 1; } "
        "START { INT x = f(TRUE, missing); }", "ARGUMENT_TYPE_MISMATCH",
    )
    assert error.name == "f" and "argument 1" in error.message


def test_conversion_metadata_follows_argument_then_statement_source_order():
    program, _, result = start(
        "FUNC f(FLOAT a, FLOAT b) -> VOID { RETURN; } "
        "START { f(1, 2 + 3.5); FLOAT x = 4; }"
    )
    call_statement, declaration = program.main.statements
    call = result.call_of(call_statement)
    first_site, = call.binding.conversions
    binary_site, = call.annotations.conversions_for(call_statement.call.args[1])
    declaration_site, = result.conversions
    assert declaration_site.parent is declaration
    assert call.annotations.all_conversions() == (first_site, binary_site)
    assert result.all_conversions() == (first_site, binary_site, declaration_site)


@pytest.mark.parametrize("body", [
    "INT x = v();",
    "INT a[1] = {v()};",
    "INT x; x = v();",
    "INT x = v() + 1;",
    "BOOL b = v() == 1;",
    "BOOL b = TRUE AND v();",
    "INT a[1]; a[v()] = 1;",
    "INT x = take(v());",
])
def test_void_call_cannot_supply_a_scalar_value(body):
    error = failed(
        "FUNC v() -> VOID { RETURN; } FUNC take(INT x) -> INT { RETURN x; } "
        f"START {{ {body} }}", "VOID_VALUE",
    )
    assert error.name == "v"


@pytest.mark.parametrize("source, category", [
    ("FUNC f(INT x) -> VOID { RETURN; } START { f(); }", "ARGUMENT_COUNT"),
    ("FUNC f(INT x) -> VOID { RETURN; } START { f(TRUE); }", "ARGUMENT_TYPE_MISMATCH"),
    ("START { missing(); }", "UNKNOWN_FUNCTION"),
])
def test_call_statement_rejects_bad_signature_uses(source, category):
    failed(source, category)


def test_array_element_argument_is_scalar_but_whole_array_is_not():
    program, _, result = start(
        "FUNC f(INT x) -> INT { RETURN x; } START { INT a[1]; INT y = f(a[0]); }"
    )
    assert result.expressions[0].analysis.type is T.INT
    failed("FUNC f(INT x) -> INT { RETURN x; } START { INT a[1]; INT y = f(a); }", "ARRAY_AS_SCALAR")


def test_self_reads_through_call_arguments_stay_rejected():
    failed("FUNC f(INT x) -> INT { RETURN x; } START { INT x = f(x); }", "READ_BEFORE_INITIALIZATION")
    failed("FUNC f(INT x) -> INT { RETURN x; } START { INT a[1] = {f(a[0])}; }", "READ_BEFORE_INITIALIZATION")


def test_argument_record_invariants_and_collection_snapshots():
    program, _, result = start("FUNC f(FLOAT x) -> INT { RETURN 1; } START { INT y = f(1); }")
    call = program.main.statements[0].initializer
    binding = result.expressions[0].analysis.annotations.call_binding_of(call)
    site, = binding.conversions
    assert ArgumentConversionSite(call, binding.function, call.args[0], 0, T.INT, T.FLOAT)
    with pytest.raises(ValueError):
        ArgumentConversionSite(call, binding.function, call.args[0], 1, T.INT, T.FLOAT)
    with pytest.raises(ValueError):
        ArgumentConversionSite(call, binding.function, call, 0, T.INT, T.FLOAT)
    with pytest.raises(ValueError):
        ArgumentConversionSite(call, binding.function, call.args[0], 0, T.FLOAT, T.INT)
    with pytest.raises(ValueError):
        CallBinding(call, binding.function, (T.INT,), ())
    types = [T.INT]
    sites = [site]
    copied = CallBinding(call, binding.function, types, sites)
    types.clear(); sites.clear()
    assert copied.argument_types == (T.INT,) and copied.conversions == (site,)
    with pytest.raises(FrozenInstanceError):
        copied.function = None
    with pytest.raises(ValueError):
        CallAnalysis(call, binding, ExpressionAnnotations())


def test_call_binding_rejects_wrong_owner_and_argument_metadata():
    program, context, result = start("FUNC f(INT x) -> INT { RETURN x; } START { INT y = f(1); }")
    call = program.main.statements[0].initializer
    binding = result.expressions[0].analysis.annotations.call_binding_of(call)
    wrong = Parser(Lexer("f(2)").tokenize()).parse_expression_only()
    with pytest.raises(ValueError):
        CallAnalysis(wrong, binding, ExpressionAnnotations())
    with pytest.raises(ValueError):
        CallBinding(call, binding.function, (T.FLOAT,), ())
    assert context.functions.resolve("f") is binding.function


def test_completed_statement_result_requires_call_metadata():
    program, _, result = start("FUNC f() -> VOID {} START { f(); }")
    with pytest.raises(ValueError, match="call statement coverage"):
        StatementAnalysis(
            program.main, result.declarations, result.targets, result.expressions,
            result.defaults, result.conversions, result.scopes,
        )


def test_failed_call_invalidates_context_without_changing_prior_result():
    program = parse("FUNC f(INT x) -> VOID {} START { INT ok = 1; f(TRUE); }")
    context = SemanticContext(); context.collect_signatures(program); context.begin_start()
    analyzer = StatementAnalyzer(context)
    completed = analyzer.analyze_statement(program.main.statements[0])
    with pytest.raises(SemanticError) as caught:
        analyzer.analyze_statement(program.main.statements[1])
    assert caught.value.category == "ARGUMENT_TYPE_MISMATCH"
    assert completed.declaration_of(program.main.statements[0]).name == "ok"
    with pytest.raises(ValueError, match="invalid after failed"):
        StatementAnalyzer(context).analyze_statement(program.main.statements[0])


def test_deep_call_tree_reports_controlled_resource_limit():
    program = parse("FUNC f(INT x) -> INT { RETURN x; } START {}")
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    root = Parser(Lexer("1").tokenize()).parse_expression_only()
    span = SourceSpan(1, 1, 1, 2)
    for _ in range(1200):
        root = CallExpr("f", (root,), span)
    with pytest.raises(SemanticError) as caught:
        ExpressionAnalyzer(context).infer(root)
    assert caught.value.category == "RESOURCE_LIMIT"
