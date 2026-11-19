"""RETURN typing and frozen conservative return-path rules."""

import pytest

from sparq.ast_nodes import Block, SourceSpan
from sparq.errors import SemanticError
from sparq.function_semantic import FunctionAnalyzer, check_guaranteed_return
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import (
    ReturnAnalysis, ReturnConversionSite, StatementAnalysis, StatementAnalyzer,
)
from sparq.symbols import ScalarType as T


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def function(source):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    return program, context, FunctionAnalyzer(context).analyze_function(program.functions[0])


def rejected(source, category):
    program = parse(source)
    context = SemanticContext()
    context.collect_signatures(program)
    with pytest.raises(SemanticError) as caught:
        FunctionAnalyzer(context).analyze_function(program.functions[0])
    assert caught.value.category == category
    assert caught.value.line >= 1 and caught.value.column >= 1
    return caught.value


def test_void_bare_return_and_invalid_value_return():
    program, _, result = function("FUNC f() -> VOID { RETURN; } START {}")
    returned = program.functions[0].body.statements[0]
    assert result.body.return_of(returned).value is None
    assert result.guarantees_return
    error = rejected("FUNC f() -> VOID { RETURN 1; } START {}", "INVALID_RETURN")
    assert error.name == "f" and error.expected == "VOID"


def test_nonvoid_bare_return_and_start_return_are_rejected():
    error = rejected("FUNC f() -> INT { RETURN; } START {}", "INVALID_RETURN")
    assert error.name == "f" and error.expected == "INT"
    for statement in ("RETURN;", "RETURN 1;"):
        program = parse(f"START {{ {{ {statement} }} }}")
        context = SemanticContext(); context.begin_start()
        with pytest.raises(SemanticError) as caught:
            StatementAnalyzer(context).analyze_block(program.main)
        assert caught.value.category == "RETURN_OUTSIDE_FUNCTION"


_LITERALS = {
    "INT": "1", "FLOAT": "2.5", "CHAR": "'a'", "STRING": '"a"', "BOOL": "TRUE",
}


@pytest.mark.parametrize("destination", _LITERALS)
@pytest.mark.parametrize("source", _LITERALS)
def test_all_ordered_scalar_return_type_pairs(destination, source):
    source_text = f"FUNC f() -> {destination} {{ RETURN {_LITERALS[source]}; }} START {{}}"
    expected_conversion = (destination, source) == ("FLOAT", "INT")
    if destination != source and not expected_conversion:
        error = rejected(source_text, "TYPE_MISMATCH")
        assert (error.expected, error.actual) == (destination, source)
    else:
        program, _, result = function(source_text)
        returned = program.functions[0].body.statements[0]
        analysis = result.body.return_of(returned)
        assert analysis.value.type.name == source
        assert (analysis.conversion is not None) == expected_conversion


def test_return_conversion_keeps_intrinsic_type_and_declared_function_type():
    program, _, result = function("FUNC f() -> FLOAT { RETURN 1 + 2; } START {}")
    returned = program.functions[0].body.statements[0]
    analysis = result.body.return_of(returned)
    site = analysis.conversion
    assert analysis.value.type is T.INT
    assert analysis.value.annotations.type_of(returned.value) is T.INT
    assert site.statement is returned and site.function is result.function
    assert site.operand is returned.value
    assert (site.source_type, site.destination_type) == (T.INT, T.FLOAT)
    assert result.function.return_type is T.FLOAT


def test_return_conversion_records_reject_wrong_function_and_missing_use():
    program, _, result = function("FUNC f() -> FLOAT { RETURN 1; } START {}")
    returned = program.functions[0].body.statements[0]
    analysis = result.body.return_of(returned)
    with pytest.raises(ValueError):
        ReturnAnalysis(returned, result.function, analysis.value)
    with pytest.raises(ValueError):
        ReturnConversionSite(returned, result.function, returned.value, T.FLOAT, T.INT)
    other = parse("FUNC g() -> INT { RETURN 1; } START {}")
    context = SemanticContext(); context.collect_signatures(other)
    int_function = context.functions.resolve("g")
    with pytest.raises(ValueError):
        ReturnConversionSite(returned, int_function, returned.value, T.INT, T.FLOAT)


