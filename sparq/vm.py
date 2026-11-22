"""Execute validated Sparq three-register target programs without host recursion."""

from __future__ import annotations

import argparse
import io
import math
import re
import sys
from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import TextIO

from sparq.ast_nodes import SourceSpan
from sparq.errors import LexicalError, SemanticError
from sparq.ir import Constant
from sparq.lexer import Lexer
from sparq.optimization import optimize_program
from sparq.parser import ParseError, Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.symbols import ScalarType, VoidType
from sparq.tac import generate_tac
from sparq.target import (
    FrameSlot, Op, Register, SlotKind, TargetInstruction, TargetProgram,
    TargetRoutine,
)
from sparq.target_codegen import generate_target
from sparq.token import TokenType


class VMErrorCode(Enum):
    INVALID_TARGET = "INVALID_TARGET"
    INVALID_STATE = "INVALID_STATE"
    DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
    REMAINDER_BY_ZERO = "REMAINDER_BY_ZERO"
    NONFINITE_FLOAT = "NONFINITE_FLOAT"
    INT_TO_FLOAT = "INT_TO_FLOAT"
    BOUNDS = "BOUNDS"
    ALLOCATION = "ALLOCATION"
    INVALID_READ = "INVALID_READ"
    INPUT_EXHAUSTED = "INPUT_EXHAUSTED"
    CALL_DEPTH = "CALL_DEPTH"
    STEP_LIMIT = "STEP_LIMIT"
    IO_ERROR = "IO_ERROR"


class VMRuntimeError(Exception):
    """Controlled target-validation or runtime failure with source provenance."""

    def __init__(self, code: VMErrorCode, message: str, span: SourceSpan | None = None) -> None:
        self.code = code
        self.message = message
        self.span = span
        super().__init__(str(self))

    def __str__(self) -> str:
        where = "" if self.span is None else f" at {self.span.start_line}:{self.span.start_column}"
        return f"{self.code.value}{where}: {self.message}"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    output: str
    consumed_fields: int
    steps: int


@dataclass(slots=True)
class _Array:
    type: ScalarType
    values: list[Constant]


@dataclass(frozen=True, slots=True)
class _Guard:
    array_slot: FrameSlot
    array: _Array
    index: int


@dataclass(slots=True)
class _Frame:
    routine: TargetRoutine
    labels: dict[object, int]
    slots: dict[FrameSlot, Constant | _Array | _Guard | None]
    registers: list[Constant | None] = field(default_factory=lambda: [None, None, None])
    arguments: list[Constant] = field(default_factory=list)
    pc: int = 0


@dataclass(frozen=True, slots=True)
class _TypeState:
    """May-types for registers/guards and must-initialized frame slots."""

    registers: tuple[frozenset[ScalarType | None], ...]
    initialized: frozenset[FrameSlot]
    guards: tuple[frozenset[FrameSlot | None], ...]
    arguments: tuple[ScalarType, ...] = ()


_ARITHMETIC = frozenset({
    TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH, TokenType.PERCENT,
})
_ORDERED = frozenset({
    TokenType.LESS, TokenType.LESS_EQUAL, TokenType.GREATER, TokenType.GREATER_EQUAL,
})
_EQUALITY = frozenset({TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL})
_DECIMAL_INT = re.compile(r"[+-]?[0-9]+\Z")
_DECIMAL_FLOAT = re.compile(r"[+-]?[0-9]+\.[0-9]+\Z")
_DECIMAL_CHUNK = 1000
_DECIMAL_BASE = 10 ** _DECIMAL_CHUNK
_DEFAULTS = {
    ScalarType.INT: 0,
    ScalarType.FLOAT: 0.0,
    ScalarType.CHAR: "\0",
    ScalarType.STRING: "",
    ScalarType.BOOL: False,
}


