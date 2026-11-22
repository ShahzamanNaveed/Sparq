"""Conservative DAG selection and register-aware optimization for Sparq targets."""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from sparq.ir import Constant
from sparq.symbols import ScalarType
from sparq.target import (
    FrameSlot, Op, Register, SlotKind, TargetInstruction, TargetProgram,
    TargetRoutine, instruction_cost,
)
from sparq.token import TokenType
from sparq.vm import VMRuntimeError, validate_target


class TargetOptimizationError(ValueError):
    """The optimizer did not publish a partially transformed target program."""


@dataclass(frozen=True, slots=True)
class TargetStage:
    name: str
    instructions: int
    estimated_cost: int


@dataclass(frozen=True, slots=True)
class TargetOptimizationReport:
    stages: tuple[TargetStage, ...]
    dag_reuses: int
    redundant_loads: int
    dead_register_definitions: int
    unused_temporary_spills: int


@dataclass(frozen=True, slots=True)
class _DagNode:
    """A typed operation and its ordered value dependencies in one pure region."""

    opcode: Op
    operator: TokenType
    kind: ScalarType
    inputs: tuple[object, ...]
    available_slot: FrameSlot | None = None


def _constant_key(constant: Constant) -> tuple[object, ...]:
    """Distinguish binary64 signed zero while retaining exact scalar types."""
    value = (struct.pack(">d", constant.value) if constant.type is ScalarType.FLOAT
             else constant.value)
    return ("constant", constant.type, value)


def _regions(routine: TargetRoutine) -> tuple[range, ...]:
    """Basic blocks: labels and instructions after transfers start new regions."""
    instructions = routine.instructions
    leaders = {0}
    for index, item in enumerate(instructions):
        if item.opcode is Op.LABEL:
            leaders.add(index)
        if item.opcode in (Op.JUMP, Op.BRANCH_BOOL, Op.RETURN, Op.RETURN_VOID, Op.HALT):
            if index + 1 < len(instructions):
                leaders.add(index + 1)
    starts = sorted(leaders)
    return tuple(range(start, end) for start, end in zip(starts, (*starts[1:], len(instructions))))


def _successors(routine: TargetRoutine) -> tuple[tuple[int, ...], ...]:
    labels = {item.operands[0]: index for index, item in enumerate(routine.instructions)
              if item.opcode is Op.LABEL}
    result = []
    for index, item in enumerate(routine.instructions):
        if item.opcode is Op.JUMP:
            successors = (labels[item.operands[0]],)
        elif item.opcode is Op.BRANCH_BOOL:
            successors = tuple(labels[label] for label in item.operands[1:])
        elif item.opcode in (Op.RETURN, Op.RETURN_VOID, Op.HALT):
            successors = ()
        elif index + 1 < len(routine.instructions):
            successors = (index + 1,)
        else:
            successors = ()
        result.append(successors)
    return tuple(result)


def _reachable(successors: tuple[tuple[int, ...], ...]) -> frozenset[int]:
    pending = [0]
    seen = set()
    while pending:
        index = pending.pop()
        if index not in seen:
            seen.add(index)
            pending.extend(successors[index])
    return frozenset(seen)


def _eligible(item: TargetInstruction) -> bool:
    op, args = item.opcode, item.operands
    if op is Op.BINARY:
        return args[4] is ScalarType.INT and args[1] in (
            TokenType.PLUS, TokenType.MINUS, TokenType.STAR
        )
    if op is Op.COMPARE:
        return args[4] is not ScalarType.FLOAT
    if op is Op.UNARY:
        return (args[1] is TokenType.NOT and args[3] is ScalarType.BOOL
                or args[1] is TokenType.MINUS and args[3] is ScalarType.INT)
    return False


