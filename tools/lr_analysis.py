"""Deterministic LR-family teaching checker for three small fixed grammars.

No Sparq source is parsed here; this is separate from the production compiler.
Run ``python -m tools.lr_analysis --write-doc`` or ``--check-doc``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


DOCUMENT = Path(__file__).resolve().parents[1] / "docs" / "LR_DEMONSTRATIONS.md"
START_MARKER = "<!-- Computed LR(0)/SLR(1) results: start -->"
END_MARKER = "<!-- Computed LR(0)/SLR(1) results: end -->"
LR1_START_MARKER = "<!-- Computed CLR(1)/LALR(1) results: start -->"
LR1_END_MARKER = "<!-- Computed CLR(1)/LALR(1) results: end -->"
END = "$"
EPSILON = "ε"


@dataclass(frozen=True)
class Production:
    identifier: str
    lhs: str
    rhs: tuple[str, ...]


@dataclass(frozen=True)
class Grammar:
    name: str
    productions: tuple[Production, ...]

    @property
    def nonterminals(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(p.lhs for p in self.productions))

    @property
    def terminals(self) -> tuple[str, ...]:
        names = set(self.nonterminals)
        return tuple(dict.fromkeys(
            symbol for p in self.productions for symbol in p.rhs if symbol not in names
        ))

    @property
    def symbols(self) -> tuple[str, ...]:
        # BFS visits terminal edges first, then nonterminal edges, each in
        # first-occurrence/first-definition order. This fixes state IDs.
        return self.terminals + self.nonterminals[1:]


@dataclass(frozen=True, order=True)
class Item:
    production: int
    dot: int


@dataclass(frozen=True, order=True)
class LR1Item:
    production: int
    dot: int
    lookahead: str

    @property
    def core(self) -> Item:
        return Item(self.production, self.dot)


@dataclass(frozen=True)
class Action:
    kind: str  # shift, reduce, accept
    target: int | None = None  # state for shift, production index for reduce

    def label(self) -> str:
        return {"shift": "s", "reduce": "r", "accept": "acc"}[self.kind] + (
            "" if self.target is None else str(self.target)
        )


@dataclass(frozen=True)
class Table:
    actions: dict[tuple[int, str], tuple[Action, ...]]
    gotos: dict[tuple[int, str], int]

    @property
    def conflicts(self) -> dict[tuple[int, str], tuple[Action, ...]]:
        return {cell: actions for cell, actions in self.actions.items() if len(actions) > 1}


@dataclass(frozen=True)
class Analysis:
    grammar: Grammar
    states: tuple[frozenset[Item], ...]
    transitions: dict[tuple[int, str], int]
    follow: dict[str, frozenset[str]]
    lr0: Table
    slr: Table


@dataclass(frozen=True)
class LR1Automaton:
    grammar: Grammar
    states: tuple[frozenset[LR1Item], ...]
    transitions: dict[tuple[int, str], int]
    table: Table


@dataclass(frozen=True)
class LR1Analysis:
    grammar: Grammar
    canonical: LR1Automaton
    lalr: LR1Automaton
    merged_from: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class TraceStep:
    number: int
    states: tuple[int, ...]
    symbols: tuple[str, ...]
    remaining: tuple[str, ...]
    action: str
    production: str = ""
    goto: str = ""


@dataclass(frozen=True)
class Trace:
    steps: tuple[TraceStep, ...]
    accepted: bool


G0 = Grammar("G0", (
    Production("P0", "S'", ("S",)),
    Production("P1", "S", ("id", "=", "V", ";")),
    Production("P2", "V", ("id",)),
    Production("P3", "V", ("int",)),
))

G1 = Grammar("G1", (
    Production("P0", "S'", ("S",)),
    Production("P1", "S", ("L", "=", "R")),
    Production("P2", "S", ("R",)),
    Production("P3", "L", ("*", "R")),
    Production("P4", "L", ("id",)),
    Production("P5", "R", ("L",)),
))

G2 = Grammar("G2", (
    Production("P0", "S'", ("S",)),
    Production("P1", "S", ("a", "B", "c")),
    Production("P2", "S", ("b", "C", "c")),
    Production("P3", "S", ("a", "C", "d")),
    Production("P4", "S", ("b", "B", "d")),
    Production("P5", "B", ("e",)),
    Production("P6", "C", ("e",)),
))


def closure(grammar: Grammar, seeds: frozenset[Item]) -> frozenset[Item]:
    """Add dot-at-start productions after every dot-before-nonterminal."""
    result = set(seeds)
    while True:
        additions = set()
        for item in result:
            rhs = grammar.productions[item.production].rhs
            if item.dot < len(rhs):
                symbol = rhs[item.dot]
                additions.update(
                    Item(index, 0) for index, p in enumerate(grammar.productions)
                    if p.lhs == symbol
                )
        if additions <= result:
            return frozenset(result)
        result |= additions


def goto(grammar: Grammar, state: frozenset[Item], symbol: str) -> frozenset[Item]:
    """Advance the dot over symbol, then close the resulting item set."""
    moved = frozenset(
        Item(item.production, item.dot + 1) for item in state
        if item.dot < len(grammar.productions[item.production].rhs)
        and grammar.productions[item.production].rhs[item.dot] == symbol
    )
    return closure(grammar, moved) if moved else frozenset()


def collection(grammar: Grammar) -> tuple[tuple[frozenset[Item], ...], dict[tuple[int, str], int]]:
    """Breadth-first canonical collection in Grammar.symbols edge order."""
    initial = closure(grammar, frozenset({Item(0, 0)}))
    states = [initial]
    numbers = {initial: 0}
    transitions: dict[tuple[int, str], int] = {}
    cursor = 0
    while cursor < len(states):
        for symbol in grammar.symbols:
            target = goto(grammar, states[cursor], symbol)
            if not target:
                continue
            if target not in numbers:
                numbers[target] = len(states)
                states.append(target)
            transitions[cursor, symbol] = numbers[target]
        cursor += 1
    return tuple(states), transitions


def follow_sets(grammar: Grammar) -> dict[str, frozenset[str]]:
    """FOLLOW fixed point for these nonnullable teaching grammars."""
    names = set(grammar.nonterminals)
    if any(not p.rhs for p in grammar.productions):
        raise ValueError("These teaching grammars must have no epsilon productions")
    first: dict[str, set[str]] = {name: set() for name in names}
    while True:
        before = sum(map(len, first.values()))
        for p in grammar.productions:
            initial = p.rhs[0]
            first[p.lhs] |= first[initial] if initial in names else {initial}
        if sum(map(len, first.values())) == before:
            break
    follow: dict[str, set[str]] = {name: set() for name in names}
    follow[grammar.productions[0].lhs].add(END)
    while True:
        before = sum(map(len, follow.values()))
        for p in grammar.productions:
            for index, symbol in enumerate(p.rhs):
                if symbol not in names:
                    continue
                if index + 1 < len(p.rhs):
                    successor = p.rhs[index + 1]
                    follow[symbol] |= first[successor] if successor in names else {successor}
                else:
                    follow[symbol] |= follow[p.lhs]
        if sum(map(len, follow.values())) == before:
            return {name: frozenset(values) for name, values in follow.items()}


def build_table(
    grammar: Grammar, states: tuple[frozenset[Item], ...],
    transitions: dict[tuple[int, str], int], follow: dict[str, frozenset[str]],
    *, slr: bool,
) -> Table:
    """Retain all distinct action candidates in each cell."""
    actions: dict[tuple[int, str], list[Action]] = {}
    gotos: dict[tuple[int, str], int] = {}

    def add(cell: tuple[int, str], action: Action) -> None:
        choices = actions.setdefault(cell, [])
        if action not in choices:
            choices.append(action)

    for (state, symbol), target in transitions.items():
        if symbol in grammar.terminals:
            add((state, symbol), Action("shift", target))
        else:
            gotos[state, symbol] = target
    for state, items in enumerate(states):
        for item in sorted(items):
            p = grammar.productions[item.production]
            if item.dot != len(p.rhs):
                continue
            if item.production == 0:
                add((state, END), Action("accept"))
            else:
                lookaheads = follow[p.lhs] if slr else grammar.terminals + (END,)
                for terminal in lookaheads:
                    add((state, terminal), Action("reduce", item.production))
    return _freeze_table(actions, gotos)


def _freeze_table(
    actions: dict[tuple[int, str], list[Action]], gotos: dict[tuple[int, str], int]
) -> Table:
    """Order distinct competing actions without discarding conflicts."""
    return Table(
        {cell: tuple(sorted(choices, key=lambda a: (
            {"shift": 0, "reduce": 1, "accept": 2}[a.kind], a.target or 0
        ))) for cell, choices in actions.items()},
        gotos,
    )


def analyze(grammar: Grammar) -> Analysis:
    states, transitions = collection(grammar)
    follow = follow_sets(grammar)
    return Analysis(
        grammar, states, transitions, follow,
        build_table(grammar, states, transitions, follow, slr=False),
        build_table(grammar, states, transitions, follow, slr=True),
    )


def first_sequence_lr1(
    sequence: tuple[str, ...], first: dict[str, set[str] | frozenset[str]],
    nonterminals: set[str],
) -> set[str]:
    """FIRST of a sequence, including ε only when the whole sequence vanishes."""
    result: set[str] = set()
    for symbol in sequence:
        if symbol not in nonterminals:
            result.add(symbol)
            return result
        result |= set(first[symbol]) - {EPSILON}
        if EPSILON not in first[symbol]:
            return result
    result.add(EPSILON)
    return result


def first_sets_lr1(grammar: Grammar) -> dict[str, frozenset[str]]:
    """Fixed-point FIRST sets, including nullable nonterminals."""
    names = set(grammar.nonterminals)
    first: dict[str, set[str]] = {name: set() for name in names}
    while True:
        changed = False
        for p in grammar.productions:
            before = len(first[p.lhs])
            first[p.lhs] |= first_sequence_lr1(p.rhs, first, names)
            changed |= len(first[p.lhs]) != before
        if not changed:
            return {name: frozenset(values) for name, values in first.items()}


def closure_lr1(
    grammar: Grammar, seeds: frozenset[LR1Item],
    first: dict[str, frozenset[str]] | None = None,
) -> frozenset[LR1Item]:
    """For [A→α•Bβ,a], add [B→•γ,b] for each b in FIRST(βa)."""
    if first is None:
        first = first_sets_lr1(grammar)
    names = set(grammar.nonterminals)
    result = set(seeds)
    while True:
        additions: set[LR1Item] = set()
        for item in result:
            rhs = grammar.productions[item.production].rhs
            if item.dot == len(rhs) or rhs[item.dot] not in names:
                continue
            symbol = rhs[item.dot]
            lookaheads = first_sequence_lr1(rhs[item.dot + 1:] + (item.lookahead,), first, names)
            if EPSILON in lookaheads:
                raise ValueError("LR(1) closure needs a terminal lookahead")
            additions.update(
                LR1Item(index, 0, lookahead)
                for index, p in enumerate(grammar.productions) if p.lhs == symbol
                for lookahead in lookaheads
            )
        if additions <= result:
            return frozenset(result)
        result |= additions


def goto_lr1(
    grammar: Grammar, state: frozenset[LR1Item], symbol: str,
    first: dict[str, frozenset[str]] | None = None,
) -> frozenset[LR1Item]:
    """Move the dot over X while retaining each item's lookahead, then close."""
    moved = frozenset(
        LR1Item(item.production, item.dot + 1, item.lookahead) for item in state
        if item.dot < len(grammar.productions[item.production].rhs)
        and grammar.productions[item.production].rhs[item.dot] == symbol
    )
    return closure_lr1(grammar, moved, first) if moved else frozenset()


