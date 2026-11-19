"""Whole-program semantic integration through real lexing and parsing."""

from dataclasses import FrozenInstanceError
import subprocess
import sys

import pytest

from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import AnalysisResult, SemanticAnalyzer
from sparq.semantic import SemanticContext
from sparq.statement_semantic import StatementAnalyzer
from sparq.symbols import ScalarType, SymbolKind, VariableSymbol


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def analyze(source):
    return SemanticAnalyzer(parse(source)).analyze()


def test_empty_start_and_independent_sessions():
    program = parse("START {}")
    analyzer = SemanticAnalyzer(program)
    first, second = analyzer.analyze(), analyzer.analyze()
    assert first.program is second.program is program
    assert first is not second and first.start is not second.start
    assert first.signatures == second.signatures == ()
    assert first.start_scope.id == second.start_scope.id == 1
    assert first.scopes[0].parent_id is None
    with pytest.raises(FrozenInstanceError):
        first.program = program


def test_signature_prepass_forward_and_mutual_calls():
    source = """FUNC first(INT n) -> INT { RETURN second(n); }
FUNC second(INT n) -> INT { WHEN (n == 0) { RETURN 0; }
OTHERWISE { RETURN first(n - 1); } }
START { SHOW(first(2)); }"""
    result = analyze(source)
    assert [item.name for item in result.signatures] == ["first", "second"]
    assert [item.function.name for item in result.functions] == ["first", "second"]
    assert result.function_of(result.program.functions[1]) is result.functions[1]
    assert result.signature_of("first") is result.signatures[0]
    assert result.start.show_of(result.program.main.statements[0]).type is ScalarType.INT
    assert result.functions[0].parameters[0].id != result.functions[1].parameters[0].id
    assert result.functions[0].scope.id != result.functions[1].scope.id
    assert all(item.guarantees_return for item in result.functions)


@pytest.mark.parametrize("source,category", [
    ("FUNC f() -> VOID {} FUNC f() -> VOID {} START {}", "DUPLICATE_FUNCTION"),
    ("FUNC f(INT x, INT x) -> VOID {} START {}", "DUPLICATE_PARAMETER"),
    ("FUNC f() -> INT { RETURN TRUE; } START {}", "TYPE_MISMATCH"),
    ("FUNC f() -> VOID {} FUNC g() -> INT {} START {}", "MISSING_RETURN"),
    ("FUNC f() -> VOID { SHOW(missing); } START {}", "UNDECLARED_NAME"),
    ("FUNC f() -> VOID {} START { RETURN; }", "RETURN_OUTSIDE_FUNCTION"),
    ("FUNC f() -> VOID { INT x; } START { SHOW(x); }", "UNDECLARED_NAME"),
    ("FUNC f() -> INT { RETURN x; } START { INT x; }", "UNDECLARED_NAME"),
])
def test_every_function_and_start_are_validated(source, category):
    with pytest.raises(SemanticError) as caught:
        analyze(source)
    assert caught.value.category == category


def test_result_retains_bindings_defaults_and_scope_snapshots():
    source = """FUNC f(FLOAT x) -> FLOAT { INT a; { INT a = 2; SHOW(a); }
RETURN x; }
START { INT a[2]; FLOAT y = f(1); SHOW(y); }"""
    result = analyze(source)
    function = result.functions[0]
    parameter = function.parameters[0]
    assert parameter.name == "x" and parameter.type is ScalarType.FLOAT
    assert result.scope_of(function.scope.id).symbols[0] is parameter
    assert result.start_scope.id != function.scope.id
    array_decl = result.program.main.statements[0]
    array_symbol = result.start.declaration_of(array_decl)
    assert array_symbol.array_length == 2
    assert any(item.symbol is array_symbol for item in result.start.defaults)
    assert any(item.symbol.name == "a" for item in function.body.defaults)
    assert len(result.scopes) >= 3
    assert any(item.parent_id == function.scope.id for item in result.scopes)
    assert result.start.all_conversions()
    assert result.start.show_of(result.program.main.statements[-1]).type is ScalarType.FLOAT


