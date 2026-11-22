"""Source-backed structural checks for statement control-flow lowering."""

import pytest

from sparq.expression_lowering import DeferredExpressionError
from sparq.ir import (
    ArrayRef, BranchBool, Call, CheckBounds, Compare, Constant, HaltStart, InitArray,
    InitScalar, Jump, Label, Load, Move, Return, RoutineId, Show, VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.statement_lowering import DeferredStatementError, StatementLowerer, StatementResourceError
from sparq.symbols import SymbolKind
from sparq.token import TokenType


def _start(body, functions="", **limits):
    program = Parser(Lexer(f"{functions} START {{ {body} }}").tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    owner = RoutineId.start()
    local = tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in semantic.start.declarations
    )
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=local)
    lowerer = StatementLowerer(builder, **limits)
    return program, semantic, builder, lowerer


def _lower(body, functions=""):
    program, semantic, builder, lowerer = _start(body, functions)
    lowerer.lower_block(semantic.start)
    return program, semantic, builder, builder.snapshot()


def _defined(items):
    return {item.target for item in items if isinstance(item, Label)}


def _referenced(items):
    refs = set()
    for item in items:
        if isinstance(item, Jump):
            refs.add(item.target)
        elif isinstance(item, BranchBool):
            refs.update((item.true_target, item.false_target))
    return refs


@pytest.mark.parametrize("otherwise", [False, True])
def test_when_paths_have_defined_destinations_and_skip_otherwise(otherwise):
    tail = " OTHERWISE { SHOW(2); }" if otherwise else ""
    _, _, _, items = _lower(f"WHEN (TRUE) {{ SHOW(1); }}{tail} SHOW(3);")
    first = next(item for item in items if isinstance(item, BranchBool))
    true_label = next(i for i, item in enumerate(items) if isinstance(item, Label)
                      and item.target is first.true_target)
    false_label = next(i for i, item in enumerate(items) if isinstance(item, Label)
                       and item.target is first.false_target)
    assert true_label < false_label
    assert _referenced(items) <= _defined(items)
    if otherwise:
        jump = next(item for item in items[true_label:false_label] if isinstance(item, Jump))
        assert jump.target is not first.false_target
        assert [type(item) for item in items if isinstance(item, Show)] == [Show, Show, Show]
    else:
        assert len([item for item in items if isinstance(item, Show)]) == 2


@pytest.mark.parametrize("selector,label", [
    ("-1", "-1"), ("'A'", "'A'"), ('"A"', '"A"'),
])
def test_select_uses_decoded_typed_case_and_no_fallthrough(selector, label):
    _, semantic, _, items = _lower(
        f"SELECT ({selector}) {{ CASE {label}: {{ SHOW(1); }} "
        "DEFAULT: { SHOW(2); } }"
    )
    compare, = (item for item in items if isinstance(item, Compare))
    assert compare.operator is TokenType.EQUAL_EQUAL
    assert compare.right.value == semantic.start.labels_of(semantic.start.root.statements[0])[0].value
    branch = next(item for item in items if isinstance(item, BranchBool))
    assert branch.condition is compare.result
    case_index = next(i for i, item in enumerate(items) if isinstance(item, Label)
                      and item.target is branch.true_target)
    unmatched_index = next(i for i, item in enumerate(items) if isinstance(item, Label)
                           and item.target is branch.false_target)
    assert any(isinstance(item, Jump) for item in items[case_index:unmatched_index])
    assert _referenced(items) <= _defined(items)


def test_select_evaluates_selector_once_and_uses_same_captured_operand():
    _, semantic, _, items = _lower(
        "INT a[2]; SELECT (a[0]) { CASE 1: { SHOW(1); } "
        "CASE 2: { SHOW(2); } DEFAULT: { SHOW(3); } }"
    )
    checks = [item for item in items if isinstance(item, CheckBounds)]
    compares = [item for item in items if isinstance(item, Compare)]
    assert len(checks) == 1 and len(compares) == 2
    assert compares[0].left is compares[1].left
    assert [item.right.value for item in compares] == [1, 2]
    assert len(semantic.start.labels_of(semantic.start.root.statements[1])) == 2
    assert _referenced(items) <= _defined(items)


@pytest.mark.parametrize("cases", ["", "CASE 1: { SHOW(1); }"])
def test_select_without_default_preserves_selector_and_join(cases):
    _, _, _, items = _lower(f"SELECT (1 / 0) {{ {cases} }}")
    assert any(type(item).__name__ == "Binary" for item in items)
    assert _referenced(items) <= _defined(items)


def test_default_only_select_evaluates_selector_before_body():
    _, _, _, items = _lower("INT a[1]; SELECT (a[0]) { DEFAULT: { SHOW(1); } }")
    assert sum(isinstance(item, CheckBounds) for item in items) == 1
    assert not any(isinstance(item, Compare) for item in items)
    assert next(i for i, item in enumerate(items) if isinstance(item, CheckBounds)) < next(
        i for i, item in enumerate(items) if isinstance(item, Show))


