"""Partial statement semantics through parsed declarations and blocks."""

from dataclasses import FrozenInstanceError

import pytest

from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import ExpressionAnalyzer, SemanticContext
from sparq.statement_semantic import (
    DefaultInitialization, StatementAnalyzer, StatementConversionSite,
)
from sparq.symbols import ScalarType as T


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def check(source):
    program = parse(source)
    context = SemanticContext()
    context.begin_start()
    return program, context, StatementAnalyzer(context).analyze_block(program.main)


@pytest.mark.parametrize("type_name, literal, expected", [
    ("INT", "10", T.INT), ("FLOAT", "2.5", T.FLOAT),
    ("CHAR", "'a'", T.CHAR), ("STRING", '"Sparq"', T.STRING),
    ("BOOL", "TRUE", T.BOOL),
])
def test_exact_scalar_initializers(type_name, literal, expected):
    program, context, result = check(f"START {{ {type_name} x = {literal}; }}")
    declaration = program.main.statements[0]
    symbol = result.declaration_of(declaration)
    assert symbol.type is expected
    assert context.current_scope.resolve("x") is symbol
    assert result.expressions[0].analysis.type is expected
    assert result.defaults == () and result.conversions == ()
    assert symbol.id in context._initialized


@pytest.mark.parametrize("type_name, expected", [
    ("INT", 0), ("FLOAT", 0.0), ("CHAR", "\0"),
    ("STRING", ""), ("BOOL", False),
])
def test_implicit_scalar_defaults_are_typed_metadata(type_name, expected):
    program, _, result = check(f"START {{ {type_name} x; }}")
    default, = result.defaults
    assert default.parent is program.main.statements[0]
    assert default.symbol is result.declaration_of(default.parent)
    assert default.element_value == expected
    assert type(default.element_value) is type(expected)
    assert default.length is None


def test_int_initializer_promotes_at_declaration_use_site():
    program, _, result = check("START { FLOAT x = 1 + 2; }")
    declaration = program.main.statements[0]
    use, = result.expressions
    site, = result.conversions
    assert use.analysis.type is T.INT
    assert use.analysis.annotations.type_of(declaration.initializer) is T.INT
    assert site.parent is declaration and site.operand is declaration.initializer
    assert (site.role, site.element_index, site.source_type, site.destination_type) == (
        "initializer", None, T.INT, T.FLOAT,
    )
    assert result.all_conversions() == (site,)


@pytest.mark.parametrize("source, expected, actual", [
    ("INT x = 2.5;", "INT", "FLOAT"),
    ("BOOL x = 1;", "BOOL", "INT"),
    ('CHAR x = "a";', "CHAR", "STRING"),
    ("STRING x = 'a';", "STRING", "CHAR"),
])
def test_incompatible_scalar_initializers_are_controlled(source, expected, actual):
    program = parse(f"START {{ {source} }}")
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert (caught.value.category, caught.value.name) == ("TYPE_MISMATCH", "x")
    assert (caught.value.expected, caught.value.actual) == (expected, actual)
    assert caught.value.line == 1 and caught.value.column >= 1


@pytest.mark.parametrize("initializer", ["x", "x + 1", "(x + 2) * 3"])
def test_scalar_self_read_is_rejected_and_transient_state_is_cleaned(initializer):
    program = parse(f"START {{ INT x = {initializer}; }}")
    context = SemanticContext()
    context.begin_start()
    analyzer = StatementAnalyzer(context)
    with pytest.raises(SemanticError) as caught:
        analyzer.analyze_block(program.main)
    assert (caught.value.category, caught.value.name) == (
        "READ_BEFORE_INITIALIZATION", "x",
    )
    assert context._initializing == set()
    with pytest.raises(ValueError, match="invalid after failed"):
        analyzer.analyze_block(program.main)
    with pytest.raises(ValueError, match="invalid after failed"):
        ExpressionAnalyzer(context).infer(program.main.statements[0].initializer)


def test_inner_self_initializer_resolves_new_shadow_not_outer_variable():
    program = parse("START { INT x = 10; { INT x = x + 1; } }")
    context = SemanticContext()
    root = context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert caught.value.category == "READ_BEFORE_INITIALIZATION"
    assert context.current_scope is root
    assert root.resolve("x") is not None
    assert context._initializing == set()