def validate_target(program: TargetProgram) -> TargetProgram:
    """Recheck records and reachable target CFGs at the execution boundary."""
    if not isinstance(program, TargetProgram):
        raise VMRuntimeError(VMErrorCode.INVALID_TARGET, "TargetProgram required")
    try:
        for routine in (*program.functions, program.entry):
            for slot in routine.slots:
                replace(slot)
            for item in routine.instructions:
                replace(item)
                if item.opcode is Op.CONST:
                    replace(item.operands[1])
            replace(routine)
        replace(program)
        if program.entry.parameters:
            raise ValueError("START cannot have parameters")
        for routine in (*program.functions, program.entry):
            _validate_routine(routine)
    except VMRuntimeError:
        raise
    except (TypeError, ValueError, AttributeError, KeyError, IndexError, RecursionError) as exc:
        raise VMRuntimeError(VMErrorCode.INVALID_TARGET, "invalid target structure") from exc
    return program


def _validate_routine(routine: TargetRoutine) -> None:
    instructions = routine.instructions
    labels = {item.operands[0]: index for index, item in enumerate(instructions)
              if item.opcode is Op.LABEL}
    for item in instructions:
        opcode = item.opcode
        if opcode is Op.HALT and routine.owner.function is not None:
            raise ValueError("HALT in function")
        if opcode in (Op.RETURN, Op.RETURN_VOID):
            if routine.owner.function is None:
                raise ValueError("RETURN in START")
            expected = routine.owner.function.return_type
            if (opcode is Op.RETURN) != isinstance(expected, ScalarType):
                raise ValueError("RETURN category differs from function signature")
        if opcode is Op.UNARY:
            operator, kind = item.operands[1], item.operands[3]
            if not ((operator is TokenType.MINUS and kind in (ScalarType.INT, ScalarType.FLOAT))
                    or (operator is TokenType.NOT and kind is ScalarType.BOOL)):
                raise ValueError("invalid unary operator/type")
        if opcode is Op.BINARY:
            operator, kind = item.operands[1], item.operands[4]
            if (operator not in _ARITHMETIC or kind not in (ScalarType.INT, ScalarType.FLOAT)
                    or operator is TokenType.PERCENT and kind is not ScalarType.INT):
                raise ValueError("invalid binary operator/type")
        if opcode is Op.COMPARE:
            operator, kind = item.operands[1], item.operands[4]
            if not (operator in _EQUALITY or operator in _ORDERED
                    and kind in (ScalarType.INT, ScalarType.FLOAT)):
                raise ValueError("invalid comparison operator/type")
        if opcode is Op.ALLOC_ARRAY:
            default = item.operands[2]
            if (default.value != _DEFAULTS[default.type]
                    or default.type is ScalarType.FLOAT
                    and math.copysign(1.0, default.value) < 0):
                raise ValueError("array default differs from frozen type default")
    if not instructions:
        raise ValueError("target routine has no instructions")
    pending = [0]
    seen = set()
    while pending:
        index = pending.pop()
        if index in seen:
            continue
        if index >= len(instructions):
            raise ValueError("reachable routine fallthrough")
        seen.add(index)
        item = instructions[index]
        if item.opcode is Op.JUMP:
            pending.append(labels[item.operands[0]])
        elif item.opcode is Op.BRANCH_BOOL:
            pending.extend(labels[label] for label in item.operands[1:])
        elif item.opcode not in (Op.RETURN, Op.RETURN_VOID, Op.HALT):
            pending.append(index + 1)
    _validate_types(routine, labels)


def _join_types(left: _TypeState, right: _TypeState,
                item: TargetInstruction) -> _TypeState:
    if left.arguments != right.arguments:
        raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                             "incompatible pending arguments at control-flow join", item.span)
    return _TypeState(
        tuple(a | b for a, b in zip(left.registers, right.registers)),
        left.initialized & right.initialized,
        tuple(a | b for a, b in zip(left.guards, right.guards)),
        left.arguments,
    )


