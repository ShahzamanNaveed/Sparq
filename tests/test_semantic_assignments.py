"""Assignment compatibility, writable locations, and use-site annotations."""

from dataclasses import FrozenInstanceError, replace

import pytest

from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import (
    ExpressionUse, StatementAnalysis, StatementAnalyzer, StatementConversionSite,
    WritableTarget,
)
from sparq.symbols import ScalarType as T, SymbolKind


LITERALS = {"INT": "1", "FLOAT": "2.5", "CHAR": "'a'", "STRING": '"a"', "BOOL": "TRUE"}


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def analyze(source):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    return program, context, StatementAnalyzer(context).analyze_block(program.main)


def rejected(source, category):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert caught.value.category == category
    assert caught.value.line >= 1 and caught.value.column >= 1
    return caught.value


@pytest.mark.parametrize("destination", LITERALS)
@pytest.mark.parametrize("source", LITERALS)
def test_all_ordered_scalar_assignment_type_pairs(destination, source):
    program = parse(f"START {{ {destination} x; x = {LITERALS[source]}; }}")
    context = SemanticContext()
    context.begin_start()
    if destination != source and (destination, source) != ("FLOAT", "INT"):
        with pytest.raises(SemanticError) as caught:
            StatementAnalyzer(context).analyze_block(program.main)
        assert (caught.value.category, caught.value.expected, caught.value.actual) == (
            "TYPE_MISMATCH", destination, source,
        )
    else:
        result = StatementAnalyzer(context).analyze_block(program.main)
        assignment = program.main.statements[1]
        target = result.target_of(assignment)
        assert target.symbol is result.declaration_of(program.main.statements[0])
        assert target.type.name == destination
        assert result.expressions[0].analysis.type.name == source
        assert len(result.conversions) == int((destination, source) == ("FLOAT", "INT"))


def test_parameter_assignment_reuses_existing_outer_function_scope():
    program = parse("FUNC f(FLOAT p) -> VOID { p = 1; } START {}")
    context = SemanticContext()
    context.collect_signatures(program)
    outer = context.begin_function(program.functions[0])
    result = StatementAnalyzer(context).analyze_block(program.functions[0].body)
    assignment = program.functions[0].body.statements[0]
    target = result.target_of(assignment)
    assert target.symbol.kind is SymbolKind.PARAMETER
    assert target.symbol is outer.resolve("p")
    assert result.scope_of(program.functions[0].body) is outer
    assert result.conversions[0].parent is assignment


@pytest.mark.parametrize("source, category", [
    ("START { missing = 1; }", "UNDECLARED_NAME"),
    ("FUNC f() -> INT { RETURN 1; } START { f = 1; }", "FUNCTION_AS_TARGET"),
    ("START { INT a[2]; a = 1; }", "WHOLE_ARRAY_ASSIGNMENT"),
    ("START { INT x; x[0] = 1; }", "WRONG_SYMBOL_KIND"),
    ("START { a[0] = 1; }", "UNDECLARED_NAME"),
])
def test_invalid_assignment_targets(source, category):
    rejected(source, category)


@pytest.mark.parametrize("index", ["2.5", "TRUE", "'a'", '"a"'])
def test_non_int_array_indexes_rejected(index):
    error = rejected(f"START {{ INT a[2]; a[{index}] = 1; }}", "INDEX_TYPE")
    assert (error.name, error.expected) == ("a", "INT")


@pytest.mark.parametrize("index", ["0", "100", "-1", "1 / 0", "2 % 0"])
def test_int_indexes_remain_runtime_values(index):
    program, _, result = analyze(f"START {{ INT a[2]; a[{index}] = 1; }}")
    target = result.target_of(program.main.statements[1])
    assert target.index_analysis.type is T.INT
    assert result.expressions[0].role == "target_index"
    assert result.expressions[1].role == "value"


def test_index_error_precedes_rhs_call_analysis():
    error = rejected("FUNC f() -> INT { RETURN 1; } START { INT a[2]; a[TRUE] = f(); }", "INDEX_TYPE")
    assert error.name == "a"


