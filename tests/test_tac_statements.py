"""Source-backed checks for the partial straight-line statement lowerer."""

from dataclasses import replace

import pytest

from sparq.expression_lowering import DeferredExpressionError
from sparq.ir import (
    ArrayRef, Binary, BranchBool, Call, CheckBounds, Constant, Convert, HaltStart,
    InitArray, InitElement, InitScalar, Label, Load, LoadElement, Move,
    ParameterRef, ReadElement, ReadScalar, Return, RoutineId, Show, StoreElement,
    VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.statement_lowering import (
    DeferredStatementError, StatementInputError, StatementLowerer,
    StatementMetadataError, StatementResourceError,
)
from sparq.symbols import ScalarType as T, SymbolKind


def _start(body, functions=""):
    program = Parser(Lexer(f"{functions} START {{ {body} }}").tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    owner = RoutineId.start()
    local = tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in semantic.start.declarations
    )
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=local)
    return program, semantic, builder, StatementLowerer(builder)


def _function(source):
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    function = semantic.functions[0]
    owner = RoutineId.for_function(function.function)
    parameters = tuple(ParameterRef(owner, symbol) for symbol in function.parameters)
    local = parameters + tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in function.body.declarations
    )
    builder = IRBuilder(owner, function.scope.id,
                        parameters=parameters, local_symbols=local)
    return program, function, builder, StatementLowerer(builder)


@pytest.mark.parametrize("kind,expected,value_type", [
    ("INT", 0, T.INT), ("FLOAT", 0.0, T.FLOAT),
    ("CHAR", "\0", T.CHAR), ("STRING", "", T.STRING),
    ("BOOL", False, T.BOOL),
])
def test_scalar_defaults_are_typed_and_keep_exact_symbol(kind, expected, value_type):
    program, analysis, builder, lowerer = _start(f"{kind} x;")
    lowerer.lower_block(analysis.start)
    instruction, = builder.snapshot()
    assert isinstance(instruction, InitScalar)
    assert instruction.target.symbol is analysis.start.declarations[0][1]
    assert instruction.value == Constant(value_type, expected)
    assert instruction.value.lexeme is None
    assert instruction.span == program.main.statements[0].span


@pytest.mark.parametrize("kind,source,expected", [
    ("INT", "7", T.INT), ("FLOAT", "1.5", T.FLOAT),
    ("CHAR", "'A'", T.CHAR), ("STRING", '"hi"', T.STRING),
    ("BOOL", "TRUE", T.BOOL),
])
def test_explicit_scalar_initializers_have_no_preceding_default(kind, source, expected):
    _, semantic, builder, lowerer = _start(f"{kind} x = {source};")
    lowerer.lower_block(semantic.start)
    instruction, = builder.snapshot()
    assert isinstance(instruction, InitScalar)
    assert instruction.value.type is expected


def test_scalar_initializer_conversion_follows_arithmetic_and_precedes_init():
    _, semantic, builder, lowerer = _start("FLOAT x = 1 + 2;")
    lowerer.lower_block(semantic.start)
    operation, conversion, init = builder.snapshot()
    assert isinstance(operation, Binary)
    assert isinstance(conversion, Convert) and conversion.operand is operation.result
    assert isinstance(init, InitScalar) and init.value is conversion.result


def test_scalar_assignment_shadows_correct_symbol_without_destination_load():
    program, semantic, builder, lowerer = _start(
        "INT x = 1; { INT x = 2; x = x + 1; } x = 3;"
    )
    lowerer.lower_block(semantic.start)
    instructions = builder.snapshot()
    outer, inner = (symbol for _, symbol in semantic.start.declarations)
    moves = [i for i in instructions if isinstance(i, Move)]
    assert [i.target.symbol for i in moves] == [inner, outer]
    assert moves[0].target.symbol is inner and moves[1].target.symbol is outer
    loads = [i for i in instructions if isinstance(i, Load)]
    assert len(loads) == 1 and loads[0].source.symbol is inner
    assert moves[0].span == program.main.statements[1].statements[1].span


def test_parameter_assignment_uses_parameter_storage_and_conversion():
    source = "FUNC f(FLOAT p) -> VOID { p = 1; RETURN; } START {}"
    _, function, builder, lowerer = _function(source)
    assignment = function.declaration.body.statements[0]
    lowerer.lower_statement(function.body, assignment)
    conversion, move = builder.snapshot()
    assert isinstance(conversion, Convert)
    assert isinstance(move, Move) and isinstance(move.target, ParameterRef)
    assert move.target.symbol is function.parameters[0]
    assert move.value is conversion.result


