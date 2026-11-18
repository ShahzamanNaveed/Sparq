"""Pure Sparq scalar compatibility and expression-operator type rules."""

from dataclasses import dataclass
from enum import Enum

from sparq.symbols import ScalarType
from sparq.token import TokenType


class Compatibility(Enum):
    EXACT = "EXACT"
    INT_TO_FLOAT = "INT_TO_FLOAT"
    INCOMPATIBLE = "INCOMPATIBLE"


def assignment_compatibility(destination: ScalarType, source: ScalarType) -> Compatibility:
    """Classify a scalar use; callers later choose the actual use context."""
    _require_scalar(destination)
    _require_scalar(source)
    if destination is source:
        return Compatibility.EXACT
    if destination is ScalarType.FLOAT and source is ScalarType.INT:
        return Compatibility.INT_TO_FLOAT
    return Compatibility.INCOMPATIBLE


@dataclass(frozen=True, slots=True)
class BinaryRule:
    result_type: ScalarType
    left_conversion: ScalarType | None = None
    right_conversion: ScalarType | None = None


_ARITHMETIC = frozenset({
    TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
})
_ORDERED = frozenset({
    TokenType.LESS, TokenType.GREATER,
    TokenType.LESS_EQUAL, TokenType.GREATER_EQUAL,
})
_EQUALITY = frozenset({TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL})
_LOGICAL = frozenset({TokenType.AND, TokenType.OR})
_BINARY = _ARITHMETIC | _ORDERED | _EQUALITY | _LOGICAL | {TokenType.PERCENT}
_NUMERIC = frozenset({ScalarType.INT, ScalarType.FLOAT})


def _require_scalar(value: ScalarType) -> None:
    if not isinstance(value, ScalarType):
        raise ValueError("a ScalarType is required")


def unary_result(operator: TokenType, operand: ScalarType) -> ScalarType | None:
    """Return the result type, or None for an invalid operand combination."""
    _require_scalar(operand)
    if operator is TokenType.MINUS:
        return operand if operand in _NUMERIC else None
    if operator is TokenType.NOT:
        return ScalarType.BOOL if operand is ScalarType.BOOL else None
    raise ValueError("unsupported unary operator")


def binary_rule(
    operator: TokenType, left: ScalarType, right: ScalarType,
) -> BinaryRule | None:
    """Return the result and operand promotions, or None for invalid types."""
    _require_scalar(left)
    _require_scalar(right)
    if operator not in _BINARY:
        raise ValueError("unsupported binary operator")
    if operator in _ARITHMETIC | _ORDERED:
        if left not in _NUMERIC or right not in _NUMERIC:
            return None
        result = ScalarType.FLOAT if ScalarType.FLOAT in (left, right) else ScalarType.INT
        conversions = (
            ScalarType.FLOAT if result is ScalarType.FLOAT and left is ScalarType.INT else None,
            ScalarType.FLOAT if result is ScalarType.FLOAT and right is ScalarType.INT else None,
        )
        return BinaryRule(
            ScalarType.BOOL if operator in _ORDERED else result, *conversions,
        )
    if operator is TokenType.PERCENT:
        return BinaryRule(ScalarType.INT) if left is right is ScalarType.INT else None
    if operator in _EQUALITY:
        if left is right:
            return BinaryRule(ScalarType.BOOL)
        if left in _NUMERIC and right in _NUMERIC:
            return BinaryRule(
                ScalarType.BOOL,
                ScalarType.FLOAT if left is ScalarType.INT else None,
                ScalarType.FLOAT if right is ScalarType.INT else None,
            )
        return None
    if left is right is ScalarType.BOOL:
        return BinaryRule(ScalarType.BOOL)
    return None
