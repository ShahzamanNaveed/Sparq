"""Array declaration semantics through real lexer and parser inputs."""

import pytest

from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import (
    DefaultInitialization, StatementAnalyzer, StatementConversionSite,
)
from sparq.symbols import ScalarType as T


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def check(source):
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


def test_array_size_and_default_metadata_do_not_allocate_elements():
    digits = "9" * 5000
    program, _, result = check(f"START {{ FLOAT a[{digits}]; }}")
    declaration = program.main.statements[0]
    symbol = result.declaration_of(declaration)
    descriptor, = result.defaults
    assert symbol.array_length == declaration.size.value
    assert symbol.array_length.bit_length() > 16000
    assert descriptor.symbol is symbol
    assert descriptor.length == symbol.array_length
    assert descriptor.element_value == 0.0
    assert type(descriptor.element_value) is float
    assert result.expressions == ()


@pytest.mark.parametrize("type_name, expected", [
    ("INT", 0), ("FLOAT", 0.0), ("CHAR", "\0"),
    ("STRING", ""), ("BOOL", False),
])
def test_array_default_descriptor_has_exact_element_type(type_name, expected):
    _, _, result = check(f"START {{ {type_name} a[3]; }}")
    descriptor, = result.defaults
    assert descriptor.element_value == expected
    assert type(descriptor.element_value) is type(expected)
    assert descriptor.length == 3


def test_zero_size_and_huge_count_mismatch_are_controlled():
    assert rejected("START { INT a[0]; }", "INVALID_ARRAY_SIZE").name == "a"
    digits = "9" * 5000
    error = rejected(f"START {{ INT a[{digits}] = {{1}}; }}", "ARRAY_INITIALIZER_COUNT")
    assert len(error.expected) < 100 and error.actual == "1"


@pytest.mark.parametrize("elements", ["1, 2", "1, 2, 3, 4"])
def test_array_initializer_count_must_match_exactly(elements):
    assert rejected(f"START {{ INT a[3] = {{{elements}}}; }}", "ARRAY_INITIALIZER_COUNT").name == "a"


def test_array_elements_are_typed_in_order_with_distinct_conversion_sites():
    program, _, result = check("START { FLOAT a[3] = {1, 2.5, 3}; }")
    declaration = program.main.statements[0]
    assert [use.element_index for use in result.expressions] == [0, 1, 2]
    assert [use.analysis.type for use in result.expressions] == [T.INT, T.FLOAT, T.INT]
    assert [(site.parent, site.operand, site.role, site.element_index) for site in result.conversions] == [
        (declaration, declaration.initializers[0], "element", 0),
        (declaration, declaration.initializers[2], "element", 2),
    ]
    assert result.all_conversions() == result.conversions


def test_incompatible_array_element_identifies_index_and_type():
    error = rejected("START { INT a[2] = {1, TRUE}; }", "TYPE_MISMATCH")
    assert (error.name, error.expected, error.actual) == ("a", "INT", "BOOL")
    assert "element 1" in error.message


@pytest.mark.parametrize("body", [
    "INT a[2] = {a[0], 1};",
    "INT a[2] = {1, a[0]};",
    "INT a[2] = {1, 2 + a[0]};",
    "INT a[2] = {1, 2 + a[a[0]]};",
    "INT a[1] = {a[0]};",
    "INT a[1] = {1}; { INT a[1] = {a[0]}; }",
])
def test_array_self_read_rejected_even_after_earlier_elements(body):
    assert rejected(f"START {{ {body} }}", "READ_BEFORE_INITIALIZATION").name == "a"


def test_other_array_read_and_scalar_array_shadowing_are_valid():
    program, context, result = check(
        "START { INT a[2] = {1, 2}; INT b[2] = {a[0], a[1]}; "
        "{ INT a = 3; INT x = a; } INT y = b[0]; }"
    )
    outer_a, b, nested, y = program.main.statements
    assert result.declaration_of(outer_a).type is T.INT
    assert result.declaration_of(nested.statements[0]).id != result.declaration_of(outer_a).id
    b_use = next(use for use in result.expressions if use.parent is b)
    assert b_use.analysis.annotations.binding_of(b.initializers[0]) is result.declaration_of(outer_a)
    y_use = next(use for use in result.expressions if use.parent is y)
    assert y_use.analysis.annotations.binding_of(y.initializer) is result.declaration_of(b)
    assert context.current_scope.resolve("a") is result.declaration_of(outer_a)


def test_array_initializer_call_is_validated():
    program, _, result = check("FUNC f() -> INT { RETURN 1; } START { INT a[1] = {f()}; }")
    use, = result.expressions
    assert use.analysis.type is T.INT
    assert use.analysis.annotations.function_of(program.main.statements[0].initializers[0]) is not None


def test_array_conversion_constructor_checks_declared_type_and_occurrence():
    program, _, result = check("START { FLOAT a[2] = {1, 2}; }")
    declaration = program.main.statements[0]
    first, second = declaration.initializers
    assert StatementConversionSite(declaration, first, "element", T.INT, T.FLOAT, 0) is not None
    assert [site.element_index for site in result.conversions] == [0, 1]
    with pytest.raises(ValueError):
        StatementConversionSite(declaration, first, "element", T.INT, T.FLOAT, 1)
    with pytest.raises(ValueError):
        StatementConversionSite(declaration, second, "element", T.INT, T.FLOAT, 2)
    int_array = parse("START { INT a[1] = {1}; }").main.statements[0]
    with pytest.raises(ValueError, match="destination"):
        StatementConversionSite(
            int_array, int_array.initializers[0], "element", T.INT, T.FLOAT, 0,
        )


def test_array_default_constructor_rejects_wrong_length_and_value():
    program, _, result = check("START { INT a[2]; }")
    declaration = program.main.statements[0]
    symbol = result.declaration_of(declaration)
    with pytest.raises(ValueError):
        DefaultInitialization(declaration, symbol, False, 2)
    with pytest.raises(ValueError):
        DefaultInitialization(declaration, symbol, 0, 3)
    valid = DefaultInitialization(declaration, symbol, 0, 2)
    assert valid.parent is declaration and valid.symbol is symbol and valid.length == 2


def test_call_in_array_assignment_index_is_validated():
    program, _, result = check(
        "FUNC f() -> INT { RETURN 0; } START { INT a[1]; a[f()] = 1; }"
    )
    target = result.target_of(program.main.statements[1])
    assert target.index_analysis.type is T.INT
    assert target.index_analysis.annotations.function_of(target.target.index) is not None