@pytest.mark.parametrize("kind,expected,value_type", [
    ("INT", 0, T.INT), ("FLOAT", 0.0, T.FLOAT),
    ("CHAR", "\0", T.CHAR), ("STRING", "", T.STRING),
    ("BOOL", False, T.BOOL),
])
def test_array_defaults_use_one_compact_descriptor(kind, expected, value_type):
    _, semantic, builder, lowerer = _start(f"{kind} a[1000000];")
    lowerer.lower_block(semantic.start)
    instruction, = builder.snapshot()
    assert isinstance(instruction, InitArray)
    assert instruction.length == 1_000_000
    assert instruction.default == Constant(value_type, expected)
    assert instruction.target.symbol is semantic.start.declarations[0][1]


def test_explicit_array_initializer_order_positions_and_conversions():
    program, semantic, builder, lowerer = _start(
        "INT a[2] = {1, 2}; FLOAT b[3] = {a[0], 2.5, a[1] + 1};"
    )
    lowerer.lower_block(semantic.start)
    instructions = builder.snapshot()
    a, b = (symbol for _, symbol in semantic.start.declarations)
    positions = [i.index for i in instructions if isinstance(i, InitElement)]
    assert positions == [0, 1, 0, 1, 2]
    assert [i.array.symbol for i in instructions if isinstance(i, InitElement)] == [a, a, b, b, b]
    assert sum(isinstance(i, Convert) for i in instructions) == 2
    assert sum(isinstance(i, CheckBounds) for i in instructions) == 2
    first_b = next(i for i in instructions if isinstance(i, InitArray) and i.target.symbol is b)
    assert instructions.index(first_b) < next(j for j, i in enumerate(instructions)
                                          if isinstance(i, CheckBounds))
    assert first_b.span == program.main.statements[1].span
    assert all(i.span == program.main.statements[1].initializers[i.index].span
               for i in instructions if isinstance(i, InitElement) and i.array.symbol is b)


def test_nested_array_access_captures_independent_guards_once():
    _, semantic, builder, lowerer = _start(
        "INT a[3]; INT b[3]; SHOW(a[b[1]] + a[2]);"
    )
    lowerer.lower_block(semantic.start)
    checks = [i for i in builder.snapshot() if isinstance(i, CheckBounds)]
    loads = [i for i in builder.snapshot() if isinstance(i, LoadElement)]
    assert [i.result.number for i in checks] == [1, 2, 3]
    assert [i.checked for i in loads] == [i.result for i in checks]
    assert checks[1].index is loads[0].result
    assert checks[0].array.symbol is semantic.start.declarations[1][1]
    assert checks[1].array.symbol is semantic.start.declarations[0][1]


def test_short_circuit_array_check_is_after_conditional_branch():
    _, semantic, builder, lowerer = _start("BOOL a[2]; SHOW(FALSE AND a[99]);")
    lowerer.lower_block(semantic.start)
    instructions = builder.snapshot()
    branch = next(i for i in instructions if isinstance(i, BranchBool))
    check = next(i for i in instructions if isinstance(i, CheckBounds))
    rhs_label = next(i for i in instructions if isinstance(i, Label)
                     and i.target is branch.true_target)
    assert instructions.index(branch) < instructions.index(rhs_label) < instructions.index(check)
    assert any(isinstance(i, Show) for i in instructions[instructions.index(check):])


def test_indexed_assignment_checks_before_rhs_trap_and_store():
    _, semantic, builder, lowerer = _start("INT a[2]; a[-1] = 1 / 0;")
    lowerer.lower_block(semantic.start)
    instructions = builder.snapshot()
    check = next(i for i in instructions if isinstance(i, CheckBounds))
    divide = next(i for i in instructions if isinstance(i, Binary))
    store = next(i for i in instructions if isinstance(i, StoreElement))
    assert instructions.index(check) < instructions.index(divide) < instructions.index(store)
    assert store.checked is check.result
    assert check.index.type is T.INT


def test_indexed_float_assignment_checks_then_evaluates_and_converts_rhs():
    _, semantic, builder, lowerer = _start(
        "FLOAT a[2]; INT i = 0; a[i + 1] = 2 + 3;"
    )
    lowerer.lower_block(semantic.start)
    instructions = builder.snapshot()
    check = next(i for i in instructions if isinstance(i, CheckBounds))
    conversion = next(i for i in instructions if isinstance(i, Convert))
    store = next(i for i in instructions if isinstance(i, StoreElement))
    operations = [i for i in instructions if isinstance(i, Binary)]
    assert len(operations) == 2
    assert instructions.index(operations[0]) < instructions.index(check)
    assert check.index is operations[0].result
    assert instructions.index(check) < instructions.index(operations[1])
    assert instructions.index(operations[1]) < instructions.index(conversion)
    assert instructions.index(conversion) < instructions.index(store)
    assert store.checked is check.result and store.value is conversion.result