def test_sequential_visibility_and_nested_shadowing_preserve_scope_identity():
    program, context, result = check(
        "START { INT x = 10; INT y = x + 1; { FLOAT x = 2.5; INT z = y; } INT w = x; }"
    )
    x, y, nested, w = program.main.statements
    inner_x, z = nested.statements
    assert result.declaration_of(x).type is T.INT
    assert result.declaration_of(inner_x).type is T.FLOAT
    assert result.declaration_of(x).id != result.declaration_of(inner_x).id
    assert result.scope_of(nested).parent is result.scope_of(program.main)
    assert result.scope_of(nested).resolve("z") is result.declaration_of(z)
    assert context.current_scope.resolve("z") is None
    assert context.current_scope.resolve("x") is result.declaration_of(x)
    y_use = next(use for use in result.expressions if use.parent is y)
    assert y_use.analysis.annotations.binding_of(y.initializer.left) is result.declaration_of(x)
    w_use = next(use for use in result.expressions if use.parent is w)
    assert w_use.analysis.annotations.binding_of(w.initializer) is result.declaration_of(x)


def test_later_declaration_is_not_precollected():
    program = parse("START { INT y = x; INT x = 1; }")
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert (caught.value.category, caught.value.name) == ("UNDECLARED_NAME", "x")
    assert context.current_scope.resolve("x") is None


def test_duplicate_same_scope_rejected_but_sibling_blocks_are_isolated():
    duplicate = parse("START { INT x; INT x; }")
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(duplicate.main)
    assert caught.value.category == "REDECLARATION"
    _, context, result = check("START { { INT x; } { INT x; } }")
    first, second = result.root.statements
    assert result.scope_of(first).resolve("x") is result.declaration_of(first.statements[0])
    assert result.scope_of(second).resolve("x") is result.declaration_of(second.statements[0])
    assert result.scope_of(first).id != result.scope_of(second).id
    assert context.current_scope.resolve("x") is None


def test_invalid_show_still_invalidates_context():
    program = parse("START { INT x; SHOW(missing); }")
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert caught.value.category == "UNDECLARED_NAME"
    assert caught.value.name == "missing"
    with pytest.raises(ValueError, match="invalid after failed"):
        StatementAnalyzer(context).analyze_statement(program.main.statements[0])


def test_completed_result_is_immutable_and_independent_of_later_failure():
    program = parse("START { INT x = 1; INT bad = bad; }")
    context = SemanticContext()
    context.begin_start()
    analyzer = StatementAnalyzer(context)
    completed = analyzer.analyze_statement(program.main.statements[0])
    with pytest.raises(SemanticError):
        analyzer.analyze_statement(program.main.statements[1])
    assert completed.declaration_of(program.main.statements[0]).name == "x"
    assert completed.expressions[0].analysis.type is T.INT
    with pytest.raises(FrozenInstanceError):
        completed.root = program.main


def test_deep_direct_block_ast_has_controlled_resource_diagnostic():
    from sparq.ast_nodes import Block, SourceSpan

    span = SourceSpan(1, 1, 1, 3)
    nested = Block((), span)
    for _ in range(1200):
        nested = Block((nested,), span)
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_statement(nested)
    assert caught.value.category == "RESOURCE_LIMIT"
    assert caught.value.line == 1 and caught.value.column == 1


def test_independent_sessions_do_not_mutate_the_shared_ast():
    program = parse("START { INT x = 1; FLOAT y = x; }")
    snapshot = repr(program)
    outputs = []
    for _ in range(2):
        context = SemanticContext()
        context.begin_start()
        outputs.append(StatementAnalyzer(context).analyze_block(program.main))
        assert repr(program) == snapshot
    x, y = program.main.statements
    assert outputs[0].declaration_of(x) is not outputs[1].declaration_of(x)
    assert outputs[0].conversions[0].parent is y
    assert outputs[1].conversions[0].parent is y


_LITERALS = {
    "INT": "1", "FLOAT": "2.5", "CHAR": "'a'", "STRING": '"a"', "BOOL": "TRUE",
}