def test_array_assignment_conversion_and_intrinsic_expression_conversions():
    program, _, result = analyze("START { FLOAT a[2]; a[0] = 1; a[1] = 1 + 2.5; }")
    first, second = program.main.statements[1:]
    assert len(result.conversions) == 1
    site, = result.conversions
    assert (site.parent, site.operand, site.role, site.element_index) == (
        first, first.value, "value", None,
    )
    second_use = next(use for use in result.expressions if use.parent is second and use.role == "value")
    assert second_use.analysis.type is T.FLOAT
    assert second_use.analysis.annotations.type_of(second.value.left) is T.INT
    binary_sites = second_use.analysis.annotations.conversions_for(second.value)
    assert len(binary_sites) == 1
    assert binary_sites[0].parent is second.value
    assert result.all_conversions() == (site, binary_sites[0])


def test_scalar_assignment_rhs_call_is_validated():
    program, _, result = analyze("FUNC f() -> INT { RETURN 1; } START { INT x; x = f(); }")
    assignment = program.main.statements[1]
    use = next(use for use in result.expressions if use.parent is assignment)
    assert use.analysis.type is T.INT
    assert use.analysis.annotations.function_of(assignment.value) is not None


def test_writable_target_resolution_can_be_reused_without_reading_value():
    program = parse("START { INT a[2]; a[1] = 3; }")
    context = SemanticContext()
    context.begin_start()
    analyzer = StatementAnalyzer(context)
    declaration, assignment = program.main.statements
    first = analyzer.analyze_statement(declaration)
    target = analyzer.resolve_writable(assignment.target)
    assert target.symbol is first.declaration_of(declaration)
    assert target.index_analysis.type is T.INT
    assert target.span is assignment.target.span
    with pytest.raises(FrozenInstanceError):
        target.type = T.FLOAT


def test_direct_conversion_record_rejects_wrong_owner_operand_and_types():
    program = parse("START { FLOAT x = 1; x = 2; }")
    declaration, assignment = program.main.statements
    with pytest.raises(ValueError):
        StatementConversionSite(declaration, assignment.value, "initializer", T.INT, T.FLOAT)
    with pytest.raises(ValueError):
        StatementConversionSite(assignment, assignment.value, "value", T.FLOAT, T.FLOAT)
    with pytest.raises(ValueError):
        StatementConversionSite(assignment, assignment.value, "element", T.INT, T.FLOAT)


def test_distinct_equal_expression_uses_have_distinct_owners():
    program, _, result = analyze("START { FLOAT a = 1; FLOAT b = 1; }")
    first, second = program.main.statements
    assert first.initializer.value == second.initializer.value
    assert first.initializer is not second.initializer
    assert result.conversions[0].parent is first
    assert result.conversions[1].parent is second
    assert result.conversions[0].operand is first.initializer
    assert result.conversions[1].operand is second.initializer


def test_manually_shared_expression_has_separate_use_site_conversions():
    program = parse("START { FLOAT a = 1; FLOAT b = 2; }")
    first, second = program.main.statements
    shared = first.initializer
    second = replace(second, initializer=shared)
    context = SemanticContext()
    context.begin_start()
    analyzer = StatementAnalyzer(context)
    first_result = analyzer.analyze_statement(first)
    second_result = analyzer.analyze_statement(second)
    assert first_result.conversions[0].operand is shared
    assert second_result.conversions[0].operand is shared
    assert first_result.conversions[0].parent is first
    assert second_result.conversions[0].parent is second
    assert first_result.expressions[0].analysis is not second_result.expressions[0].analysis


def test_shared_variable_expression_in_different_scopes_keeps_both_bindings():
    program = parse("START { INT x; INT y = x; { FLOAT x; FLOAT z = x; } }")
    outer_x, outer_y, nested = program.main.statements
    inner_x, inner_z = nested.statements
    shared = outer_y.initializer
    inner_z = replace(inner_z, initializer=shared)
    context = SemanticContext()
    context.begin_start()
    analyzer = StatementAnalyzer(context)
    outer_symbol = analyzer.analyze_statement(outer_x).declaration_of(outer_x)
    outer_result = analyzer.analyze_statement(outer_y)
    context.enter_block()
    try:
        inner_symbol = analyzer.analyze_statement(inner_x).declaration_of(inner_x)
        inner_result = analyzer.analyze_statement(inner_z)
    finally:
        context.exit_scope()
    assert outer_result.expressions[0].analysis.annotations.binding_of(shared) is outer_symbol
    assert inner_result.expressions[0].analysis.annotations.binding_of(shared) is inner_symbol
    assert outer_result.expressions[0].analysis.type is T.INT
    assert inner_result.expressions[0].analysis.type is T.FLOAT


