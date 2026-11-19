"""READ and SHOW lowering preserves source occurrences and effect order."""

import pytest

from sparq.expression_lowering import DeferredExpressionError
from sparq.ir import (
    ArrayRef, Binary, CheckBounds, Convert, Load, LoadElement, ParameterRef,
    ReadElement, ReadScalar, RoutineId, Show, VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.statement_lowering import StatementLowerer
from sparq.symbols import ScalarType as T, SymbolKind


def _start(body, functions=""):
    program = Parser(Lexer(f"{functions} START {{ {body} }}").tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    owner = RoutineId.start()
    inventory = tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in semantic.start.declarations
    )
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=inventory)
    lowerer = StatementLowerer(builder)
    lowerer.lower_block(semantic.start)
    return program, semantic, builder.snapshot()


@pytest.mark.parametrize("kind", ["INT", "FLOAT", "CHAR", "STRING", "BOOL"])
def test_scalar_read_all_types_emits_exactly_one_input_instruction(kind):
    program, semantic, instructions = _start(f"{kind} x; READ(x);")
    reads = [i for i in instructions if isinstance(i, ReadScalar)]
    assert len(reads) == 1
    assert reads[0].target.symbol is semantic.start.declarations[0][1]
    assert reads[0].target.type is T[kind]
    assert reads[0].span == program.main.statements[1].span
    assert not any(isinstance(i, Load) for i in instructions)


def test_parameter_read_writes_the_analyzed_parameter_slot():
    source = "FUNC f(INT p) -> VOID { READ(p); RETURN; } START {}"
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    function = semantic.functions[0]
    owner = RoutineId.for_function(function.function)
    parameter = ParameterRef(owner, function.parameters[0])
    builder = IRBuilder(owner, function.scope.id, parameters=(parameter,),
                        local_symbols=(parameter,))
    StatementLowerer(builder).lower_statement(
        function.body, program.functions[0].body.statements[0],
    )
    read, = builder.snapshot()
    assert isinstance(read, ReadScalar) and isinstance(read.target, ParameterRef)
    assert read.target.symbol is function.parameters[0]


def test_show_parameter_loads_value_before_emitting_output_record():
    source = "FUNC f(INT p) -> VOID { SHOW(p); RETURN; } START {}"
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    function = semantic.functions[0]
    owner = RoutineId.for_function(function.function)
    parameter = ParameterRef(owner, function.parameters[0])
    builder = IRBuilder(owner, function.scope.id, parameters=(parameter,),
                        local_symbols=(parameter,))
    StatementLowerer(builder).lower_statement(
        function.body, program.functions[0].body.statements[0],
    )
    load, show = builder.snapshot()
    assert isinstance(load, Load) and isinstance(load.source, ParameterRef)
    assert load.source.symbol is function.parameters[0]
    assert isinstance(show, Show) and show.value is load.result


@pytest.mark.parametrize("index", ["0", "i + 1", "b[0]"])
def test_indexed_read_checks_before_input_and_uses_same_guard(index):
    program, semantic, instructions = _start(
        f"INT a[2]; INT b[2]; INT i = 0; READ(a[{index}]);"
    )
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    read = next(i for i in instructions if isinstance(i, ReadElement))
    assert read.checked is checks[-1].result
    assert instructions.index(checks[-1]) < instructions.index(read)
    assert checks[-1].array.symbol is semantic.start.declarations[0][1]
    assert read.span == program.main.statements[-1].span
    assert not any(isinstance(i, ReadScalar) for i in instructions)
    if index == "b[0]":
        assert len(checks) == 2
        assert isinstance(next(i for i in instructions if isinstance(i, LoadElement)), LoadElement)


@pytest.mark.parametrize("body,expected", [
    ("SHOW(1);", T.INT),
    ("SHOW(1.0);", T.FLOAT),
    ("SHOW('A');", T.CHAR),
    ('SHOW("x");', T.STRING),
    ("SHOW(TRUE);", T.BOOL),
    ("INT x = 1; SHOW(x);", T.INT),
    ("FLOAT x = 1.0; SHOW(x + 2);", T.FLOAT),
    ("BOOL x = TRUE; SHOW(x AND FALSE);", T.BOOL),
    ("INT a[2]; SHOW(a[1]);", T.INT),
    ("INT a[2]; SHOW(a[a[0]]);", T.INT),
    ("SHOW(1 / 0);", T.INT),
])
def test_show_receives_final_typed_value_without_source_output(body, expected, capsys):
    program, semantic, instructions = _start(body)
    shows = [i for i in instructions if isinstance(i, Show)]
    assert len(shows) == 1 and shows[0].value.type is expected
    assert shows[0].span == program.main.statements[-1].span
    assert capsys.readouterr().out == ""


def test_mixed_numeric_show_places_conversion_before_binary_and_show():
    _, _, instructions = _start("INT a[1]; SHOW(a[0] + 2.5);")
    check = next(i for i in instructions if isinstance(i, CheckBounds))
    conversion = next(i for i in instructions if isinstance(i, Convert))
    binary = next(i for i in instructions if isinstance(i, Binary))
    show = next(i for i in instructions if isinstance(i, Show))
    assert instructions.index(check) < instructions.index(conversion)
    assert instructions.index(conversion) < instructions.index(binary)
    assert instructions.index(binary) < instructions.index(show)
    assert show.value is binary.result


@pytest.mark.parametrize("body", [
    "INT a[1]; READ(a[f()]);",
    "SHOW(f());",
    "INT a[1]; SHOW(a[f()]);",
])
def test_nested_io_calls_are_deferred_without_source_io(body, capsys):
    program = Parser(Lexer(
        f"FUNC f() -> INT {{ RETURN 0; }} START {{ {body} }}"
    ).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    owner = RoutineId.start()
    inventory = tuple(ArrayRef(owner, symbol) for _, symbol in semantic.start.declarations)
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=inventory)
    lowerer = StatementLowerer(builder)
    with pytest.raises(DeferredExpressionError):
        lowerer.lower_block(semantic.start)
    assert lowerer.failed and capsys.readouterr().out == ""
