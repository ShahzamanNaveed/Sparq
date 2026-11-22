"""Whole-program ownership and reachable-path availability checks for typed TAC."""

from __future__ import annotations

from collections import deque

from sparq.ir import (
    ArrayRef, Binary, BoolMergeTemp, BranchBool, Call, CheckBounds, CheckedElement,
    Compare, Convert, HaltStart, IRProgram, IRRoutine, InitArray, InitElement,
    InitScalar, Jump, Label, Load, LoadElement, Move, ParameterRef, ReadElement,
    Return, Show, StoreElement, Temporary, Unary, VariableRef,
)
from sparq.symbols import SymbolKind


class IRVerificationError(ValueError):
    """A structurally valid fragment is not a valid complete Sparq program."""


def _expected_symbols(analysis, owner, parameters=()):
    return tuple(parameters) + tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in analysis.declarations
    )


def _same_inventory(actual, expected):
    return len(actual) == len(expected) and all(
        type(left) is type(right) and left.owner is right.owner
        and left.symbol is right.symbol
        for left, right in zip(actual, expected)
    )


def _within(inner, outer):
    return ((outer.start_line, outer.start_column)
            <= (inner.start_line, inner.start_column)
            <= (inner.end_line, inner.end_column)
            <= (outer.end_line, outer.end_column))


def _uses(instruction):
    if isinstance(instruction, (InitScalar, InitElement, Show, Return)):
        values = (instruction.value,)
    elif isinstance(instruction, StoreElement):
        values = (instruction.checked, instruction.value)
    elif isinstance(instruction, Move):
        values = (instruction.value,)
    elif isinstance(instruction, (Unary, Convert)):
        values = (instruction.operand,)
    elif isinstance(instruction, (Binary, Compare)):
        values = (instruction.left, instruction.right)
    elif isinstance(instruction, CheckBounds):
        values = (instruction.index,)
    elif isinstance(instruction, (LoadElement, ReadElement)):
        values = (instruction.checked,)
    elif isinstance(instruction, BranchBool):
        values = (instruction.condition,)
    elif isinstance(instruction, Call):
        values = instruction.arguments
    else:
        values = ()
    return tuple(value for value in values if isinstance(
        value, (Temporary, BoolMergeTemp, CheckedElement)
    ))


def _key(value):
    return ("guard" if isinstance(value, CheckedElement)
            else "merge" if isinstance(value, BoolMergeTemp) else "temp", value.number)


def _definition(instruction):
    if isinstance(instruction, CheckBounds):
        return instruction.result
    if isinstance(instruction, Move) and isinstance(instruction.target, (Temporary, BoolMergeTemp)):
        return instruction.target
    result = getattr(instruction, "result", None)
    return result if isinstance(result, (Temporary, BoolMergeTemp)) else None


def _successors(items):
    labels = {item.target: index for index, item in enumerate(items)
              if isinstance(item, Label)}
    edges = []
    for index, item in enumerate(items):
        if isinstance(item, Jump):
            targets = (labels[item.target],)
        elif isinstance(item, BranchBool):
            targets = (labels[item.true_target], labels[item.false_target])
        elif isinstance(item, (Return, HaltStart)):
            targets = ()
        else:
            targets = (index + 1,)
        edges.append(targets)
    return edges


