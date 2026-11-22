"""Immutable instructions and frame layout for Sparq's three-register VM target."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from sparq.ast_nodes import SourceSpan
from sparq.ir import Constant, FunctionRef, IRProgram, LabelRef, RoutineId
from sparq.ir_verify import verify_program
from sparq.symbols import ScalarType, SymbolKind, VariableSymbol
from sparq.token import TokenType


class Register(Enum):
    R0 = 0
    R1 = 1
    R2 = 2


class SlotKind(Enum):
    VARIABLE = auto()
    PARAMETER = auto()
    ARRAY = auto()
    TEMP = auto()
    MERGE = auto()
    GUARD = auto()


@dataclass(frozen=True, slots=True)
class FrameSlot:
    owner: RoutineId
    kind: SlotKind
    number: int
    type: ScalarType | None
    symbol: VariableSymbol | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.owner, RoutineId) or not isinstance(self.kind, SlotKind):
            raise TypeError("frame slot needs a routine and category")
        if type(self.number) is not int or self.number < 1:
            raise ValueError("frame slot number must be positive")
        expected = {
            SlotKind.VARIABLE: SymbolKind.VARIABLE,
            SlotKind.PARAMETER: SymbolKind.PARAMETER,
            SlotKind.ARRAY: SymbolKind.ARRAY,
        }
        if self.kind in expected:
            if (not isinstance(self.symbol, VariableSymbol)
                    or self.symbol.id != self.number
                    or self.symbol.kind is not expected[self.kind]
                    or self.type is not self.symbol.type):
                raise ValueError("source slot does not match its exact symbol metadata")
        elif self.symbol is not None:
            raise ValueError("compiler slot cannot carry a source symbol")
        if self.kind is SlotKind.GUARD:
            if self.type is not None:
                raise ValueError("guard slot has no scalar type")
        elif self.kind is SlotKind.MERGE:
            if self.type is not ScalarType.BOOL:
                raise ValueError("merge slot must be BOOL")
        elif not isinstance(self.type, ScalarType):
            raise TypeError("scalar or array element type is required")

    def __repr__(self) -> str:
        label = self.symbol.name if self.symbol is not None else ""
        return f"{self.kind.name.lower()}{self.number}({label}):{self.type.name if self.type else 'GUARD'}"


class Op(Enum):
    CONST = auto()
    LOAD = auto()
    STORE = auto()
    INIT_SCALAR = auto()
    ALLOC_ARRAY = auto()
    INIT_ELEMENT = auto()
    CHECK_BOUNDS = auto()
    LOAD_ELEMENT = auto()
    STORE_ELEMENT = auto()
    LABEL = auto()
    JUMP = auto()
    BRANCH_BOOL = auto()
    UNARY = auto()
    BINARY = auto()
    COMPARE = auto()
    TO_FLOAT = auto()
    PUSH_ARG = auto()
    CALL = auto()
    RETURN = auto()
    RETURN_VOID = auto()
    READ_SCALAR = auto()
    READ_ELEMENT = auto()
    SHOW = auto()
    HALT = auto()


_SHAPES = {
    Op.CONST: (Register, Constant),
    Op.LOAD: (Register, FrameSlot),
    Op.STORE: (FrameSlot, Register),
    Op.INIT_SCALAR: (FrameSlot, Register),
    Op.ALLOC_ARRAY: (FrameSlot, int, Constant),
    Op.INIT_ELEMENT: (FrameSlot, int, Register),
    Op.CHECK_BOUNDS: (FrameSlot, FrameSlot, Register),
    Op.LOAD_ELEMENT: (Register, FrameSlot),
    Op.STORE_ELEMENT: (FrameSlot, Register),
    Op.LABEL: (LabelRef,),
    Op.JUMP: (LabelRef,),
    Op.BRANCH_BOOL: (Register, LabelRef, LabelRef),
    Op.UNARY: (Register, TokenType, Register, ScalarType),
    Op.BINARY: (Register, TokenType, Register, Register, ScalarType),
    Op.COMPARE: (Register, TokenType, Register, Register, ScalarType),
    Op.TO_FLOAT: (Register, Register),
    Op.PUSH_ARG: (Register, ScalarType),
    Op.CALL: (FunctionRef, int),
    Op.RETURN: (Register,),
    Op.RETURN_VOID: (),
    Op.READ_SCALAR: (FrameSlot,),
    Op.READ_ELEMENT: (FrameSlot,),
    Op.SHOW: (Register,),
    Op.HALT: (),
}


@dataclass(frozen=True, slots=True)
class TargetInstruction:
    owner: RoutineId
    opcode: Op
    operands: tuple[object, ...]
    span: SourceSpan

    def __post_init__(self) -> None:
        if not isinstance(self.owner, RoutineId) or not isinstance(self.opcode, Op):
            raise TypeError("target instruction needs owner and opcode")
        if not isinstance(self.span, SourceSpan):
            raise TypeError("target instruction needs a source span")
        if not isinstance(self.operands, (tuple, list)):
            raise TypeError("operands must be a tuple or list")
        object.__setattr__(self, "operands", tuple(self.operands))
        shape = _SHAPES[self.opcode]
        if len(self.operands) != len(shape) or any(
            not isinstance(value, expected) or expected is int and type(value) is not int
            for value, expected in zip(self.operands, shape)
        ):
            raise ValueError("target operand shape does not match opcode")
        for value in self.operands:
            if isinstance(value, (FrameSlot, LabelRef)) and value.owner is not self.owner:
                raise ValueError("target operand belongs to another routine")
        if self.opcode in (Op.LOAD, Op.STORE) and (
            (self.operands[1] if self.opcode is Op.LOAD else self.operands[0]).kind
            in (SlotKind.ARRAY, SlotKind.GUARD)
        ):
            raise ValueError("ordinary register transfer requires a scalar frame slot")
        if self.opcode in (Op.ALLOC_ARRAY, Op.INIT_ELEMENT) and (
            self.operands[0].kind is not SlotKind.ARRAY
            or type(self.operands[1]) is not int or self.operands[1] < 0
        ):
            raise ValueError("array target and size/index are required")
        if self.opcode is Op.ALLOC_ARRAY and (
            self.operands[1] != self.operands[0].symbol.array_length
            or self.operands[2].type is not self.operands[0].type
        ):
            raise ValueError("array allocation metadata is inconsistent")
        if self.opcode is Op.INIT_ELEMENT and self.operands[1] >= self.operands[0].symbol.array_length:
            raise ValueError("initializer index exceeds array length")
        if self.opcode is Op.CHECK_BOUNDS and (
            self.operands[0].kind is not SlotKind.GUARD
            or self.operands[1].kind is not SlotKind.ARRAY
        ):
            raise ValueError("bounds check needs guard and array slots")
        if self.opcode in (Op.LOAD_ELEMENT, Op.STORE_ELEMENT, Op.READ_ELEMENT) and (
            (self.operands[1] if self.opcode is Op.LOAD_ELEMENT else self.operands[0]).kind
            is not SlotKind.GUARD
        ):
            raise ValueError("element access needs a checked guard slot")
        if self.opcode in (Op.READ_SCALAR, Op.INIT_SCALAR) and self.operands[0].kind not in (
            SlotKind.VARIABLE, SlotKind.PARAMETER
        ):
            raise ValueError("scalar target needs a source scalar slot")
        if self.opcode is Op.CALL and (
            self.operands[1] != len(self.operands[0].parameter_types)
            or self.operands[1] < 0
        ):
            raise ValueError("CALL arity differs from its signature")


@dataclass(frozen=True, slots=True)
class TargetRoutine:
    owner: RoutineId
    slots: tuple[FrameSlot, ...]
    parameters: tuple[FrameSlot, ...]
    instructions: tuple[TargetInstruction, ...]

    def __post_init__(self) -> None:
        for field in ("slots", "parameters", "instructions"):
            value = getattr(self, field)
            if not isinstance(value, (tuple, list)):
                raise TypeError("target routine collections must be tuples or lists")
            object.__setattr__(self, field, tuple(value))
        if not isinstance(self.owner, RoutineId):
            raise TypeError("target routine owner is required")
        keys = [(slot.kind, slot.number) for slot in self.slots]
        if (len(set(keys)) != len(keys)
                or any(not isinstance(slot, FrameSlot) or slot.owner is not self.owner for slot in self.slots)
                or any(slot.kind is not SlotKind.PARAMETER or slot not in self.slots
                       for slot in self.parameters)):
            raise ValueError("target frame has duplicate or foreign slots")
        known = {(slot.kind, slot.number): slot for slot in self.slots}
        if any(known.get((slot.kind, slot.number)) is not slot for slot in self.parameters):
            raise ValueError("parameters must use registered frame slots")
        labels = set()
        references = set()
        pending_arguments = []
        for item in self.instructions:
            if not isinstance(item, TargetInstruction) or item.owner is not self.owner:
                raise ValueError("target routine has a foreign instruction")
            for operand in item.operands:
                if isinstance(operand, FrameSlot):
                    slot = known.get((operand.kind, operand.number))
                    if slot is not operand:
                        raise ValueError("target instruction uses an unregistered frame slot")
            if item.opcode is Op.PUSH_ARG:
                pending_arguments.append(item.operands[1])
            elif item.opcode is Op.CALL:
                if tuple(pending_arguments) != item.operands[0].parameter_types:
                    raise ValueError("target CALL argument types differ from its signature")
                pending_arguments.clear()
            elif pending_arguments and item.opcode in (
                Op.LABEL, Op.JUMP, Op.BRANCH_BOOL, Op.RETURN, Op.RETURN_VOID, Op.HALT
            ):
                raise ValueError("pending CALL arguments cross a control boundary")
            if item.opcode is Op.LABEL:
                if item.operands[0] in labels:
                    raise ValueError("target label defined twice")
                labels.add(item.operands[0])
            elif item.opcode is Op.JUMP:
                references.add(item.operands[0])
            elif item.opcode is Op.BRANCH_BOOL:
                references.update(item.operands[1:])
        if pending_arguments or not references <= labels:
            raise ValueError("target branch references an undefined label")


@dataclass(frozen=True, slots=True)
class TargetProgram:
    source_ir: IRProgram
    functions: tuple[TargetRoutine, ...]
    entry: TargetRoutine

    def __post_init__(self) -> None:
        verify_program(self.source_ir)
        if not isinstance(self.functions, (tuple, list)):
            raise TypeError("target functions must be ordered")
        object.__setattr__(self, "functions", tuple(self.functions))
        if (not isinstance(self.entry, TargetRoutine)
                or self.entry.owner is not self.source_ir.entry.owner
                or len(self.functions) != len(self.source_ir.functions)):
            raise ValueError("target START or function inventory is inconsistent")
        for target, source in zip(self.functions, self.source_ir.functions):
            if (not isinstance(target, TargetRoutine)
                    or target.owner is not source.body.owner
                    or len(target.parameters) != len(source.parameters)
                    or any(slot.symbol is not parameter.symbol
                           for slot, parameter in zip(target.parameters, source.parameters))):
                raise ValueError("target function owner or parameters differ from source IR")
        for routine in (*self.functions, self.entry):
            for item in routine.instructions:
                if item.opcode is Op.CALL and not any(
                    item.operands[0].symbol is signature for signature in self.source_ir.semantic_owner.signatures
                ):
                    raise ValueError("target CALL has foreign function ownership")


_BASE_COST = {op: 1 for op in Op}
_BASE_COST.update({Op.LABEL: 0, Op.CHECK_BOUNDS: 2, Op.TO_FLOAT: 2,
                   Op.READ_SCALAR: 5, Op.READ_ELEMENT: 5, Op.SHOW: 5,
                   Op.CALL: 5, Op.ALLOC_ARRAY: 3})


def instruction_cost(item: TargetInstruction) -> int:
    """Deterministic target cost estimate, not a measured runtime count."""
    if not isinstance(item, TargetInstruction):
        raise TypeError("target instruction required")
    cost = _BASE_COST[item.opcode]
    if item.opcode is Op.ALLOC_ARRAY:
        cost += item.operands[1]
    elif item.opcode is Op.CALL:
        cost += item.operands[1]
    elif item.opcode is Op.BINARY and item.operands[-1] is ScalarType.FLOAT:
        cost += 1
    return cost


def _display(value) -> str:
    if type(value) is int and value.bit_length() > 4096:
        return repr(Constant(ScalarType.INT, value))
    if isinstance(value, Register):
        return value.name
    if isinstance(value, LabelRef):
        return f"L{value.number}"
    if isinstance(value, FunctionRef):
        return f"{value.symbol.name}#{value.symbol.id}"
    if isinstance(value, TokenType):
        return value.name
    if isinstance(value, ScalarType):
        return value.name
    return repr(value)


def format_target(program: TargetProgram) -> str:
    if not isinstance(program, TargetProgram):
        raise TypeError("TargetProgram required")
    lines = []
    for routine in (*program.functions, program.entry):
        if routine.owner.function is None:
            lines.append("START")
        else:
            function = routine.owner.function
            lines.append(f"FUNC {function.name}#{function.id} -> {function.return_type.name}")
        lines.append("  frame: " + ", ".join(map(repr, routine.slots)))
        for index, item in enumerate(routine.instructions):
            args = " ".join(_display(value) for value in item.operands)
            lines.append(f"  {index:04d} {item.opcode.name}" + (f" {args}" if args else ""))
    return "\n".join(lines)