def collection_lr1(
    grammar: Grammar,
) -> tuple[tuple[frozenset[LR1Item], ...], dict[tuple[int, str], int]]:
    """Breadth-first LR(1) collection using the existing grammar symbol order."""
    first = first_sets_lr1(grammar)
    initial = closure_lr1(grammar, frozenset({LR1Item(0, 0, END)}), first)
    states = [initial]
    numbers = {initial: 0}
    transitions: dict[tuple[int, str], int] = {}
    cursor = 0
    while cursor < len(states):
        for symbol in grammar.symbols:
            target = goto_lr1(grammar, states[cursor], symbol, first)
            if not target:
                continue
            if target not in numbers:
                numbers[target] = len(states)
                states.append(target)
            transitions[cursor, symbol] = numbers[target]
        cursor += 1
    return tuple(states), transitions


def lr0_core(state: frozenset[LR1Item]) -> frozenset[Item]:
    return frozenset(item.core for item in state)


def merge_lr1_cores(
    states: tuple[frozenset[LR1Item], ...],
    transitions: dict[tuple[int, str], int],
) -> tuple[
    tuple[frozenset[LR1Item], ...], dict[tuple[int, str], int],
    tuple[tuple[int, ...], ...],
]:
    """Union lookaheads for identical cores; reject inconsistent redirects."""
    groups: list[list[int]] = []
    by_core: dict[frozenset[Item], int] = {}
    old_to_new: dict[int, int] = {}
    for old, state in enumerate(states):
        core = lr0_core(state)
        if core not in by_core:
            by_core[core] = len(groups)
            groups.append([])
        new = by_core[core]
        groups[new].append(old)
        old_to_new[old] = new
    merged = tuple(frozenset().union(*(states[old] for old in group)) for group in groups)
    redirected: dict[tuple[int, str], int] = {}
    for (old, symbol), target in transitions.items():
        edge = old_to_new[old], symbol
        new_target = old_to_new[target]
        if edge in redirected and redirected[edge] != new_target:
            raise ValueError(f"Inconsistent LALR transition {edge}: "
                             f"{redirected[edge]} versus {new_target}")
        redirected[edge] = new_target
    return merged, redirected, tuple(tuple(group) for group in groups)


