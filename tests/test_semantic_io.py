"""READ writable targets and SHOW scalar expression semantics."""

from dataclasses import replace

import pytest

from sparq.errors import SemanticError
from sparq.function_semantic import FunctionAnalyzer
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import StatementAnalyzer
from sparq.symbols import ScalarType, SymbolKind


def parsed(source):
    return Parser(Lexer(source).tokenize()).parse()


def start(body, functions=""):
    program = parsed(f"{functions} START {{ {body} }}")
    context = SemanticContext(); context.collect_signatures(program); context.begin_start()
    return program, context, StatementAnalyzer(context).analyze_block(program.main)


def error(body, category, functions=""):
    with pytest.raises(SemanticError) as caught:
        start(body, functions)
    assert caught.value.category == category


@pytest.mark.parametrize("kind, value", [
    ("INT", "1"), ("FLOAT", "1.5"), ("CHAR", "'a'"),
    ("STRING", '"text"'), ("BOOL", "TRUE"),
])
def test_read_and_show_all_scalar_types_without_io(capsys, kind, value):
    program, _, result = start(f"{kind} x; READ(x); SHOW({value});")
    read, show = program.main.statements[1:]
    assert result.read_of(read).type.name == kind
    assert result.show_of(show).type.name == kind
    assert capsys.readouterr().out == ""


def test_read_parameter_array_element_and_index_call_annotations():
    program = parsed(
        "FUNC index() -> INT { RETURN 0; } "
        "FUNC f(INT p) -> VOID { INT a[1]; READ(p); READ(a[index()]); RETURN; } START {}"
    )
    context = SemanticContext(); context.collect_signatures(program)
    result = FunctionAnalyzer(context).analyze_function(program.functions[1])
    first, second = program.functions[1].body.statements[1:3]
    assert result.body.read_of(first).symbol.kind is SymbolKind.PARAMETER
    target = result.body.read_of(second)
    assert target.symbol.kind is SymbolKind.ARRAY
    assert target.index_analysis.type is ScalarType.INT
    assert target.index_analysis.annotations.function_of(second.target.index) is context.functions.resolve("index")


@pytest.mark.parametrize("body, category", [
    ("READ(missing);", "UNDECLARED_NAME"),
    ("INT a[1]; READ(a);", "WHOLE_ARRAY_ASSIGNMENT"),
    ("INT x; READ(x[0]);", "WRONG_SYMBOL_KIND"),
    ("INT a[1]; READ(a[TRUE]);", "INDEX_TYPE"),
    ("SHOW(missing);", "UNDECLARED_NAME"),
    ("INT a[1]; SHOW(a);", "ARRAY_AS_SCALAR"),
    ("SHOW(v());", "VOID_VALUE"),
])
def test_invalid_io_uses_are_controlled(body, category):
    error(body, category, "FUNC v() -> VOID {}")


def test_read_index_traps_and_out_of_range_values_remain_runtime_matters():
    program, _, result = start("INT a[2]; READ(a[-1]); READ(a[99]); READ(a[1 / 0]);")
    for read in program.main.statements[1:]:
        assert result.read_of(read).index_analysis.type is ScalarType.INT


def test_show_preserves_nested_call_conversion_and_completed_coverage(capsys):
    program, context, result = start(
        "SHOW(1 + f(1));", "FUNC f(FLOAT x) -> FLOAT { RETURN x; }"
    )
    statement = program.main.statements[0]
    analysis = result.show_of(statement)
    call = statement.value.right
    binding = analysis.annotations.call_binding_of(call)
    assert binding.function is context.functions.resolve("f")
    assert [site.index for site in binding.conversions] == [0]
    assert len(result.all_conversions()) == 2
    assert capsys.readouterr().out == ""
    with pytest.raises(ValueError, match="SHOW expression coverage"):
        replace(result, shows=())


def test_read_completed_coverage_and_unreachable_io_validation():
    program, _, result = start("INT x; READ(x);")
    with pytest.raises(ValueError, match="READ target coverage"):
        replace(result, reads=())
    other_program, _, other_result = start("INT y; READ(y); SHOW(1);")
    with pytest.raises(ValueError, match="READ target does not match"):
        replace(result, reads=((program.main.statements[1], other_result.read_of(other_program.main.statements[1])),))
    program = parsed("FUNC f() -> INT { RETURN 1; READ(missing); } START {}")
    context = SemanticContext(); context.collect_signatures(program)
    with pytest.raises(SemanticError) as caught:
        FunctionAnalyzer(context).analyze_function(program.functions[0])
    assert caught.value.category == "UNDECLARED_NAME"