def test_complete_representative_program_retains_all_statement_categories():
    source = """FUNC helper(FLOAT x) -> FLOAT { RETURN x; }
FUNC rec(INT n) -> INT { WHEN (n == 0) { RETURN 0; }
OTHERWISE { RETURN rec(n - 1); } }
START { INT a[2] = {1, 2}; INT i; FLOAT x = helper(1); a[0] = i;
WHEN (TRUE) { SHOW(x); } OTHERWISE { SHOW(0); }
SELECT (i) { CASE 0: { SHOW(i); } DEFAULT: { SHOW(1); } }
WHILE (FALSE) { i = i + 1; }
DO { i = i + 1; } WHILE (FALSE);
REPEAT (INT j = 0; j < 2; j = j + 1) { SHOW(j); }
READ(i); SHOW(a[0]); }"""
    result = analyze(source)
    assert len(result.functions) == 2
    assert len(result.start.scopes) == 8
    assert len(result.start.case_labels) == 1
    assert len(result.start.reads) == 1
    assert len(result.start.repeat_scopes) == 1
    assert len(result.start.all_conversions()) == 1
    assert result.start.scope_of(result.program.main) is result.start_scope
    assert all(item.guarantees_return for item in result.functions)


def test_result_constructor_rejects_missing_or_wrong_owners_and_snapshots_lists():
    result = analyze("FUNC f() -> VOID {} START {}")
    values = list(result.functions)
    copied = AnalysisResult(result.program, list(result.signatures), values,
                            result.start, result.start_scope, list(result.scopes))
    values.clear()
    assert len(copied.functions) == 1
    with pytest.raises(ValueError, match="every function"):
        AnalysisResult(result.program, result.signatures, (), result.start,
                       result.start_scope, result.scopes)
    other = analyze("FUNC f() -> VOID {} START {}")
    with pytest.raises(ValueError, match="wrong owner"):
        AnalysisResult(result.program, result.signatures, other.functions,
                       result.start, result.start_scope, result.scopes)
    with pytest.raises(ValueError, match="wrong owner"):
        AnalysisResult(result.program, result.signatures, result.functions,
                       other.start, other.start_scope, result.scopes)


def test_failed_session_does_not_poison_another():
    invalid = parse("START { SHOW(missing); }")
    for _ in range(2):
        with pytest.raises(SemanticError):
            SemanticAnalyzer(invalid).analyze()
    valid = analyze("START { INT x; SHOW(x); }")
    assert valid.start.declaration_of(valid.program.main.statements[0]).name == "x"


def test_diagnostic_pass_order_and_separate_namespaces():
    with pytest.raises(SemanticError) as caught:
        analyze("FUNC f() -> VOID { SHOW(missing); } FUNC f() -> VOID {} START { SHOW(other); }")
    assert caught.value.category == "DUPLICATE_FUNCTION"
    with pytest.raises(SemanticError) as caught:
        analyze("FUNC f() -> VOID { SHOW(missing); } START { SHOW(other); }")
    assert caught.value.category == "UNDECLARED_NAME" and caught.value.name == "missing"
    result = analyze("FUNC f() -> INT { RETURN 1; } START { INT f = 2; SHOW(f()); }")
    assert result.start.declaration_of(result.program.main.statements[0]).name == "f"
    assert result.start.show_of(result.program.main.statements[1]).type is ScalarType.INT


def test_runtime_traps_are_statically_deferred_and_deep_errors_controlled():
    large = "9" * 5000
    result = analyze(f"START {{ INT a[1]; SHOW(1 / 0); SHOW(a[-1]); SHOW({large}); }}")
    assert len(result.start.shows) == 3
    assert result.start.show_of(result.program.main.statements[-1]).type is ScalarType.INT
    with pytest.raises(SemanticError) as caught:
        analyze("START { SHOW(" + "1 + " * 2000 + "1); }")
    assert caught.value.category == "RESOURCE_LIMIT"