def build_lr1_table(
    grammar: Grammar, states: tuple[frozenset[LR1Item], ...],
    transitions: dict[tuple[int, str], int],
) -> Table:
    actions: dict[tuple[int, str], list[Action]] = {}
    gotos: dict[tuple[int, str], int] = {}

    def add(cell: tuple[int, str], action: Action) -> None:
        choices = actions.setdefault(cell, [])
        if action not in choices:
            choices.append(action)

    for (state, symbol), target in transitions.items():
        if symbol in grammar.terminals:
            add((state, symbol), Action("shift", target))
        else:
            gotos[state, symbol] = target
    for state, items in enumerate(states):
        for item in sorted(items):
            p = grammar.productions[item.production]
            if item.dot != len(p.rhs):
                continue
            if item.production == 0:
                if item.lookahead != END:
                    raise ValueError("Augmented LR(1) item needs $ lookahead")
                add((state, END), Action("accept"))
            else:
                add((state, item.lookahead), Action("reduce", item.production))
    return _freeze_table(actions, gotos)


def analyze_lr1(grammar: Grammar) -> LR1Analysis:
    states, transitions = collection_lr1(grammar)
    merged, redirected, groups = merge_lr1_cores(states, transitions)
    return LR1Analysis(
        grammar,
        LR1Automaton(grammar, states, transitions, build_lr1_table(grammar, states, transitions)),
        LR1Automaton(grammar, merged, redirected, build_lr1_table(grammar, merged, redirected)),
        groups,
    )