def _require_register(state: _TypeState, register: Register,
                      item: TargetInstruction, expected: ScalarType | None = None
                      ) -> frozenset[ScalarType]:
    possible = state.registers[register.value]
    if None in possible:
        raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                             f"{register.name} may be undefined", item.span)
    if expected is not None and possible != frozenset((expected,)):
        raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                             f"{register.name} must hold {expected.name}", item.span)
    return possible


def _validate_types(routine: TargetRoutine, labels: dict[object, int]) -> None:
    """Reachable, terminating may-type analysis; no value or trap is evaluated."""
    instructions = routine.instructions
    guard_slots = tuple(slot for slot in routine.slots if slot.kind is SlotKind.GUARD)
    guard_positions = {slot: index for index, slot in enumerate(guard_slots)}
    undefined = frozenset((None,))
    entry = _TypeState((undefined, undefined, undefined),
                       frozenset(routine.parameters),
                       tuple(undefined for _ in guard_slots))
    incoming = {0: entry}
    worklist = deque((0,))
    while worklist:
        index = worklist.popleft()
        item = instructions[index]
        op, args = item.opcode, item.operands
        state = incoming[index]
        registers = list(state.registers)
        initialized = state.initialized
        guards = list(state.guards)
        arguments = state.arguments

        def assign(register: Register, kinds: frozenset[ScalarType | None]) -> None:
            registers[register.value] = kinds

        def checked_guard(slot: FrameSlot) -> frozenset[FrameSlot]:
            possible = state.guards[guard_positions[slot]]
            if None in possible:
                raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                                     "element guard may be undefined or stale", item.span)
            return possible

        if op is Op.CONST:
            assign(args[0], frozenset((args[1].type,)))
        elif op is Op.LOAD:
            if args[1] not in initialized:
                raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                                     "scalar slot may be uninitialized", item.span)
            assign(args[0], frozenset((args[1].type,)))
        elif op in (Op.STORE, Op.INIT_SCALAR):
            _require_register(state, args[1], item, args[0].type)
            initialized = initialized | frozenset((args[0],))
        elif op is Op.ALLOC_ARRAY:
            initialized = initialized | frozenset((args[0],))
            guards = [frozenset(None if array is args[0] else array for array in possible)
                      for possible in guards]
        elif op is Op.INIT_ELEMENT:
            if args[0] not in initialized:
                raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                                     "array may be unallocated", item.span)
            _require_register(state, args[2], item, args[0].type)
        elif op is Op.CHECK_BOUNDS:
            if args[1] not in initialized:
                raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                                     "array may be unallocated", item.span)
            _require_register(state, args[2], item, ScalarType.INT)
            guards[guard_positions[args[0]]] = frozenset((args[1],))
        elif op is Op.LOAD_ELEMENT:
            arrays = checked_guard(args[1])
            assign(args[0], frozenset(array.type for array in arrays))
        elif op is Op.STORE_ELEMENT:
            arrays = checked_guard(args[0])
            possible = _require_register(state, args[1], item)
            if any(possible != frozenset((array.type,)) for array in arrays):
                raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                                     "array element store type mismatch", item.span)
        elif op is Op.READ_ELEMENT:
            checked_guard(args[0])
        elif op is Op.BRANCH_BOOL:
            _require_register(state, args[0], item, ScalarType.BOOL)
        elif op is Op.UNARY:
            _require_register(state, args[2], item, args[3])
            assign(args[0], frozenset((args[3],)))
        elif op is Op.BINARY:
            _require_register(state, args[2], item, args[4])
            _require_register(state, args[3], item, args[4])
            assign(args[0], frozenset((args[4],)))
        elif op is Op.COMPARE:
            _require_register(state, args[2], item, args[4])
            _require_register(state, args[3], item, args[4])
            assign(args[0], frozenset((ScalarType.BOOL,)))
        elif op is Op.TO_FLOAT:
            _require_register(state, args[1], item, ScalarType.INT)
            assign(args[0], frozenset((ScalarType.FLOAT,)))
        elif op is Op.PUSH_ARG:
            _require_register(state, args[0], item, args[1])
            arguments += (args[1],)
        elif op is Op.CALL:
            if arguments != args[0].parameter_types:
                raise VMRuntimeError(VMErrorCode.INVALID_TARGET,
                                     "CALL argument buffer differs from signature", item.span)
            result = args[0].return_type
            registers = [frozenset((result,)) if isinstance(result, ScalarType) else undefined,
                         undefined, undefined]
            arguments = ()
        elif op is Op.RETURN:
            _require_register(state, args[0], item, routine.owner.function.return_type)
        elif op is Op.READ_SCALAR:
            initialized = initialized | frozenset((args[0],))
        elif op is Op.SHOW:
            _require_register(state, args[0], item)

        outgoing = _TypeState(tuple(registers), initialized, tuple(guards), arguments)
        if op is Op.JUMP:
            successors = (labels[args[0]],)
        elif op is Op.BRANCH_BOOL:
            successors = (labels[args[1]], labels[args[2]])
        elif op in (Op.RETURN, Op.RETURN_VOID, Op.HALT):
            successors = ()
        else:
            successors = (index + 1,)
        for successor in successors:
            previous = incoming.get(successor)
            merged = outgoing if previous is None else _join_types(
                previous, outgoing, instructions[successor]
            )
            if merged != previous:
                incoming[successor] = merged
                worklist.append(successor)


