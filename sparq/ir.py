"""Typed, structural Sparq IR records. No source lowering or execution lives here."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from enum import Enum
from typing import TypeAlias

from sparq.ast_nodes import Program, SourceSpan
from sparq.program_semantic import AnalysisResult
from sparq.symbols import FunctionSymbol, ScalarType, SymbolKind, VariableSymbol, VoidType
from sparq.token import TokenType


def _positive(value: object, label: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def _tuple(value: object, label: str) -> tuple:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{label} must be a tuple or list")
    return tuple(value)


class RoutineKind(Enum):
    START = "START"
    FUNCTION = "FUNCTION"


@dataclass(frozen=True, slots=True, eq=False)
class RoutineId:
    """Identity belongs to one IR construction session, even when IDs repeat."""

    kind: RoutineKind
    function: FunctionSymbol | None = None

    def __post_init__(self) -> None:
        if self.kind is RoutineKind.START:
            if self.function is not None:
                raise ValueError("START cannot own a function signature")
        elif self.kind is RoutineKind.FUNCTION:
            if not isinstance(self.function, FunctionSymbol):
                raise TypeError("function routine requires a FunctionSymbol")
            _positive(self.function.id, "function ID")
        else:
            raise ValueError("invalid routine kind")

    @classmethod
    def start(cls) -> RoutineId:
        return cls(RoutineKind.START)

    @classmethod
    def for_function(cls, function: FunctionSymbol) -> RoutineId:
        return cls(RoutineKind.FUNCTION, function)

    def __repr__(self) -> str:
        return "RoutineId(START)" if self.kind is RoutineKind.START else (
            f"RoutineId(FUNCTION#{self.function.id}:{self.function.name})"
        )


def _owner(value: object) -> None:
    if not isinstance(value, RoutineId):
        raise TypeError("routine owner must be a RoutineId")


def _symbol(value: object, kind: SymbolKind) -> None:
    if not isinstance(value, VariableSymbol):
        raise TypeError("resolved operand requires a VariableSymbol")
    if value.kind is not kind:
        raise ValueError(f"resolved operand requires {kind.name} symbol")
    _positive(value.id, "symbol ID")
    _positive(value.scope_id, "scope ID")
    if not isinstance(value.name, str) or not value.name:
        raise ValueError("symbol name is required")
    if not isinstance(value.type, ScalarType):
        raise ValueError("symbol type must be scalar")


def _short_value(kind: ScalarType, value: object) -> str:
    if kind is ScalarType.INT:
        if value.bit_length() > 4096:
            high = abs(value) >> max(0, value.bit_length() - 64)
            return f"<{'-' if value < 0 else '+'}INT bits={value.bit_length()} high=0x{high:x}>"
        return str(value)
    if isinstance(value, str) and len(value) > 80:
        return repr(value[:77] + "...")
    return repr(value)


@dataclass(frozen=True, slots=True)
class Constant:
    type: ScalarType
    value: object
    lexeme: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.type, ScalarType):
            raise TypeError("constant type must be ScalarType")
        if self.type is ScalarType.INT:
            valid = type(self.value) is int
        elif self.type is ScalarType.FLOAT:
            valid = type(self.value) is float and math.isfinite(self.value)
        elif self.type is ScalarType.BOOL:
            valid = type(self.value) is bool
        elif self.type is ScalarType.CHAR:
            valid = (type(self.value) is str and len(self.value) == 1
                     and not 0xD800 <= ord(self.value) <= 0xDFFF)
        else:
            valid = (type(self.value) is str
                     and all(not 0xD800 <= ord(ch) <= 0xDFFF for ch in self.value))
        if not valid:
            raise ValueError("constant value does not match its scalar type")
        if self.lexeme is not None and not isinstance(self.lexeme, str):
            raise TypeError("constant lexeme must be a string or None")

    def __repr__(self) -> str:
        return f"Constant({self.type.name}, {_short_value(self.type, self.value)})"


@dataclass(frozen=True, slots=True)
class VariableRef:
    owner: RoutineId
    symbol: VariableSymbol

    def __post_init__(self) -> None:
        _owner(self.owner)
        _symbol(self.symbol, SymbolKind.VARIABLE)

    @property
    def type(self) -> ScalarType:
        return self.symbol.type

    def __repr__(self) -> str:
        return f"v{self.symbol.id}({self.symbol.name}):{self.type.name}@{self.owner!r}"


@dataclass(frozen=True, slots=True)
class ParameterRef:
    owner: RoutineId
    symbol: VariableSymbol

    def __post_init__(self) -> None:
        _owner(self.owner)
        if self.owner.kind is not RoutineKind.FUNCTION:
            raise ValueError("a parameter must belong to a function routine")
        _symbol(self.symbol, SymbolKind.PARAMETER)

    @property
    def type(self) -> ScalarType:
        return self.symbol.type

    def __repr__(self) -> str:
        return f"p{self.symbol.id}({self.symbol.name}):{self.type.name}@{self.owner!r}"


@dataclass(frozen=True, slots=True)
class ArrayRef:
    owner: RoutineId
    symbol: VariableSymbol

    def __post_init__(self) -> None:
        _owner(self.owner)
        _symbol(self.symbol, SymbolKind.ARRAY)
        _positive(self.symbol.array_length, "array length")

    @property
    def element_type(self) -> ScalarType:
        return self.symbol.type

    @property
    def length(self) -> int:
        return self.symbol.array_length

    def __repr__(self) -> str:
        length = _short_value(ScalarType.INT, self.length)
        return f"a{self.symbol.id}({self.symbol.name}):{self.element_type.name}[{length}]@{self.owner!r}"


@dataclass(frozen=True, slots=True)
class Temporary:
    owner: RoutineId
    number: int
    type: ScalarType

    def __post_init__(self) -> None:
        _owner(self.owner)
        _positive(self.number, "temporary number")
        if not isinstance(self.type, ScalarType):
            raise TypeError("temporary type must be scalar")

    def __repr__(self) -> str:
        return f"%t{self.number}:{self.type.name}@{self.owner!r}"


@dataclass(frozen=True, slots=True)
class BoolMergeTemp:
    owner: RoutineId
    number: int

    def __post_init__(self) -> None:
        _owner(self.owner)
        _positive(self.number, "merge temporary number")

    @property
    def type(self) -> ScalarType:
        return ScalarType.BOOL

    def __repr__(self) -> str:
        return f"%m{self.number}:BOOL@{self.owner!r}"


IndexValue: TypeAlias = Constant | Temporary


@dataclass(frozen=True, slots=True)
class CheckedElement:
    owner: RoutineId
    number: int
    array: ArrayRef
    index: IndexValue

    def __post_init__(self) -> None:
        _owner(self.owner)
        _positive(self.number, "guard number")
        if not isinstance(self.array, ArrayRef) or self.array.owner is not self.owner:
            raise ValueError("guard array must belong to its routine")
        if not isinstance(self.index, (Constant, Temporary)) or self.index.type is not ScalarType.INT:
            raise TypeError("guard index must be a captured INT constant or temporary")
        if isinstance(self.index, Temporary) and self.index.owner is not self.owner:
            raise ValueError("guard index temporary belongs to another routine")

    def __repr__(self) -> str:
        return f"%g{self.number}({self.array.symbol.id}, {self.index!r})@{self.owner!r}"


@dataclass(frozen=True, slots=True)
class LabelRef:
    owner: RoutineId
    number: int

    def __post_init__(self) -> None:
        _owner(self.owner)
        _positive(self.number, "label number")

    def __repr__(self) -> str:
        return f"L{self.number}@{self.owner!r}"


@dataclass(frozen=True, slots=True)
class FunctionRef:
    symbol: FunctionSymbol

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, FunctionSymbol):
            raise TypeError("function reference requires a FunctionSymbol")
        _positive(self.symbol.id, "function ID")
        if not isinstance(self.symbol.name, str) or not self.symbol.name:
            raise ValueError("function name is required")

    @property
    def parameter_types(self) -> tuple[ScalarType, ...]:
        return self.symbol.parameter_types

    @property
    def return_type(self) -> ScalarType | VoidType:
        return self.symbol.return_type

    def __repr__(self) -> str:
        return f"f{self.symbol.id}({self.symbol.name})"


Value: TypeAlias = Constant | VariableRef | ParameterRef | Temporary | BoolMergeTemp
Storage: TypeAlias = VariableRef | ParameterRef


def _value(
    value: object, expected: ScalarType | None = None, owner: RoutineId | None = None,
) -> ScalarType:
    if not isinstance(value, (Constant, VariableRef, ParameterRef, Temporary, BoolMergeTemp)):
        raise TypeError("scalar value operand required")
    if expected is not None and value.type is not expected:
        raise ValueError("scalar operand type does not match instruction")
    if owner is not None and getattr(value, "owner", owner) is not owner:
        raise ValueError("scalar operand belongs to another routine")
    return value.type


def _instruction(owner: RoutineId, span: SourceSpan) -> None:
    _owner(owner)
    if not isinstance(span, SourceSpan):
        raise TypeError("instruction source span is required")


@dataclass(frozen=True, slots=True)
class InitScalar:
    owner: RoutineId
    span: SourceSpan
    target: VariableRef
    value: Value

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.target, VariableRef):
            raise TypeError("scalar initialization requires a variable target")
        _value(self.value, self.target.type, self.owner)
        if self.target.owner is not self.owner:
            raise ValueError("target belongs to another routine")


@dataclass(frozen=True, slots=True)
class Move:
    owner: RoutineId
    span: SourceSpan
    target: Storage | Temporary | BoolMergeTemp
    value: Value

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.target, (VariableRef, ParameterRef, Temporary, BoolMergeTemp)):
            raise TypeError("move target must be scalar storage or temporary")
        _value(self.value, self.target.type, self.owner)
        if self.target.owner is not self.owner:
            raise ValueError("target belongs to another routine")
        if isinstance(self.target, BoolMergeTemp) and not (
            isinstance(self.value, Constant) and self.value.type is ScalarType.BOOL
        ):
            raise ValueError("BOOL merge assignment needs a BOOL literal")


@dataclass(frozen=True, slots=True)
class Load:
    owner: RoutineId
    span: SourceSpan
    source: Storage
    result: Temporary

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.source, (VariableRef, ParameterRef)) or not isinstance(self.result, Temporary):
            raise TypeError("load needs scalar storage and an ordinary temporary")
        if self.source.owner is not self.owner or self.result.owner is not self.owner:
            raise ValueError("load operand belongs to another routine")
        if self.source.type is not self.result.type:
            raise ValueError("load result type must match storage")


_ARITHMETIC = frozenset({
    TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH, TokenType.PERCENT,
})
_ORDERED = frozenset({
    TokenType.LESS, TokenType.GREATER, TokenType.LESS_EQUAL, TokenType.GREATER_EQUAL,
})
_EQUALITY = frozenset({TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL})
_NUMERIC = frozenset({ScalarType.INT, ScalarType.FLOAT})
_DEFAULTS = {
    ScalarType.INT: 0,
    ScalarType.FLOAT: 0.0,
    ScalarType.CHAR: "\0",
    ScalarType.STRING: "",
    ScalarType.BOOL: False,
}


@dataclass(frozen=True, slots=True)
class Unary:
    owner: RoutineId
    span: SourceSpan
    operator: TokenType
    operand: Value
    result: Temporary

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.result, Temporary) or self.result.owner is not self.owner:
            raise ValueError("unary result needs an owned ordinary temporary")
        operand_type = _value(self.operand, owner=self.owner)
        if self.operator is TokenType.MINUS:
            valid = operand_type in _NUMERIC and self.result.type is operand_type
        elif self.operator is TokenType.NOT:
            valid = operand_type is self.result.type is ScalarType.BOOL
        else:
            valid = False
        if not valid:
            raise ValueError("unary operation has incompatible normalized types")


@dataclass(frozen=True, slots=True)
class Binary:
    owner: RoutineId
    span: SourceSpan
    operator: TokenType
    left: Value
    right: Value
    result: Temporary

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.result, Temporary) or self.result.owner is not self.owner:
            raise ValueError("binary result needs an owned ordinary temporary")
        left = _value(self.left, owner=self.owner)
        right = _value(self.right, owner=self.owner)
        if (self.operator not in _ARITHMETIC or left not in _NUMERIC
                or left is not right or self.result.type is not left
                or self.operator is TokenType.PERCENT and left is not ScalarType.INT):
            raise ValueError("binary operation has incompatible normalized types")


@dataclass(frozen=True, slots=True)
class Compare:
    owner: RoutineId
    span: SourceSpan
    operator: TokenType
    left: Value
    right: Value
    result: Temporary

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if (not isinstance(self.result, Temporary) or self.result.owner is not self.owner
                or self.result.type is not ScalarType.BOOL):
            raise ValueError("comparison result needs an owned BOOL temporary")
        left = _value(self.left, owner=self.owner)
        right = _value(self.right, owner=self.owner)
        if (left is not right or
                (self.operator in _ORDERED and left not in _NUMERIC) or
                self.operator not in _ORDERED | _EQUALITY):
            raise ValueError("comparison has incompatible normalized types")


@dataclass(frozen=True, slots=True)
class Convert:
    owner: RoutineId
    span: SourceSpan
    operand: Value
    result: Temporary

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        _value(self.operand, ScalarType.INT, self.owner)
        if (not isinstance(self.result, Temporary) or self.result.owner is not self.owner
                or self.result.type is not ScalarType.FLOAT):
            raise ValueError("conversion must be INT-to-FLOAT into a FLOAT temporary")


@dataclass(frozen=True, slots=True)
class InitArray:
    owner: RoutineId
    span: SourceSpan
    target: ArrayRef
    length: int
    default: Constant

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.target, ArrayRef) or self.target.owner is not self.owner:
            raise ValueError("array initialization needs an owned array")
        if type(self.length) is not int or self.length != self.target.length:
            raise ValueError("array initialization length must match symbol")
        if not isinstance(self.default, Constant):
            raise TypeError("array default must be a typed constant")
        _value(self.default, self.target.element_type)
        expected = _DEFAULTS[self.target.element_type]
        if (self.default.value != expected
                or self.target.element_type is ScalarType.FLOAT
                and math.copysign(1.0, self.default.value) < 0):
            raise ValueError("array default must be the frozen type default")

    def __repr__(self) -> str:
        return f"InitArray({self.target!r}, length={_short_value(ScalarType.INT, self.length)})"


@dataclass(frozen=True, slots=True)
class InitElement:
    owner: RoutineId
    span: SourceSpan
    array: ArrayRef
    index: int
    value: Value

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.array, ArrayRef) or self.array.owner is not self.owner:
            raise ValueError("element initializer needs an owned array")
        if type(self.index) is not int or not 0 <= self.index < self.array.length:
            raise ValueError("initializer position must be within array length")
        _value(self.value, self.array.element_type, self.owner)

    def __repr__(self) -> str:
        return (
            f"InitElement({self.array!r}, index={_short_value(ScalarType.INT, self.index)}, "
            f"value={self.value!r})"
        )


@dataclass(frozen=True, slots=True)
class CheckBounds:
    owner: RoutineId
    span: SourceSpan
    array: ArrayRef
    index: IndexValue
    result: CheckedElement

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.array, ArrayRef) or self.array.owner is not self.owner:
            raise ValueError("bounds check needs an owned array")
        if not isinstance(self.index, (Constant, Temporary)):
            raise TypeError("bounds index must be a captured INT constant or temporary")
        _value(self.index, ScalarType.INT, self.owner)
        if (not isinstance(self.result, CheckedElement) or self.result.owner is not self.owner
                or self.result.array is not self.array or self.result.index is not self.index):
            raise ValueError("bounds guard must retain the exact array and index")


@dataclass(frozen=True, slots=True)
class LoadElement:
    owner: RoutineId
    span: SourceSpan
    checked: CheckedElement
    result: Temporary

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if (not isinstance(self.checked, CheckedElement) or self.checked.owner is not self.owner
                or not isinstance(self.result, Temporary) or self.result.owner is not self.owner
                or self.result.type is not self.checked.array.element_type):
            raise ValueError("element load needs matching guard and result type")


@dataclass(frozen=True, slots=True)
class StoreElement:
    owner: RoutineId
    span: SourceSpan
    checked: CheckedElement
    value: Value

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.checked, CheckedElement) or self.checked.owner is not self.owner:
            raise ValueError("element store needs an owned guard")
        _value(self.value, self.checked.array.element_type, self.owner)


@dataclass(frozen=True, slots=True)
class Label:
    owner: RoutineId
    span: SourceSpan
    target: LabelRef

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.target, LabelRef) or self.target.owner is not self.owner:
            raise ValueError("label definition belongs to another routine")


@dataclass(frozen=True, slots=True)
class Jump:
    owner: RoutineId
    span: SourceSpan
    target: LabelRef

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.target, LabelRef) or self.target.owner is not self.owner:
            raise ValueError("jump target belongs to another routine")


@dataclass(frozen=True, slots=True)
class BranchBool:
    owner: RoutineId
    span: SourceSpan
    condition: Value
    true_target: LabelRef
    false_target: LabelRef

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        _value(self.condition, ScalarType.BOOL, self.owner)
        if (not isinstance(self.true_target, LabelRef)
                or not isinstance(self.false_target, LabelRef)
                or self.true_target.owner is not self.owner
                or self.false_target.owner is not self.owner):
            raise ValueError("branch targets must belong to this routine")


@dataclass(frozen=True, slots=True)
class Call:
    owner: RoutineId
    span: SourceSpan
    function: FunctionRef
    arguments: tuple[Value, ...]
    result: Temporary | None = None
    discard_result: bool = False

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.function, FunctionRef):
            raise TypeError("CALL needs a resolved function reference")
        object.__setattr__(self, "arguments", _tuple(self.arguments, "CALL arguments"))
        if len(self.arguments) != len(self.function.parameter_types):
            raise ValueError("CALL argument count does not match signature")
        for value, expected in zip(self.arguments, self.function.parameter_types):
            _value(value, expected, self.owner)
        if type(self.discard_result) is not bool:
            raise TypeError("discard_result must be bool")
        if self.function.return_type is VoidType.VOID:
            if self.result is not None or self.discard_result:
                raise ValueError("VOID CALL has no result to capture or discard")
        elif self.discard_result:
            if self.result is not None:
                raise ValueError("discarded CALL must not define a result")
        elif (not isinstance(self.result, Temporary) or self.result.owner is not self.owner
              or self.result.type is not self.function.return_type):
            raise ValueError("value CALL needs an owned temporary of return type")


@dataclass(frozen=True, slots=True)
class Return:
    owner: RoutineId
    span: SourceSpan
    value: Value | None = None

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if self.owner.kind is not RoutineKind.FUNCTION:
            raise ValueError("RETURN is only valid in a function routine")
        required = self.owner.function.return_type
        if required is VoidType.VOID:
            if self.value is not None:
                raise ValueError("VOID RETURN cannot carry a value")
        elif self.value is None:
            raise ValueError("non-VOID RETURN needs a value")
        else:
            _value(self.value, required, self.owner)


@dataclass(frozen=True, slots=True)
class ReadScalar:
    owner: RoutineId
    span: SourceSpan
    target: Storage

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if (not isinstance(self.target, (VariableRef, ParameterRef))
                or self.target.owner is not self.owner):
            raise ValueError("READ needs owned scalar storage")


@dataclass(frozen=True, slots=True)
class ReadElement:
    owner: RoutineId
    span: SourceSpan
    checked: CheckedElement

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if not isinstance(self.checked, CheckedElement) or self.checked.owner is not self.owner:
            raise ValueError("indexed READ needs an owned guard")


@dataclass(frozen=True, slots=True)
class Show:
    owner: RoutineId
    span: SourceSpan
    value: Value

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        _value(self.value, owner=self.owner)


@dataclass(frozen=True, slots=True)
class HaltStart:
    owner: RoutineId
    span: SourceSpan

    def __post_init__(self) -> None:
        _instruction(self.owner, self.span)
        if self.owner.kind is not RoutineKind.START:
            raise ValueError("HALT_START belongs only to START")


Instruction: TypeAlias = (
    InitScalar | Move | Load | Unary | Binary | Compare | Convert
    | InitArray | InitElement | CheckBounds | LoadElement | StoreElement
    | Label | Jump | BranchBool | Call | Return | ReadScalar
    | ReadElement | Show | HaltStart
)
_INSTRUCTION_TYPES = (
    InitScalar, Move, Load, Unary, Binary, Compare, Convert,
    InitArray, InitElement, CheckBounds, LoadElement, StoreElement,
    Label, Jump, BranchBool, Call, Return, ReadScalar,
    ReadElement, Show, HaltStart,
)
_OPERAND_TYPES = (
    Constant, VariableRef, ParameterRef, ArrayRef, Temporary,
    BoolMergeTemp, CheckedElement, LabelRef, FunctionRef,
)


def instruction_operands(instruction: Instruction) -> tuple[object, ...]:
    """Expose nested operand records for structural owner checks."""
    found: list[object] = []
    for field in fields(instruction):
        value = getattr(instruction, field.name)
        if isinstance(value, _OPERAND_TYPES):
            found.append(value)
        elif isinstance(value, tuple):
            found.extend(item for item in value if isinstance(item, _OPERAND_TYPES))
    return tuple(found)


class Effect(Enum):
    READ_STORAGE = "READ_STORAGE"
    WRITE_STORAGE = "WRITE_STORAGE"
    MAY_TRAP = "MAY_TRAP"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    CALL = "CALL"
    CONTROL = "CONTROL"


def effects(instruction: Instruction) -> frozenset[Effect]:
    """Conservative intrinsic effects; no optimizer is implemented here."""
    if not isinstance(instruction, _INSTRUCTION_TYPES):
        raise TypeError("IR instruction required")
    result: set[Effect] = set()
    if isinstance(instruction, Load):
        result.add(Effect.READ_STORAGE)
    elif isinstance(instruction, (CheckBounds, LoadElement)):
        result.add(Effect.READ_STORAGE)
    elif isinstance(instruction, (Unary, Convert, BranchBool, Return, Show, InitScalar, Move, InitElement, StoreElement)):
        value = getattr(instruction, "value", getattr(instruction, "operand", getattr(instruction, "condition", None)))
        if isinstance(value, (VariableRef, ParameterRef)):
            result.add(Effect.READ_STORAGE)
    elif isinstance(instruction, (Binary, Compare)):
        if isinstance(instruction.left, (VariableRef, ParameterRef)) or isinstance(instruction.right, (VariableRef, ParameterRef)):
            result.add(Effect.READ_STORAGE)
    elif isinstance(instruction, Call):
        if any(isinstance(item, (VariableRef, ParameterRef)) for item in instruction.arguments):
            result.add(Effect.READ_STORAGE)
    if isinstance(instruction, (InitScalar, Move, InitArray, InitElement, StoreElement, ReadScalar, ReadElement)):
        result.add(Effect.WRITE_STORAGE)
    if isinstance(instruction, (Binary, CheckBounds, Convert, ReadScalar, ReadElement, Call, InitArray)):
        if (not isinstance(instruction, Binary)
                or instruction.operator in (TokenType.SLASH, TokenType.PERCENT)
                or instruction.result.type is ScalarType.FLOAT):
            result.add(Effect.MAY_TRAP)
    if isinstance(instruction, (ReadScalar, ReadElement)):
        result.add(Effect.INPUT)
    if isinstance(instruction, Show):
        result.add(Effect.OUTPUT)
    if isinstance(instruction, Call):
        result.update((Effect.CALL, Effect.INPUT, Effect.OUTPUT))
    if isinstance(instruction, (Jump, BranchBool, Return, HaltStart)):
        result.add(Effect.CONTROL)
    return frozenset(result)


def _structural_identities(owner: RoutineId, instructions: tuple[Instruction, ...]) -> None:
    defined: set[LabelRef] = set()
    referenced: set[LabelRef] = set()
    temporary_metadata: dict[int, tuple[type, ScalarType]] = {}
    guard_metadata: dict[int, CheckedElement] = {}
    ordinary_defs: set[int] = set()
    guard_defs: set[int] = set()

    def register_temporary(value: Temporary | BoolMergeTemp) -> None:
        metadata = (type(value), value.type)
        previous = temporary_metadata.setdefault(value.number, metadata)
        if previous != metadata:
            raise ValueError("temporary identity has conflicting category or type")

    def register_guard(value: CheckedElement) -> None:
        previous = guard_metadata.setdefault(value.number, value)
        if previous.array.symbol is not value.array.symbol:
            raise ValueError("guard identity has conflicting array metadata")
        previous_index, index = previous.index, value.index
        if type(previous_index) is not type(index):
            raise ValueError("guard identity has conflicting captured index")
        if isinstance(index, Temporary):
            register_temporary(index)
            if (previous_index.number != index.number
                    or previous_index.type is not index.type):
                raise ValueError("guard identity has conflicting captured index")
        elif (previous_index.type is not index.type
              or previous_index.value != index.value):
            raise ValueError("guard identity has conflicting captured index")

    for instruction in instructions:
        if not isinstance(instruction, _INSTRUCTION_TYPES) or instruction.owner is not owner:
            raise ValueError("routine contains a foreign or invalid instruction")
        for operand in instruction_operands(instruction):
            if getattr(operand, "owner", owner) is not owner:
                raise ValueError("routine contains a foreign operand")
            if isinstance(operand, (Temporary, BoolMergeTemp)):
                register_temporary(operand)
            elif isinstance(operand, CheckedElement):
                register_guard(operand)
                if isinstance(operand.index, Temporary):
                    register_temporary(operand.index)
        target = instruction.target if isinstance(instruction, Move) else getattr(instruction, "result", None)
        if isinstance(target, Temporary):
            if target.number in ordinary_defs:
                raise ValueError("ordinary temporary defined twice")
            ordinary_defs.add(target.number)
        if isinstance(instruction, CheckBounds):
            if instruction.result.number in guard_defs:
                raise ValueError("guard defined twice")
            guard_defs.add(instruction.result.number)
        if isinstance(instruction, Label):
            if instruction.target in defined:
                raise ValueError("label defined twice")
            defined.add(instruction.target)
        elif isinstance(instruction, Jump):
            referenced.add(instruction.target)
        elif isinstance(instruction, BranchBool):
            referenced.update((instruction.true_target, instruction.false_target))
    if not referenced <= defined:
        raise ValueError("routine has undefined branch label")


@dataclass(frozen=True, slots=True, eq=False)
class IRRoutine:
    """Structurally checked fragment, not a fully verified lowered routine."""

    owner: RoutineId
    root_scope_id: int
    parameters: tuple[ParameterRef, ...]
    local_symbols: tuple[VariableRef | ParameterRef | ArrayRef, ...]
    instructions: tuple[Instruction, ...]

    def __post_init__(self) -> None:
        _owner(self.owner)
        _positive(self.root_scope_id, "root scope ID")
        for name in ("parameters", "local_symbols", "instructions"):
            object.__setattr__(self, name, _tuple(getattr(self, name), name))
        if self.owner.kind is RoutineKind.START and self.parameters:
            raise ValueError("START cannot have parameters")
        if self.owner.kind is RoutineKind.FUNCTION:
            signature = self.owner.function
            if len(self.parameters) != len(signature.parameter_types):
                raise ValueError("function parameters do not match signature")
            for parameter, name, kind in zip(
                self.parameters, signature.parameter_names, signature.parameter_types,
            ):
                if (not isinstance(parameter, ParameterRef) or parameter.owner is not self.owner
                        or parameter.symbol.name != name or parameter.type is not kind
                        or parameter.symbol.scope_id != self.root_scope_id):
                    raise ValueError("function parameter metadata is inconsistent")
        local_ids: set[int] = set()
        locals_by_id: dict[int, VariableRef | ParameterRef | ArrayRef] = {}
        for symbol in self.local_symbols:
            if (not isinstance(symbol, (VariableRef, ParameterRef, ArrayRef))
                    or symbol.owner is not self.owner or symbol.symbol.id in local_ids):
                raise ValueError("local symbol identities must be unique and owned")
            local_ids.add(symbol.symbol.id)
            locals_by_id[symbol.symbol.id] = symbol
        if any(
            not isinstance(locals_by_id.get(parameter.symbol.id), ParameterRef)
            or locals_by_id[parameter.symbol.id].symbol is not parameter.symbol
            for parameter in self.parameters
        ):
            raise ValueError("parameters must retain their registered semantic symbols")
        _structural_identities(self.owner, self.instructions)
        for instruction in self.instructions:
            for operand in instruction_operands(instruction):
                source_refs = (operand.array,) if isinstance(operand, CheckedElement) else (operand,)
                for reference in source_refs:
                    if isinstance(reference, (VariableRef, ParameterRef, ArrayRef)):
                        registered = locals_by_id.get(reference.symbol.id)
                        if (registered is None or type(registered) is not type(reference)
                                or registered.symbol is not reference.symbol):
                            raise ValueError("instruction uses an unlisted source symbol")

    def __repr__(self) -> str:
        return f"IRRoutine({self.owner!r}, instructions={len(self.instructions)})"


@dataclass(frozen=True, slots=True, eq=False)
class IRFunction:
    function: FunctionRef
    parameters: tuple[ParameterRef, ...]
    body: IRRoutine

    def __post_init__(self) -> None:
        if not isinstance(self.function, FunctionRef) or not isinstance(self.body, IRRoutine):
            raise TypeError("IR function needs signature and routine")
        object.__setattr__(self, "parameters", _tuple(self.parameters, "parameters"))
        if (self.body.owner.kind is not RoutineKind.FUNCTION
                or self.body.owner.function is not self.function.symbol
                or len(self.parameters) != len(self.body.parameters)
                or any(
                    not isinstance(parameter, ParameterRef)
                    or parameter.owner is not self.body.owner
                    or parameter.symbol is not body_parameter.symbol
                    for parameter, body_parameter in zip(self.parameters, self.body.parameters)
                )):
            raise ValueError("IR function metadata does not match routine")

    def __repr__(self) -> str:
        return f"IRFunction({self.function!r}, instructions={len(self.body.instructions)})"


@dataclass(frozen=True, slots=True, eq=False)
class IRProgram:
    """Structural container; complete IR verification is deferred to M5 Task 08."""

    source_program: Program
    semantic_owner: AnalysisResult
    functions: tuple[IRFunction, ...]
    entry: IRRoutine

    def __post_init__(self) -> None:
        if not isinstance(self.source_program, Program) or not isinstance(self.semantic_owner, AnalysisResult):
            raise TypeError("IR program needs original Program and AnalysisResult")
        object.__setattr__(self, "functions", _tuple(self.functions, "functions"))
        if self.semantic_owner.program is not self.source_program:
            raise ValueError("semantic result does not own source Program")
        if (not isinstance(self.entry, IRRoutine)
                or self.entry.owner.kind is not RoutineKind.START
                or self.entry.root_scope_id != self.semantic_owner.start_scope.id):
            raise ValueError("START routine does not match semantic result")
        if len(self.functions) != len(self.semantic_owner.signatures):
            raise ValueError("IR function coverage is incomplete")
        for item, signature, analysis in zip(
            self.functions, self.semantic_owner.signatures, self.semantic_owner.functions,
        ):
            if (not isinstance(item, IRFunction) or item.function.symbol is not signature
                    or analysis.function is not signature
                    or item.body.root_scope_id != analysis.scope.id
                    or len(item.parameters) != len(analysis.parameters)
                    or any(param.symbol is not analyzed
                           for param, analyzed in zip(item.parameters, analysis.parameters))):
                raise ValueError("IR function order or ownership is inconsistent")
        owners = [self.entry.owner, *(item.body.owner for item in self.functions)]
        if len({id(owner) for owner in owners}) != len(owners):
            raise ValueError("IR routines must have distinct owners")

    def __repr__(self) -> str:
        return f"IRProgram(functions={len(self.functions)}, entry={self.entry!r})"
