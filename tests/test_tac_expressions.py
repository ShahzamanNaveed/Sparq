"""Source-to-typed-IR checks for the M5 scalar-expression checkpoint."""

from dataclasses import replace

import pytest

from sparq.ast_nodes import BinaryExpr, ShowStmt, UnaryExpr
from sparq.expression_lowering import (
    DeferredExpressionError, ExpressionLowerer, LoweringConstructionError,
    LoweringInputError, LoweringMetadataError, LoweringResourceError,
)
from sparq.ir import (
    ArrayRef, Binary, BoolMergeTemp, BranchBool, CheckBounds, Compare, Constant,
    Convert, Jump, Label, LabelRef, Load, LoadElement, Move, ParameterRef,
    RoutineId, Temporary, Unary, VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.semantic import ExpressionAnalysis, ExpressionAnalyzer, ExpressionAnnotations, SemanticContext
from sparq.symbols import ScalarType as T, SymbolKind
from sparq.token import TokenType as K


def _start(expression, declarations=""):
    program = Parser(Lexer(f"START {{ {declarations} SHOW({expression}); }}").tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    show = program.main.statements[-1]
    result = semantic.start.show_of(show)
    owner = RoutineId.start()
    locals_ = tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in semantic.start.declarations
    )
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=locals_)
    return result, ExpressionLowerer(builder), builder, semantic


@pytest.mark.parametrize("source,kind,value", [
    ("0", T.INT, 0), ("42", T.INT, 42), ("2.5", T.FLOAT, 2.5),
    ("'A'", T.CHAR, "A"), ("'\\0'", T.CHAR, "\0"),
    ('""', T.STRING, ""), ('"a\\nb"', T.STRING, "a\nb"),
    ('"Ω"', T.STRING, "Ω"), ("TRUE", T.BOOL, True), ("FALSE", T.BOOL, False),
])
def test_literals_preserve_type_decoded_value_and_lexeme(source, kind, value):
    analysis, lowerer, builder, _ = _start(source)
    result = lowerer.lower_value(analysis)
    assert isinstance(result, Constant)
    assert result.type is kind and type(result.value) is type(value)
    assert result.value == value and result.lexeme == analysis.root.lexeme
    assert builder.snapshot() == ()


def test_5000_digit_integer_remains_exact_without_unsafe_debug_conversion():
    source = "9" * 5000
    analysis, lowerer, builder, _ = _start(source)
    result = lowerer.lower_value(analysis)
    assert result.value == 10**5000 - 1
    assert result.lexeme == source and len(repr(result)) < 120
    assert builder.snapshot() == ()


def test_scalar_reference_is_eagerly_loaded_with_exact_symbol_and_span():
    analysis, lowerer, builder, semantic = _start("t1", "INT t1;")
    result = lowerer.lower_value(analysis)
    load, = builder.snapshot()
    assert isinstance(result, Temporary) and result.type is T.INT
    assert isinstance(load, Load) and load.result is result
    assert isinstance(load.source, VariableRef)
    assert load.source.symbol is semantic.start.declarations[0][1]
    assert load.source.symbol.name == "t1" and load.source is not result
    assert load.span == analysis.root.span