def _parse_int(text: str) -> int:
    """Parse arbitrary decimal input without changing Python's safety limit."""
    sign = -1 if text.startswith("-") else 1
    digits = text[1:] if text[:1] in "+-" else text
    value = 0
    for start in range(0, len(digits), _DECIMAL_CHUNK):
        chunk = digits[start:start + _DECIMAL_CHUNK]
        value = value * (10 ** len(chunk)) + int(chunk)
    return sign * value


def _format_int(value: int) -> str:
    """Format arbitrary INT values without Python's global decimal-conversion override."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    remaining = abs(value)
    pieces = []
    while remaining:
        remaining, piece = divmod(remaining, _DECIMAL_BASE)
        pieces.append(str(piece) if not remaining else f"{piece:0{_DECIMAL_CHUNK}d}")
    return sign + "".join(reversed(pieces))


def _to_float(value: int, span: SourceSpan) -> Constant:
    try:
        converted = float(value)
    except OverflowError as exc:
        raise VMRuntimeError(VMErrorCode.INT_TO_FLOAT, "INT cannot convert to finite FLOAT", span) from exc
    if not math.isfinite(converted):
        raise VMRuntimeError(VMErrorCode.INT_TO_FLOAT, "INT cannot convert to finite FLOAT", span)
    return Constant(ScalarType.FLOAT, converted)


class VirtualMachine:
    """One-shot VM; output and consumed_fields remain inspectable after an error."""

    def __init__(
        self, program: TargetProgram, *, input_stream: str | TextIO = "",
        output_stream: TextIO | None = None, max_call_depth: int = 1000,
        max_array_elements: int = 1_000_000, max_steps: int | None = None,
    ) -> None:
        validate_target(program)
        if type(max_call_depth) is not int or max_call_depth < 1:
            raise ValueError("max_call_depth must be a positive integer")
        if type(max_array_elements) is not int or max_array_elements < 1:
            raise ValueError("max_array_elements must be a positive integer")
        if max_steps is not None and (type(max_steps) is not int or max_steps < 0):
            raise ValueError("max_steps must be a nonnegative integer or None")
        if isinstance(input_stream, str):
            input_stream = io.StringIO(input_stream)
        if not callable(getattr(input_stream, "read", None)):
            raise TypeError("input_stream must be text or a readable text stream")
        if output_stream is not None and not callable(getattr(output_stream, "write", None)):
            raise TypeError("output_stream must be a writable text stream")
        self.program = program
        self.input_stream = input_stream
        self.output_stream = output_stream
        self.max_call_depth = max_call_depth
        self.max_array_elements = max_array_elements
        self.max_steps = max_steps
        self.consumed_fields = 0
        self.steps = 0
        self._output: list[str] = []
        self._started = False
        self._live_elements = 0
        self._functions = {id(routine.owner.function): routine for routine in program.functions}
        self._stack: list[_Frame] = []

    @property
    def output(self) -> str:
        return "".join(self._output)

    def _frame(self, routine: TargetRoutine, arguments: tuple[Constant, ...] = ()) -> _Frame:
        labels = {item.operands[0]: index for index, item in enumerate(routine.instructions)
                  if item.opcode is Op.LABEL}
        slots: dict[FrameSlot, Constant | _Array | _Guard | None] = {
            slot: None for slot in routine.slots
        }
        if len(arguments) != len(routine.parameters):
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "call argument count mismatch")
        for slot, argument in zip(routine.parameters, arguments):
            if argument.type is not slot.type:
                raise VMRuntimeError(VMErrorCode.INVALID_STATE, "call argument type mismatch")
            slots[slot] = argument
        return _Frame(routine, labels, slots)

    def _read_register(self, frame: _Frame, register: Register, span: SourceSpan,
                       expected: ScalarType | None = None) -> Constant:
        value = frame.registers[register.value]
        if not isinstance(value, Constant) or expected is not None and value.type is not expected:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "uninitialized or mistyped register", span)
        return value

    def _read_slot(self, frame: _Frame, slot: FrameSlot, span: SourceSpan) -> Constant:
        value = frame.slots[slot]
        if not isinstance(value, Constant) or value.type is not slot.type:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "uninitialized or mistyped scalar slot", span)
        return value

    def _array(self, frame: _Frame, slot: FrameSlot, span: SourceSpan) -> _Array:
        value = frame.slots[slot]
        if not isinstance(value, _Array) or value.type is not slot.type:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "array is not allocated", span)
        return value

    def _guard(self, frame: _Frame, slot: FrameSlot, span: SourceSpan) -> _Guard:
        value = frame.slots[slot]
        if (not isinstance(value, _Guard)
                or frame.slots.get(value.array_slot) is not value.array
                or not 0 <= value.index < len(value.array.values)):
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "missing or stale bounds guard", span)
        return value

    def _input_field(self, span: SourceSpan) -> str:
        chars = []
        try:
            while True:
                char = self.input_stream.read(1)
                if not isinstance(char, str) or len(char) > 1:
                    raise VMRuntimeError(VMErrorCode.IO_ERROR, "input stream returned invalid text", span)
                if not char:
                    raise VMRuntimeError(VMErrorCode.INPUT_EXHAUSTED, "READ reached end of input", span)
                if not char.isspace():
                    chars.append(char)
                    break
            while True:
                char = self.input_stream.read(1)
                if not isinstance(char, str) or len(char) > 1:
                    raise VMRuntimeError(VMErrorCode.IO_ERROR, "input stream returned invalid text", span)
                if not char or char.isspace():
                    break
                chars.append(char)
        except (OSError, UnicodeError, ValueError) as exc:
            raise VMRuntimeError(VMErrorCode.IO_ERROR, "input stream failed", span) from exc
        self.consumed_fields += 1
        return "".join(chars)

    def _parse_field(self, kind: ScalarType, span: SourceSpan) -> Constant:
        field = self._input_field(span)
        if kind is ScalarType.INT and _DECIMAL_INT.fullmatch(field):
            return Constant(kind, _parse_int(field))
        if kind is ScalarType.FLOAT:
            if _DECIMAL_INT.fullmatch(field):
                return _to_float(_parse_int(field), span)
            if _DECIMAL_FLOAT.fullmatch(field):
                try:
                    value = float(field)
                except ValueError as exc:
                    raise VMRuntimeError(VMErrorCode.INVALID_READ, "invalid FLOAT field", span) from exc
                if math.isfinite(value):
                    return Constant(kind, value)
        if kind is ScalarType.BOOL and field in ("TRUE", "FALSE"):
            return Constant(kind, field == "TRUE")
        if kind is ScalarType.CHAR and len(field) == 1 and not 0xD800 <= ord(field) <= 0xDFFF:
            return Constant(kind, field)
        if kind is ScalarType.STRING:
            try:
                return Constant(kind, field)
            except ValueError:
                pass
        raise VMRuntimeError(VMErrorCode.INVALID_READ, f"invalid {kind.name} input field", span)

    def _show(self, value: Constant, span: SourceSpan) -> None:
        if value.type is ScalarType.INT:
            rendered = _format_int(value.value)
        elif value.type is ScalarType.FLOAT:
            rendered = repr(value.value)
        elif value.type is ScalarType.BOOL:
            rendered = "TRUE" if value.value else "FALSE"
        else:
            rendered = value.value
        text = rendered + "\n"
        if self.output_stream is not None:
            try:
                self.output_stream.write(text)
                flush = getattr(self.output_stream, "flush", None)
                if callable(flush):
                    flush()
            except (OSError, UnicodeError, ValueError) as exc:
                raise VMRuntimeError(VMErrorCode.IO_ERROR, "output stream failed", span) from exc
        self._output.append(text)

    def _unary(self, operator: TokenType, value: Constant, kind: ScalarType,
               span: SourceSpan) -> Constant:
        if value.type is not kind:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "unary operand type mismatch", span)
        if operator is TokenType.NOT:
            return Constant(ScalarType.BOOL, not value.value)
        result = -value.value
        if kind is ScalarType.FLOAT and not math.isfinite(result):
            raise VMRuntimeError(VMErrorCode.NONFINITE_FLOAT, "nonfinite unary FLOAT result", span)
        return Constant(kind, result)

    def _binary(self, operator: TokenType, left: Constant, right: Constant,
                kind: ScalarType, span: SourceSpan) -> Constant:
        if left.type is not kind or right.type is not kind:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "binary operand type mismatch", span)
        a, b = left.value, right.value
        if operator in (TokenType.SLASH, TokenType.PERCENT) and b == 0:
            code = VMErrorCode.DIVISION_BY_ZERO if operator is TokenType.SLASH else VMErrorCode.REMAINDER_BY_ZERO
            raise VMRuntimeError(code, "zero divisor", span)
        if operator is TokenType.PLUS:
            result = a + b
        elif operator is TokenType.MINUS:
            result = a - b
        elif operator is TokenType.STAR:
            result = a * b
        elif operator is TokenType.SLASH:
            if kind is ScalarType.INT:
                magnitude = abs(a) // abs(b)
                result = -magnitude if (a < 0) != (b < 0) else magnitude
            else:
                result = a / b
        else:
            magnitude = abs(a) // abs(b)
            quotient = -magnitude if (a < 0) != (b < 0) else magnitude
            result = a - quotient * b
        if kind is ScalarType.FLOAT and not math.isfinite(result):
            raise VMRuntimeError(VMErrorCode.NONFINITE_FLOAT, "nonfinite FLOAT result", span)
        return Constant(kind, result)

    def _compare(self, operator: TokenType, left: Constant, right: Constant,
                 kind: ScalarType, span: SourceSpan) -> Constant:
        if left.type is not kind or right.type is not kind:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "comparison operand type mismatch", span)
        a, b = left.value, right.value
        comparisons = {
            TokenType.EQUAL_EQUAL: lambda: a == b,
            TokenType.BANG_EQUAL: lambda: a != b,
            TokenType.LESS: lambda: a < b,
            TokenType.LESS_EQUAL: lambda: a <= b,
            TokenType.GREATER: lambda: a > b,
            TokenType.GREATER_EQUAL: lambda: a >= b,
        }
        return Constant(ScalarType.BOOL, comparisons[operator]())

    def _return(self, value: Constant | None, span: SourceSpan) -> None:
        callee = self._stack.pop()
        signature = callee.routine.owner.function
        if signature is None or (value is None) != (signature.return_type is VoidType.VOID):
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "invalid function return", span)
        if value is not None and value.type is not signature.return_type:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "return type mismatch", span)
        self._live_elements -= sum(len(item.values) for item in callee.slots.values()
                                   if isinstance(item, _Array))
        if not self._stack:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "function returned without caller", span)
        caller = self._stack[-1]
        caller.registers[:] = [value, None, None]

    def _execute(self, frame: _Frame, item: TargetInstruction) -> bool:
        op, args, span = item.opcode, item.operands, item.span
        if op is Op.CONST:
            frame.registers[args[0].value] = args[1]
        elif op is Op.LOAD:
            frame.registers[args[0].value] = self._read_slot(frame, args[1], span)
        elif op in (Op.STORE, Op.INIT_SCALAR):
            value = self._read_register(frame, args[1], span, args[0].type)
            frame.slots[args[0]] = value
        elif op is Op.ALLOC_ARRAY:
            slot, length, default = args
            old = frame.slots[slot]
            previous = len(old.values) if isinstance(old, _Array) else 0
            if length > self.max_array_elements - (self._live_elements - previous):
                raise VMRuntimeError(VMErrorCode.ALLOCATION, "array allocation limit exceeded", span)
            try:
                values = [default] * length
            except (MemoryError, OverflowError) as exc:
                raise VMRuntimeError(VMErrorCode.ALLOCATION, "array allocation failed", span) from exc
            frame.slots[slot] = _Array(slot.type, values)
            self._live_elements += length - previous
            for guard_slot, current in frame.slots.items():
                if isinstance(current, _Guard) and current.array_slot is slot:
                    frame.slots[guard_slot] = None
        elif op is Op.INIT_ELEMENT:
            array = self._array(frame, args[0], span)
            array.values[args[1]] = self._read_register(frame, args[2], span, array.type)
        elif op is Op.CHECK_BOUNDS:
            guard_slot, array_slot, register = args
            array = self._array(frame, array_slot, span)
            index = self._read_register(frame, register, span, ScalarType.INT).value
            if not 0 <= index < len(array.values):
                raise VMRuntimeError(VMErrorCode.BOUNDS, "array index out of range", span)
            frame.slots[guard_slot] = _Guard(array_slot, array, index)
        elif op is Op.LOAD_ELEMENT:
            guard = self._guard(frame, args[1], span)
            frame.registers[args[0].value] = guard.array.values[guard.index]
        elif op is Op.STORE_ELEMENT:
            guard = self._guard(frame, args[0], span)
            guard.array.values[guard.index] = self._read_register(
                frame, args[1], span, guard.array.type
            )
        elif op is Op.LABEL:
            pass
        elif op is Op.JUMP:
            frame.pc = frame.labels[args[0]]
        elif op is Op.BRANCH_BOOL:
            condition = self._read_register(frame, args[0], span, ScalarType.BOOL).value
            frame.pc = frame.labels[args[1] if condition else args[2]]
        elif op is Op.UNARY:
            value = self._read_register(frame, args[2], span)
            frame.registers[args[0].value] = self._unary(args[1], value, args[3], span)
        elif op is Op.BINARY:
            left = self._read_register(frame, args[2], span)
            right = self._read_register(frame, args[3], span)
            frame.registers[args[0].value] = self._binary(args[1], left, right, args[4], span)
        elif op is Op.COMPARE:
            left = self._read_register(frame, args[2], span)
            right = self._read_register(frame, args[3], span)
            frame.registers[args[0].value] = self._compare(args[1], left, right, args[4], span)
        elif op is Op.TO_FLOAT:
            source = self._read_register(frame, args[1], span, ScalarType.INT)
            frame.registers[args[0].value] = _to_float(source.value, span)
        elif op is Op.PUSH_ARG:
            frame.arguments.append(self._read_register(frame, args[0], span, args[1]))
        elif op is Op.CALL:
            function, count = args
            if len(frame.arguments) != count:
                raise VMRuntimeError(VMErrorCode.INVALID_STATE, "CALL argument buffer mismatch", span)
            if len(self._stack) - 1 >= self.max_call_depth:
                raise VMRuntimeError(VMErrorCode.CALL_DEPTH, "maximum VM call depth exceeded", span)
            callee = self._functions.get(id(function.symbol))
            if callee is None:
                raise VMRuntimeError(VMErrorCode.INVALID_STATE, "unknown function target", span)
            new_frame = self._frame(callee, tuple(frame.arguments))
            frame.arguments.clear()
            self._stack.append(new_frame)
        elif op is Op.RETURN:
            self._return(self._read_register(frame, args[0], span), span)
        elif op is Op.RETURN_VOID:
            self._return(None, span)
        elif op is Op.READ_SCALAR:
            frame.slots[args[0]] = self._parse_field(args[0].type, span)
        elif op is Op.READ_ELEMENT:
            guard = self._guard(frame, args[0], span)
            value = self._parse_field(guard.array.type, span)
            guard.array.values[guard.index] = value
        elif op is Op.SHOW:
            self._show(self._read_register(frame, args[0], span), span)
        elif op is Op.HALT:
            if len(self._stack) != 1 or frame.routine is not self.program.entry:
                raise VMRuntimeError(VMErrorCode.INVALID_STATE, "HALT outside START", span)
            return True
        else:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "unknown target operation", span)
        return False

    def run(self) -> ExecutionResult:
        if self._started:
            raise VMRuntimeError(VMErrorCode.INVALID_STATE, "VM session cannot run twice")
        self._started = True
        self._stack.append(self._frame(self.program.entry))
        while self._stack:
            frame = self._stack[-1]
            if not 0 <= frame.pc < len(frame.routine.instructions):
                raise VMRuntimeError(VMErrorCode.INVALID_STATE, "program counter escaped routine")
            item = frame.routine.instructions[frame.pc]
            if self.max_steps is not None and self.steps >= self.max_steps:
                raise VMRuntimeError(VMErrorCode.STEP_LIMIT, "execution step limit reached", item.span)
            frame.pc += 1
            self.steps += 1
            try:
                halted = self._execute(frame, item)
            except VMRuntimeError:
                raise
            except MemoryError as exc:
                raise VMRuntimeError(VMErrorCode.ALLOCATION, "runtime resource exhausted", item.span) from exc
            except (TypeError, ValueError, OverflowError, ZeroDivisionError, IndexError, KeyError) as exc:
                raise VMRuntimeError(VMErrorCode.INVALID_STATE, "invalid target execution state", item.span) from exc
            if halted:
                return ExecutionResult(self.output, self.consumed_fields, self.steps)
        raise VMRuntimeError(VMErrorCode.INVALID_STATE, "execution ended without HALT")


def run_target(program: TargetProgram, **options) -> ExecutionResult:
    """Execute one validated target program and return captured output and counters."""
    return VirtualMachine(program, **options).run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile and execute Sparq source on its target VM")
    parser.add_argument("source", help=".spq source file")
    parser.add_argument("--optimize", action="store_true", help="execute optimized verified TAC")
    parser.add_argument("--target-optimize", action="store_true",
                        help="execute machine-dependent optimized target")
    args = parser.parse_args(argv)
    try:
        source = Path(args.source).read_text(encoding="utf-8")
        program = Parser(Lexer(source).tokenize()).parse()
        analysis = SemanticAnalyzer(program).analyze()
        ir = generate_tac(program, analysis)
        if args.optimize:
            ir = optimize_program(ir, analysis)
        target = generate_target(ir)
        if args.target_optimize:
            from sparq.target_optimization import optimize_target
            target = optimize_target(target)
    except (OSError, UnicodeError, LexicalError, ParseError, SemanticError,
            TypeError, ValueError, RecursionError) as exc:
        print(f"Sparq compilation error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    try:
        VirtualMachine(target, input_stream=sys.stdin, output_stream=sys.stdout).run()
        return 0
    except VMRuntimeError as exc:
        print(f"Sparq runtime error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