def test_while_rechecks_condition_and_keeps_body_initialization_inside_backedge():
    _, semantic, _, items = _lower("INT x = 0; WHILE (x < 2) { INT y = 1; x = x + y; }")
    branch = next(item for item in items if isinstance(item, BranchBool))
    test_index = next(i for i, item in enumerate(items) if isinstance(item, Label)
                      and item.target is next(j.target for j in items if isinstance(j, Jump)))
    body_index = next(i for i, item in enumerate(items) if isinstance(item, Label)
                      and item.target is branch.true_target)
    inner = semantic.start.declaration_of(semantic.start.root.statements[1].body.statements[0])
    init_index = next(i for i, item in enumerate(items) if isinstance(item, InitScalar)
                      and item.target.symbol is inner)
    assert test_index < body_index < init_index
    assert _referenced(items) <= _defined(items)


def test_do_while_body_precedes_first_condition():
    _, _, _, items = _lower("INT x = 0; DO { x = x + 1; } WHILE (x < 2);")
    body_jump = next(item for item in items if isinstance(item, BranchBool))
    body_index = next(i for i, item in enumerate(items) if isinstance(item, Label)
                      and item.target is body_jump.true_target)
    assert body_index < next(i for i, item in enumerate(items) if isinstance(item, Move))
    assert next(i for i, item in enumerate(items) if isinstance(item, Move)) < items.index(body_jump)
    assert _referenced(items) <= _defined(items)


@pytest.mark.parametrize("header", [
    "INT i = 0; i < 2; i = i + 1", "i = 0; ; i = i + 1",
    "; i < 2; i = i + 1", "i = 0; i < 2;", "; ;",
])
def test_repeat_optional_parts_have_defined_loop_edges(header):
    _, _, _, items = _lower(f"INT i = 0; REPEAT ({header}) {{ SHOW(i); }}")
    assert _referenced(items) <= _defined(items)
    assert any(isinstance(item, Jump) for item in items)
    assert any(isinstance(item, Show) for item in items)


def test_repeat_initializer_body_update_order_and_symbol_shadowing():
    program, semantic, _, items = _lower(
        "INT i = 9; REPEAT (INT i = 0; i < 2; i = i + 1) "
        "{ INT a[1]; SHOW(i); }"
    )
    loop = program.main.statements[1]
    outer = semantic.start.declaration_of(program.main.statements[0])
    inner = semantic.start.declaration_of(loop.initializer)
    assert inner is not outer
    header_init = next(i for i, item in enumerate(items) if isinstance(item, InitScalar)
                       and item.target.symbol is inner)
    body_init = next(i for i, item in enumerate(items) if isinstance(item, InitArray))
    update = next(i for i, item in enumerate(items) if isinstance(item, Move)
                  and item.target.symbol is inner)
    assert header_init < body_init < update
    assert any(isinstance(item, Load) and item.source.symbol is inner for item in items)
    assert _referenced(items) <= _defined(items)


def test_nested_conditions_loops_and_short_circuit_guard_order():
    _, _, _, items = _lower(
        "BOOL flags[1]; REPEAT (;; ) { WHEN (FALSE AND flags[99]) "
        "{ WHILE (FALSE) { SHOW(1); } } OTHERWISE { SHOW(2); } }"
    )
    branch = next(item for item in items if isinstance(item, BranchBool))
    check = next(i for i, item in enumerate(items) if isinstance(item, CheckBounds))
    assert items.index(branch) < check
    assert _referenced(items) <= _defined(items)


@pytest.mark.parametrize("body,functions,exception", [
    ("WHEN (TRUE) { f(); }", "FUNC f() -> VOID { RETURN; }", DeferredStatementError),
    ("WHILE (TRUE) { SHOW(f()); }", "FUNC f() -> INT { RETURN 1; }", DeferredExpressionError),
])
def test_calls_inside_control_flow_lower_on_their_own_paths(body, functions, exception):
    _, semantic, builder, lowerer = _start(body, functions)
    lowerer.lower_block(semantic.start)
    assert sum(isinstance(item, Call) for item in builder.snapshot()) == 1
    assert not lowerer.failed


def test_nested_control_flow_resource_limit_is_controlled():
    _, semantic, builder, lowerer = _start("WHEN (TRUE) { WHILE (TRUE) { SHOW(1); } }",
                                           max_depth=3)
    with pytest.raises(StatementResourceError):
        lowerer.lower_block(semantic.start)
    assert lowerer.failed and builder.snapshot() == ()


def test_return_nested_in_function_control_flow_lowers():
    program = Parser(Lexer(
        "FUNC f() -> INT { WHEN (TRUE) { RETURN 1; } OTHERWISE { RETURN 2; } } "
        "START {}"
    ).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    function = semantic.functions[0]
    owner = RoutineId.for_function(function.function)
    builder = IRBuilder(owner, function.scope.id)
    lowerer = StatementLowerer(builder)
    lowerer.lower_block(function.body)
    assert sum(isinstance(item, Return) for item in builder.snapshot()) == 2
    assert not lowerer.failed


def test_representative_control_flow_fragment_is_structurally_finishable():
    program, semantic, builder, lowerer = _start(
        "INT x = 0; INT a[2]; WHEN (TRUE) { REPEAT (INT i = 0; i < 2; i = i + 1) "
        "{ SHOW(a[i]); } } OTHERWISE { DO { x = x + 1; } WHILE (FALSE); } "
        "SELECT (x) { CASE 0: { SHOW(x); } DEFAULT: { SHOW(1); } }"
    )
    lowerer.lower_block(semantic.start)
    snapshot = builder.snapshot()
    assert _referenced(snapshot) <= _defined(snapshot)
    builder.emit(HaltStart(builder.owner, program.main.span))
    assert builder.finish().instructions[:-1] == snapshot