def test_parameter_reference_is_loaded_from_original_semantic_symbol():
    program = Parser(Lexer("FUNC f(INT p) -> INT { RETURN p; } START {}").tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    function = semantic.functions[0]
    returned = function.body.return_of(program.functions[0].body.statements[0])
    owner = RoutineId.for_function(function.function)
    parameter = ParameterRef(owner, function.parameters[0])
    builder = IRBuilder(owner, function.scope.id, parameters=(parameter,),
                        local_symbols=(ParameterRef(owner, function.parameters[0]),))
    value = ExpressionLowerer(builder).lower_value(returned.value)
    load, = builder.snapshot()
    assert isinstance(load, Load) and load.source.symbol is function.parameters[0]
    assert isinstance(load.source, ParameterRef) and load.result is value
    assert value.owner is owner and value.type is T.INT


@pytest.mark.parametrize("source,operator,kind", [
    ("1 + 2", K.PLUS, T.INT), ("4 - 3", K.MINUS, T.INT),
    ("2 * 3", K.STAR, T.INT), ("6 / 2", K.SLASH, T.INT),
    ("6 % 2", K.PERCENT, T.INT), ("1.5 + 2.5", K.PLUS, T.FLOAT),
])
def test_arithmetic_operators_emit_typed_binary_records(source, operator, kind):
    analysis, lowerer, builder, _ = _start(source)
    value = lowerer.lower_value(analysis)
    instruction, = builder.snapshot()
    assert isinstance(instruction, Binary) and instruction.operator is operator
    assert instruction.result is value and value.type is kind
    assert instruction.span == analysis.root.span


def test_precedence_grouping_left_associativity_and_load_order():
    analysis, lowerer, builder, semantic = _start("a + b * 2", "INT a; INT b;")
    result = lowerer.lower_value(analysis)
    instructions = builder.snapshot()
    assert [type(item) for item in instructions] == [Load, Load, Binary, Binary]
    assert [item.source.symbol for item in instructions[:2]] == [
        symbol for _, symbol in semantic.start.declarations
    ]
    assert instructions[2].operator is K.STAR
    assert instructions[3].operator is K.PLUS
    assert instructions[3].left is instructions[0].result
    assert instructions[3].right is instructions[2].result
    assert result is instructions[3].result

    analysis, lowerer, builder, _ = _start("a / b - c", "INT a; INT b; INT c;")
    lowerer.lower_value(analysis)
    assert [type(item) for item in builder.snapshot()] == [Load, Load, Binary, Load, Binary]
    assert [item.operator for item in builder.snapshot() if isinstance(item, Binary)] == [K.SLASH, K.MINUS]

    analysis, lowerer, builder, _ = _start("10 - 3 - 2")
    lowerer.lower_value(analysis)
    first, second = builder.snapshot()
    assert first.operator is second.operator is K.MINUS
    assert second.left is first.result


@pytest.mark.parametrize("source,operator,kind", [
    ("-2", K.MINUS, T.INT), ("-2.0", K.MINUS, T.FLOAT),
    ("NOT TRUE", K.NOT, T.BOOL),
])
def test_unary_operations_are_emitted_not_folded(source, operator, kind):
    analysis, lowerer, builder, _ = _start(source)
    result = lowerer.lower_value(analysis)
    instruction, = builder.snapshot()
    assert isinstance(instruction, Unary) and instruction.operator is operator
    assert instruction.result is result and result.type is kind


@pytest.mark.parametrize("source,operator", [
    ("1 < 2", K.LESS), ("1 > 2", K.GREATER),
    ("1 <= 2", K.LESS_EQUAL), ("1 >= 2", K.GREATER_EQUAL),
    ("1 == 2", K.EQUAL_EQUAL), ("1.0 != 2.0", K.BANG_EQUAL),
    ("'A' == 'B'", K.EQUAL_EQUAL), ('"a" != "b"', K.BANG_EQUAL),
    ("TRUE == FALSE", K.EQUAL_EQUAL),
])
def test_comparisons_preserve_operators_and_bool_result(source, operator):
    analysis, lowerer, builder, _ = _start(source)
    result = lowerer.lower_value(analysis)
    comparison, = builder.snapshot()
    assert isinstance(comparison, Compare) and comparison.operator is operator
    assert comparison.result is result and result.type is T.BOOL


def test_binary_conversions_follow_each_operand_evaluation():
    analysis, lowerer, builder, semantic = _start("a + b * 2.5", "INT a; INT b;")
    result = lowerer.lower_value(analysis)
    items = builder.snapshot()
    assert [type(item) for item in items] == [Load, Convert, Load, Convert, Binary, Binary]
    assert items[0].source.symbol is semantic.start.declarations[0][1]
    assert items[1].operand is items[0].result
    assert items[2].source.symbol is semantic.start.declarations[1][1]
    assert items[3].operand is items[2].result
    assert items[4].operator is K.STAR and items[4].left is items[3].result
    assert items[5].operator is K.PLUS and items[5].left is items[1].result
    assert items[5].right is items[4].result and result is items[5].result
    assert items[1].span == analysis.root.left.span
    assert items[3].span == analysis.root.right.left.span
    assert analysis.annotations.type_of(analysis.root.left) is T.INT


@pytest.mark.parametrize("source,converted_role", [
    ("1 + 2.5", "left"), ("2.5 + 1", "right"),
    ("1 < 2.5", "left"), ("2.5 >= 1", "right"),
    ("1 == 1.0", "left"), ("1.0 != 1", "right"),
])
def test_mixed_numeric_operations_use_exact_semantic_conversion_site(source, converted_role):
    analysis, lowerer, builder, _ = _start(source)
    site, = analysis.annotations.conversions_for(analysis.root)
    assert site.role == converted_role
    value = lowerer.lower_value(analysis)
    conversion, final = builder.snapshot()
    assert isinstance(conversion, Convert) and conversion.result.type is T.FLOAT
    assert conversion.operand.type is T.INT
    assert conversion.span == site.operand.span
    assert isinstance(final, (Binary, Compare)) and final.result is value
    assert getattr(final, converted_role) is conversion.result


def test_nested_conversion_sites_are_not_merged_by_equal_structure():
    analysis, lowerer, builder, _ = _start("(1 + 2.0) + (1 + 2.0)")
    root = analysis.root
    assert isinstance(root, BinaryExpr)
    assert root.left.operator is root.right.operator is K.PLUS
    assert root.left.left.value == root.right.left.value == 1
    assert root.left is not root.right
    assert analysis.annotations.conversions_for(root.left)[0].parent is root.left
    assert analysis.annotations.conversions_for(root.right)[0].parent is root.right
    lowerer.lower_value(analysis)
    items = builder.snapshot()
    assert [type(item) for item in items] == [Convert, Binary, Convert, Binary, Binary]
    assert items[0].result is items[1].left
    assert items[2].result is items[3].left
    assert items[0].result is not items[2].result


def test_equal_ast_records_with_distinct_identities_each_emit_a_conversion():
    parsed = Parser(Lexer("1 + 2.0").tokenize()).parse_expression_only()
    equal_but_distinct = replace(parsed)
    assert parsed == equal_but_distinct and parsed is not equal_but_distinct
    root = BinaryExpr(K.PLUS, parsed, equal_but_distinct, parsed.span)
    analysis = ExpressionAnalyzer(SemanticContext()).infer(root)
    owner = RoutineId.start()
    builder = IRBuilder(owner, 1)
    value = ExpressionLowerer(builder).lower_value(analysis)
    items = builder.snapshot()
    assert [type(item) for item in items] == [Convert, Binary, Convert, Binary, Binary]
    assert items[0].result is items[1].left
    assert items[2].result is items[3].left
    assert items[-1].result is value


def test_right_operand_conversion_follows_its_load_and_left_result():
    analysis, lowerer, builder, semantic = _start("2.5 + x", "INT x;")
    value = lowerer.lower_value(analysis)
    load, conversion, addition = builder.snapshot()
    assert load.source.symbol is semantic.start.declarations[0][1]
    assert conversion.operand is load.result
    assert addition.left == Constant(T.FLOAT, 2.5, "2.5")
    assert addition.right is conversion.result and addition.result is value


def test_negative_float_zero_remains_an_unexecuted_unary_operation():
    analysis, lowerer, builder, _ = _start("-0.0")
    result = lowerer.lower_value(analysis)
    operation, = builder.snapshot()
    assert isinstance(operation, Unary) and operation.operator is K.MINUS
    assert operation.operand == Constant(T.FLOAT, 0.0, "0.0")
    assert result.type is T.FLOAT


def test_runtime_deferred_traps_remain_ir_instructions():
    for source, operator in (("1 / 0", K.SLASH), ("1 % 0", K.PERCENT)):
        analysis, lowerer, builder, _ = _start(source)
        lowerer.lower_value(analysis)
        assert isinstance(builder.snapshot()[-1], Binary)
        assert builder.snapshot()[-1].operator is operator
    huge = "9" * 5000
    analysis, lowerer, builder, _ = _start(f"{huge} + 1.0")
    lowerer.lower_value(analysis)
    conversion, arithmetic = builder.snapshot()
    assert isinstance(conversion, Convert) and conversion.operand.value == 10**5000 - 1
    assert isinstance(arithmetic, Binary) and arithmetic.left is conversion.result
    large_finite = "9" * 308 + ".0"
    analysis, lowerer, builder, _ = _start(f"{large_finite} * {large_finite}")
    lowerer.lower_value(analysis)
    assert isinstance(builder.snapshot()[-1], Binary)


def test_approved_conversion_order_preserves_competing_runtime_trap_precedence():
    huge = "9" * 5000
    analysis, lowerer, builder, _ = _start(f"{huge} + ((1 / 0) * 1.0)")
    site, = analysis.annotations.conversions_for(analysis.root)
    assert site.parent is analysis.root and site.operand is analysis.root.left
    assert site.role == "left"
    lowerer.lower_value(analysis)
    first = builder.snapshot()
    assert [type(item) for item in first] == [Convert, Binary, Convert, Binary, Binary]
    assert first[0].operand.value == 10**5000 - 1
    assert first[1].operator is K.SLASH
    assert first[3].operator is K.STAR and first[4].operator is K.PLUS
    assert first[4].left is first[0].result

    analysis, lowerer, builder, _ = _start("((1 / 0) * 1.0) + 2")
    site, = analysis.annotations.conversions_for(analysis.root)
    assert site.parent is analysis.root and site.operand is analysis.root.right
    assert site.role == "right"
    lowerer.lower_value(analysis)
    second = builder.snapshot()
    assert [type(item) for item in second] == [Binary, Convert, Binary, Convert, Binary]
    assert second[0].operator is K.SLASH
    assert second[3].operand == Constant(T.INT, 2, "2")
    assert second[4].right is second[3].result


def test_ordinary_bool_values_avoid_unneeded_merge_temporaries():
    for source, expected in (("TRUE", Constant), ("b", Temporary),
                             ("1 < 2", Temporary), ("NOT TRUE", Temporary)):
        analysis, lowerer, builder, _ = _start(source, "BOOL b;")
        value = lowerer.lower_value(analysis)
        assert isinstance(value, expected) and value.type is T.BOOL
        assert not any(isinstance(item, Move) and isinstance(item.target, BoolMergeTemp)
                       for item in builder.snapshot())


@pytest.mark.parametrize("source,short_operator", [
    ("FALSE AND (1 / 0 > 0)", K.AND),
    ("TRUE OR (1 / 0 > 0)", K.OR),
])
def test_short_circuit_value_places_trap_on_only_the_rhs_path(source, short_operator):
    analysis, lowerer, builder, _ = _start(source)
    merge = lowerer.lower_value(analysis)
    items = builder.snapshot()
    assert isinstance(merge, BoolMergeTemp)
    assert [type(item) for item in items] == [
        BranchBool, Label, Binary, Compare, BranchBool, Label,
        Move, Jump, Label, Move, Label,
    ]
    first, rhs_label, division = items[:3]
    true_label, false_label = items[5].target, items[8].target
    if short_operator is K.AND:
        assert first.true_target is rhs_label.target and first.false_target is false_label
    else:
        assert first.true_target is true_label and first.false_target is rhs_label.target
    assert division.operator is K.SLASH
    assert items[4].true_target is true_label and items[4].false_target is false_label
    assert items[6].target is items[9].target is merge
    assert items[6].value == Constant(T.BOOL, True)
    assert items[7].target is items[10].target
    assert items[9].value == Constant(T.BOOL, False)
    assert builder.finish().instructions == items


def test_bool_condition_uses_caller_labels_without_materializing_value():
    analysis, lowerer, builder, _ = _start("a != 0 AND b / a > 2", "INT a; INT b;")
    on_true, on_false = builder.label(), builder.label()
    assert lowerer.lower_condition(analysis, on_true, on_false) is None
    items = builder.snapshot()
    assert [type(item) for item in items] == [
        Load, Compare, BranchBool, Label, Load, Load, Binary, Compare, BranchBool,
    ]
    first_branch = items[2]
    assert first_branch.true_target is items[3].target
    assert first_branch.false_target is on_false
    assert items[6].operator is K.SLASH
    assert items[8].true_target is on_true and items[8].false_target is on_false
    with pytest.raises(ValueError, match="undefined"):
        builder.finish()
    builder.define(on_true, analysis.root.span)
    builder.define(on_false, analysis.root.span)
    assert len(builder.finish().instructions) == len(items) + 2


@pytest.mark.parametrize("source,swapped", [
    ("NOT a", True), ("NOT NOT a", False),
])
def test_not_condition_swaps_destinations(source, swapped):
    analysis, lowerer, builder, _ = _start(source, "BOOL a;")
    true_label, false_label = builder.label(), builder.label()
    lowerer.lower_condition(analysis, true_label, false_label)
    load, branch = builder.snapshot()
    assert isinstance(load, Load) and isinstance(branch, BranchBool)
    assert branch.condition is load.result
    assert branch.true_target is (false_label if swapped else true_label)
    assert branch.false_target is (true_label if swapped else false_label)


@pytest.mark.parametrize("source,operator", [
    ("NOT (a AND b)", K.AND), ("NOT (a OR b)", K.OR),
])
def test_not_around_short_circuit_uses_branch_destinations(source, operator):
    analysis, lowerer, builder, _ = _start(source, "BOOL a; BOOL b;")
    true_label, false_label = builder.label(), builder.label()
    lowerer.lower_condition(analysis, true_label, false_label)
    items = builder.snapshot()
    branches = [item for item in items if isinstance(item, BranchBool)]
    assert len(branches) == 2
    assert not any(isinstance(item, Move) for item in items)
    internal = next(item.target for item in items if isinstance(item, Label))
    if operator is K.AND:
        assert branches[0].true_target is internal and branches[0].false_target is true_label
    else:
        assert branches[0].true_target is false_label and branches[0].false_target is internal
    assert branches[1].true_target is false_label
    assert branches[1].false_target is true_label


def test_nested_boolean_value_has_one_merge_and_defined_internal_labels():
    analysis, lowerer, builder, _ = _start("(a AND b) OR c", "BOOL a; BOOL b; BOOL c;")
    value = lowerer.lower_value(analysis)
    items = builder.snapshot()
    assert isinstance(value, BoolMergeTemp)
    assert not any(isinstance(item, Binary) for item in items)
    assert sum(isinstance(item, Move) and item.target is value for item in items) == 2
    true_assignment = next(i for i, item in enumerate(items)
                           if isinstance(item, Move) and item.value == Constant(T.BOOL, True))
    false_assignment = next(i for i, item in enumerate(items)
                            if isinstance(item, Move) and item.value == Constant(T.BOOL, False))
    assert isinstance(items[true_assignment + 1], Jump)
    assert true_assignment < false_assignment
    assert builder.finish().instructions == items


def test_not_around_and_value_uses_one_branch_based_merge():
    analysis, lowerer, builder, _ = _start("NOT (a AND b)", "BOOL a; BOOL b;")
    value = lowerer.lower_value(analysis)
    items = builder.snapshot()
    assert isinstance(value, BoolMergeTemp)
    assert sum(isinstance(item, Move) and item.target is value for item in items) == 2
    assert not any(isinstance(item, Unary) for item in items)
    assert builder.finish().instructions == items


def test_distinct_materialized_values_have_distinct_merge_temporary_ids():
    analysis, lowerer, builder, _ = _start("a AND b", "BOOL a; BOOL b;")
    first = lowerer.lower_value(analysis)
    before = builder.snapshot()
    second = lowerer.lower_value(analysis)
    assert isinstance(first, BoolMergeTemp) and isinstance(second, BoolMergeTemp)
    assert first.number != second.number and first.owner is second.owner
    assert builder.snapshot()[:len(before)] == before
    assert builder.finish()


def test_shadowed_variable_occurrences_keep_distinct_analyzed_symbols():
    source = "START { INT x; SHOW(x); { FLOAT x; SHOW(x); } }"
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    outer_show = program.main.statements[1]
    inner_show = program.main.statements[2].statements[1]
    owner = RoutineId.start()
    symbols = tuple(symbol for _, symbol in semantic.start.declarations)
    builder = IRBuilder(owner, semantic.start_scope.id,
                        local_symbols=tuple(VariableRef(owner, symbol) for symbol in symbols))
    lowerer = ExpressionLowerer(builder)
    outer = lowerer.lower_value(semantic.start.show_of(outer_show))
    inner = lowerer.lower_value(semantic.start.show_of(inner_show))
    first, second = builder.snapshot()
    assert isinstance(first, Load) and isinstance(second, Load)
    assert first.source.symbol is symbols[0] and second.source.symbol is symbols[1]
    assert first.source.symbol.name == second.source.symbol.name == "x"
    assert first.source.symbol.id != second.source.symbol.id
    assert outer.type is T.INT and inner.type is T.FLOAT


def test_independent_lowering_sessions_reset_ids_and_do_not_share_state():
    first_analysis, first_lowerer, first_builder, _ = _start("1 + 2")
    second_analysis, second_lowerer, second_builder, _ = _start("1 + 2")
    left = first_lowerer.lower_value(first_analysis)
    right = second_lowerer.lower_value(second_analysis)
    assert left.number == right.number == 1
    assert left.owner is not right.owner
    assert [repr(item) for item in first_builder.snapshot()] == [
        repr(item) for item in second_builder.snapshot()
    ]


def test_array_access_now_emits_a_guarded_load():
    analysis, lowerer, builder, semantic = _start("1 + arr[0]", "INT arr[2];")
    result = lowerer.lower_value(analysis)
    check, load, addition = builder.snapshot()
    assert isinstance(check, CheckBounds) and isinstance(load, LoadElement)
    assert check.array.symbol is semantic.start.declarations[0][1]
    assert load.checked is check.result and isinstance(addition, Binary)
    assert addition.right is load.result and addition.result is result
    assert not lowerer.failed


def test_deferred_root_call_is_not_a_semantic_error():
    source = "FUNC f() -> INT { RETURN 1; } START { SHOW(f()); }"
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    analysis = semantic.start.show_of(program.main.statements[0])
    builder = IRBuilder(RoutineId.start(), semantic.start_scope.id)
    with pytest.raises(DeferredExpressionError, match="function call"):
        ExpressionLowerer(builder).lower_value(analysis)
    assert builder.snapshot() == ()


@pytest.mark.parametrize("source,category", [
    ("FUNC f() -> INT { RETURN 1; } START { SHOW(1 + f()); }", "function call"),
    ("FUNC p() -> BOOL { RETURN TRUE; } START { SHOW(FALSE AND p()); }", "function call"),
    ("FUNC f() -> INT { RETURN 0; } START { INT arr[2]; SHOW(NOT (arr[f()] == 0)); }", "function call"),
])
def test_nested_deferred_categories_never_publish_partial_fragments(source, category):
    program = Parser(Lexer(source).tokenize()).parse()
    semantic = SemanticAnalyzer(program).analyze()
    analysis = semantic.start.show_of(program.main.statements[-1])
    owner = RoutineId.start()
    builder = IRBuilder(owner, semantic.start_scope.id)
    lowerer = ExpressionLowerer(builder)
    with pytest.raises(DeferredExpressionError, match=category):
        lowerer.lower_value(analysis)
    assert builder.snapshot() == () and lowerer.failed


def test_invalid_direct_arguments_and_non_bool_condition_are_controlled():
    analysis, lowerer, builder, _ = _start("1 + 2")
    with pytest.raises(LoweringInputError, match="BOOL"):
        lowerer.lower_condition(analysis, builder.label(), builder.label())
    assert builder.snapshot() == () and lowerer.failed

    _, lowerer, builder, _ = _start("TRUE")
    with pytest.raises(LoweringInputError, match="ExpressionAnalysis"):
        lowerer.lower_value(None)
    assert builder.snapshot() == () and lowerer.failed


def test_foreign_or_unallocated_condition_labels_are_rejected():
    analysis, lowerer, builder, _ = _start("TRUE")
    with pytest.raises(LoweringInputError, match="labels"):
        lowerer.lower_condition(analysis, LabelRef(RoutineId.start(), 1), builder.label())
    assert builder.snapshot() == () and lowerer.failed

    analysis, lowerer, builder, _ = _start("TRUE")
    unallocated = LabelRef(builder.owner, 1)
    with pytest.raises(LoweringConstructionError, match="construct"):
        lowerer.lower_condition(analysis, unallocated, builder.label())
    assert builder.snapshot() == () and lowerer.failed


def test_missing_binary_conversion_metadata_is_rejected_before_emission():
    analysis, lowerer, builder, _ = _start("1 + 2.0")
    root = analysis.root
    facts = ExpressionAnnotations()
    facts._type(root.left, T.INT)
    facts._type(root.right, T.FLOAT)
    facts._type(root, T.FLOAT)
    inconsistent = ExpressionAnalysis(root, T.FLOAT, facts)
    with pytest.raises(LoweringMetadataError, match="conversion"):
        lowerer.lower_value(inconsistent)
    assert builder.snapshot() == () and lowerer.failed


def test_unrelated_symbol_inventory_failure_discards_partial_construction():
    analysis, _, _, semantic = _start("x + y", "INT x; INT y;")
    owner = RoutineId.start()
    only_x = VariableRef(owner, semantic.start.declarations[0][1])
    builder = IRBuilder(owner, semantic.start_scope.id, local_symbols=(only_x,))
    lowerer = ExpressionLowerer(builder)
    before = builder.snapshot()
    with pytest.raises(LoweringConstructionError, match="construct"):
        lowerer.lower_value(analysis)
    assert before == ()
    assert len(builder.snapshot()) == 1
    assert isinstance(builder.snapshot()[0], Load)
    assert lowerer.failed
    with pytest.raises(LoweringInputError, match="discard"):
        lowerer.lower_value(analysis)


def test_closed_builder_is_rejected_even_for_pure_literal_lowering():
    analysis, lowerer, builder, _ = _start("TRUE")
    assert builder.finish()
    assert builder.is_complete
    with pytest.raises(LoweringInputError, match="completed"):
        lowerer.lower_value(analysis)
    assert lowerer.failed
    with pytest.raises(LoweringInputError, match="open"):
        ExpressionLowerer(builder)


def test_depth_and_work_limits_fail_before_emission_without_recursion_error():
    source = " + ".join("1" for _ in range(80))
    analysis, _, builder, _ = _start(source)
    lowerer = ExpressionLowerer(builder, max_depth=16)
    with pytest.raises(LoweringResourceError, match="resource limit"):
        lowerer.lower_value(analysis)
    assert builder.snapshot() == () and lowerer.failed

    analysis, _, builder, _ = _start("1 + 2 + 3 + 4")
    lowerer = ExpressionLowerer(builder, max_nodes=3)
    with pytest.raises(LoweringResourceError, match="resource limit"):
        lowerer.lower_value(analysis)
    assert builder.snapshot() == ()


def test_resource_settings_reject_bool_and_nonpositive_values():
    builder = IRBuilder(RoutineId.start(), 1)
    for options in ({"max_depth": True}, {"max_depth": 0}, {"max_nodes": 0}):
        with pytest.raises(LoweringInputError):
            ExpressionLowerer(builder, **options)


def test_condition_source_spans_and_internal_labels_use_originating_expression():
    analysis, lowerer, builder, _ = _start("FALSE AND (1 < 2)")
    on_true, on_false = builder.label(), builder.label()
    lowerer.lower_condition(analysis, on_true, on_false)
    items = builder.snapshot()
    assert items[0].span == analysis.root.left.span
    assert items[1].span == analysis.root.span  # synthetic RHS label
    assert items[-1].span == analysis.root.right.span
    assert all(item.span.start_line == 1 for item in items)