def test_read_scalar_and_indexed_read_preserve_input_order():
    _, semantic, builder, lowerer = _start("INT x; INT a[2]; READ(x); READ(a[x + 1]);")
    lowerer.lower_block(semantic.start)
    instructions = builder.snapshot()
    scalar = next(i for i in instructions if isinstance(i, ReadScalar))
    check = next(i for i in instructions if isinstance(i, CheckBounds))
    indexed = next(i for i in instructions if isinstance(i, ReadElement))
    assert scalar.target.symbol is semantic.start.declarations[0][1]
    assert instructions.index(scalar) < instructions.index(check) < instructions.index(indexed)
    assert indexed.checked is check.result
    assert sum(isinstance(i, ReadScalar) for i in instructions) == 1


@pytest.mark.parametrize("kind,value", [
    ("INT", "1"), ("FLOAT", "1.5"), ("CHAR", "'A'"),
    ("STRING", '"hi"'), ("BOOL", "TRUE"),
])
def test_show_all_scalar_literal_types(kind, value):
    _, semantic, builder, lowerer = _start(f"SHOW({value});")
    lowerer.lower_block(semantic.start)
    instruction, = builder.snapshot()
    assert isinstance(instruction, Show)
    assert instruction.value.type is T[kind]


def test_representative_fragment_is_structurally_finishable():
    program, semantic, builder, lowerer = _start(
        "INT x; FLOAT f = 1 + 2; INT a[2] = {1, 2}; BOOL flags[2]; "
        "x = a[1]; a[0] = x; READ(a[1]); SHOW(f); "
        "{ INT x = 5; SHOW(x); }"
    )
    lowerer.lower_block(semantic.start)
    snapshot = builder.snapshot()
    assert [type(i).__name__ for i in snapshot] == [
        "InitScalar", "Binary", "Convert", "InitScalar", "InitArray",
        "InitElement", "InitElement", "InitArray", "CheckBounds",
        "LoadElement", "Move", "CheckBounds", "Load", "StoreElement",
        "CheckBounds", "ReadElement", "Load", "Show", "InitScalar",
        "Load", "Show",
    ]
    builder.emit(HaltStart(builder.owner, program.main.span))
    assert builder.finish().instructions[:-1] == snapshot


def test_multiple_statement_invocations_share_builder_counters_and_order():
    program, semantic, builder, lowerer = _start(
        "INT a[2]; INT i = 0; SHOW(a[i]); SHOW(a[i + 1]);"
    )
    for statement in program.main.statements:
        lowerer.lower_statement(semantic.start, statement)
    instructions = builder.snapshot()
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    assert [i.result.number for i in checks] == [1, 2]
    assert checks[0].index.number < checks[1].index.number
    assert sum(isinstance(i, Show) for i in instructions) == 2
    assert not lowerer.failed and not builder.is_complete


def test_short_circuit_boolean_initializer_and_assignment_keep_merge_before_write():
    _, semantic, builder, lowerer = _start(
        "BOOL flags[1]; BOOL b = FALSE AND flags[99]; b = TRUE OR flags[99];"
    )
    lowerer.lower_block(semantic.start)
    instructions = builder.snapshot()
    checks = [i for i in instructions if isinstance(i, CheckBounds)]
    branches = [i for i in instructions if isinstance(i, BranchBool)]
    writes = [i for i in instructions if isinstance(i, (InitScalar, Move))
              and isinstance(i.target, VariableRef) and i.target.symbol.name == "b"]
    assert len(checks) == len(writes) == 2 and len(branches) == 4
    assert instructions.index(branches[0]) < instructions.index(checks[0]) < instructions.index(writes[0])
    assert instructions.index(branches[2]) < instructions.index(checks[1]) < instructions.index(writes[1])


@pytest.mark.parametrize("body,kind", [
    ("FUNC_CALL_PLACEHOLDER", "CallStmt"),
])
def test_standalone_call_statement_lowers(body, kind):
    functions = "FUNC f() -> VOID { RETURN; }" if kind == "CallStmt" else ""
    body = "f();" if kind == "CallStmt" else body
    _, semantic, builder, lowerer = _start(body, functions)
    lowerer.lower_block(semantic.start)
    call, = builder.snapshot()
    assert isinstance(call, Call) and call.result is None and not call.discard_result


