"""Source-backed CALL, argument, RETURN, and function-routine checks."""

import pytest

from sparq.expression_lowering import ExpressionLowerer, LoweringInputError, LoweringResourceError
from sparq.function_lowering import lower_function
from sparq.ir import (
    ArrayRef, BranchBool, Call, CheckBounds, Constant, Convert, IRFunction,
    Load, ParameterRef, Return, RoutineId, Show, VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.statement_lowering import StatementLowerer
from sparq.symbols import ScalarType as T, SymbolKind


def _start(source):
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    owner = RoutineId.start()
    locals_ = tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in semantic.start.declarations
    )
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=locals_)
    StatementLowerer(builder).lower_block(semantic.start)
    return program, semantic, builder.snapshot()


@pytest.mark.parametrize("type_name,literal", [
    ("INT", "1"), ("FLOAT", "1.5"), ("CHAR", "'A'"),
    ("STRING", '"hello"'), ("BOOL", "TRUE"),
])
def test_scalar_argument_and_return_type_preserved(type_name, literal):
    _, semantic, items = _start(
        f"FUNC echo({type_name} x) -> {type_name} {{ RETURN x; }} "
        f"START {{ SHOW(echo({literal})); }}"
    )
    call, show = items
    assert isinstance(call, Call) and isinstance(show, Show)
    assert call.function.symbol is semantic.functions[0].function
    assert call.arguments[0].type is T[type_name]
    assert call.result.type is T[type_name] and show.value is call.result
    function = lower_function(semantic.functions[0])
    assert isinstance(function, IRFunction)
    assert isinstance(function.body.instructions[-1], Return)
    assert isinstance(function.body.instructions[0], Load)
    assert function.body.instructions[0].source.symbol is semantic.functions[0].parameters[0]


def test_nested_calls_and_argument_conversions_are_immediate_and_ordered():
    _, semantic, items = _start(
        "FUNC g(INT x) -> INT { RETURN x; } "
        "FUNC h(INT x) -> INT { RETURN x; } "
        "FUNC f(FLOAT a, FLOAT b) -> FLOAT { RETURN a + b; } "
        "START { SHOW(f(g(1), h(2))); }"
    )
    calls = [item for item in items if isinstance(item, Call)]
    assert [call.function.symbol.name for call in calls] == ["g", "h", "f"]
    conversions = [item for item in items if isinstance(item, Convert)]
    assert len(conversions) == 2
    assert items.index(calls[0]) < items.index(conversions[0]) < items.index(calls[1])
    assert items.index(calls[1]) < items.index(conversions[1]) < items.index(calls[2])
    assert calls[2].arguments == (conversions[0].result, conversions[1].result)
    assert calls[2].function.symbol is semantic.functions[2].function


def test_earlier_scalar_argument_is_captured_before_later_call():
    _, _, items = _start(
        "FUNC mutate() -> INT { RETURN 2; } "
        "FUNC f(INT a, INT b) -> INT { RETURN a; } "
        "START { INT x = 1; SHOW(f(x, mutate())); }"
    )
    load = next(item for item in items if isinstance(item, Load))
    calls = [item for item in items if isinstance(item, Call)]
    assert items.index(load) < items.index(calls[0]) < items.index(calls[1])
    assert calls[1].arguments == (load.result, calls[0].result)


def test_discarded_nonvoid_and_void_calls_have_no_result_temporary():
    _, _, items = _start(
        "FUNC n() -> INT { RETURN 1; } FUNC v() -> VOID { RETURN; } "
        "START { n(); v(); }"
    )
    first, second = items
    assert isinstance(first, Call) and first.result is None and first.discard_result
    assert isinstance(second, Call) and second.result is None and not second.discard_result


def test_explicit_bare_void_return_has_no_fabricated_value():
    program = Parser(Lexer("FUNC v() -> VOID { RETURN; } START {}").tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    function = lower_function(semantic.functions[0])
    instruction, = function.body.instructions
    assert isinstance(instruction, Return) and instruction.value is None


def test_nested_calls_keep_separate_immutable_argument_tuples():
    _, _, items = _start(
        "FUNC g(INT x) -> INT { RETURN x; } "
        "FUNC f(INT a, INT b) -> INT { RETURN a; } "
        "START { SHOW(f(g(1), g(2))); }"
    )
    first, second, outer = (item for item in items if isinstance(item, Call))
    assert first.arguments == (Constant(T.INT, 1, "1"),)
    assert second.arguments == (Constant(T.INT, 2, "2"),)
    assert first.arguments is not second.arguments
    assert outer.arguments == (first.result, second.result)
    assert isinstance(outer.arguments, tuple)


def test_indexed_assignment_check_precedes_call_rhs_and_selector_call_is_once():
    _, _, items = _start(
        "FUNC f() -> INT { RETURN 1; } START { INT a[2]; "
        "a[0] = f(); SELECT (f()) { CASE 1: { SHOW(a[0]); } } }"
    )
    checks = [item for item in items if isinstance(item, CheckBounds)]
    calls = [item for item in items if isinstance(item, Call)]
    assert len(calls) == 2
    assert items.index(checks[0]) < items.index(calls[0])
    assert items.index(calls[0]) < items.index(calls[1])


def test_short_circuit_call_remains_behind_rhs_branch():
    _, _, items = _start(
        "FUNC p() -> BOOL { RETURN TRUE; } START { SHOW(FALSE AND p()); }"
    )
    first_branch = next(item for item in items if isinstance(item, BranchBool))
    call = next(item for item in items if isinstance(item, Call))
    assert items.index(first_branch) < items.index(call)


def test_return_conversion_and_void_fallthrough():
    program = Parser(Lexer(
        "FUNC f() -> FLOAT { RETURN 1; } FUNC v() -> VOID { SHOW(1); } START {}"
    ).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    f, v = (lower_function(result) for result in semantic.functions)
    convert, ret = f.body.instructions
    assert isinstance(convert, Convert) and isinstance(ret, Return)
    assert ret.value is convert.result
    assert isinstance(v.body.instructions[-1], Return)
    assert v.body.instructions[-1].value is None


def test_forward_self_and_mutual_recursion_use_symbolic_references():
    program = Parser(Lexer(
        "FUNC a(INT n) -> INT { WHEN (n == 0) { RETURN 0; } "
        "OTHERWISE { RETURN b(n - 1); } } "
        "FUNC b(INT n) -> INT { WHEN (n == 0) { RETURN a(0); } "
        "OTHERWISE { RETURN b(n - 1); } } START { SHOW(a(2)); }"
    ).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    first, second = (lower_function(result) for result in semantic.functions)
    first_calls = [i for i in first.body.instructions if isinstance(i, Call)]
    second_calls = [i for i in second.body.instructions if isinstance(i, Call)]
    assert [i.function.symbol for i in first_calls] == [semantic.functions[1].function]
    assert [i.function.symbol for i in second_calls] == [semantic.functions[0].function,
                                                        semantic.functions[1].function]


def test_argument_expression_resource_failure_invalidates_lowerer():
    program = Parser(Lexer(
        "FUNC f(INT x) -> INT { RETURN x; } START { SHOW(f(1 + 2)); }"
    ).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    builder = IRBuilder(RoutineId.start(), semantic.start_scope.id)
    lowerer = ExpressionLowerer(builder, max_nodes=2)
    expression = semantic.start.show_of(program.main.statements[0])
    with pytest.raises(LoweringResourceError):
        lowerer.lower_value(expression)
    assert lowerer.failed and builder.snapshot() == ()
    with pytest.raises(LoweringInputError, match="discard"):
        lowerer.lower_value(expression)