def trace(analysis: Analysis | LR1Automaton, table: Table, tokens: tuple[str, ...]) -> Trace:
    """Run a conflict-free teaching table; stop at errors or unresolved conflicts."""
    if not tokens or tokens[-1] != END or END in tokens[:-1]:
        raise ValueError("Input needs exactly one final $ marker")
    states = [0]
    symbols: list[str] = []
    position = 0
    steps: list[TraceStep] = []
    for number in range(1, 1000):
        lookahead = tokens[position]
        choices = table.actions.get((states[-1], lookahead), ())
        snapshot = (number, tuple(states), tuple(symbols), tokens[position:])
        if not choices:
            steps.append(TraceStep(*snapshot, "error: empty ACTION cell"))
            return Trace(tuple(steps), False)
        if len(choices) > 1:
            labels = "/".join(action.label() for action in choices)
            steps.append(TraceStep(*snapshot, f"conflict: {labels}"))
            return Trace(tuple(steps), False)
        action = choices[0]
        if action.kind == "shift":
            assert action.target is not None and lookahead != END
            steps.append(TraceStep(*snapshot, action.label()))
            symbols.append(lookahead)
            states.append(action.target)
            position += 1
        elif action.kind == "reduce":
            assert action.target is not None
            p = analysis.grammar.productions[action.target]
            width = len(p.rhs)
            if width:
                if tuple(symbols[-width:]) != p.rhs:
                    raise ValueError("Reduction does not match the symbol stack")
                del symbols[-width:]
                del states[-width:]
            target = table.gotos.get((states[-1], p.lhs))
            if target is None:
                raise ValueError("Missing GOTO after reduction")
            steps.append(TraceStep(*snapshot, action.label(), p.identifier, str(target)))
            symbols.append(p.lhs)
            states.append(target)
        else:
            assert lookahead == END and action.kind == "accept"
            steps.append(TraceStep(*snapshot, "accept"))
            return Trace(tuple(steps), True)
    raise ValueError("Teaching trace exceeded step limit")


