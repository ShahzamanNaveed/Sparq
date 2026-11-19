"""Controlled construction of structural IR routine fragments.

This builder validates local shape and ownership. It does not lower source,
prove path-dependent availability, or publish a fully verified program.
"""

from __future__ import annotations

from sparq.ast_nodes import SourceSpan
from sparq.ir import (
    ArrayRef, BoolMergeTemp, BranchBool, CheckBounds, CheckedElement,
    Constant, IRRoutine, Instruction, Jump, Label, LabelRef, Move, ParameterRef,
    RoutineId, Temporary, VariableRef, _INSTRUCTION_TYPES,
    instruction_operands,
)
from sparq.symbols import ScalarType


class IRBuilder:
    """One mutable routine builder; failed local operations leave it usable."""

    def __init__(
        self,
        owner: RoutineId,
        root_scope_id: int,
        *,
        parameters: tuple[ParameterRef, ...] | list[ParameterRef] = (),
        local_symbols: tuple[VariableRef | ParameterRef | ArrayRef, ...]
                       | list[VariableRef | ParameterRef | ArrayRef] = (),
    ) -> None:
        if not isinstance(owner, RoutineId):
            raise TypeError("builder needs a RoutineId")
        if type(root_scope_id) is not int or root_scope_id < 1:
            raise ValueError("root scope ID must be positive")
        if not isinstance(parameters, (list, tuple)) or not isinstance(local_symbols, (list, tuple)):
            raise TypeError("builder symbol collections must be lists or tuples")
        self._owner = owner
        self._root_scope_id = root_scope_id
        self._parameters = tuple(parameters)
        self._local_symbols = tuple(local_symbols)
        # Validate the static header before exposing a mutable builder.
        IRRoutine(owner, root_scope_id, self._parameters, self._local_symbols, ())
        self._local_by_id = {item.symbol.id: item for item in self._local_symbols}
        self._instructions: list[Instruction] = []
        self._next_temp = 1
        self._next_guard = 1
        self._next_label = 1
        self._temps: set[int] = set()
        self._guards: set[int] = set()
        self._labels: set[int] = set()
        self._defined_labels: set[int] = set()
        self._ordinary_defs: set[int] = set()
        self._guard_defs: set[int] = set()
        self._completed: IRRoutine | None = None

    @property
    def owner(self) -> RoutineId:
        return self._owner

    @property
    def root_scope_id(self) -> int:
        return self._root_scope_id

    @property
    def is_complete(self) -> bool:
        """Whether finish() has closed this builder to further emission."""
        return self._completed is not None

    def _open(self) -> None:
        if self._completed is not None:
            raise ValueError("IR builder is already completed")

    def temp(self, kind: ScalarType) -> Temporary:
        self._open()
        result = Temporary(self.owner, self._next_temp, kind)
        self._temps.add(id(result))
        self._next_temp += 1
        return result

    def merge_temp(self) -> BoolMergeTemp:
        self._open()
        result = BoolMergeTemp(self.owner, self._next_temp)
        self._temps.add(id(result))
        self._next_temp += 1
        return result

    def guard(self, array: ArrayRef, index: Constant | Temporary) -> CheckedElement:
        self._open()
        result = CheckedElement(self.owner, self._next_guard, array, index)
        self._check_operand(array)
        self._check_operand(index)
        self._guards.add(id(result))
        self._next_guard += 1
        return result

    def label(self) -> LabelRef:
        self._open()
        result = LabelRef(self.owner, self._next_label)
        self._labels.add(id(result))
        self._next_label += 1
        return result

    def _check_operand(self, operand: object) -> None:
        if isinstance(operand, (VariableRef, ParameterRef, ArrayRef)):
            if operand.owner is not self.owner:
                raise ValueError("source operand belongs to another routine")
            listed = self._local_by_id.get(operand.symbol.id)
            if (listed is None or type(listed) is not type(operand)
                    or listed.symbol is not operand.symbol):
                raise ValueError("source operand is not in this routine's symbol inventory")
        elif isinstance(operand, (Temporary, BoolMergeTemp)):
            if operand.owner is not self.owner or id(operand) not in self._temps:
                raise ValueError("temporary was not allocated by this builder")
        elif isinstance(operand, CheckedElement):
            if operand.owner is not self.owner or id(operand) not in self._guards:
                raise ValueError("guard was not allocated by this builder")
            self._check_operand(operand.array)
            self._check_operand(operand.index)
        elif isinstance(operand, LabelRef):
            if operand.owner is not self.owner or id(operand) not in self._labels:
                raise ValueError("label was not allocated by this builder")

    def emit(self, instruction: Instruction) -> Instruction:
        self._open()
        if not isinstance(instruction, _INSTRUCTION_TYPES):
            raise TypeError("IR instruction required")
        if instruction.owner is not self.owner:
            raise ValueError("instruction belongs to another routine")
        # Validate before mutating any builder state.
        for operand in instruction_operands(instruction):
            self._check_operand(operand)
        if isinstance(instruction, Label) and id(instruction.target) in self._defined_labels:
            raise ValueError("label defined twice")
        target = getattr(instruction, "result", None)
        if isinstance(instruction, Move):
            target = instruction.target
        if isinstance(target, Temporary) and id(target) in self._ordinary_defs:
            raise ValueError("ordinary temporary defined twice")
        if isinstance(instruction, CheckBounds) and id(instruction.result) in self._guard_defs:
            raise ValueError("guard defined twice")
        if isinstance(instruction, Label):
            self._defined_labels.add(id(instruction.target))
        if isinstance(target, Temporary):
            self._ordinary_defs.add(id(target))
        if isinstance(instruction, CheckBounds):
            self._guard_defs.add(id(instruction.result))
        self._instructions.append(instruction)
        return instruction

    def define(self, label: LabelRef, span: SourceSpan) -> Label:
        """Emit one symbolic label definition; allocation may precede it."""
        return self.emit(Label(self.owner, span, label))

    def snapshot(self) -> tuple[Instruction, ...]:
        """Detached immutable instruction sequence; builder remains open."""
        return tuple(self._instructions)

    def finish(self) -> IRRoutine:
        """Freeze a structurally checked fragment, not a full IR verification."""
        if self._completed is not None:
            return self._completed
        result = IRRoutine(
            self.owner, self.root_scope_id,
            self._parameters, self._local_symbols, tuple(self._instructions),
        )
        self._completed = result
        return result