def test_assignment_conversion_destination_is_checked_against_resolved_target():
    program, _, result = analyze("START { INT x; x = 1; }")
    assignment = program.main.statements[1]
    site = StatementConversionSite(assignment, assignment.value, "value", T.INT, T.FLOAT)
    with pytest.raises(ValueError, match="conversion coverage"):
        StatementAnalysis(
            result.root, result.declarations, result.targets, result.expressions,
            result.defaults, (site,), result.scopes,
        )

    program, _, result = analyze("START { FLOAT x; x = 1; }")
    assignment = program.main.statements[1]
    site, = result.conversions
    assert site.parent is assignment and site.destination_type is T.FLOAT
    copy = StatementAnalysis(
        result.root, result.declarations, result.targets, result.expressions,
        result.defaults, (site,), result.scopes,
    )
    assert copy.conversions == (site,)


def test_completed_result_snapshots_outer_lists_and_binding_pairs():
    _, _, result = analyze("START { FLOAT x = 1; x = 2; }")
    declarations = [list(pair) for pair in result.declarations]
    targets = [list(pair) for pair in result.targets]
    scopes = [list(pair) for pair in result.scopes]
    expressions = list(result.expressions)
    defaults = list(result.defaults)
    conversions = list(result.conversions)
    copy = StatementAnalysis(
        result.root, declarations, targets, expressions, defaults, conversions, scopes,
    )
    declarations[0][1] = None
    targets.clear()
    scopes[0][0] = None
    expressions.clear()
    conversions.clear()
    assert copy.declarations == result.declarations
    assert copy.targets == result.targets
    assert copy.scopes == result.scopes
    assert copy.expressions == result.expressions
    assert copy.conversions == result.conversions
    assert all(isinstance(value, tuple) for value in (
        copy.declarations, copy.targets, copy.scopes, copy.expressions,
        copy.defaults, copy.conversions,
    ))


def test_completed_result_requires_coverage_but_allows_empty_block():
    program = parse("START { INT x = 1; }")
    with pytest.raises(ValueError, match="scope coverage"):
        StatementAnalysis(program.main, [], [], [], [], [], [])
    _, _, result = analyze("START {}")
    assert result.declarations == result.expressions == result.defaults == ()
    copy = StatementAnalysis(
        result.root, [], [], [], [], [], [list(result.scopes[0])],
    )
    assert copy.scopes == result.scopes


def test_writable_target_and_expression_use_reject_contradictory_records():
    program, _, result = analyze("START { INT x = 1; INT a[1]; x = 2; a[0] = 3; }")
    declaration, array, assignment, indexed = program.main.statements
    scalar = result.declaration_of(declaration)
    array_symbol = result.declaration_of(array)
    with pytest.raises(ValueError):
        WritableTarget(assignment.target, array_symbol, T.INT)
    with pytest.raises(ValueError):
        WritableTarget(assignment.target, scalar, T.FLOAT)
    with pytest.raises(ValueError):
        WritableTarget(indexed.target, array_symbol, T.INT)
    index_use = next(use for use in result.expressions if use.parent is indexed and use.role == "target_index")
    assert WritableTarget(indexed.target, array_symbol, T.INT, index_use.analysis).span is indexed.target.span
    with pytest.raises(ValueError):
        ExpressionUse(declaration, "value", result.expressions[0].analysis)
    with pytest.raises(ValueError):
        ExpressionUse(assignment, "value", result.expressions[0].analysis)
    with pytest.raises(TypeError):
        ExpressionUse(assignment, "value", index_use)


def test_result_rejects_missing_expression_or_target_binding():
    _, _, result = analyze("START { INT x = 1; x = 2; }")
    with pytest.raises(ValueError, match="target coverage"):
        StatementAnalysis(
            result.root, result.declarations, (), result.expressions,
            result.defaults, result.conversions, result.scopes,
        )
    with pytest.raises(ValueError, match="expression use coverage"):
        StatementAnalysis(
            result.root, result.declarations, result.targets, (),
            result.defaults, result.conversions, result.scopes,
        )