def test_return_expression_can_contain_validated_forward_call():
    program = parse(
        "FUNC first() -> FLOAT { RETURN later(1); } "
        "FUNC later(FLOAT x) -> FLOAT { RETURN x; } START {}"
    )
    context = SemanticContext(); context.collect_signatures(program)
    result = FunctionAnalyzer(context).analyze_function(program.functions[0])
    returned = program.functions[0].body.statements[0]
    value = result.body.return_of(returned).value
    binding = value.annotations.call_binding_of(returned.value)
    assert binding.function is context.functions.resolve("later")
    assert len(binding.conversions) == 1
    assert result.body.return_of(returned).conversion is None


def test_return_inside_nested_function_block_keeps_function_context():
    program, _, result = function("FUNC f() -> INT { { RETURN 1; } } START {}")
    nested = program.functions[0].body.statements[0]
    returned = nested.statements[0]
    assert result.guarantees_return
    assert result.body.return_of(returned).function is result.function
    with pytest.raises(ValueError, match="return statement coverage"):
        StatementAnalysis(
            result.body.root, result.body.declarations, result.body.targets,
            result.body.expressions, result.body.defaults, result.body.conversions,
            result.body.scopes, result.body.calls, (), result.function,
        )


def test_void_call_cannot_be_nonvoid_return_value():
    program = parse(
        "FUNC v() -> VOID { RETURN; } "
        "FUNC f() -> INT { RETURN v(); } START {}"
    )
    context = SemanticContext(); context.collect_signatures(program)
    with pytest.raises(SemanticError) as caught:
        FunctionAnalyzer(context).analyze_function(program.functions[1])
    assert caught.value.category == "VOID_VALUE"


@pytest.mark.parametrize("body, expected", [
    ("", False),
    ("RETURN 1;", True),
    ("INT x; RETURN 1;", True),
    ("{ RETURN 1; }", True),
    ("WHEN (TRUE) { RETURN 1; }", False),
    ("WHEN (TRUE) { RETURN 1; } OTHERWISE { INT x; }", False),
    ("WHEN (TRUE) { RETURN 1; } OTHERWISE { RETURN 2; }", True),
    ("WHEN (TRUE) { WHEN (TRUE) { RETURN 1; } OTHERWISE { RETURN 2; } } OTHERWISE { RETURN 3; }", True),
    ("SELECT (1) { CASE 1: { RETURN 1; } }", False),
    ("SELECT (1) { CASE 1: { RETURN 1; } DEFAULT: { INT x; } }", False),
    ("SELECT (1) { CASE 1: { RETURN 1; } CASE 2: { RETURN 2; } DEFAULT: { RETURN 3; } }", True),
    ("SELECT (1) { DEFAULT: { RETURN 1; } }", True),
    ("DO { RETURN 1; } WHILE (FALSE);", True),
    ("WHILE (TRUE) { RETURN 1; }", False),
    ("REPEAT (; TRUE; ) { RETURN 1; }", False),
    ("REPEAT (; ; ) { RETURN 1; }", False),
    ("RETURN 1; INT x = TRUE;", True),
])
def test_conservative_structural_return_paths(body, expected):
    program = parse(f"START {{ {body} }}")
    assert check_guaranteed_return(program.main) is expected


def test_static_validation_still_visits_statements_after_return():
    rejected("FUNC f() -> INT { RETURN 1; INT x = TRUE; } START {}", "TYPE_MISMATCH")


def test_deep_structural_return_checker_is_iterative():
    span = SourceSpan(1, 1, 1, 2)
    leaf = parse("START { RETURN 1; }").main.statements[0]
    root = leaf
    for _ in range(2000):
        root = Block((root,), span)
    assert check_guaranteed_return(root)