def _dag_select(routine: TargetRoutine) -> tuple[TargetRoutine, int]:
    """Hash-cons pure typed nodes and select a cached-slot LOAD on a DAG hit."""
    reachable = _reachable(_successors(routine))
    output: list[TargetInstruction] = []
    hits = 0
    for region in _regions(routine):
        nodes: dict[tuple[object, ...], _DagNode] = {}
        values: dict[FrameSlot, tuple[object, ...]] = {}
        versions: dict[FrameSlot, int] = {}
        registers: list[tuple[object, ...] | None] = [None, None, None]
        for index in region:
            item = routine.instructions[index]
            if index not in reachable:
                output.append(item)
                continue
            op, args = item.opcode, item.operands
            if op is Op.CONST:
                registers[args[0].value] = _constant_key(args[1])
            elif op is Op.LOAD:
                slot = args[1]
                registers[args[0].value] = values.get(
                    slot, ("slot", slot, versions.get(slot, 0))
                )
            elif _eligible(item):
                sources = (args[2],) if op is Op.UNARY else (args[2], args[3])
                dependencies = tuple(registers[register.value] for register in sources)
                key = (op, args[1], args[-1], *dependencies)
                if any(dependency is None for dependency in dependencies):
                    registers[args[0].value] = None
                else:
                    node = nodes.get(key)
                    if node is not None and node.available_slot is not None:
                        output.append(TargetInstruction(item.owner, Op.LOAD,
                                                        (args[0], node.available_slot), item.span))
                        registers[args[0].value] = key
                        hits += 1
                        continue
                    nodes[key] = _DagNode(op, args[1], args[-1], dependencies)
                    registers[args[0].value] = key
            elif op in (Op.STORE, Op.INIT_SCALAR):
                slot, register = args
                for key, node in tuple(nodes.items()):
                    if node.available_slot is slot:
                        nodes[key] = replace(node, available_slot=None)
                versions[slot] = versions.get(slot, 0) + 1
                value = registers[register.value]
                values[slot] = value if value is not None else ("slot", slot, versions[slot])
                if value in nodes:
                    nodes[value] = replace(nodes[value], available_slot=slot)
            elif op is Op.READ_SCALAR:
                slot = args[0]
                versions[slot] = versions.get(slot, 0) + 1
                values[slot] = ("slot", slot, versions[slot])
            elif op in (Op.LOAD_ELEMENT, Op.TO_FLOAT):
                registers[args[0].value] = None
            elif op is Op.CALL:
                registers = [None, None, None]
            if op in (Op.CALL, Op.READ_SCALAR, Op.READ_ELEMENT, Op.SHOW,
                      Op.ALLOC_ARRAY, Op.INIT_ELEMENT, Op.CHECK_BOUNDS,
                      Op.LOAD_ELEMENT, Op.STORE_ELEMENT, Op.PUSH_ARG, Op.TO_FLOAT,
                      Op.LABEL, Op.JUMP, Op.BRANCH_BOOL, Op.RETURN,
                      Op.RETURN_VOID, Op.HALT) or op in (Op.UNARY, Op.BINARY, Op.COMPARE) and not _eligible(item):
                nodes.clear()
                values.clear()
                registers = [None, None, None]
            output.append(item)
    return replace(routine, instructions=tuple(output)), hits


def _reuse_registers(routine: TargetRoutine) -> tuple[TargetRoutine, int]:
    """Remove a LOAD/CONST only when its destination already holds that value."""
    reachable = _reachable(_successors(routine))
    output: list[TargetInstruction] = []
    removed = 0
    for region in _regions(routine):
        known: list[tuple[object, ...] | None] = [None, None, None]
        versions: dict[FrameSlot, int] = {}
        for index in region:
            item = routine.instructions[index]
            if index not in reachable:
                output.append(item)
                continue
            op, args = item.opcode, item.operands
            if op in (Op.CONST, Op.LOAD):
                key = (_constant_key(args[1]) if op is Op.CONST else
                       ("slot", args[1], versions.get(args[1], 0)))
                register = args[0].value
                if known[register] == key:
                    removed += 1
                    continue
                known[register] = key
            elif op in (Op.STORE, Op.INIT_SCALAR, Op.READ_SCALAR):
                slot = args[0]
                versions[slot] = versions.get(slot, 0) + 1
                known = [None if value is not None and value[:2] == ("slot", slot)
                         else value for value in known]
                if op is not Op.READ_SCALAR:
                    known[args[1].value] = ("slot", slot, versions[slot])
            elif op in (Op.UNARY, Op.BINARY, Op.COMPARE, Op.TO_FLOAT, Op.LOAD_ELEMENT):
                known[args[0].value] = None
            elif op is Op.CALL:
                known = [None, None, None]
            output.append(item)
    return replace(routine, instructions=tuple(output)), removed