def test_nested_call_statement_keeps_prior_source_order():
    _, semantic, builder, lowerer = _start(
        "INT x; { SHOW(x); WHEN (TRUE) { f(); } }",
        "FUNC f() -> VOID { RETURN; }",
    )
    lowerer.lower_block(semantic.start)
    items = builder.snapshot()
    assert [type(item) for item in items if isinstance(item, (Show, Call))] == [Show, Call]
    assert not lowerer.failed


def test_return_statement_uses_retained_function_value():
    _, function, builder, lowerer = _function(
        "FUNC f() -> INT { RETURN 1; } START {}"
    )
    lowerer.lower_block(function.body)
    instruction, = builder.snapshot()
    assert isinstance(instruction, Return) and instruction.value == Constant(T.INT, 1, "1")


def test_call_inside_initializer_uses_shared_session():
    _, semantic, builder, lowerer = _start(
        "INT x = f();", "FUNC f() -> INT { RETURN 1; }"
    )
    lowerer.lower_block(semantic.start)
    call, init = builder.snapshot()
    assert isinstance(call, Call) and isinstance(init, InitScalar)
    assert init.value is call.result and not lowerer.failed


def test_invalid_input_completed_builder_and_limits_are_controlled():
    _, semantic, builder, lowerer = _start("INT x; SHOW(x);")
    with pytest.raises(StatementInputError, match="StatementAnalysis"):
        lowerer.lower_block(None)
    assert lowerer.failed and builder.snapshot() == ()
    limited = StatementLowerer(builder, max_statements=2)
    with pytest.raises(StatementResourceError):
        limited.lower_block(semantic.start)
    assert limited.failed and builder.snapshot() == ()
    builder.finish()
    with pytest.raises(StatementInputError, match="open"):
        StatementLowerer(builder)


def test_nested_statement_depth_limit_is_controlled():
    _, semantic, builder, _ = _start("{{ SHOW(1); }}")
    lowerer = StatementLowerer(builder, max_depth=2)
    with pytest.raises(StatementResourceError):
        lowerer.lower_block(semantic.start)
    assert lowerer.failed and builder.snapshot() == ()


@pytest.mark.parametrize("branch,expected", [
    ("then_block", 1), ("else_block", 2),
])
def test_selected_when_and_otherwise_bodies_lower_only_their_own_occurrences(branch, expected):
    program, semantic, builder, lowerer = _start(
        "SHOW(9); WHEN (TRUE) { SHOW(1); } OTHERWISE { SHOW(2); } SHOW(8);"
    )
    selected = getattr(program.main.statements[1], branch)
    assert selected is not None and semantic.start.scope_of(selected) is not None
    lowerer.lower_block(semantic.start, selected)
    instruction, = builder.snapshot()
    assert isinstance(instruction, Show)
    assert instruction.value == Constant(T.INT, expected, str(expected))
    assert instruction.span == selected.statements[0].span


def test_selected_nested_declaration_and_statement_keep_exact_shadowed_symbol():
    program, semantic, builder, lowerer = _start(
        "INT x = 9; WHEN (TRUE) { INT x = 1; SHOW(x); } "
        "OTHERWISE { INT x = 2; SHOW(x); }"
    )
    selected = program.main.statements[1].then_block
    declaration, output = selected.statements
    lowerer.lower_statement(semantic.start, declaration)
    lowerer.lower_statement(semantic.start, output)
    init, load, show = builder.snapshot()
    inner = semantic.start.declaration_of(declaration)
    outer = semantic.start.declaration_of(program.main.statements[0])
    assert inner is not None and inner is not outer
    assert isinstance(init, InitScalar) and init.target.symbol is inner
    assert isinstance(load, Load) and load.source.symbol is inner
    assert isinstance(show, Show) and show.value is load.result


@pytest.mark.parametrize("case_index,expected", [
    (0, 1), (1, 2), (None, 3),
])
def test_selected_select_case_and_default_bodies_are_isolated(case_index, expected):
    program, semantic, builder, lowerer = _start(
        "SELECT (1) { CASE 1: { SHOW(1); } CASE 2: { SHOW(2); } "
        "DEFAULT: { SHOW(3); } }"
    )
    select = program.main.statements[0]
    selected = select.default if case_index is None else select.cases[case_index].body
    assert selected is not None and semantic.start.scope_of(selected) is not None
    lowerer.lower_block(semantic.start, selected)
    instruction, = builder.snapshot()
    assert isinstance(instruction, Show)
    assert instruction.value == Constant(T.INT, expected, str(expected))


