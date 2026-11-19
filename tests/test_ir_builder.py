"""Task 02 builder invariants and manually assembled IR fragments."""

from dataclasses import FrozenInstanceError

import pytest

from sparq.ast_nodes import SourceSpan
from sparq.ir import (
    ArrayRef, Binary, BoolMergeTemp, BranchBool, Call, CheckBounds,
    Constant, Convert, FunctionRef, IRRoutine, InitScalar, Jump, Label, LabelRef,
    LoadElement, Move, ParameterRef, ReadElement, RoutineId, Show,
    StoreElement, Temporary, VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.symbols import ScalarType as T, SymbolKind, VariableSymbol
from sparq.token import TokenType as K


SPAN = SourceSpan(1, 1, 1, 2)


@pytest.fixture
def setup():
    owner = RoutineId.start()
    x = VariableRef(owner, VariableSymbol(1, "x", T.INT, SymbolKind.VARIABLE, 1, SPAN))
    y = VariableRef(owner, VariableSymbol(2, "y", T.FLOAT, SymbolKind.VARIABLE, 1, SPAN))
    b = VariableRef(owner, VariableSymbol(3, "b", T.BOOL, SymbolKind.VARIABLE, 1, SPAN))
    array = ArrayRef(owner, VariableSymbol(4, "a", T.INT, SymbolKind.ARRAY, 1, SPAN, 2))
    builder = IRBuilder(owner, 1, local_symbols=(x, y, b, array))
    return builder, owner, x, y, b, array


def test_allocator_is_deterministic_owned_and_separates_categories(setup):
    builder, owner, x, _, _, array = setup
    t1 = builder.temp(T.INT)
    merge = builder.merge_temp()
    guard = builder.guard(array, t1)
    label = builder.label()
    assert (t1.number, merge.number, guard.number, label.number) == (1, 2, 1, 1)
    assert t1.owner is merge.owner is guard.owner is label.owner is owner
    assert type(t1) is Temporary and type(merge) is BoolMergeTemp
    other_owner = RoutineId.start()
    other = IRBuilder(other_owner, 1)
    assert other.temp(T.INT).number == 1 and other.label().number == 1
    assert other_owner is not owner
    assert VariableRef(owner, VariableSymbol(5, "t1", T.INT, SymbolKind.VARIABLE, 1, SPAN)) != t1
    with pytest.raises(TypeError):
        builder.guard(array, x)  # a mutable variable is not a captured index
    assert builder.guard(array, Constant(T.INT, 0)).number == 2


def test_manual_arithmetic_and_conversion_fragments(setup):
    builder, owner, x, y, _, _ = setup
    product = builder.temp(T.INT)
    sum_value = builder.temp(T.INT)
    converted = builder.temp(T.FLOAT)
    total = builder.temp(T.FLOAT)
    builder.emit(Binary(owner, SPAN, K.STAR, x, Constant(T.INT, 2), product))
    builder.emit(Binary(owner, SPAN, K.PLUS, x, product, sum_value))
    builder.emit(Move(owner, SPAN, x, sum_value))
    builder.emit(Convert(owner, SPAN, x, converted))
    builder.emit(Binary(owner, SPAN, K.PLUS, converted, Constant(T.FLOAT, 2.5), total))
    builder.emit(Move(owner, SPAN, y, total))
    routine = builder.finish()
    assert isinstance(routine, IRRoutine)
    assert [type(item).__name__ for item in routine.instructions] == [
        "Binary", "Binary", "Move", "Convert", "Binary", "Move",
    ]
    assert routine.instructions[0].result is product
    assert routine.instructions[3].result is converted


def test_forward_labels_and_boolean_merge_fragment(setup):
    builder, owner, _, _, b, _ = setup
    true_label, false_label, join = builder.label(), builder.label(), builder.label()
    merge = builder.merge_temp()
    builder.emit(BranchBool(owner, SPAN, Constant(T.BOOL, True), true_label, false_label))
    builder.define(true_label, SPAN)
    builder.emit(Move(owner, SPAN, merge, Constant(T.BOOL, True)))
    builder.emit(Jump(owner, SPAN, join))
    builder.define(false_label, SPAN)
    builder.emit(Move(owner, SPAN, merge, Constant(T.BOOL, False)))
    builder.define(join, SPAN)
    builder.emit(InitScalar(owner, SPAN, b, merge))
    routine = builder.finish()
    assert len(routine.instructions) == 8
    assert routine.instructions[2].target is routine.instructions[5].target is merge
    assert routine.instructions[0].true_target is true_label


def test_guarded_array_fragment_and_exact_association(setup):
    builder, owner, _, _, _, array = setup
    index = builder.temp(T.INT)
    guard = builder.guard(array, index)
    value = builder.temp(T.INT)
    builder.emit(CheckBounds(owner, SPAN, array, index, guard))
    builder.emit(LoadElement(owner, SPAN, guard, value))
    builder.emit(StoreElement(owner, SPAN, guard, Constant(T.INT, 4)))
    builder.emit(ReadElement(owner, SPAN, guard))
    routine = builder.finish()
    assert routine.instructions[0].result is guard
    assert all(item.checked is guard for item in routine.instructions[1:])


def test_failed_emit_leaves_builder_unchanged_and_reusable(setup):
    builder, owner, x, _, _, _ = setup
    issued = builder.temp(T.INT)
    foreign = Temporary(RoutineId.start(), 1, T.INT)
    with pytest.raises(ValueError):
        builder.emit(Binary(owner, SPAN, K.PLUS, foreign, Constant(T.INT, 1), issued))
    assert builder.snapshot() == ()
    with pytest.raises(ValueError):
        builder.emit(Binary(owner, SPAN, K.PLUS, x, Constant(T.INT, 1),
                            Temporary(owner, 1, T.INT)))  # unallocated clone
    assert builder.snapshot() == ()
    valid = Binary(owner, SPAN, K.PLUS, x, Constant(T.INT, 1), issued)
    builder.emit(valid)
    assert builder.snapshot() == (valid,)
    with pytest.raises(ValueError):
        builder.emit(Binary(owner, SPAN, K.PLUS, x, Constant(T.INT, 2), issued))
    assert builder.snapshot() == (valid,)


def test_unresolved_label_can_be_defined_then_finish_retried(setup):
    builder, owner, *_ = setup
    later = builder.label()
    builder.emit(Jump(owner, SPAN, later))
    with pytest.raises(ValueError, match="undefined"):
        builder.finish()
    assert len(builder.snapshot()) == 1
    builder.define(later, SPAN)
    assert builder.finish().instructions[-1].target is later
    with pytest.raises(ValueError, match="completed"):
        builder.label()
    with pytest.raises(ValueError, match="completed"):
        builder.emit(Jump(owner, SPAN, later))
    assert builder.finish() is builder.finish()


def test_duplicate_foreign_and_unallocated_labels_rejected(setup):
    builder, owner, *_ = setup
    label = builder.label()
    builder.define(label, SPAN)
    with pytest.raises(ValueError, match="twice"):
        builder.define(label, SPAN)
    with pytest.raises(ValueError):
        builder.emit(Jump(owner, SPAN, LabelRef(owner, label.number)))
    foreign = IRBuilder(RoutineId.start(), 1)
    with pytest.raises(ValueError):
        builder.emit(Jump(owner, SPAN, foreign.label()))
    assert builder.snapshot() == (Label(owner, SPAN, label),)


def test_snapshot_is_detached_and_completed_records_are_immutable(setup):
    builder, owner, x, _, _, _ = setup
    with pytest.raises(AttributeError):
        builder.owner = RoutineId.start()
    with pytest.raises(AttributeError):
        builder.root_scope_id = 2
    first = InitScalar(owner, SPAN, x, Constant(T.INT, 0))
    builder.emit(first)
    snapshot = builder.snapshot()
    builder.emit(Show(owner, SPAN, x))
    assert snapshot == (first,)
    completed = builder.finish()
    assert completed.instructions == (first, Show(owner, SPAN, x))
    with pytest.raises(FrozenInstanceError):
        completed.instructions = ()
    with pytest.raises(ValueError):
        builder.temp(T.INT)


def test_call_argument_snapshot_survives_nested_construction(setup):
    builder, owner, _, y, _, _ = setup
    program = Parser(Lexer(
        "FUNC outer(FLOAT x) -> FLOAT { RETURN x; } "
        "FUNC inner() -> FLOAT { RETURN 2.0; } START {}"
    ).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    inner_result = builder.temp(T.FLOAT)
    inner = Call(owner, SPAN, FunctionRef(analysis.signatures[1]), (), inner_result)
    builder.emit(inner)
    args = [inner_result]
    outer_result = builder.temp(T.FLOAT)
    outer = Call(owner, SPAN, FunctionRef(analysis.signatures[0]), args, outer_result)
    builder.emit(outer)
    args.clear()
    assert outer.arguments == (inner_result,)
    assert builder.finish().instructions == (inner, outer)


def test_function_parameter_inventory_is_checked():
    program = Parser(Lexer("FUNC f(INT p) -> VOID {} START {}").tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    owner = RoutineId.for_function(analysis.signatures[0])
    parameter = ParameterRef(owner, analysis.functions[0].parameters[0])
    with pytest.raises(ValueError):
        IRBuilder(owner, analysis.functions[0].scope.id, parameters=(parameter,))
    builder = IRBuilder(owner, analysis.functions[0].scope.id,
                        parameters=(parameter,), local_symbols=(parameter,))
    assert builder.finish().parameters == (parameter,)