def _item_text(grammar: Grammar, item: Item) -> str:
    p = grammar.productions[item.production]
    rhs = list(p.rhs)
    rhs.insert(item.dot, "•")
    return f"{p.identifier} {p.lhs} → {' '.join(rhs)}"


def _table_text(
    analysis: Analysis | LR1Automaton, table: Table, *, prefix: str = "I",
    label_gotos: bool = False,
) -> str:
    grammar = analysis.grammar
    terminals = grammar.terminals + (END,)
    nonterminals = grammar.nonterminals[1:]
    lines = [
        "| State | " + " | ".join(f"ACTION `{x}`" for x in terminals)
        + " | " + " | ".join(f"GOTO `{x}`" for x in nonterminals) + " |",
        "|---:" + "|:---:" * (len(terminals) + len(nonterminals)) + "|",
    ]
    for state in range(len(analysis.states)):
        cells = ["/".join(a.label() for a in table.actions.get((state, t), ())) or "—"
                 for t in terminals]
        cells += [
            (f"{prefix}{table.gotos[state, nt]}" if label_gotos else str(table.gotos[state, nt]))
            if (state, nt) in table.gotos else "—"
            for nt in nonterminals
        ]
        lines.append(f"| {prefix}{state} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _trace_text(value: Trace) -> str:
    lines = ["| Step | State stack | Symbol stack | Remaining input | ACTION | Production | GOTO |",
             "|---:|---|---|---|---|---|---:|"]
    for step in value.steps:
        lines.append(
            f"| {step.number} | `{' '.join(map(str, step.states))}` | "
            f"`{' '.join(step.symbols) or '∅'}` | `{' '.join(step.remaining)}` | "
            f"{step.action} | {step.production or '—'} | {step.goto or '—'} |"
        )
    return "\n".join(lines)


def conflict_kind(actions: tuple[Action, ...]) -> str:
    """Name the competing action types in one populated ACTION cell."""
    kinds = {action.kind for action in actions}
    if {"shift", "reduce"} <= kinds:
        return "shift/reduce"
    if sum(action.kind == "reduce" for action in actions) > 1:
        return "reduce/reduce"
    return "other"


def _conflict_text(analysis: Analysis, table: Table) -> str:
    if not table.conflicts:
        return "No conflicting ACTION cells."
    lines = []
    for (state, terminal), choices in sorted(table.conflicts.items()):
        category = conflict_kind(choices)
        causes = []
        for action in choices:
            if action.kind == "shift":
                causes.extend(_item_text(analysis.grammar, item) for item in sorted(analysis.states[state])
                              if item.dot < len(analysis.grammar.productions[item.production].rhs)
                              and analysis.grammar.productions[item.production].rhs[item.dot] == terminal)
            elif action.kind == "reduce":
                causes.append(_item_text(analysis.grammar, Item(action.target, len(
                    analysis.grammar.productions[action.target].rhs))))
        lines.append(
            f"- `ACTION[I{state}, {terminal}]` = **{'/'.join(a.label() for a in choices)}** "
            f"({category}); responsible items: " + "; ".join(f"`{cause}`" for cause in causes) + "."
        )
    return "\n".join(lines)


def _section(analysis: Analysis) -> str:
    grammar = analysis.grammar
    lines = [f"## Computed {grammar.name} results", "", "### Productions", "",
             "| ID | Rule |", "|---|---|"]
    lines += [f"| {p.identifier} | `{p.lhs} → {' '.join(p.rhs)}` |"
              for p in grammar.productions]
    lines += ["", f"### Canonical LR(0) collection ({len(analysis.states)} states)", ""]
    for number, state in enumerate(analysis.states):
        lines.append(f"**I{number}**")
        lines.append("")
        lines += [f"- `{_item_text(grammar, item)}`" for item in sorted(state)]
        lines.append("")
    lines += ["### Complete DFA transitions", "", "| From | Symbol | To |",
              "|---|---|---|"]
    for (source, symbol), target in sorted(
        analysis.transitions.items(), key=lambda e: (e[0][0], grammar.symbols.index(e[0][1]))
    ):
        lines.append(f"| I{source} | `{symbol}` | I{target} |")
    lines += ["", "### FOLLOW sets for SLR(1)", "",
              "| Nonterminal | FOLLOW |", "|---|---|"]
    for name in grammar.nonterminals:
        lines.append(f"| `{name}` | " + ", ".join(f"`{s}`" for s in sorted(analysis.follow[name])) + " |")
    for method, table in (("LR(0)", analysis.lr0), ("SLR(1)", analysis.slr)):
        lines += ["", f"### Complete {method} ACTION/GOTO table", "",
                  "`sJ` shifts to state J, `rK` reduces by PK, `acc` accepts; "
                  "`—` is an error. Multiple actions in one cell are retained and separated by `/`.", "",
                  _table_text(analysis, table), "",
                  f"Conflicting ACTION cells: **{len(table.conflicts)}**.", "",
                  _conflict_text(analysis, table)]
    if grammar.name == "G0":
        valid = ("id", "=", "int", ";", END)
        invalid = ("id", "=", ";", END)
        for title, table, symbols in (
            ("LR(0) valid trace: `id = int ; $`", analysis.lr0, valid),
            ("SLR(1) valid trace: `id = int ; $`", analysis.slr, valid),
            ("LR(0) invalid trace: `id = ; $`", analysis.lr0, invalid),
            ("SLR(1) invalid trace: `id = ; $`", analysis.slr, invalid),
        ):
            result = trace(analysis, table, symbols)
            lines += ["", f"### {title}", "", _trace_text(result), "",
                      f"Result: **{'accepted' if result.accepted else 'rejected'}**."]
    return "\n".join(lines)


def render_computed(g0: Analysis, g1: Analysis) -> str:
    return _section(g0) + "\n\n" + _section(g1)


def _lr1_item_text(grammar: Grammar, item: LR1Item) -> str:
    return f"[{_item_text(grammar, item.core)}, {item.lookahead}]"


def _lr1_conflict_text(automaton: LR1Automaton, *, prefix: str) -> str:
    if not automaton.table.conflicts:
        return "No conflicting ACTION cells."
    lines = []
    for (state, terminal), choices in sorted(automaton.table.conflicts.items()):
        causes = []
        for action in choices:
            if action.kind == "shift":
                causes.extend(
                    _lr1_item_text(automaton.grammar, item)
                    for item in sorted(automaton.states[state])
                    if item.dot < len(automaton.grammar.productions[item.production].rhs)
                    and automaton.grammar.productions[item.production].rhs[item.dot] == terminal
                )
            elif action.kind == "reduce":
                causes.extend(
                    _lr1_item_text(automaton.grammar, item)
                    for item in sorted(automaton.states[state])
                    if item.production == action.target
                    and item.dot == len(automaton.grammar.productions[item.production].rhs)
                    and item.lookahead == terminal
                )
        lines.append(
            f"- `ACTION[{prefix}{state}, {terminal}]` = **{'/'.join(a.label() for a in choices)}** "
            f"({conflict_kind(choices)}); responsible items: "
            + "; ".join(f"`{cause}`" for cause in causes) + "."
        )
    return "\n".join(lines)


def _lr1_trace_text(value: Trace, grammar: Grammar, *, prefix: str) -> str:
    lines = [
        "| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |",
        "|---:|---|---|---|---|---|---|---:|---:|",
    ]
    for step in value.steps:
        state = step.states[-1]
        lookahead = step.remaining[0]
        shifted = f"`{lookahead}`" if step.action.startswith("s") else "—"
        popped = str(len(grammar.productions[int(step.production[1:])].rhs)) if step.production else "—"
        lines.append(
            f"| {step.number} | `{' '.join(map(str, step.states))}` | "
            f"`{' '.join(step.symbols) or '∅'}` | `{' '.join(step.remaining)}` | "
            f"`ACTION[{prefix}{state}, {lookahead}]` → {step.action} | {shifted} | "
            f"{step.production or '—'} | {popped} | "
            f"{prefix + step.goto if step.goto else '—'} |"
        )
    return "\n".join(lines)


def _lr1_automaton_text(automaton: LR1Automaton, *, label: str) -> str:
    grammar = automaton.grammar
    prefix = "I" if label == "CLR(1)" else "J"
    lines = [f"### Complete {label} item collection ({len(automaton.states)} states)", ""]
    for number, state in enumerate(automaton.states):
        lines += [f"**{prefix}{number}**", ""]
        lines += [f"- `{_lr1_item_text(grammar, item)}`" for item in sorted(state)]
        lines.append("")
    lines += [f"### Complete {label} DFA transitions", "", "| From | Symbol | To |",
              "|---|---|---|"]
    for (source, symbol), target in sorted(
        automaton.transitions.items(),
        key=lambda edge: (edge[0][0], grammar.symbols.index(edge[0][1])),
    ):
        lines.append(f"| {prefix}{source} | `{symbol}` | {prefix}{target} |")
    lines += ["", f"### Complete {label} ACTION/GOTO table", "",
              "`sJ` shifts to J; `rK` reduces by PK; `acc` accepts; `—` is "
              "an error. Multiple candidate actions remain visible, separated by `/`.", "",
              _table_text(automaton, automaton.table, prefix=prefix, label_gotos=True), "",
              f"Conflicting ACTION cells: **{len(automaton.table.conflicts)}**.", "",
              _lr1_conflict_text(automaton, prefix=prefix)]
    return "\n".join(lines)


def _lr1_trace_section(
    automaton: LR1Automaton, title: str, tokens: tuple[str, ...],
    *, expected: str, prefix: str,
) -> str:
    result = trace(automaton, automaton.table, tokens)
    actual = ("accepted" if result.accepted else
              "stopped at conflict" if result.steps[-1].action.startswith("conflict:") else
              "rejected")
    if actual != expected:
        raise ValueError(f"Unexpected {title} outcome: {actual}")
    return "\n".join([
        f"### {title}", "", _lr1_trace_text(result, automaton.grammar, prefix=prefix), "",
        f"Result: **{actual}**.",
    ])


def _lr1_section(analysis: LR1Analysis) -> str:
    grammar = analysis.grammar
    lines = [f"## Computed {grammar.name} CLR(1) and LALR(1) results", "",
             "### Production IDs", "", "| ID | Rule |", "|---|---|"]
    lines += [f"| {p.identifier} | `{p.lhs} → {' '.join(p.rhs) or EPSILON}` |"
              for p in grammar.productions]
    lines += ["", _lr1_automaton_text(analysis.canonical, label="CLR(1)"), "",
              "### Identical-core groups and LALR(1) numbering", "",
              "Merged state Jk has ID k; canonical states are Ik. Groups are "
              "listed in first canonical-state appearance order.", "",
              "| Merged state | Canonical source states | LR(0) core items |",
              "|---|---|---|"]
    for number, sources in enumerate(analysis.merged_from):
        core = lr0_core(analysis.canonical.states[sources[0]])
        lines.append(
            f"| J{number} | " + ", ".join(f"I{source}" for source in sources)
            + " | " + "<br>".join(f"`{_item_text(grammar, item)}`" for item in sorted(core))
            + " |"
        )
    lines += ["", _lr1_automaton_text(analysis.lalr, label="LALR(1)"), ""]
    if grammar.name == "G1":
        cases = (
            (analysis.canonical, "G1 CLR(1) valid: `id = id $`", ("id", "=", "id", END), "accepted"),
            (analysis.lalr, "G1 LALR(1) valid: `id = id $`", ("id", "=", "id", END), "accepted"),
            (analysis.canonical, "G1 CLR(1) dereference: `* id = id $`", ("*", "id", "=", "id", END), "accepted"),
            (analysis.lalr, "G1 LALR(1) dereference: `* id = id $`", ("*", "id", "=", "id", END), "accepted"),
            (analysis.canonical, "G1 CLR(1) invalid: `id = $`", ("id", "=", END), "rejected"),
            (analysis.lalr, "G1 LALR(1) invalid: `id = $`", ("id", "=", END), "rejected"),
        )
    else:
        cases = (
            (analysis.canonical, "G2 CLR(1) valid: `a e c $`", ("a", "e", "c", END), "accepted"),
            (analysis.canonical, "G2 CLR(1) valid: `b e c $`", ("b", "e", "c", END), "accepted"),
            (analysis.canonical, "G2 CLR(1) invalid: `a e $`", ("a", "e", END), "rejected"),
            (analysis.lalr, "G2 LALR(1) unresolved: `a e c $`", ("a", "e", "c", END), "stopped at conflict"),
        )
    for automaton, title, tokens, expected in cases:
        prefix = "I" if automaton is analysis.canonical else "J"
        lines += [_lr1_trace_section(automaton, title, tokens, expected=expected, prefix=prefix), ""]
    return "\n".join(lines).rstrip()


def render_lr1_computed(g1: LR1Analysis, g2: LR1Analysis) -> str:
    return _lr1_section(g1) + "\n\n" + _lr1_section(g2)


def document_with_computed(document: str, computed: str) -> str:
    if document.count(START_MARKER) != 1 or document.count(END_MARKER) != 1:
        raise ValueError("Document needs exactly one generated-section marker pair")
    prefix, rest = document.split(START_MARKER)
    _, suffix = rest.split(END_MARKER)
    return prefix + START_MARKER + "\n" + computed + "\n" + END_MARKER + suffix


def document_with_lr1_computed(document: str, computed: str) -> str:
    if document.count(LR1_START_MARKER) != 1 or document.count(LR1_END_MARKER) != 1:
        raise ValueError("Document needs exactly one CLR/LALR marker pair")
    prefix, rest = document.split(LR1_START_MARKER)
    _, suffix = rest.split(LR1_END_MARKER)
    return prefix + LR1_START_MARKER + "\n" + computed + "\n" + LR1_END_MARKER + suffix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write-doc", action="store_true")
    group.add_argument("--check-doc", action="store_true")
    options = parser.parse_args()
    g0, g1 = analyze(G0), analyze(G1)
    g1_lr1, g2_lr1 = analyze_lr1(G1), analyze_lr1(G2)
    if options.write_doc or options.check_doc:
        before = DOCUMENT.read_text(encoding="utf-8")
        expected = document_with_computed(before, render_computed(g0, g1))
        expected = document_with_lr1_computed(expected, render_lr1_computed(g1_lr1, g2_lr1))
        if options.write_doc:
            DOCUMENT.write_text(expected, encoding="utf-8", newline="\n")
        elif before != expected:
            print("LR_DEMONSTRATIONS.md computed section is stale")
            return 1
    for result in (g0, g1):
        print(f"{result.grammar.name}: {len(result.states)} states; "
              f"LR(0) conflicts {len(result.lr0.conflicts)}; "
              f"SLR(1) conflicts {len(result.slr.conflicts)}")
    for result in (g1_lr1, g2_lr1):
        print(f"{result.grammar.name}: CLR(1) {len(result.canonical.states)} states, "
              f"{len(result.canonical.table.conflicts)} conflicts; "
              f"LALR(1) {len(result.lalr.states)} states, "
              f"{len(result.lalr.table.conflicts)} conflicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
