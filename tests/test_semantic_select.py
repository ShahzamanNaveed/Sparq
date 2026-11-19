"""SELECT selector, decoded CASE labels, and branch scope semantics."""

from dataclasses import replace

import pytest

from sparq.errors import SemanticError
from sparq.function_semantic import FunctionAnalyzer
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import CaseLabelAnalysis, SelectorUse, StatementAnalyzer
from sparq.symbols import ScalarType


def run(body, functions=""):
    program = Parser(Lexer(f"{functions} START {{ {body} }}").tokenize()).parse()
    context = SemanticContext(); context.collect_signatures(program); context.begin_start()
    return program, context, StatementAnalyzer(context).analyze_block(program.main)


def error(body, category, functions=""):
    with pytest.raises(SemanticError) as caught:
        run(body, functions)
    assert caught.value.category == category
    assert caught.value.span.start_line >= 1


@pytest.mark.parametrize("selector, label, expected", [
    ("1", "1", ScalarType.INT), ("'a'", "'a'", ScalarType.CHAR),
    ('"a"', '"a"', ScalarType.STRING), ("a[0]", "1", ScalarType.INT),
    ("f()", "1", ScalarType.INT),
])
def test_valid_selector_types_and_exact_case_labels(selector, label, expected):
    program, context, result = run(
        f"INT a[1] = {{1}}; SELECT ({selector}) {{ CASE {label}: {{ SHOW(1); }} }}",
        "FUNC f() -> INT { RETURN 1; }",
    )
    node = program.main.statements[1]
    assert result.selector_of(node).type is expected
    assert result.labels_of(node)[0].type is expected
    if selector == "f()":
        assert result.selector_of(node).annotations.function_of(node.selector) is context.functions.resolve("f")


@pytest.mark.parametrize("selector, category", [
    ("1.5", "INVALID_SELECTOR_TYPE"), ("TRUE", "INVALID_SELECTOR_TYPE"),
    ("v()", "VOID_VALUE"), ("a", "ARRAY_AS_SCALAR"),
])
def test_invalid_selectors(selector, category):
    error(f"INT a[1]; SELECT ({selector}) {{}}", category,
          "FUNC v() -> VOID {}")


@pytest.mark.parametrize("source", [
    "SELECT (1) { CASE 'a': {} }",
    "SELECT ('a') { CASE \"a\": {} }",
    "SELECT (\"a\") { CASE 'a': {} }",
])
def test_case_type_must_match_selector_exactly(source):
    error(source, "CASE_TYPE_MISMATCH")


@pytest.mark.parametrize("labels", [
    "CASE 1: {} CASE 1: {}",
    "CASE 1: {} CASE 01: {}",
    "CASE 0: {} CASE -0: {}",
    "CASE -01: {} CASE -1: {}",
])
def test_duplicate_integer_labels_use_decoded_values(labels):
    error(f"SELECT (1) {{ {labels} }}", "DUPLICATE_CASE")


@pytest.mark.parametrize("selector, labels", [
    ("'a'", "CASE 'a': {} CASE 'a': {}"),
    ('"a"', 'CASE "a": {} CASE "a": {}'),
])
def test_duplicate_text_labels(selector, labels):
    error(f"SELECT ({selector}) {{ {labels} }}", "DUPLICATE_CASE")


def test_equivalent_permitted_escape_labels_and_huge_integer():
    error(r'''SELECT ('"') { CASE '"': {} CASE '\"': {} }''', "DUPLICATE_CASE")
    error(r'''SELECT ("'") { CASE "'": {} CASE "\'": {} }''', "DUPLICATE_CASE")
    digits = "9" * 5000
    error(f"SELECT ({digits}) {{ CASE {digits}: {{}} CASE {digits}: {{}} }}", "DUPLICATE_CASE")


def test_case_default_scopes_nested_selects_and_label_ownership():
    program, context, result = run(
        "INT outer; SELECT (1) { CASE 1: { INT x; SELECT (2) { CASE 1: {} DEFAULT: {} } } "
        "CASE 2: { INT x; } DEFAULT: { INT x; } } SELECT (1) { CASE 1: {} }"
    )
    first, second = program.main.statements[1:]
    case_scopes = [result.scope_of(case.body) for case in first.cases]
    default_scope = result.scope_of(first.default)
    assert len({scope.id for scope in (*case_scopes, default_scope)}) == 3
    assert all(scope.parent is context.current_scope for scope in (*case_scopes, default_scope))
    assert context.current_scope.lookup_local("x") is None
    assert [record.value for record in result.labels_of(first)] == [1, 2]
    assert [record.value for record in result.labels_of(second)] == [1]
    with pytest.raises(ValueError, match="CASE label coverage"):
        replace(result, case_labels=())
    swapped = list(result.case_labels)
    swapped[0], swapped[2] = swapped[2], swapped[0]
    with pytest.raises(ValueError, match="CASE labels must follow"):
        replace(result, case_labels=swapped)
    with pytest.raises(ValueError, match="SELECT selector coverage"):
        replace(result, selectors=())
    with pytest.raises(ValueError):
        CaseLabelAnalysis(second, first.cases[0], ScalarType.INT, 1)
    with pytest.raises(ValueError):
        CaseLabelAnalysis(first, first.cases[0], ScalarType.INT, 2)
    with pytest.raises(ValueError):
        SelectorUse(second, result.selector_of(first))


def test_default_only_and_empty_select_are_valid_and_returns_integrate():
    program, _, result = run("SELECT (1) {} SELECT (1) { DEFAULT: { SHOW(1); } }")
    assert result.labels_of(program.main.statements[0]) == ()
    assert result.scope_of(program.main.statements[1].default) is not None
    program = Parser(Lexer(
        "FUNC f() -> INT { SELECT (1) { CASE 1: { RETURN 1; } DEFAULT: { RETURN 2; } } } START {}"
    ).tokenize()).parse()
    context = SemanticContext(); context.collect_signatures(program)
    assert FunctionAnalyzer(context).analyze_function(program.functions[0]).guarantees_return


def test_select_missing_default_or_bad_branch_return_is_rejected():
    for body, category in [
        ("SELECT (1) { CASE 1: { RETURN 1; } }", "MISSING_RETURN"),
        ("SELECT (1) { CASE 1: { RETURN TRUE; } DEFAULT: { RETURN 2; } }", "TYPE_MISMATCH"),
        ("SELECT (TRUE) { DEFAULT: { RETURN 1; } }", "INVALID_SELECTOR_TYPE"),
    ]:
        program = Parser(Lexer(f"FUNC f() -> INT {{ {body} }} START {{}}").tokenize()).parse()
        context = SemanticContext(); context.collect_signatures(program)
        with pytest.raises(SemanticError) as caught:
            FunctionAnalyzer(context).analyze_function(program.functions[0])
        assert caught.value.category == category


def test_bad_case_in_unreachable_select_is_still_rejected():
    program = Parser(Lexer(
        "FUNC f() -> INT { RETURN 1; SELECT (1) { CASE 01: {} CASE 1: {} } } START {}"
    ).tokenize()).parse()
    context = SemanticContext(); context.collect_signatures(program)
    with pytest.raises(SemanticError) as caught:
        FunctionAnalyzer(context).analyze_function(program.functions[0])
    assert caught.value.category == "DUPLICATE_CASE"