@pytest.mark.parametrize("body", [
    "WHILE (TRUE) { SHOW(1); }",
    "DO { SHOW(1); } WHILE (FALSE);",
])
def test_selected_while_and_do_while_bodies_lower_without_enclosing_loop(body):
    program, semantic, builder, lowerer = _start(f"SHOW(9); {body} SHOW(8);")
    selected = program.main.statements[1].body
    lowerer.lower_block(semantic.start, selected)
    instruction, = builder.snapshot()
    assert isinstance(instruction, Show)
    assert instruction.value == Constant(T.INT, 1, "1")


@pytest.mark.parametrize("part,expected_types", [
    ("initializer", (InitScalar,)),
    ("body", (Load, Show)),
    ("update", (Load, Binary, Move)),
])
def test_selected_repeat_parts_use_exact_analyzed_symbol(part, expected_types):
    program, semantic, builder, lowerer = _start(
        "REPEAT (INT i = 0; i < 2; i = i + 1) { SHOW(i); }"
    )
    selected = getattr(program.main.statements[0], part)
    if part == "body":
        lowerer.lower_block(semantic.start, selected)
    else:
        lowerer.lower_statement(semantic.start, selected)
    instructions = builder.snapshot()
    assert tuple(type(item) for item in instructions) == expected_types
    symbol = semantic.start.declaration_of(program.main.statements[0].initializer)
    assert symbol is not None
    references = [item.target for item in instructions if isinstance(item, (InitScalar, Move))]
    references += [item.source for item in instructions if isinstance(item, Load)]
    assert references and all(ref.symbol is symbol for ref in references)


def test_selected_occurrence_through_multiple_control_flow_ancestors():
    program, semantic, builder, lowerer = _start(
        "WHEN (TRUE) { SELECT (1) { CASE 1: { WHILE (TRUE) { "
        "REPEAT (INT i = 0; i < 1; i = i + 1) { SHOW(i); } "
        "SHOW(99); } } } }"
    )
    repeat = program.main.statements[0].then_block.statements[0].cases[0].body.statements[0].body.statements[0]
    lowerer.lower_block(semantic.start, repeat.body)
    load, show = builder.snapshot()
    assert isinstance(load, Load) and isinstance(show, Show)
    assert load.source.symbol is semantic.start.declaration_of(repeat.initializer)
    assert show.value is load.result


@pytest.mark.parametrize("clone", [False, True])
def test_selected_foreign_or_cloned_control_flow_descendant_is_rejected(clone):
    program, semantic, builder, lowerer = _start("WHEN (TRUE) { SHOW(1); }")
    selected = program.main.statements[0].then_block
    if clone:
        selected = replace(selected)
    else:
        other, _, _, _ = _start("WHEN (TRUE) { SHOW(1); }")
        selected = other.main.statements[0].then_block
    with pytest.raises(StatementInputError, match="not an occurrence"):
        lowerer.lower_block(semantic.start, selected)
    assert builder.snapshot() == () and lowerer.failed


@pytest.mark.parametrize("body", [
    "WHEN (TRUE) { SHOW(1); } OTHERWISE { SHOW(2); }",
    "SELECT (1) { CASE 1: { SHOW(1); } DEFAULT: { SHOW(2); } }",
    "WHILE (TRUE) { SHOW(1); }",
    "DO { SHOW(1); } WHILE (FALSE);",
    "REPEAT (INT i = 0; i < 1; i = i + 1) { SHOW(i); }",
])
def test_direct_control_flow_selection_lowers_successfully(body):
    program, semantic, builder, lowerer = _start(body)
    lowerer.lower_statement(semantic.start, program.main.statements[0])
    assert builder.snapshot() and not lowerer.failed
    assert all(item.target.owner is builder.owner for item in builder.snapshot()
               if isinstance(item, Label))


def test_foreign_symbol_inventory_fails_and_earlier_snapshot_is_immutable():
    _, semantic, builder, lowerer = _start("INT x; SHOW(x);")
    first = semantic.start.root.statements[0]
    lowerer.lower_statement(semantic.start, first)
    snapshot = builder.snapshot()
    other = IRBuilder(builder.owner, builder.root_scope_id)
    bad = StatementLowerer(other)
    with pytest.raises(ValueError):
        bad.lower_statement(semantic.start, first)
    assert bad.failed and snapshot == builder.snapshot()


def test_missing_expression_metadata_is_controlled_when_mutated_externally():
    _, semantic, builder, lowerer = _start("INT x = 1;")
    altered = replace(semantic.start, expressions=semantic.start.expressions)
    object.__setattr__(altered, "expressions", ())
    with pytest.raises(StatementMetadataError, match="expression metadata"):
        lowerer.lower_block(altered)
    assert lowerer.failed and builder.snapshot() == ()