def _register_effects(item: TargetInstruction) -> tuple[frozenset[Register], frozenset[Register]]:
    op, args = item.opcode, item.operands
    if op in (Op.CONST, Op.LOAD, Op.LOAD_ELEMENT):
        return frozenset(), frozenset((args[0],))
    if op in (Op.STORE, Op.INIT_SCALAR):
        return frozenset((args[1],)), frozenset()
    if op in (Op.INIT_ELEMENT, Op.CHECK_BOUNDS):
        return frozenset((args[2],)), frozenset()
    if op is Op.STORE_ELEMENT:
        return frozenset((args[1],)), frozenset()
    if op is Op.BRANCH_BOOL:
        return frozenset((args[0],)), frozenset()
    if op is Op.UNARY:
        return frozenset((args[2],)), frozenset((args[0],))
    if op in (Op.BINARY, Op.COMPARE):
        return frozenset((args[2], args[3])), frozenset((args[0],))
    if op is Op.TO_FLOAT:
        return frozenset((args[1],)), frozenset((args[0],))
    if op in (Op.PUSH_ARG, Op.RETURN, Op.SHOW):
        return frozenset((args[0],)), frozenset()
    if op is Op.CALL:
        return frozenset(), frozenset(Register)
    return frozenset(), frozenset()


def _drop_dead_register_definitions(routine: TargetRoutine) -> tuple[TargetRoutine, int]:
    """Backward three-register liveness over every reachable branch and loop."""
    successors = _successors(routine)
    reachable = _reachable(successors)
    live_in = [frozenset() for _ in routine.instructions]
    live_out = [frozenset() for _ in routine.instructions]
    changed = True
    while changed:
        changed = False
        for index in reversed(range(len(routine.instructions))):
            if index not in reachable:
                continue
            out = frozenset().union(*(live_in[next_index] for next_index in successors[index]))
            reads, writes = _register_effects(routine.instructions[index])
            before = reads | (out - writes)
            if before != live_in[index] or out != live_out[index]:
                live_in[index], live_out[index] = before, out
                changed = True
    kept = tuple(item for index, item in enumerate(routine.instructions)
                 if not (index in reachable and item.opcode in (Op.CONST, Op.LOAD)
                         and item.operands[0] not in live_out[index]))
    return replace(routine, instructions=kept), len(routine.instructions) - len(kept)


def _drop_unused_spills(routine: TargetRoutine) -> tuple[TargetRoutine, int]:
    """A compiler temporary with no remaining LOAD never needs a frame write."""
    read_slots = {item.operands[1] for item in routine.instructions if item.opcode is Op.LOAD}
    kept = tuple(item for item in routine.instructions if not (
        item.opcode is Op.STORE and item.operands[0].kind in (SlotKind.TEMP, SlotKind.MERGE)
        and item.operands[0] not in read_slots
    ))
    return replace(routine, instructions=kept), len(routine.instructions) - len(kept)


def _map_routines(program: TargetProgram, operation):
    results = [operation(routine) for routine in (*program.functions, program.entry)]
    return replace(program, functions=tuple(result[0] for result in results[:-1]),
                   entry=results[-1][0]), sum(result[1] for result in results)


def _stage(name: str, program: TargetProgram) -> TargetStage:
    items = tuple(item for routine in (*program.functions, program.entry)
                  for item in routine.instructions)
    return TargetStage(name, len(items), sum(instruction_cost(item) for item in items))


def optimize_target_with_report(program: TargetProgram) -> tuple[TargetProgram, TargetOptimizationReport]:
    """Optimize a validated target, publishing only a cheaper validated program."""
    try:
        validate_target(program)
        stages = [_stage("ordinary", program)]
        current, dag_reuses = _map_routines(program, _dag_select)
        validate_target(current)
        stages.append(_stage("DAG selection", current))
        current, redundant_loads = _map_routines(current, _reuse_registers)
        validate_target(current)
        stages.append(_stage("register reuse", current))
        current, dead_registers = _map_routines(current, _drop_dead_register_definitions)
        validate_target(current)
        stages.append(_stage("register liveness", current))
        current, dead_spills = _map_routines(current, _drop_unused_spills)
        validate_target(current)
        stages.append(_stage("unused spill cleanup", current))
        current, additional = _map_routines(current, _drop_dead_register_definitions)
        dead_registers += additional
        validate_target(current)
        stages.append(_stage("final register liveness", current))
        if stages[-1].estimated_cost > stages[0].estimated_cost:
            raise TargetOptimizationError("target optimization increased estimated cost")
        report = TargetOptimizationReport(tuple(stages), dag_reuses, redundant_loads,
                                          dead_registers, dead_spills)
        return current, report
    except (VMRuntimeError, TypeError, ValueError, KeyError, RecursionError) as exc:
        raise TargetOptimizationError("cannot publish a validated optimized target") from exc


def optimize_target(program: TargetProgram) -> TargetProgram:
    """Return machine-dependent optimized target instructions for the existing ISA."""
    return optimize_target_with_report(program)[0]
