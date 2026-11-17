"""Small operator-precedence recognizer for the illustrative E/T/F grammar.

This teaching utility does not parse Sparq source or build an AST. A reduced
substring keeps every nonterminal category it can derive, so unit productions
never require a manually selected promotion.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


RULES = (
    ("O1", "E", ("E", "+", "T")),
    ("O2", "E", ("T",)),
    ("O3", "T", ("T", "*", "F")),
    ("O4", "T", ("F",)),
    ("O5", "F", ("(", "E", ")")),
    ("O6", "F", ("id",)),
)
NONTERMINALS = frozenset({lhs for _, lhs, _ in RULES})
TERMINALS = ("id", "+", "*", "(", ")")
END = "$"
DOCUMENT = Path(__file__).resolve().parents[1] / "docs" / "PARSER_THEORY.md"
GENERATED_START = "<!-- Computed operator-precedence traces: start -->"
GENERATED_END = "<!-- Computed operator-precedence traces: end -->"
Category = frozenset[str]
StackSymbol = str | Category


@dataclass(frozen=True)
class Step:
    stack: tuple[StackSymbol, ...]
    remaining: tuple[str, ...]
    comparison: str
    action: str
    handle: tuple[StackSymbol, ...] = ()
    productions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Trace:
    steps: tuple[Step, ...]
    accepted: bool


def precedence_sets() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """Calculate FIRSTVT and LASTVT to a fixed point from O1-O6."""
    first = {name: set() for name in NONTERMINALS}
    last = {name: set() for name in NONTERMINALS}
    while True:
        before = ({name: values.copy() for name, values in first.items()},
                  {name: values.copy() for name, values in last.items()})
        for _, lhs, rhs in RULES:
            if rhs[0] in NONTERMINALS:
                first[lhs].update(first[rhs[0]])
                if len(rhs) > 1 and rhs[1] not in NONTERMINALS:
                    first[lhs].add(rhs[1])
            else:
                first[lhs].add(rhs[0])
            if rhs[-1] in NONTERMINALS:
                last[lhs].update(last[rhs[-1]])
                if len(rhs) > 1 and rhs[-2] not in NONTERMINALS:
                    last[lhs].add(rhs[-2])
            else:
                last[lhs].add(rhs[-1])
        if before == (first, last):
            return ({name: frozenset(values) for name, values in first.items()},
                    {name: frozenset(values) for name, values in last.items()})


def precedence_table() -> dict[tuple[str, str], str]:
    """Construct relations and reject any conflicting ordered terminal pair."""
    first, last = precedence_sets()
    candidates: dict[tuple[str, str], set[str]] = {}

    def add(left: str, right: str, relation: str) -> None:
        candidates.setdefault((left, right), set()).add(relation)

    for _, _, rhs in RULES:
        for index, symbol in enumerate(rhs):
            if index + 1 < len(rhs):
                next_symbol = rhs[index + 1]
                if symbol in NONTERMINALS and next_symbol not in NONTERMINALS:
                    for terminal in last[symbol]:
                        add(terminal, next_symbol, ">")
                elif symbol not in NONTERMINALS and next_symbol in NONTERMINALS:
                    for terminal in first[next_symbol]:
                        add(symbol, terminal, "<")
                elif symbol not in NONTERMINALS and next_symbol not in NONTERMINALS:
                    add(symbol, next_symbol, "=")
            if (index + 2 < len(rhs) and symbol not in NONTERMINALS
                    and rhs[index + 1] in NONTERMINALS
                    and rhs[index + 2] not in NONTERMINALS):
                add(symbol, rhs[index + 2], "=")
    for terminal in first["E"]:
        add(END, terminal, "<")
    for terminal in last["E"]:
        add(terminal, END, ">")
    add(END, END, "=")
    conflicts = {cell: values for cell, values in candidates.items() if len(values) != 1}
    if conflicts:
        raise ValueError(f"Conflicting precedence relations: {conflicts}")
    return {cell: next(iter(values)) for cell, values in candidates.items()}


def _unit_closure(categories: set[str]) -> tuple[Category, tuple[str, ...]]:
    """Keep all reachable LHS categories, recording every applied unit rule."""
    used = []
    while True:
        added = False
        for identifier, lhs, rhs in RULES:
            if len(rhs) == 1 and rhs[0] in NONTERMINALS and rhs[0] in categories:
                if lhs not in categories:
                    categories.add(lhs)
                    used.append(identifier)
                    added = True
        if not added:
            return frozenset(categories), tuple(used)


def _reduce_handle(handle: tuple[StackSymbol, ...]) -> tuple[Category, tuple[str, ...]]:
    direct = []
    categories = set()
    for identifier, lhs, rhs in RULES:
        if len(rhs) == 1 and rhs[0] in NONTERMINALS:
            continue  # Unit rules are applied only by fixed-point closure.
        if len(handle) != len(rhs):
            continue
        if all((required in actual if isinstance(actual, frozenset)
                else required == actual) for actual, required in zip(handle, rhs)):
            direct.append(identifier)
            categories.add(lhs)
    if not categories:
        return frozenset(), ()
    closed, units = _unit_closure(categories)
    return closed, tuple(direct) + units


def _handle_start(stack: list[StackSymbol], table: dict[tuple[str, str], str]) -> int:
    """Find the rightmost '<' between stack terminals; '=' stays in a handle."""
    right = next(i for i in range(len(stack) - 1, -1, -1)
                 if isinstance(stack[i], str))
    while right > 0:
        left = next(i for i in range(right - 1, -1, -1)
                    if isinstance(stack[i], str))
        relation = table.get((stack[left], stack[right]))
        if relation == "<":
            return left + 1
        if relation not in ("=", ">"):
            raise ValueError("No precedence boundary for stack handle")
        right = left
    raise ValueError("No precedence boundary for stack handle")


def parse(tokens: tuple[str, ...]) -> Trace:
    """Recognize token strings using precedence-guided shifts and reductions."""
    if not tokens or tokens[-1] != END or END in tokens[:-1]:
        raise ValueError("Input needs exactly one final $ marker")
    table = precedence_table()
    stack: list[StackSymbol] = [END]
    steps = []
    position = 0
    while True:
        lookahead = tokens[position]
        before = tuple(stack)
        remaining = tokens[position:]
        terminal = next(value for value in reversed(stack) if isinstance(value, str))
        relation = table.get((terminal, lookahead))
        comparison = f"{terminal} {relation or '?'} {lookahead}"
        if relation is None:
            steps.append(Step(before, remaining, comparison, "error: undefined relation"))
            return Trace(tuple(steps), False)
        if terminal == END and lookahead == END:
            accepted = (len(stack) == 2 and isinstance(stack[1], frozenset)
                        and "E" in stack[1])
            steps.append(Step(before, remaining, comparison,
                              "accept" if accepted else "error: incomplete expression"))
            return Trace(tuple(steps), accepted)
        if relation in ("<", "="):
            if lookahead not in TERMINALS:
                steps.append(Step(before, remaining, comparison, "error: invalid terminal"))
                return Trace(tuple(steps), False)
            steps.append(Step(before, remaining, comparison, f"shift {lookahead}"))
            stack.append(lookahead)
            position += 1
            continue
        try:
            start = _handle_start(stack, table)
        except ValueError:
            steps.append(Step(before, remaining, comparison, "error: no handle boundary"))
            return Trace(tuple(steps), False)
        handle = tuple(stack[start:])
        categories, productions = _reduce_handle(handle)
        if not categories:
            steps.append(Step(before, remaining, comparison,
                              "error: invalid handle", handle))
            return Trace(tuple(steps), False)
        steps.append(Step(before, remaining, comparison, "reduce", handle, productions))
        stack[start:] = [categories]


def display_symbol(symbol: StackSymbol) -> str:
    if isinstance(symbol, str):
        return symbol
    return "[" + "/".join(name for name in ("F", "T", "E") if name in symbol) + "]"


def trace_table(trace: Trace) -> str:
    """Render the recorded decisions as a compact Markdown table."""
    lines = ["| Step | Stack | Remaining input | Comparison | Action | Handle | Rules |",
             "|---:|---|---|---|---|---|---|"]
    for number, step in enumerate(trace.steps, 1):
        lines.append("| " + " | ".join((
            str(number), "`" + " ".join(map(display_symbol, step.stack)) + "`",
            "`" + " ".join(step.remaining) + "`", f"`{step.comparison}`",
            step.action, "`" + " ".join(map(display_symbol, step.handle)) + "`"
            if step.handle else "—", ", ".join(step.productions) or "—",
        )) + " |")
    return "\n".join(lines)


EXAMPLES = (
    ("Valid A: `id + id * id`", ("id", "+", "id", "*", "id", END)),
    ("Valid B: `( id + id ) * id`", ("(", "id", "+", "id", ")", "*", "id", END)),
    ("Valid C: `id * id + id`", ("id", "*", "id", "+", "id", END)),
    ("Invalid: `id + * id`", ("id", "+", "*", "id", END)),
)


def render_demonstrations() -> str:
    sections = []
    for heading, tokens in EXAMPLES:
        result = parse(tokens)
        sections.append(f"#### {heading}\n\n{trace_table(result)}\n\n"
                        f"Result: **{'accepted' if result.accepted else 'rejected'}**.")
    return "\n\n".join(sections)


def document_with_demonstrations(document: str) -> str:
    if document.count(GENERATED_START) != 1 or document.count(GENERATED_END) != 1:
        raise ValueError("Document needs exactly one precedence-trace marker pair")
    prefix, rest = document.split(GENERATED_START)
    _, suffix = rest.split(GENERATED_END)
    return prefix + GENERATED_START + "\n" + render_demonstrations() + "\n" + GENERATED_END + suffix


def main() -> int:
    options = argparse.ArgumentParser(description=__doc__)
    group = options.add_mutually_exclusive_group()
    group.add_argument("--check-doc", action="store_true")
    group.add_argument("--write-doc", action="store_true")
    args = options.parse_args()
    if args.check_doc or args.write_doc:
        before = DOCUMENT.read_text(encoding="utf-8")
        expected = document_with_demonstrations(before)
        if args.write_doc:
            DOCUMENT.write_text(expected, encoding="utf-8", newline="\n")
        elif before != expected:
            print("PARSER_THEORY.md precedence traces are stale")
            return 1
    print("30 precedence relations; four deterministic traces checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
