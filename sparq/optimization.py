"""Conservative, immutable optimization of verified Sparq typed TAC."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import math
from typing import Callable

from sparq.ir import (
    Binary, BoolMergeTemp, BranchBool, Call, CheckBounds, Compare, Constant,
    Convert, HaltStart, IRProgram, IRRoutine, InitArray, InitElement, InitScalar,
    Jump, Label, Load, LoadElement, Move, ParameterRef, ReadElement,
    ReadScalar, Return, Show, StoreElement, Temporary, Unary, VariableRef,
)
from sparq.ir_verify import verify_program
from sparq.program_semantic import AnalysisResult
from sparq.symbols import ScalarType
from sparq.token import TokenType


class OptimizationError(ValueError):
    """Optimization could not publish a complete verified IRProgram."""


@dataclass(frozen=True, slots=True)
class BasicBlock:
    number: int
    start: int
    end: int  # exclusive instruction index
    successors: tuple[int, ...]
    predecessors: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ControlFlowGraph:
    blocks: tuple[BasicBlock, ...]
    instruction_successors: tuple[tuple[int, ...], ...]
    reachable: frozenset[int]
    backedges: tuple[tuple[int, int], ...]


def analyze_routine(routine: IRRoutine) -> ControlFlowGraph:
    """Identify deterministic basic blocks and instruction-level CFG edges."""
    if not isinstance(routine, IRRoutine):
        raise TypeError("IRRoutine is required")
    items = routine.instructions
    if not items:
        return ControlFlowGraph((), (), frozenset(), ())
    labels = {item.target: i for i, item in enumerate(items) if isinstance(item, Label)}
    edges = []
    leaders = {0, *labels.values()}
    for i, item in enumerate(items):
        if isinstance(item, Jump):
            targets = (labels[item.target],)
        elif isinstance(item, BranchBool):
            targets = tuple(dict.fromkeys((labels[item.true_target], labels[item.false_target])))
        elif isinstance(item, (Return, HaltStart)):
            targets = ()
        else:
            targets = (i + 1,) if i + 1 < len(items) else ()
        edges.append(targets)
        if isinstance(item, (Jump, BranchBool, Return, HaltStart)) and i + 1 < len(items):
            leaders.add(i + 1)
    starts = sorted(leaders)
    block_of = {i: b for b, start in enumerate(starts)
                for i in range(start, starts[b + 1] if b + 1 < len(starts) else len(items))}
    successors = [tuple(dict.fromkeys(block_of[target] for target in edges[
        (starts[b + 1] if b + 1 < len(starts) else len(items)) - 1
    ])) for b in range(len(starts))]
    predecessors: list[list[int]] = [[] for _ in starts]
    for b, targets in enumerate(successors):
        for target in targets:
            predecessors[target].append(b)
    blocks = tuple(BasicBlock(b, start, starts[b + 1] if b + 1 < len(starts)
                              else len(items), successors[b], tuple(predecessors[b]))
                   for b, start in enumerate(starts))
    reachable = {0}
    pending = deque([0])
    while pending:
        for target in edges[pending.popleft()]:
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    # A backward edge is reported structurally; it need not be a natural-loop edge.
    backedges = tuple((b, target) for b, block in enumerate(blocks)
                      for target in block.successors if blocks[target].start <= block.start)
    return ControlFlowGraph(blocks, tuple(edges), frozenset(reachable), backedges)


def _key(value):
    if isinstance(value, (VariableRef, ParameterRef)):
        return ("storage", id(value.symbol))
    if isinstance(value, BoolMergeTemp):
        return ("merge", value.number)
    if isinstance(value, Temporary):
        return ("temp", value.number)
    return None


def _same_constant(a: Constant, b: Constant) -> bool:
    if a.type is not b.type or a.value != b.value:
        return False
    return (a.type is not ScalarType.FLOAT
            or math.copysign(1.0, a.value) == math.copysign(1.0, b.value))


def _resolve(value, facts):
    if isinstance(value, Constant):
        return value
    return facts.get(_key(value))


_FOLD_BITS = 4096


def _fold(item, facts):
    if isinstance(item, Unary):
        operand = _resolve(item.operand, facts)
        if operand is None:
            return None
        if item.operator is TokenType.NOT:
            return Constant(ScalarType.BOOL, not operand.value)
        if operand.type is ScalarType.INT and operand.value.bit_length() <= _FOLD_BITS:
            return Constant(ScalarType.INT, -operand.value)
        return None
    if isinstance(item, Convert):
        operand = _resolve(item.operand, facts)
        # Exactly represented integers cannot overflow or round during conversion.
        if operand is not None and abs(operand.value) <= (1 << 53):
            return Constant(ScalarType.FLOAT, float(operand.value))
        return None
    if isinstance(item, Compare):
        left, right = _resolve(item.left, facts), _resolve(item.right, facts)
        if left is None or right is None or left.type is ScalarType.FLOAT:
            return None
        a, b = left.value, right.value
        operations = {
            TokenType.EQUAL_EQUAL: lambda: a == b,
            TokenType.BANG_EQUAL: lambda: a != b,
            TokenType.LESS: lambda: a < b,
            TokenType.LESS_EQUAL: lambda: a <= b,
            TokenType.GREATER: lambda: a > b,
            TokenType.GREATER_EQUAL: lambda: a >= b,
        }
        return Constant(ScalarType.BOOL, operations[item.operator]())
    if isinstance(item, Binary):
        left, right = _resolve(item.left, facts), _resolve(item.right, facts)
        if (left is None or right is None or item.result.type is not ScalarType.INT
                or left.value.bit_length() > _FOLD_BITS
                or right.value.bit_length() > _FOLD_BITS):
            return None
        a, b = left.value, right.value
        op = item.operator
        if op in (TokenType.PLUS, TokenType.MINUS) and max(a.bit_length(), b.bit_length()) >= _FOLD_BITS:
            return None
        if op is TokenType.STAR and a.bit_length() + b.bit_length() > _FOLD_BITS:
            return None
        if op is TokenType.PLUS:
            result = a + b
        elif op is TokenType.MINUS:
            result = a - b
        elif op is TokenType.STAR:
            result = a * b
        elif op in (TokenType.SLASH, TokenType.PERCENT):
            if b == 0:
                return None  # Retain the exact runtime trap.
            quotient = abs(a) // abs(b)
            quotient = -quotient if (a < 0) != (b < 0) else quotient
            result = quotient if op is TokenType.SLASH else a - quotient * b
        else:
            return None
        return Constant(ScalarType.INT, result) if result.bit_length() <= _FOLD_BITS else None
    return None


def _algebraic(item, facts):
    if not isinstance(item, Binary) or item.result.type is not ScalarType.INT:
        return None
    left, right = _resolve(item.left, facts), _resolve(item.right, facts)
    op = item.operator
    if op is TokenType.PLUS:
        if right is not None and right.value == 0:
            return item.left
        if left is not None and left.value == 0:
            return item.right
    if op is TokenType.MINUS and right is not None and right.value == 0:
        return item.left
    if op is TokenType.STAR:
        if right is not None and right.value == 1:
            return item.left
        if left is not None and left.value == 1:
            return item.right
    if op is TokenType.SLASH and right is not None and right.value == 1:
        return item.left
    return None


def _rewrite(item, facts):
    """Replace stable operand values without moving their evaluation points."""
    def value(v):
        return _resolve(v, facts) or v
    if isinstance(item, (InitScalar, InitElement, Show, Return, StoreElement)):
        if getattr(item, "value", None) is not None:
            return replace(item, value=value(item.value))
    if isinstance(item, Move):
        return replace(item, value=value(item.value))
    if isinstance(item, (Unary, Convert)):
        return replace(item, operand=value(item.operand))
    if isinstance(item, (Binary, Compare)):
        return replace(item, left=value(item.left), right=value(item.right))
    if isinstance(item, BranchBool):
        return replace(item, condition=value(item.condition))
    if isinstance(item, Call):
        return replace(item, arguments=tuple(value(arg) for arg in item.arguments))
    return item


def _transfer(item, facts):
    result = facts.copy()
    if isinstance(item, (Call, ReadScalar, ReadElement)):
        # CALL and READ may have effects. Keep captured temps, forget storage.
        result = {key: value for key, value in result.items() if key[0] != "storage"}
    target = None
    value = None
    if isinstance(item, (InitScalar, Move)):
        target, value = item.target, _resolve(item.value, facts)
    elif isinstance(item, Load):
        target, value = item.result, facts.get(_key(item.source))
    elif isinstance(item, (Unary, Binary, Compare, Convert)):
        target, value = item.result, _fold(item, facts)
        if value is None:
            simplified = _algebraic(item, facts)
            if simplified is not None:
                value = _resolve(simplified, facts)
    elif isinstance(item, (Call, LoadElement)):
        target = item.result
    if target is not None:
        key = _key(target)
        result.pop(key, None)
        if value is not None:
            result[key] = value
    return result


def _meet(states):
    states = [state for state in states if state is not None]
    if not states:
        return None
    common = states[0].copy()
    for state in states[1:]:
        common = {key: value for key, value in common.items()
                  if key in state and _same_constant(value, state[key])}
    return common


def _constant_facts(routine):
    graph = analyze_routine(routine)
    items = routine.instructions
    predecessors = [[] for _ in items]
    for index, successors in enumerate(graph.instruction_successors):
        for successor in successors:
            predecessors[successor].append(index)
    incoming: list[dict | None] = [None] * len(items)
    outgoing: list[dict | None] = [None] * len(items)
    pending = deque([0])
    queued = {0}
    steps = 0
    limit = max(1000, len(items) * len(items) * 8)
    while pending:
        index = pending.popleft()
        queued.remove(index)
        facts = {} if index == 0 else _meet(outgoing[p] for p in predecessors[index])
        if facts is None:
            continue
        after = _transfer(items[index], facts)
        incoming[index] = facts
        if outgoing[index] != after:
            outgoing[index] = after
            for target in graph.instruction_successors[index]:
                if target not in queued:
                    queued.add(target)
                    pending.append(target)
        steps += 1
        if steps > limit:
            raise OptimizationError("constant propagation exceeded its work limit")
    return incoming


def _propagate_fold(routine):
    incoming = _constant_facts(routine)
    changed = []
    for item, facts in zip(routine.instructions, incoming):
        if facts is None:
            changed.append(item)
            continue
        rewritten = _rewrite(item, facts)
        folded = _fold(item, facts)
        if folded is not None:
            rewritten = Move(item.owner, item.span, item.result, folded)
        elif isinstance(item, Binary):
            simpler = _algebraic(item, facts)
            if simpler is not None:
                rewritten = Move(item.owner, item.span, item.result,
                                 _resolve(simpler, facts) or simpler)
        elif isinstance(rewritten, BranchBool) and isinstance(rewritten.condition, Constant):
            destination = rewritten.true_target if rewritten.condition.value else rewritten.false_target
            rewritten = Jump(item.owner, item.span, destination)
        elif isinstance(rewritten, Load):
            known = facts.get(_key(item.source))
            if known is not None:
                rewritten = Move(item.owner, item.span, item.result, known)
        changed.append(rewritten)
    return replace(routine, instructions=tuple(changed))


def _operand_key(value):
    if isinstance(value, Constant):
        if value.type is ScalarType.FLOAT:
            return ("constant", value.type, value.value.hex())
        return ("constant", value.type, value.value)
    if isinstance(value, Temporary):
        return ("temp", value.number, value.type)
    if isinstance(value, BoolMergeTemp):
        return ("merge", value.number)
    return None


def _dag_key(item):
    if isinstance(item, Binary) and item.result.type is ScalarType.INT and item.operator in (
        TokenType.PLUS, TokenType.MINUS, TokenType.STAR
    ):
        operands = (item.left, item.right)
    elif isinstance(item, Compare):
        operands = (item.left, item.right)
    elif isinstance(item, Unary):
        operands = (item.operand,)
    else:
        return None
    keys = tuple(_operand_key(value) for value in operands)
    if any(key is None for key in keys):
        return None
    return (type(item), item.operator, keys, item.result.type)


def _local_dag_cse(routine):
    graph = analyze_routine(routine)
    items = list(routine.instructions)
    for block in graph.blocks:
        seen = {}
        loads = {}
        aliases = {}

        def canonical(value):
            if not isinstance(value, Temporary):
                return value
            return aliases.get(value.number, value)

        for index in range(block.start, block.end):
            item = items[index]
            if isinstance(item, Load):
                previous = loads.get(id(item.source.symbol))
                if previous is not None:
                    items[index] = Move(item.owner, item.span, item.result, previous)
                    aliases[item.result.number] = previous
                else:
                    loads[id(item.source.symbol)] = item.result
                continue
            candidate = item
            if isinstance(item, (Binary, Compare)):
                candidate = replace(item, left=canonical(item.left), right=canonical(item.right))
            elif isinstance(item, Unary):
                candidate = replace(item, operand=canonical(item.operand))
            key = _dag_key(candidate)
            if key is not None:
                previous = seen.get(key)
                if previous is not None:
                    items[index] = Move(item.owner, item.span, item.result, previous)
                    aliases[item.result.number] = previous
                else:
                    items[index] = candidate
                    seen[key] = item.result
            elif isinstance(item, Move) and isinstance(item.target, Temporary):
                source = canonical(item.value)
                if isinstance(source, Temporary):
                    aliases[item.target.number] = source
            if isinstance(item, (InitScalar, InitArray, InitElement, StoreElement,
                                 ReadScalar, ReadElement, Call, Show, Return)) or (
                    isinstance(item, Move) and isinstance(item.target, (VariableRef, ParameterRef))):
                seen.clear()
                loads.clear()
    return replace(routine, instructions=tuple(items))


def _uses(item):
    if isinstance(item, (InitScalar, InitElement, Show, Return, Move)):
        values = (item.value,)
    elif isinstance(item, StoreElement):
        values = (item.checked, item.value)
    elif isinstance(item, (Unary, Convert)):
        values = (item.operand,)
    elif isinstance(item, (Binary, Compare)):
        values = (item.left, item.right)
    elif isinstance(item, CheckBounds):
        values = (item.index,)
    elif isinstance(item, (LoadElement, ReadElement)):
        values = (item.checked,)
    elif isinstance(item, BranchBool):
        values = (item.condition,)
    elif isinstance(item, Call):
        values = item.arguments
    else:
        values = ()
    return {_key(value) for value in values if isinstance(value, (Temporary, BoolMergeTemp))}


def _dead_candidate(item):
    if isinstance(item, (Load, Unary, Compare)):
        return item.result
    if isinstance(item, Binary) and item.result.type is ScalarType.INT and item.operator in (
        TokenType.PLUS, TokenType.MINUS, TokenType.STAR
    ):
        return item.result
    if isinstance(item, Move) and isinstance(item.target, Temporary):
        return item.target
    return None


def _dead_once(routine):
    items = routine.instructions
    if not items:
        return routine
    graph = analyze_routine(routine)
    live_in = [set() for _ in items]
    live_out = [set() for _ in items]
    changed = True
    while changed:
        changed = False
        for index in range(len(items) - 1, -1, -1):
            after = set().union(*(live_in[i] for i in graph.instruction_successors[index]))
            item = items[index]
            definition = _dead_candidate(item)
            if definition is not None and _key(definition) not in after:
                before = after
            else:
                before = (after - ({_key(definition)} if definition is not None else set())) | _uses(item)
            if before != live_in[index] or after != live_out[index]:
                live_in[index], live_out[index] = before, after
                changed = True
    keep = [item for index, item in enumerate(items) if not (
        _dead_candidate(item) is not None
        and _key(_dead_candidate(item)) not in live_out[index]
    )]
    return replace(routine, instructions=tuple(keep))


def _dead_code(routine):
    current = routine
    for _ in range(len(routine.instructions) + 1):
        updated = _dead_once(current)
        if len(updated.instructions) == len(current.instructions):
            return current
        current = updated
    raise OptimizationError("dead-code elimination exceeded its pass limit")


def _unreachable(routine):
    graph = analyze_routine(routine)
    return replace(routine, instructions=tuple(item for index, item in enumerate(
        routine.instructions) if index in graph.reachable))


_PASSES: tuple[tuple[str, Callable], ...] = (
    ("unreachable", _unreachable),
    ("global_constant_propagation_and_folding", _propagate_fold),
    ("constant_branch_and_loop_pruning", _unreachable),
    ("local_expression_dag_cse", _local_dag_cse),
    ("dead_code_and_copy_cleanup", _dead_code),
    ("final_unreachable_cleanup", _unreachable),
)


def optimize_program(ir_program: IRProgram, analysis: AnalysisResult | None = None) -> IRProgram:
    """Return a new verified canonical program, leaving the input untouched."""
    if not isinstance(ir_program, IRProgram):
        raise OptimizationError("a complete IRProgram is required")
    if analysis is not None and (not isinstance(analysis, AnalysisResult)
                                 or ir_program.semantic_owner is not analysis):
        raise OptimizationError("analysis must be the exact owning AnalysisResult")
    try:
        verify_program(ir_program)
        current = ir_program
        for _, operation in _PASSES:
            functions = tuple(replace(function, body=operation(function.body))
                              for function in current.functions)
            current = replace(current, functions=functions, entry=operation(current.entry))
            verify_program(current)
        return current
    except (TypeError, ValueError, RecursionError) as exc:
        raise OptimizationError("cannot produce a verified optimized program") from exc


def pass_names() -> tuple[str, ...]:
    return tuple(name for name, _ in _PASSES)