def test_completed_start_function_and_nested_scopes_reject_injection():
    program = parse("""FUNC f(INT p) -> VOID { INT y; { INT z; } }
START { INT x; REPEAT (INT i = 0; i < 1; i = i + 1) { INT n; } }""")
    result = SemanticAnalyzer(program).analyze()
    scopes = [result.start_scope, result.functions[0].scope]
    scopes.extend(scope for _, scope in result.start.scopes)
    scopes.extend(scope for _, scope in result.functions[0].body.scopes)
    scopes.extend(scope for _, scope in result.start.repeat_scopes)
    assert len({scope.id for scope in scopes}) == len(result.scopes)
    original = tuple((snap.id, snap.parent_id, snap.symbols) for snap in result.scopes)
    for scope in scopes:
        with pytest.raises(ValueError, match="read-only"):
            scope.declare(VariableSymbol(999, "extra", ScalarType.INT,
                                         SymbolKind.VARIABLE, scope.id, program.span))
        assert scope.resolve("extra") is None
        assert all(symbol.name != "extra" for symbol in result.scope_of(scope.id).symbols)
    assert tuple((snap.id, snap.parent_id, snap.symbols) for snap in result.scopes) == original
    assert result.functions[0].parameters[0].name == "p"
    assert result.start.declaration_of(program.main.statements[0]).name == "x"
    repeated = SemanticAnalyzer(program).analyze()
    assert [(item.id, item.parent_id) for item in repeated.scopes] == [
        (item.id, item.parent_id) for item in result.scopes
    ]
    assert result.scope_of(result.start_scope.id).symbols[0].name == "x"


def test_standalone_analysis_scopes_remain_mutable_until_program_completion():
    program = parse("START { INT x; }")
    context = SemanticContext()
    scope = context.begin_start()
    StatementAnalyzer(context).analyze_block(program.main)
    assert scope.resolve("x") is not None
    scope.declare(VariableSymbol(999, "extra", ScalarType.INT,
                                 SymbolKind.VARIABLE, scope.id, program.span))
    assert scope.resolve("extra") is not None


def test_complete_program_retains_all_seven_conversion_contexts():
    program = parse("""FUNC f(FLOAT p) -> FLOAT { RETURN 1; }
START { FLOAT a = 1; FLOAT arr[1] = {1}; a = 1; arr[0] = 1;
FLOAT b = 1 + 2.0; SHOW(f(1)); }""")
    result = SemanticAnalyzer(program).analyze()
    returned = result.functions[0].body.all_conversions()
    assert len(returned) == 1 and type(returned[0]).__name__ == "ReturnConversionSite"
    assert returned[0].statement is program.functions[0].body.statements[0]
    sites = result.start.all_conversions()
    assert len(sites) == 6
    assert [(type(site).__name__, getattr(site, "role", None)) for site in sites] == [
        ("StatementConversionSite", "initializer"),
        ("StatementConversionSite", "element"),
        ("StatementConversionSite", "value"),
        ("StatementConversionSite", "value"),
        ("ConversionSite", "left"),
        ("ArgumentConversionSite", None),
    ]
    assert sites[0].parent is program.main.statements[0]
    assert sites[1].parent is program.main.statements[1] and sites[1].element_index == 0
    assert sites[2].parent is program.main.statements[2]
    assert sites[3].parent is program.main.statements[3]
    assert sites[4].parent is program.main.statements[4].initializer
    assert sites[5].call is program.main.statements[5].value and sites[5].index == 0
    assert all(site.source_type is ScalarType.INT and site.destination_type is ScalarType.FLOAT
               for site in returned + sites)


def test_cli_success_and_source_errors(tmp_path):
    cases = (("START {}", 0, "Semantic analysis succeeded"),
             ("START { @ }", 1, "INVALID_CHARACTER"),
             ("START { SHOW(); }", 1, "EXPECTED_EXPRESSION"),
             ("START { SHOW(x); }", 1, "UNDECLARED_NAME"))
    for index, (source, exit_code, message) in enumerate(cases):
        path = tmp_path / f"case{index}.spq"
        path.write_text(source, encoding="utf-8")
        run = subprocess.run((sys.executable, "-m", "sparq.program_semantic", str(path)),
                             capture_output=True, text=True, check=False)
        assert run.returncode == exit_code
        assert message in run.stdout + run.stderr
        assert "Traceback" not in run.stderr
    missing = subprocess.run((sys.executable, "-m", "sparq.program_semantic",
                              str(tmp_path / "missing.spq")), capture_output=True,
                             text=True, check=False)
    assert missing.returncode == 1 and "Traceback" not in missing.stderr
