"""Frozen specification type matrices, independent of expression traversal."""

import pytest

from sparq.symbols import ScalarType as T, VoidType
from sparq.token import TokenType as Op
from sparq.type_rules import (
    BinaryRule, Compatibility as C, assignment_compatibility,
    binary_rule, unary_result,
)


TYPES = (T.INT, T.FLOAT, T.CHAR, T.STRING, T.BOOL)
NUMERIC = (T.INT, T.FLOAT)


@pytest.mark.parametrize("destination", TYPES)
@pytest.mark.parametrize("source", TYPES)
def test_all_25_ordered_scalar_compatibilities(destination, source):
    expected = {
        T.INT: (C.EXACT, C.INCOMPATIBLE, C.INCOMPATIBLE, C.INCOMPATIBLE, C.INCOMPATIBLE),
        T.FLOAT: (C.INT_TO_FLOAT, C.EXACT, C.INCOMPATIBLE, C.INCOMPATIBLE, C.INCOMPATIBLE),
        T.CHAR: (C.INCOMPATIBLE, C.INCOMPATIBLE, C.EXACT, C.INCOMPATIBLE, C.INCOMPATIBLE),
        T.STRING: (C.INCOMPATIBLE, C.INCOMPATIBLE, C.INCOMPATIBLE, C.EXACT, C.INCOMPATIBLE),
        T.BOOL: (C.INCOMPATIBLE, C.INCOMPATIBLE, C.INCOMPATIBLE, C.INCOMPATIBLE, C.EXACT),
    }
    assert assignment_compatibility(destination, source) is expected[destination][TYPES.index(source)]


@pytest.mark.parametrize("invalid", [VoidType.VOID, Op.INT, "INT", True, 1])
def test_compatibility_rejects_non_scalar_representations(invalid):
    with pytest.raises(ValueError, match="ScalarType"):
        assignment_compatibility(T.FLOAT, invalid)
    with pytest.raises(ValueError, match="ScalarType"):
        assignment_compatibility(invalid, T.INT)


def expected_numeric_result(left, right, *, comparison=False):
    if left not in NUMERIC or right not in NUMERIC:
        return None
    mixed = left is not right
    return BinaryRule(
        T.BOOL if comparison else (T.FLOAT if T.FLOAT in (left, right) else T.INT),
        T.FLOAT if mixed and left is T.INT else None,
        T.FLOAT if mixed and right is T.INT else None,
    )


@pytest.mark.parametrize("operator", [Op.PLUS, Op.MINUS, Op.STAR, Op.SLASH])
@pytest.mark.parametrize("left", TYPES)
@pytest.mark.parametrize("right", TYPES)
def test_arithmetic_matrix(operator, left, right):
    assert binary_rule(operator, left, right) == expected_numeric_result(left, right)


@pytest.mark.parametrize("left", TYPES)
@pytest.mark.parametrize("right", TYPES)
def test_modulo_matrix(left, right):
    expected = BinaryRule(T.INT) if left is right is T.INT else None
    assert binary_rule(Op.PERCENT, left, right) == expected


@pytest.mark.parametrize("operator", [Op.LESS, Op.GREATER, Op.LESS_EQUAL, Op.GREATER_EQUAL])
@pytest.mark.parametrize("left", TYPES)
@pytest.mark.parametrize("right", TYPES)
def test_ordered_comparison_matrix(operator, left, right):
    assert binary_rule(operator, left, right) == expected_numeric_result(
        left, right, comparison=True,
    )


@pytest.mark.parametrize("operator", [Op.EQUAL_EQUAL, Op.BANG_EQUAL])
@pytest.mark.parametrize("left", TYPES)
@pytest.mark.parametrize("right", TYPES)
def test_equality_matrix(operator, left, right):
    expected = (
        BinaryRule(T.BOOL) if left is right
        else expected_numeric_result(left, right, comparison=True)
    )
    assert binary_rule(operator, left, right) == expected


@pytest.mark.parametrize("operator", [Op.AND, Op.OR])
@pytest.mark.parametrize("left", TYPES)
@pytest.mark.parametrize("right", TYPES)
def test_logical_matrix(operator, left, right):
    expected = BinaryRule(T.BOOL) if left is right is T.BOOL else None
    assert binary_rule(operator, left, right) == expected


@pytest.mark.parametrize("operand", TYPES)
def test_unary_rules_for_every_scalar_type(operand):
    assert unary_result(Op.MINUS, operand) is (operand if operand in NUMERIC else None)
    assert unary_result(Op.NOT, operand) is (T.BOOL if operand is T.BOOL else None)


def test_type_rules_reject_unsupported_operators_and_type_representations():
    with pytest.raises(ValueError, match="unary"):
        unary_result(Op.PLUS, T.INT)
    with pytest.raises(ValueError, match="binary"):
        binary_rule(Op.EQUAL, T.INT, T.INT)
    with pytest.raises(ValueError, match="ScalarType"):
        unary_result(Op.MINUS, VoidType.VOID)
    with pytest.raises(ValueError, match="ScalarType"):
        binary_rule(Op.PLUS, T.INT, VoidType.VOID)