def _verify_routine(routine: IRRoutine) -> None:
    items = routine.instructions
    if not items:
        raise IRVerificationError("complete routine has no termination instruction")
    edges = _successors(items)
    reachable = {0}
    queue = deque([0])
    while queue:
        for target in edges[queue.popleft()]:
            if target == len(items):
                raise IRVerificationError("reachable routine path falls through")
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
    if routine.owner.function is None:
        if any(isinstance(items[i], Return) for i in reachable):
            raise IRVerificationError("START path contains RETURN")
    elif any(isinstance(items[i], HaltStart) for i in reachable):
        raise IRVerificationError("function path contains HaltStart")

    # Definite availability uses intersection at joins. Bitsets keep routines
    # with many temporaries bounded in memory; all non-entry nodes start at top.
    keys = {_key(value) for item in items for value in
            (*_uses(item), _definition(item)) if value is not None}
    bits = {key: 1 << number for number, key in enumerate(keys)}
    full = (1 << len(bits)) - 1
    guards_by_array = {}
    for item in items:
        if isinstance(item, CheckBounds):
            array_id = id(item.array.symbol)
            guards_by_array[array_id] = (
                guards_by_array.get(array_id, 0) | bits[_key(item.result)]
            )
    predecessors = {index: [] for index in reachable}
    for index in reachable:
        for target in edges[index]:
            if target in reachable:
                predecessors[target].append(index)
    incoming = {index: (0 if index == 0 else full) for index in reachable}
    outgoing = {index: full for index in reachable}
    pending = deque(sorted(reachable))
    queued = set(reachable)
    while pending:
        index = pending.popleft()
        queued.remove(index)
        parents = predecessors[index]
        facts = 0 if index == 0 else full
        for parent in parents:
            facts &= outgoing[parent]
        item = items[index]
        after = facts
        if isinstance(item, InitArray):
            after &= ~guards_by_array.get(id(item.target.symbol), 0)
        defined = _definition(item)
        if defined is not None:
            after |= bits[_key(defined)]
        incoming[index] = facts
        if after != outgoing[index]:
            outgoing[index] = after
            for target in edges[index]:
                if target in reachable and target not in queued:
                    pending.append(target)
                    queued.add(target)
    for index in sorted(reachable):
        for used in _uses(items[index]):
            if not incoming[index] & bits[_key(used)]:
                raise IRVerificationError(
                    f"instruction {index} uses a temporary or guard unavailable on every path"
                )

    # Two BOOL-merge writes must be separated by a use or by mutually
    # exclusive control paths, rather than silently overwriting one another.
    merge_writes = {}
    for index in reachable:
        item = items[index]
        if isinstance(item, Move) and isinstance(item.target, BoolMergeTemp):
            merge_writes.setdefault(item.target.number, []).append(index)
    for number, positions in merge_writes.items():
        if len(positions) < 2:
            continue
        for origin in positions:
            seen = set()
            pending = list(edges[origin])
            while pending:
                index = pending.pop()
                if index in seen or index not in reachable:
                    continue
                seen.add(index)
                if index in positions and index != origin:
                    raise IRVerificationError("BOOL merge assignments may execute sequentially")
                if any(isinstance(value, BoolMergeTemp) and value.number == number
                       for value in _uses(items[index])):
                    continue
                pending.extend(edges[index])


def verify_program(program: IRProgram) -> IRProgram:
    """Verify an accepted program's exact semantic ownership and reachable IR paths."""
    if not isinstance(program, IRProgram):
        raise IRVerificationError("IRProgram is required")
    semantic = program.semantic_owner
    if program.source_program is not semantic.program:
        raise IRVerificationError("source and semantic program identities differ")
    entry = program.entry
    if not _same_inventory(entry.local_symbols, _expected_symbols(semantic.start, entry.owner)):
        raise IRVerificationError("START symbol inventory differs from semantic analysis")
    routines = [(entry, semantic.program.main.span)]
    for item, analysis in zip(program.functions, semantic.functions):
        expected_parameters = tuple(ParameterRef(item.body.owner, symbol)
                                    for symbol in analysis.parameters)
        if (item.function.symbol is not analysis.function
                or not _same_inventory(item.parameters, expected_parameters)
                or not _same_inventory(item.body.local_symbols, _expected_symbols(
                    analysis.body, item.body.owner, expected_parameters))):
            raise IRVerificationError("function symbol inventory differs from semantic analysis")
        routines.append((item.body, analysis.declaration.body.span))
    for routine, source_span in routines:
        for instruction in routine.instructions:
            if not _within(instruction.span, source_span):
                raise IRVerificationError("instruction span lies outside its owning source body")
            if isinstance(instruction, Call) and not any(
                instruction.function.symbol is signature for signature in semantic.signatures
            ):
                raise IRVerificationError("CALL target is foreign to the owning analysis")
        _verify_routine(routine)
    return program