@pytest.mark.parametrize("destination", _LITERALS)
@pytest.mark.parametrize("source", _LITERALS)
def test_all_ordered_declaration_initializer_type_pairs(destination, source):
    program = parse(f"START {{ {destination} x = {_LITERALS[source]}; }}")
    context = SemanticContext()
    context.begin_start()
    expected_conversion = (destination, source) == ("FLOAT", "INT")
    if destination != source and not expected_conversion:
        with pytest.raises(SemanticError) as caught:
            StatementAnalyzer(context).analyze_block(program.main)
        assert (caught.value.category, caught.value.expected, caught.value.actual) == (
            "TYPE_MISMATCH", destination, source,
        )
    else:
        result = StatementAnalyzer(context).analyze_block(program.main)
        assert result.expressions[0].analysis.type.name == source
        assert len(result.conversions) == int(expected_conversion)


def test_scalar_conversion_constructor_checks_declared_destination():
    float_declaration = parse("START { FLOAT x = 1; }").main.statements[0]
    valid = StatementConversionSite(
        float_declaration, float_declaration.initializer, "initializer", T.INT, T.FLOAT,
    )
    assert valid.parent is float_declaration
    int_declaration = parse("START { INT x = 1; }").main.statements[0]
    with pytest.raises(ValueError, match="destination"):
        StatementConversionSite(
            int_declaration, int_declaration.initializer, "initializer", T.INT, T.FLOAT,
        )
    with pytest.raises(ValueError):
        StatementConversionSite(
            float_declaration, float_declaration.initializer, "initializer", T.FLOAT, T.INT,
        )


def test_default_descriptors_reject_python_cross_type_equal_values():
    for type_name, wrong_value in (("INT", False), ("FLOAT", 0), ("BOOL", 0),
                                   ("CHAR", ""), ("STRING", "\0")):
        program, _, result = check(f"START {{ {type_name} x; }}")
        declaration = program.main.statements[0]
        symbol = result.declaration_of(declaration)
        with pytest.raises(ValueError, match="default descriptor"):
            DefaultInitialization(declaration, symbol, wrong_value)
        valid = DefaultInitialization(
            declaration, symbol, result.defaults[0].element_value,
        )
        assert type(valid.element_value) is type(result.defaults[0].element_value)


@pytest.mark.parametrize("source, category", [
    ("START { INT x = TRUE; }", "TYPE_MISMATCH"),
    ("START { INT a[2] = {1}; }", "ARRAY_INITIALIZER_COUNT"),
    ("START { INT x; INT x; }", "REDECLARATION"),
    ("START { INT a[1]; a[FALSE] = 1; }", "INDEX_TYPE"),
])
def test_failed_context_rejects_all_later_analyzers(source, category):
    program = parse(source)
    context = SemanticContext()
    context.begin_start()
    analyzer = StatementAnalyzer(context)
    with pytest.raises(SemanticError) as caught:
        analyzer.analyze_block(program.main)
    assert caught.value.category == category
    with pytest.raises(ValueError, match="invalid after failed"):
        analyzer.analyze_block(program.main)
    with pytest.raises(ValueError, match="invalid after failed"):
        StatementAnalyzer(context).analyze_block(program.main)
    with pytest.raises(ValueError, match="invalid after failed"):
        ExpressionAnalyzer(context).infer(parse("START { SHOW(1); }").main.statements[0].value)
    fresh = SemanticContext()
    fresh.begin_start()
    assert StatementAnalyzer(fresh).analyze_block(parse("START { INT ok; }").main).defaults


@pytest.mark.parametrize("statement", [
    "SHOW(1);", "READ(x);", "WHEN (TRUE) {}",
])
def test_newly_supported_statement_kinds_validate_inside_nested_blocks(statement):
    program = parse(f"START {{ INT x; {{ {statement} }} }}")
    context = SemanticContext()
    context.begin_start()
    result = StatementAnalyzer(context).analyze_block(program.main)
    nested = program.main.statements[1]
    assert result.scope_of(nested) is not None
    assert result.scope_of(nested) is not context.current_scope


def test_return_nested_in_start_is_now_rejected_as_outside_function():
    program = parse("START { { RETURN; } }")
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        StatementAnalyzer(context).analyze_block(program.main)
    assert caught.value.category == "RETURN_OUTSIDE_FUNCTION"
