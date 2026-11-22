"""Guard, evaluation-order, and conversion checks for array expressions."""

import pytest

from sparq.expression_lowering import DeferredExpressionError, ExpressionLowerer
from sparq.ir import (
    ArrayRef, Binary, BranchBool, Call, CheckBounds, Compare, Convert, InitArray,
    InitElement,
    Label, Load, LoadElement, RoutineId, Show, StoreElement,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.statement_lowering import StatementLowerer
from sparq.symbols import ScalarType as T, SymbolKind
from sparq.ir import VariableRef


def _lower(body, functions=""):
    program = Parser(Lexer(f"{functions} START {{ {body} }}").tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    owner = RoutineId.start()
    inventory = tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in semantic.start.declarations
    )
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=inventory)
    StatementLowerer(builder).lower_block(semantic.start)
    return program, semantic, builder.snapshot()


@pytest.mark.parametrize("index", ["0", "-1", "99", "i", "i + 1", "b[0]"])
def test_index_forms_emit_one_guard_before_load(index):
    _, semantic, instructions = _lower(
        f"INT a[3]; INT b[3]; INT i = 1; SHOW(a[{index}]);"
    )
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    loads = [i for i in instructions if isinstance(i, LoadElement)]
    assert len(checks) == len(loads) == (2 if index == "b[0]" else 1)
    assert [i.checked for i in loads] == [i.result for i in checks]
    assert instructions.index(checks[-1]) < instructions.index(loads[-1])
    assert checks[-1].array.symbol is semantic.start.declarations[0][1]


@pytest.mark.parametrize("expression,result_type", [
    ("a[0] + b[1]", T.INT),
    ("a[0] < b[1]", T.BOOL),
    ("a[0] == 1.0", T.BOOL),
    ("a[0] * 2.5", T.FLOAT),
    ("a[0] + a[0]", T.INT),
])
def test_array_expression_types_independent_accesses_and_promotion(expression, result_type):
    _, semantic, instructions = _lower(
        f"INT a[2]; INT b[2]; SHOW({expression});"
    )
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    assert len(checks) == expression.count("[")
    assert len({id(i.result) for i in checks}) == len(checks)
    assert isinstance(instructions[-1], Show) and instructions[-1].value.type is result_type
    if result_type is T.FLOAT or "1.0" in expression:
        assert any(isinstance(i, Convert) for i in instructions)
    if "<" in expression or "==" in expression:
        assert any(isinstance(i, Compare) for i in instructions)


def test_left_conversion_precedes_right_bounds_check():
    _, _, instructions = _lower("INT a[1]; SHOW(1 + a[99] * 2.5);")
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    conversions = [i for i in instructions if isinstance(i, Convert)]
    assert len(checks) == 1 and len(conversions) == 2
    assert instructions.index(conversions[0]) < instructions.index(checks[0])
    assert instructions.index(checks[0]) < instructions.index(conversions[1])
    # The inverse nesting places the outer left conversion before the right check.
    _, _, inverse = _lower("INT a[1]; SHOW((1 / 0) * 2.5 + a[99]);")
    divide = next(i for i in inverse if isinstance(i, Binary) and i.operator.name == "SLASH")
    check = next(i for i in inverse if isinstance(i, CheckBounds))
    assert inverse.index(divide) < inverse.index(check)


def test_left_array_bounds_check_precedes_right_conversion():
    _, _, instructions = _lower("INT a[1]; SHOW(a[99] + 2.5);")
    check = next(i for i in instructions if isinstance(i, CheckBounds))
    convert = next(i for i in instructions if isinstance(i, Convert))
    assert instructions.index(check) < instructions.index(convert)


def test_potentially_failing_huge_int_conversion_precedes_right_array_check():
    huge = "9" * 5000
    _, _, instructions = _lower(f"INT a[1]; SHOW(({huge} + 0.0) + a[99]);")
    conversion = next(i for i in instructions if isinstance(i, Convert))
    check = next(i for i in instructions if isinstance(i, CheckBounds))
    assert conversion.operand.value == 10**5000 - 1
    assert instructions.index(conversion) < instructions.index(check)


def test_explicit_array_init_records_allocation_before_trapping_element():
    _, semantic, instructions = _lower("INT a[1] = {1 / 0};")
    init = next(i for i in instructions if isinstance(i, InitArray))
    division = next(i for i in instructions if isinstance(i, Binary))
    element = next(i for i in instructions if isinstance(i, InitElement))
    assert instructions.index(init) < instructions.index(division) < instructions.index(element)
    assert init.target.symbol is semantic.start.declarations[0][1]


def test_boolean_array_short_circuit_paths_keep_rhs_check_behind_branch():
    for operator, rhs_target in (("AND", "true_target"), ("OR", "false_target")):
        _, _, instructions = _lower(f"BOOL flags[2]; SHOW(TRUE {operator} flags[99]);")
        branch = next(i for i in instructions if isinstance(i, BranchBool))
        target = getattr(branch, rhs_target)
        label = next(i for i in instructions if isinstance(i, Label) and i.target is target)
        check = next(i for i in instructions if isinstance(i, CheckBounds))
        assert instructions.index(branch) < instructions.index(label) < instructions.index(check)


def test_shadowed_arrays_retain_distinct_exact_bindings():
    _, semantic, instructions = _lower(
        "INT a[1] = {1}; { INT a[1] = {2}; SHOW(a[0]); } SHOW(a[0]);"
    )
    outer, inner = (symbol for _, symbol in semantic.start.declarations)
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    assert [i.array.symbol for i in checks] == [inner, outer]
    assert checks[0].array.symbol is not checks[1].array.symbol


def test_indexed_assignment_nested_index_and_rhs_evaluate_once():
    _, semantic, instructions = _lower(
        "INT a[2]; INT b[2]; a[b[0] + 1] = b[1] / 0;"
    )
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    loads = [i for i in instructions if isinstance(i, LoadElement)]
    store = next(i for i in instructions if isinstance(i, StoreElement))
    divide = next(i for i in instructions if isinstance(i, Binary)
                  and i.operator.name == "SLASH")
    assert len(checks) == 3 and len(loads) == 2
    assert instructions.index(checks[0]) < instructions.index(checks[1])
    assert instructions.index(checks[1]) < instructions.index(checks[2])
    assert instructions.index(checks[2]) < instructions.index(divide)
    assert instructions.index(divide) < instructions.index(store)
    assert store.checked is checks[1].result
    assert checks[1].array.symbol is semantic.start.declarations[0][1]


@pytest.mark.parametrize("body", [
    "INT a[1]; SHOW(a[f()]);",
    "INT a[1]; a[f()] = 1;",
    "INT a[1]; a[0] = f();",
    "INT a[1] = {f()};",
    "INT a[1]; INT b[1] = {a[f()]};",
])
def test_calls_nested_in_array_contexts_lower_once(body):
    program = Parser(Lexer(
        f"FUNC f() -> INT {{ RETURN 0; }} START {{ {body} }}"
    ).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    owner = RoutineId.start()
    inventory = tuple(ArrayRef(owner, symbol) for _, symbol in semantic.start.declarations)
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=inventory)
    lowerer = StatementLowerer(builder)
    lowerer.lower_block(semantic.start)
    assert sum(isinstance(item, Call) for item in builder.snapshot()) == 1
    assert not lowerer.failed
