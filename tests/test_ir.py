"""Focused construction tests for M5 Task 02 structural IR records."""

from dataclasses import FrozenInstanceError, replace

import pytest

from sparq.ast_nodes import SourceSpan
from sparq.ir import (
    ArrayRef, Binary, BoolMergeTemp, BranchBool, Call, CheckBounds,
    CheckedElement, Compare, Constant, Convert, Effect, FunctionRef, HaltStart,
    IRFunction, IRProgram, IRRoutine, InitArray, InitElement, InitScalar,
    Jump, Label, LabelRef, Load, LoadElement, Move, ParameterRef,
    ReadElement, ReadScalar, Return, RoutineId, RoutineKind, Show,
    StoreElement, Temporary, Unary, VariableRef, effects,
)
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.symbols import ScalarType as T, SymbolKind, VariableSymbol
from sparq.token import TokenType as K


SPAN = SourceSpan(1, 1, 1, 2)


@pytest.fixture
def sample():
    program = Parser(Lexer("""FUNC f(INT p, FLOAT q) -> FLOAT { RETURN q; }
FUNC g() -> VOID {}
START { INT x; FLOAT y; BOOL b; INT arr[2]; FLOAT fa[2]; }""").tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    start = RoutineId.start()
    function = RoutineId.for_function(analysis.signatures[0])
    empty_function = RoutineId.for_function(analysis.signatures[1])
    declarations = {node.name: symbol for node, symbol in analysis.start.declarations}
    refs = {name: (ArrayRef(start, symbol) if symbol.kind is SymbolKind.ARRAY
                   else VariableRef(start, symbol))
            for name, symbol in declarations.items()}
    parameters = tuple(ParameterRef(function, item) for item in analysis.functions[0].parameters)
    return program, analysis, start, function, empty_function, refs, parameters


@pytest.mark.parametrize("kind,value", [
    (T.INT, 0), (T.FLOAT, 0.0), (T.FLOAT, -0.0),
    (T.CHAR, "A"), (T.CHAR, "\0"), (T.STRING, ""), (T.STRING, "a\nb"),
    (T.BOOL, False), (T.BOOL, True),
])
def test_valid_constants_keep_exact_value_and_type(kind, value):
    item = Constant(kind, value)
    assert item.type is kind and type(item.value) is type(value) and item.value == value
    with pytest.raises(FrozenInstanceError):
        item.value = None


@pytest.mark.parametrize("kind,value", [
    (T.INT, True), (T.INT, 1.0), (T.BOOL, 1), (T.BOOL, "TRUE"),
    (T.FLOAT, 1), (T.FLOAT, float("inf")), (T.FLOAT, float("nan")),
    (T.CHAR, ""), (T.CHAR, "ab"), (T.CHAR, "\ud800"),
    (T.STRING, 1), (T.STRING, "\udfff"),
])
def test_constant_rejects_wrong_host_value(kind, value):
    with pytest.raises((TypeError, ValueError)):
        Constant(kind, value)


def test_large_integer_and_lexeme_remain_exact_with_bounded_debug_repr():
    lexeme = "9" * 5000
    value = 10 ** 5000 - 1
    item = Constant(T.INT, value, lexeme)
    assert item.value == value and item.lexeme == lexeme
    shown = repr(item)
    assert "bits=" in shown and len(shown) < 120
    owner = RoutineId.start()
    assert len(repr(Binary(owner, SPAN, K.PLUS, item, Constant(T.INT, 1),
                           Temporary(owner, 1, T.INT)))) < 350
    assert repr(Constant(T.INT, 42)) == "Constant(INT, 42)"


def test_huge_array_length_is_metadata_and_has_bounded_repr():
    owner = RoutineId.start()
    huge = 10 ** 5000
    symbol = VariableSymbol(1, "items", T.INT, SymbolKind.ARRAY, 1, SPAN, huge)
    array = ArrayRef(owner, symbol)
    initialization = InitArray(owner, SPAN, array, huge, Constant(T.INT, 0))
    assert array.length is huge and initialization.length is huge
    assert len(repr(array)) < 180 and len(repr(initialization)) < 250


def test_operand_categories_preserve_resolved_identity(sample):
    _, _, start, function, _, refs, parameters = sample
    assert refs["x"].symbol is not refs["y"].symbol
    assert refs["arr"].length == 2 and refs["arr"].element_type is T.INT
    assert parameters[0].type is T.INT and parameters[1].type is T.FLOAT
    assert parameters[0].owner is function and refs["x"].owner is start
    assert type(refs["x"]) is VariableRef
    assert type(refs["arr"]) is ArrayRef
    assert type(parameters[0]) is ParameterRef
    assert type(Temporary(start, 1, T.INT)) is not type(LabelRef(start, 1))
    assert RoutineId.start() is not RoutineId.start()
    assert RoutineId.start() != RoutineId.start()
    with pytest.raises(FrozenInstanceError):
        refs["x"].symbol = refs["y"].symbol


def test_invalid_operand_categories_and_owners(sample):
    _, analysis, start, function, _, refs, parameters = sample
    with pytest.raises(ValueError):
        ArrayRef(start, refs["x"].symbol)
    with pytest.raises(ValueError):
        VariableRef(start, refs["arr"].symbol)
    with pytest.raises(ValueError):
        ParameterRef(start, parameters[0].symbol)
    with pytest.raises(ValueError):
        Temporary(start, True, T.INT)
    with pytest.raises(TypeError):
        Temporary(start, 1, None)
    with pytest.raises(ValueError):
        LabelRef(start, 0)
    with pytest.raises(TypeError):
        CheckedElement(start, 1, refs["arr"], refs["x"])
    with pytest.raises(ValueError):
        CheckedElement(function, 1, refs["arr"], Constant(T.INT, 0))
    with pytest.raises(ValueError):
        RoutineId(RoutineKind.START, analysis.signatures[0])


def test_function_ref_signature_and_owner_identity(sample):
    _, analysis, start, function, _, _, _ = sample
    ref = FunctionRef(analysis.signatures[0])
    assert ref.parameter_types == (T.INT, T.FLOAT)
    assert ref.return_type is T.FLOAT
    assert function.function is ref.symbol
    assert start.kind is RoutineKind.START
    with pytest.raises(TypeError):
        FunctionRef(None)


def test_instruction_families_accept_normalized_types_and_deferred_traps(sample):
    _, analysis, owner, function, _, refs, _ = sample
    ci = Constant(T.INT, 1)
    cf = Constant(T.FLOAT, 2.5)
    cb = Constant(T.BOOL, True)
    ti = Temporary(owner, 1, T.INT)
    tf = Temporary(owner, 2, T.FLOAT)
    tb = Temporary(owner, 3, T.BOOL)
    array = refs["arr"]
    index = Constant(T.INT, 0)
    guard = CheckedElement(owner, 1, array, index)
    label = LabelRef(owner, 1)
    instructions = [
        InitScalar(owner, SPAN, refs["x"], ci),
        Move(owner, SPAN, refs["x"], ci),
        Load(owner, SPAN, refs["x"], ti),
        Unary(owner, SPAN, K.MINUS, ci, ti),
        Unary(owner, SPAN, K.NOT, cb, tb),
        Binary(owner, SPAN, K.PLUS, ci, ci, ti),
        Binary(owner, SPAN, K.SLASH, ci, Constant(T.INT, 0), ti),
        Compare(owner, SPAN, K.EQUAL_EQUAL, ci, ci, tb),
        Convert(owner, SPAN, ci, tf),
        InitArray(owner, SPAN, array, 2, Constant(T.INT, 0)),
        InitElement(owner, SPAN, array, 0, ci),
        CheckBounds(owner, SPAN, array, index, guard),
        LoadElement(owner, SPAN, guard, ti),
        StoreElement(owner, SPAN, guard, ci),
        Label(owner, SPAN, label), Jump(owner, SPAN, label),
        BranchBool(owner, SPAN, cb, label, label),
        Call(owner, SPAN, FunctionRef(analysis.signatures[0]),
             (ci, cf), tf),
        Return(function, SPAN, cf),
        ReadScalar(owner, SPAN, refs["x"]),
        ReadElement(owner, SPAN, guard),
        Show(owner, SPAN, ci),
        HaltStart(owner, SPAN),
    ]
    assert len(instructions) == 23
    assert Effect.MAY_TRAP in effects(instructions[6])
    assert Effect.MAY_TRAP in effects(instructions[8])
    assert Effect.MAY_TRAP in effects(instructions[11])
    assert Effect.INPUT in effects(instructions[-3])
    assert Effect.OUTPUT in effects(instructions[-2])
    assert Effect.CALL in effects(instructions[17])
    assert Effect.CONTROL in effects(instructions[-1])
    assert Effect.READ_STORAGE not in effects(instructions[0])


def test_instruction_rejects_invalid_normalized_types_and_shapes(sample):
    _, analysis, owner, other, _, refs, _ = sample
    ti = Temporary(owner, 1, T.INT)
    tf = Temporary(owner, 2, T.FLOAT)
    tb = Temporary(owner, 3, T.BOOL)
    ci = Constant(T.INT, 1)
    cf = Constant(T.FLOAT, 1.0)
    cb = Constant(T.BOOL, True)
    index = Constant(T.INT, 0)
    guard = CheckedElement(owner, 1, refs["arr"], index)
    wrong = CheckedElement(owner, 2, refs["fa"], index)
    bad = [
        lambda: InitScalar(owner, SPAN, refs["x"], cb),
        lambda: Move(owner, SPAN, refs["x"], refs["arr"]),
        lambda: Load(owner, SPAN, refs["x"], tf),
        lambda: Unary(owner, SPAN, K.NOT, ci, tb),
        lambda: Unary(owner, SPAN, K.MINUS, cb, ti),
        lambda: Binary(owner, SPAN, K.PLUS, ci, cf, tf),
        lambda: Binary(owner, SPAN, K.PERCENT, cf, cf, tf),
        lambda: Binary(owner, SPAN, K.PLUS, cb, cb, tb),
        lambda: Compare(owner, SPAN, K.LESS, cb, cb, tb),
        lambda: Compare(owner, SPAN, K.EQUAL_EQUAL, ci, ci, ti),
        lambda: Convert(owner, SPAN, cf, tf),
        lambda: Convert(owner, SPAN, ci, ti),
        lambda: InitArray(owner, SPAN, refs["arr"], 3, ci),
        lambda: InitArray(owner, SPAN, refs["arr"], 2, ci),
        lambda: InitElement(owner, SPAN, refs["arr"], 2, ci),
        lambda: InitElement(owner, SPAN, refs["arr"], 0, cf),
        lambda: CheckBounds(owner, SPAN, refs["arr"], refs["x"], guard),
        lambda: CheckBounds(owner, SPAN, refs["arr"], index, wrong),
        lambda: LoadElement(owner, SPAN, guard, tf),
        lambda: StoreElement(owner, SPAN, guard, cf),
        lambda: StoreElement(owner, SPAN, guard, wrong),
        lambda: BranchBool(owner, SPAN, ci, LabelRef(owner, 1), LabelRef(owner, 2)),
        lambda: Jump(owner, SPAN, LabelRef(other, 1)),
        lambda: Return(owner, SPAN, ci),
        lambda: Return(other, SPAN, ci),
        lambda: ReadScalar(owner, SPAN, refs["arr"]),
        lambda: ReadElement(owner, SPAN, wrong.array),
        lambda: Show(owner, SPAN, guard),
        lambda: HaltStart(other, SPAN),
    ]
    for make in bad:
        with pytest.raises((TypeError, ValueError)):
            make()


def test_instruction_inputs_reject_foreign_routine_and_merge_type(sample):
    _, _, owner, _, _, refs, _ = sample
    foreign = Temporary(RoutineId.start(), 1, T.INT)
    local = Temporary(owner, 1, T.INT)
    with pytest.raises(ValueError, match="another routine"):
        Binary(owner, SPAN, K.PLUS, foreign, Constant(T.INT, 1), local)
    with pytest.raises(ValueError, match="another routine"):
        Show(owner, SPAN, foreign)
    with pytest.raises(ValueError):
        Move(owner, SPAN, BoolMergeTemp(owner, 2), refs["b"])
    with pytest.raises(ValueError):
        CheckBounds(owner, SPAN, refs["arr"], foreign,
                    CheckedElement(owner, 1, refs["arr"], Constant(T.INT, 0)))


def test_array_defaults_and_effect_contract(sample):
    _, analysis, owner, _, _, refs, _ = sample
    assert InitArray(owner, SPAN, refs["fa"], 2, Constant(T.FLOAT, 0.0))
    with pytest.raises(ValueError):
        InitArray(owner, SPAN, refs["fa"], 2, Constant(T.FLOAT, -0.0))
    div = Binary(owner, SPAN, K.SLASH, Constant(T.INT, 1),
                 Constant(T.INT, 0), Temporary(owner, 1, T.INT))
    assert Effect.MAY_TRAP in effects(div)
    show = Show(owner, SPAN, refs["x"])
    assert effects(show) == frozenset({Effect.READ_STORAGE, Effect.OUTPUT})
    call = Call(owner, SPAN, FunctionRef(analysis.signatures[1]), ())
    assert {Effect.CALL, Effect.MAY_TRAP, Effect.INPUT, Effect.OUTPUT} <= effects(call)


def test_call_owns_argument_tuple_and_validates_result_forms(sample):
    _, analysis, owner, _, _, _, _ = sample
    function = FunctionRef(analysis.signatures[0])
    arguments = [Constant(T.INT, 1), Constant(T.FLOAT, 2.0)]
    result = Temporary(owner, 1, T.FLOAT)
    call = Call(owner, SPAN, function, arguments, result)
    arguments.clear()
    assert call.arguments == (Constant(T.INT, 1), Constant(T.FLOAT, 2.0))
    assert isinstance(call.arguments, tuple)
    discarded = Call(owner, SPAN, function, list(call.arguments), discard_result=True)
    assert discarded.arguments == call.arguments and discarded.result is None
    void = Call(owner, SPAN, FunctionRef(analysis.signatures[1]), ())
    assert void.result is None and void.arguments == ()
    with pytest.raises(ValueError):
        Call(owner, SPAN, function, (Constant(T.INT, 1),), result)
    with pytest.raises(ValueError):
        Call(owner, SPAN, function, (Constant(T.INT, 1), Constant(T.INT, 2)), result)
    with pytest.raises(ValueError):
        Call(owner, SPAN, function, call.arguments, Temporary(owner, 2, T.INT))
    with pytest.raises(ValueError):
        Call(owner, SPAN, function, call.arguments)
    with pytest.raises(ValueError):
        Call(owner, SPAN, FunctionRef(analysis.signatures[1]), (), discard_result=True)
    with pytest.raises(FrozenInstanceError):
        call.arguments = ()


def test_structural_routine_and_program_snapshot_collections(sample):
    program, analysis, start, function, empty, refs, parameters = sample
    start_instructions = [HaltStart(start, SPAN)]
    symbols = list(refs.values())
    entry = IRRoutine(start, analysis.start_scope.id, (), symbols, start_instructions)
    start_instructions.clear()
    symbols.clear()
    assert len(entry.instructions) == 1 and len(entry.local_symbols) == len(refs)
    f_body = IRRoutine(function, analysis.functions[0].scope.id,
                       list(parameters), list(parameters),
                       [Return(function, SPAN, parameters[1])])
    g_body = IRRoutine(empty, analysis.functions[1].scope.id, (), (),
                       [Return(empty, SPAN)])
    functions = [IRFunction(FunctionRef(analysis.signatures[0]), list(parameters), f_body),
                 IRFunction(FunctionRef(analysis.signatures[1]), (), g_body)]
    result = IRProgram(program, analysis, functions, entry)
    functions.clear()
    assert len(result.functions) == 2
    assert result.source_program is program and result.semantic_owner is analysis
    with pytest.raises(FrozenInstanceError):
        entry.instructions = ()
    with pytest.raises(ValueError):
        IRProgram(program, analysis, (), entry)
    with pytest.raises(ValueError):
        IRRoutine(start, analysis.start_scope.id, (), (), [Jump(start, SPAN, LabelRef(start, 1))])
    with pytest.raises(ValueError):
        IRRoutine(start, analysis.start_scope.id, (), (), [
            Label(start, SPAN, LabelRef(start, 1)), Label(start, SPAN, LabelRef(start, 1)),
        ])
    with pytest.raises(ValueError):
        IRRoutine(start, analysis.start_scope.id, (), (), [Show(start, SPAN, refs["x"])])
    temp = Temporary(start, 1, T.INT)
    with pytest.raises(ValueError, match="defined twice"):
        IRRoutine(start, analysis.start_scope.id, (), (refs["x"],), [
            Load(start, SPAN, refs["x"], temp),
            Move(start, SPAN, temp, Constant(T.INT, 1)),
        ])


@pytest.mark.parametrize("first,second", [
    (Temporary, Temporary),
    (Temporary, BoolMergeTemp),
    (BoolMergeTemp, Temporary),
])
def test_direct_routine_rejects_conflicting_temporary_definitions(first, second):
    owner = RoutineId.start()
    left = first(owner, 1, T.INT) if first is Temporary else first(owner, 1)
    right = second(owner, 1, T.BOOL) if second is Temporary else second(owner, 1)
    instructions = (
        Move(owner, SPAN, left, Constant(left.type, 1 if left.type is T.INT else True)),
        Move(owner, SPAN, right, Constant(T.BOOL, True)),
    )
    with pytest.raises(ValueError, match="temporary identity"):
        IRRoutine(owner, 1, (), (), instructions)


def test_direct_routine_rejects_conflicting_temporary_uses(sample):
    _, analysis, owner, function, _, refs, _ = sample
    defined_int = Temporary(owner, 1, T.INT)
    contradictory_bool = Temporary(owner, 1, T.BOOL)
    definition = Move(owner, SPAN, defined_int, Constant(T.INT, 1))
    target = LabelRef(owner, 1)
    cases = (
        (Show(owner, SPAN, contradictory_bool),),
        (BranchBool(owner, SPAN, contradictory_bool, target, target), Label(owner, SPAN, target)),
        (Call(owner, SPAN, FunctionRef(analysis.signatures[0]),
              (Constant(T.INT, 1), Temporary(owner, 1, T.FLOAT)),
              Temporary(owner, 2, T.FLOAT)),),
    )
    for trailing in cases:
        with pytest.raises(ValueError, match="temporary identity"):
            IRRoutine(owner, analysis.start_scope.id, (), tuple(refs.values()),
                      (definition, *trailing))

    function_int = Temporary(function, 1, T.INT)
    function_float = Temporary(function, 1, T.FLOAT)
    with pytest.raises(ValueError, match="temporary identity"):
        IRRoutine(function, analysis.functions[0].scope.id,
                  tuple(ParameterRef(function, item) for item in analysis.functions[0].parameters),
                  tuple(ParameterRef(function, item) for item in analysis.functions[0].parameters),
                  (Move(function, SPAN, function_int, Constant(T.INT, 1)),
                   Return(function, SPAN, function_float)))


def test_direct_routine_checks_temporary_metadata_inside_guard_index(sample):
    _, analysis, owner, _, _, refs, _ = sample
    defined = Temporary(owner, 1, T.FLOAT)
    index = Temporary(owner, 1, T.INT)
    guard = CheckedElement(owner, 1, refs["arr"], index)
    with pytest.raises(ValueError, match="temporary identity"):
        IRRoutine(owner, analysis.start_scope.id, (), tuple(refs.values()), (
            Move(owner, SPAN, defined, Constant(T.FLOAT, 1.0)),
            ReadElement(owner, SPAN, guard),
        ))


def test_consistent_temporary_references_and_merge_assignments_remain_valid():
    owner = RoutineId.start()
    original = Temporary(owner, 1, T.INT)
    equivalent = Temporary(owner, 1, T.INT)
    result = Temporary(owner, 2, T.INT)
    merge = BoolMergeTemp(owner, 3)
    equivalent_merge = BoolMergeTemp(owner, 3)
    instructions = (
        Move(owner, SPAN, original, Constant(T.INT, 1)),
        Binary(owner, SPAN, K.PLUS, equivalent, Constant(T.INT, 2), result),
        Show(owner, SPAN, equivalent),
        Move(owner, SPAN, merge, Constant(T.BOOL, True)),
        Move(owner, SPAN, equivalent_merge, Constant(T.BOOL, False)),
        Show(owner, SPAN, merge),
    )
    assert len(IRRoutine(owner, 1, (), (), instructions).instructions) == 6
    with pytest.raises(ValueError, match="defined twice"):
        IRRoutine(owner, 1, (), (), (
            Move(owner, SPAN, original, Constant(T.INT, 1)),
            Move(owner, SPAN, equivalent, Constant(T.INT, 2)),
        ))
    other = RoutineId.start()
    assert IRRoutine(other, 1, (), (), (
        Move(other, SPAN, Temporary(other, 1, T.FLOAT), Constant(T.FLOAT, 1.0)),
    ))


@pytest.mark.parametrize("variation", ["index", "array", "same"])
def test_direct_routine_rejects_redefined_guard_number(sample, variation):
    _, analysis, owner, _, _, refs, _ = sample
    first_index = Constant(T.INT, 0)
    first_array = refs["arr"]
    first = CheckedElement(owner, 1, first_array, first_index)
    second_array = refs["fa"] if variation == "array" else first_array
    second_index = Constant(T.INT, 1) if variation == "index" else first_index
    second = CheckedElement(owner, 1, second_array, second_index)
    with pytest.raises(ValueError, match="guard (identity|defined twice)"):
        IRRoutine(owner, analysis.start_scope.id, (), tuple(refs.values()), (
            CheckBounds(owner, SPAN, first_array, first_index, first),
            CheckBounds(owner, SPAN, second_array, second_index, second),
        ))


@pytest.mark.parametrize("variation", ["index", "array"])
def test_guard_use_cannot_change_existing_identity_metadata(sample, variation):
    _, analysis, owner, _, _, refs, _ = sample
    index = Constant(T.INT, 0)
    original = CheckedElement(owner, 1, refs["arr"], index)
    different = CheckedElement(
        owner, 1,
        refs["fa"] if variation == "array" else refs["arr"],
        Constant(T.INT, 1) if variation == "index" else index,
    )
    with pytest.raises(ValueError, match="guard identity"):
        IRRoutine(owner, analysis.start_scope.id, (), tuple(refs.values()), (
            CheckBounds(owner, SPAN, refs["arr"], index, original),
            ReadElement(owner, SPAN, different),
        ))


def test_consistent_guard_references_and_runtime_deferred_indexes(sample):
    _, analysis, owner, _, _, refs, _ = sample
    array = refs["arr"]
    checks = []
    for number, position in enumerate((-1, array.length, array.length + 1), 1):
        index = Constant(T.INT, position)
        guard = CheckedElement(owner, number, array, index)
        checks.extend((CheckBounds(owner, SPAN, array, index, guard),
                       StoreElement(owner, SPAN, guard, Constant(T.INT, 4))))
    equivalent = CheckedElement(owner, 1, array, Constant(T.INT, -1))
    checks.append(LoadElement(owner, SPAN, equivalent, Temporary(owner, 1, T.INT)))
    checks.append(ReadElement(owner, SPAN, equivalent))
    assert len(IRRoutine(owner, analysis.start_scope.id, (), tuple(refs.values()),
                         checks).instructions) == 8
    other = RoutineId.start()
    other_array = ArrayRef(other, refs["arr"].symbol)
    other_index = Constant(T.INT, 0)
    other_guard = CheckedElement(other, 1, other_array, other_index)
    assert IRRoutine(other, 1, (), (other_array,), (
        CheckBounds(other, SPAN, other_array, other_index, other_guard),
    ))
    assert type(other_guard) is not type(Temporary(other, 1, T.INT))
    assert type(other_guard) is not type(LabelRef(other, 1))


@pytest.mark.parametrize("position,valid", [
    (-1, False), (0, True), (1, True), (2, False), (True, False),
])
def test_initializer_positions_are_known_in_range_ints(sample, position, valid):
    _, _, owner, _, _, refs, _ = sample
    if valid:
        assert InitElement(owner, SPAN, refs["arr"], position, Constant(T.INT, 7)).index == position
    else:
        with pytest.raises(ValueError):
            InitElement(owner, SPAN, refs["arr"], position, Constant(T.INT, 7))


def test_routine_parameter_inventory_requires_the_exact_semantic_symbol(sample):
    _, analysis, _, owner, _, _, parameters = sample
    original = parameters[0]
    clone = ParameterRef(owner, replace(original.symbol))
    assert clone.symbol == original.symbol and clone.symbol is not original.symbol
    with pytest.raises(ValueError, match="registered semantic symbols"):
        IRRoutine(owner, analysis.functions[0].scope.id,
                  (clone, parameters[1]), parameters,
                  (Return(owner, SPAN, parameters[1]),))
    valid = IRRoutine(
        owner, analysis.functions[0].scope.id,
        tuple(ParameterRef(owner, item.symbol) for item in parameters),
        tuple(ParameterRef(owner, item.symbol) for item in parameters),
        (Return(owner, SPAN, parameters[1]),),
    )
    assert valid.parameters[0] is not valid.local_symbols[0]
    assert valid.parameters[0].symbol is valid.local_symbols[0].symbol


def _sample_ir_program(sample, parameters):
    program, analysis, start, function, empty, refs, _ = sample
    body = IRRoutine(function, analysis.functions[0].scope.id,
                     parameters, tuple(ParameterRef(function, item.symbol) for item in parameters),
                     (Return(function, SPAN, parameters[1]),))
    empty_body = IRRoutine(empty, analysis.functions[1].scope.id, (), (),
                           (Return(empty, SPAN),))
    entry = IRRoutine(start, analysis.start_scope.id, (), tuple(refs.values()),
                      (HaltStart(start, SPAN),))
    return IRProgram(program, analysis, (
        IRFunction(FunctionRef(analysis.signatures[0]),
                   tuple(ParameterRef(function, item.symbol) for item in parameters), body),
        IRFunction(FunctionRef(analysis.signatures[1]), (), empty_body),
    ), entry)


def test_program_rejects_cloned_parameter_even_when_routine_is_self_consistent(sample):
    _, analysis, _, owner, _, _, parameters = sample
    clone = ParameterRef(owner, replace(parameters[0].symbol))
    assert clone.symbol == analysis.functions[0].parameters[0]
    with pytest.raises(ValueError, match="order or ownership"):
        _sample_ir_program(sample, (clone, parameters[1]))
    valid = _sample_ir_program(sample, parameters)
    assert tuple(item.symbol for item in valid.functions[0].parameters) == analysis.functions[0].parameters
    assert all(item.symbol is analyzed for item, analyzed in zip(
        valid.functions[0].parameters, analysis.functions[0].parameters))


def test_ir_function_rejects_equal_but_distinct_parameter_symbol(sample):
    _, analysis, _, owner, _, _, parameters = sample
    body = IRRoutine(owner, analysis.functions[0].scope.id,
                     parameters, parameters, (Return(owner, SPAN, parameters[1]),))
    cloned = ParameterRef(owner, replace(parameters[0].symbol))
    with pytest.raises(ValueError, match="metadata"):
        IRFunction(FunctionRef(analysis.signatures[0]),
                   (cloned, parameters[1]), body)
    assert IRFunction(FunctionRef(analysis.signatures[0]),
                      tuple(ParameterRef(owner, p.symbol) for p in parameters), body)


def test_parameter_order_and_independent_semantic_sessions(sample):
    _, analysis, _, owner, _, _, parameters = sample
    with pytest.raises(ValueError):
        IRRoutine(owner, analysis.functions[0].scope.id,
                  tuple(reversed(parameters)), parameters, ())
    valid = _sample_ir_program(sample, parameters)
    independent = SemanticAnalyzer(
        Parser(Lexer("FUNC f(INT p, FLOAT q) -> FLOAT { RETURN q; } "
                     "FUNC g() -> VOID {} START { INT x; FLOAT y; BOOL b; "
                     "INT arr[2]; FLOAT fa[2]; }").tokenize()).parse()
    ).analyze()
    with pytest.raises(ValueError, match="semantic result does not own"):
        IRProgram(valid.source_program, independent, valid.functions, valid.entry)


def test_identically_named_parameters_in_distinct_functions_keep_identity():
    program = Parser(Lexer(
        "FUNC f(INT x) -> VOID {} FUNC g(INT x) -> VOID {} START {}"
    ).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    assert analysis.functions[0].parameters[0].name == analysis.functions[1].parameters[0].name
    assert analysis.functions[0].parameters[0].id != analysis.functions[1].parameters[0].id
    assert analysis.functions[0].parameters[0] is not analysis.functions[1].parameters[0]


def test_effects_classify_each_instruction_family_conservatively(sample):
    _, analysis, owner, function, _, refs, parameters = sample
    E = Effect
    ci, cf = Constant(T.INT, 1), Constant(T.FLOAT, 2.5)
    ti, tf, tb = Temporary(owner, 1, T.INT), Temporary(owner, 2, T.FLOAT), Temporary(owner, 3, T.BOOL)
    index = Constant(T.INT, 0)
    guard = CheckedElement(owner, 1, refs["arr"], index)
    target = LabelRef(owner, 1)
    cases = (
        (InitScalar(owner, SPAN, refs["x"], ci), {E.WRITE_STORAGE}),
        (Move(owner, SPAN, refs["x"], refs["x"]), {E.READ_STORAGE, E.WRITE_STORAGE}),
        (Load(owner, SPAN, refs["x"], ti), {E.READ_STORAGE}),
        (Unary(owner, SPAN, K.MINUS, refs["x"], ti), {E.READ_STORAGE}),
        (Binary(owner, SPAN, K.PLUS, refs["x"], ci, ti), {E.READ_STORAGE}),
        (Binary(owner, SPAN, K.SLASH, ci, Constant(T.INT, 0), ti), {E.MAY_TRAP}),
        (Binary(owner, SPAN, K.PERCENT, ci, Constant(T.INT, 0), ti), {E.MAY_TRAP}),
        (Binary(owner, SPAN, K.PLUS, cf, cf, tf), {E.MAY_TRAP}),
        (Compare(owner, SPAN, K.EQUAL_EQUAL, refs["x"], ci, tb), {E.READ_STORAGE}),
        (Convert(owner, SPAN, refs["x"], tf), {E.READ_STORAGE, E.MAY_TRAP}),
        (InitArray(owner, SPAN, refs["arr"], 2, Constant(T.INT, 0)),
         {E.WRITE_STORAGE, E.MAY_TRAP}),
        (InitElement(owner, SPAN, refs["arr"], 0, refs["x"]),
         {E.READ_STORAGE, E.WRITE_STORAGE}),
        (CheckBounds(owner, SPAN, refs["arr"], index, guard),
         {E.READ_STORAGE, E.MAY_TRAP}),
        (LoadElement(owner, SPAN, guard, ti), {E.READ_STORAGE}),
        (StoreElement(owner, SPAN, guard, refs["x"]),
         {E.READ_STORAGE, E.WRITE_STORAGE}),
        (Label(owner, SPAN, target), set()),
        (Jump(owner, SPAN, target), {E.CONTROL}),
        (BranchBool(owner, SPAN, refs["b"], target, target),
         {E.READ_STORAGE, E.CONTROL}),
        (Call(owner, SPAN, FunctionRef(analysis.signatures[0]), (refs["x"], cf), tf),
         {E.READ_STORAGE, E.CALL, E.MAY_TRAP, E.INPUT, E.OUTPUT}),
        (Return(function, SPAN, parameters[1]), {E.READ_STORAGE, E.CONTROL}),
        (ReadScalar(owner, SPAN, refs["x"]),
         {E.WRITE_STORAGE, E.MAY_TRAP, E.INPUT}),
        (ReadElement(owner, SPAN, guard),
         {E.WRITE_STORAGE, E.MAY_TRAP, E.INPUT}),
        (Show(owner, SPAN, refs["x"]), {E.READ_STORAGE, E.OUTPUT}),
        (HaltStart(owner, SPAN), {E.CONTROL}),
    )
    for instruction, expected in cases:
        assert effects(instruction) == frozenset(expected), type(instruction).__name__
