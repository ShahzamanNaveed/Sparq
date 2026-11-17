"""Reproducible LL(1) analysis of the fenced BNF in the frozen Sparq spec.

This is a grammar teaching utility. It does not recognize Sparq source or
participate in the production compiler.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "SPARQ_LANGUAGE_SPEC.md"
DOCUMENT = ROOT / "docs" / "LL1_ANALYSIS.md"
EPSILON = "ε"
END_MARKER = "$"
GENERATED_START = "<!-- Computed grammar analysis: start -->"
GENERATED_END = "<!-- Computed grammar analysis: end -->"
NONTERMINAL = re.compile(r"<[^<>\s]+>")
DEFINITION = re.compile(r"^\s*(<[^<>\s]+>)\s*::=\s*(.*)$")
SYMBOL = re.compile(r'<[^<>\s]+>|"[^"\n]*"|[A-Z][A-Z0-9_]*|ε|\|')


@dataclass(frozen=True)
class Production:
    identifier: str
    lhs: str
    rhs: tuple[str, ...]
    source_line: int = 0


@dataclass(frozen=True)
class Grammar:
    start: str
    nonterminals: tuple[str, ...]
    terminals: tuple[str, ...]
    productions: tuple[Production, ...]
    bnf_sha256: str = ""


@dataclass(frozen=True)
class Analysis:
    grammar: Grammar
    nullable_rounds: tuple[frozenset[str], ...]
    first: dict[str, frozenset[str]]
    follow: dict[str, frozenset[str]]
    select: dict[str, frozenset[str]]
    table: dict[tuple[str, str], tuple[str, ...]]
    undefined: tuple[str, ...]
    unreachable: tuple[str, ...]
    unproductive: tuple[str, ...]
    duplicates: tuple[tuple[str, str], ...]

    @property
    def nullable(self) -> frozenset[str]:
        return self.nullable_rounds[-1]

    @property
    def conflicts(self) -> dict[tuple[str, str], tuple[str, ...]]:
        return {cell: ids for cell, ids in self.table.items() if len(ids) > 1}

    @property
    def conflicting_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            tuple(sorted(pair))
            for ids in self.conflicts.values()
            for pair in combinations(ids, 2)
        )


@dataclass(frozen=True)
class TraceStep:
    number: int
    stack: tuple[str, ...]
    remaining: tuple[str, ...]
    action: str


@dataclass(frozen=True)
class Trace:
    steps: tuple[TraceStep, ...]
    accepted: bool


def grammar_from_productions(
    productions: tuple[Production, ...], *, bnf_sha256: str = ""
) -> Grammar:
    """Build a grammar without assuming any historical symbol counts."""
    if not productions:
        raise ValueError("Grammar has no productions")
    nonterminals = tuple(dict.fromkeys(p.lhs for p in productions))
    terminals = tuple(sorted({
        symbol for p in productions for symbol in p.rhs
        if not NONTERMINAL.fullmatch(symbol)
    }))
    return Grammar(productions[0].lhs, nonterminals, terminals, productions, bnf_sha256)


def _bnf_fence(text: str) -> tuple[str, int]:
    openings = list(re.finditer(r"(?m)^~~~bnf\s*$", text))
    if len(openings) != 1:
        raise ValueError("Expected exactly one fenced BNF grammar")
    opening = openings[0]
    closing = re.search(r"(?m)^~~~\s*$", text[opening.end():])
    if closing is None:
        raise ValueError("BNF fence is not closed")
    body = text[opening.end():opening.end() + closing.start()].strip("\r\n")
    first_line = text[:opening.end()].count("\n") + 2
    return body, first_line


def _symbols(fragment: str) -> list[str]:
    found = []
    cursor = 0
    for match in SYMBOL.finditer(fragment):
        if fragment[cursor:match.start()].strip():
            raise ValueError(f"Unrecognized BNF text: {fragment[cursor:match.start()]!r}")
        raw = match.group()
        found.append(raw[1:-1] if raw.startswith('"') else raw)
        cursor = match.end()
    if fragment[cursor:].strip():
        raise ValueError(f"Unrecognized BNF text: {fragment[cursor:]!r}")
    return found


def extract_frozen_grammar(path: Path = SPEC) -> Grammar:
    """Read only the sole ~~~bnf fence, preserving alternative order."""
    body, first_line = _bnf_fence(path.read_text(encoding="utf-8"))
    productions: list[Production] = []
    lhs: str | None = None
    rhs: list[str] = []
    alternative_line = first_line

    def finish() -> None:
        if lhs is None:
            return
        if not rhs or (EPSILON in rhs and rhs != [EPSILON]):
            raise ValueError(f"Invalid or empty alternative for {lhs} at line {alternative_line}")
        productions.append(Production(
            f"P{len(productions) + 1:03d}", lhs,
            () if rhs == [EPSILON] else tuple(rhs), alternative_line,
        ))
        rhs.clear()

    for offset, line in enumerate(body.splitlines()):
        if not line.strip():
            continue
        definition = DEFINITION.match(line)
        if definition:
            if lhs is not None:
                finish()
            lhs = definition.group(1)
            fragment = definition.group(2)
        else:
            if lhs is None:
                raise ValueError(f"BNF continuation before a definition at line {first_line + offset}")
            fragment = line
        for symbol in _symbols(fragment):
            if symbol == "|":
                finish()
            else:
                if not rhs:
                    alternative_line = first_line + offset
                rhs.append(symbol)
    finish()
    grammar = grammar_from_productions(
        tuple(productions), bnf_sha256=sha256(body.encode("utf-8")).hexdigest()
    )
    _check_lexer_symbols(grammar)
    return grammar


def _check_lexer_symbols(grammar: Grammar) -> None:
    """Ensure BNF terminals have corresponding lexer token spellings."""
    from sparq.lexer import ONE_CHARACTER, TWO_CHARACTER
    from sparq.token import TokenType

    punctuation = set(ONE_CHARACTER) | set(TWO_CHARACTER)
    unknown = sorted(set(grammar.terminals) - punctuation - set(TokenType.__members__))
    if unknown:
        raise ValueError(f"BNF terminals absent from lexer token vocabulary: {unknown}")


def grammar_integrity(grammar: Grammar) -> tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]
]:
    defined = set(grammar.nonterminals)
    used = {s for p in grammar.productions for s in p.rhs if NONTERMINAL.fullmatch(s)}
    undefined = tuple(sorted(used - defined))
    reachable = {grammar.start}
    while True:
        more = {s for p in grammar.productions if p.lhs in reachable
                for s in p.rhs if NONTERMINAL.fullmatch(s)}
        if more <= reachable:
            break
        reachable |= more
    productive: set[str] = set()
    while True:
        more = {p.lhs for p in grammar.productions if all(
            not NONTERMINAL.fullmatch(s) or s in productive for s in p.rhs
        )}
        if more <= productive:
            break
        productive |= more
    seen: dict[tuple[str, tuple[str, ...]], str] = {}
    duplicates = []
    for p in grammar.productions:
        key = p.lhs, p.rhs
        if key in seen:
            duplicates.append((seen[key], p.identifier))
        else:
            seen[key] = p.identifier
    return (
        undefined, tuple(sorted(defined - reachable)),
        tuple(sorted(defined - productive)), tuple(duplicates),
    )


def nullable_rounds(grammar: Grammar) -> tuple[frozenset[str], ...]:
    current = {p.lhs for p in grammar.productions if not p.rhs}
    rounds = [frozenset(current)]
    while True:
        more = {p.lhs for p in grammar.productions if all(
            NONTERMINAL.fullmatch(s) and s in current for s in p.rhs
        )}
        if more <= current:
            break
        current |= more
        rounds.append(frozenset(current))
    return tuple(rounds)


def first_sequence(
    sequence: tuple[str, ...], first: dict[str, set[str] | frozenset[str]],
    nullable: frozenset[str],
) -> set[str]:
    result: set[str] = set()
    for symbol in sequence:
        if not NONTERMINAL.fullmatch(symbol):
            result.add(symbol)
            break
        result |= set(first[symbol]) - {EPSILON}
        if symbol not in nullable:
            break
    else:
        result.add(EPSILON)
    return result


def first_sets(grammar: Grammar, nullable: frozenset[str]) -> dict[str, frozenset[str]]:
    first: dict[str, set[str]] = {name: set() for name in grammar.nonterminals}
    while True:
        changed = False
        for p in grammar.productions:
            before = len(first[p.lhs])
            first[p.lhs] |= first_sequence(p.rhs, first, nullable)
            changed |= len(first[p.lhs]) != before
        if not changed:
            return {name: frozenset(values) for name, values in first.items()}


def follow_sets(
    grammar: Grammar, nullable: frozenset[str], first: dict[str, frozenset[str]]
) -> dict[str, frozenset[str]]:
    follow: dict[str, set[str]] = {name: set() for name in grammar.nonterminals}
    follow[grammar.start].add(END_MARKER)
    while True:
        changed = False
        for p in grammar.productions:
            for index, symbol in enumerate(p.rhs):
                if not NONTERMINAL.fullmatch(symbol):
                    continue
                suffix_first = first_sequence(p.rhs[index + 1:], first, nullable)
                additions = suffix_first - {EPSILON}
                if EPSILON in suffix_first:
                    additions |= follow[p.lhs]
                before = len(follow[symbol])
                follow[symbol] |= additions
                changed |= len(follow[symbol]) != before
        if not changed:
            return {name: frozenset(values) for name, values in follow.items()}


def analyze(grammar: Grammar) -> Analysis:
    undefined, unreachable, unproductive, duplicates = grammar_integrity(grammar)
    if undefined:
        raise ValueError(f"Undefined nonterminals: {undefined}")
    rounds = nullable_rounds(grammar)
    first = first_sets(grammar, rounds[-1])
    follow = follow_sets(grammar, rounds[-1], first)
    select = {}
    table: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in grammar.productions:
        choices = first_sequence(p.rhs, first, rounds[-1])
        selected = choices - {EPSILON}
        if EPSILON in choices:
            selected |= follow[p.lhs]
        select[p.identifier] = frozenset(selected)
        for terminal in sorted(selected):
            table[p.lhs, terminal].append(p.identifier)
    return Analysis(
        grammar, rounds, first, follow, select,
        {cell: tuple(ids) for cell, ids in table.items()},
        undefined, unreachable, unproductive, duplicates,
    )


def predictive_trace(analysis: Analysis, input_symbols: tuple[str, ...]) -> Trace:
    """Trace grammar-symbol choices only; no source lexing or AST construction."""
    if not input_symbols or input_symbols[-1] != END_MARKER:
        raise ValueError("Predictive input must end with the conceptual $ marker")
    stack = [END_MARKER, analysis.grammar.start]
    by_id = {p.identifier: p for p in analysis.grammar.productions}
    steps = []
    position = 0
    while True:
        top = stack[-1]
        lookahead = input_symbols[position]
        before = tuple(stack)
        remaining = input_symbols[position:]
        if top == END_MARKER and lookahead == END_MARKER:
            action = "accept"
            accepted = True
        elif top in analysis.grammar.nonterminals:
            candidates = analysis.table.get((top, lookahead), ())
            if len(candidates) != 1:
                action = (f"error: M[{top}, {lookahead}] is empty" if not candidates
                          else f"conflict: M[{top}, {lookahead}] = {', '.join(candidates)}")
                accepted = False
            else:
                p = by_id[candidates[0]]
                stack.pop()
                stack.extend(reversed(p.rhs))
                action = f"{p.identifier}: {p.lhs} → {rhs_text(p.rhs)}"
                accepted = None
        elif top == lookahead:
            stack.pop()
            position += 1
            action = f"match {top}"
            accepted = None
        else:
            action = f"error: expected {top}, found {lookahead}"
            accepted = False
        steps.append(TraceStep(len(steps) + 1, before, remaining, action))
        if accepted is not None:
            return Trace(tuple(steps), accepted)
        if position >= len(input_symbols) or len(steps) > 10_000:
            raise ValueError("Predictive trace did not terminate")


def rhs_text(rhs: tuple[str, ...]) -> str:
    return " ".join(f'"{s}"' if s in {'(', ')', '{', '}', '[', ']', ';', ',', ':',
                                          '+', '-', '*', '/', '%', '=', '<', '>',
                                          '<=', '>=', '==', '!=', '->'} else s
                    for s in rhs) if rhs else EPSILON


def _code(value: str) -> str:
    return f"`{value}`"


def _set_text(values: set[str] | frozenset[str] | tuple[str, ...]) -> str:
    return "{ " + ", ".join(_code(s) for s in sorted(values)) + " }" if values else "∅"


def _trace_table(trace: Trace) -> str:
    lines = ["| Step | Stack (top at right) | Remaining input | Action |",
             "|---:|---|---|---|"]
    for step in trace.steps:
        lines.append(
            f"| {step.number} | {_code(' '.join(step.stack))} | "
            f"{_code(' '.join(step.remaining))} | {_code(step.action)} |"
        )
    return "\n".join(lines)


def render_computed(analysis: Analysis) -> str:
    grammar = analysis.grammar
    nullable = analysis.nullable
    valid = predictive_trace(analysis, ("START", "{", "}", "EOF", END_MARKER))
    invalid = predictive_trace(
        analysis, ("START", "{", "SHOW", "(", ")", ";", "}", "EOF", END_MARKER)
    )
    assert valid.accepted and not invalid.accepted
    lines = [
        "## Computed grammar inventory",
        "",
        f"BNF fence SHA-256 (UTF-8, normalized newlines): `{grammar.bnf_sha256}`.",
        f"Start symbol: {_code(grammar.start)}. Distinct nonterminals: "
        f"**{len(grammar.nonterminals)}**. Production alternatives: "
        f"**{len(grammar.productions)}**. Distinct grammar terminals: "
        f"**{len(grammar.terminals)}**.",
        "",
        "Nonterminals in first-definition order: " + ", ".join(_code(s) for s in grammar.nonterminals) + ".",
        "",
        "Terminals: " + ", ".join(_code(s) for s in grammar.terminals) + ".",
        "",
        f"The explicit {_code('EOF')} is a grammar terminal. The conceptual {_code('$')} "
        "is separate and occurs only as the end marker and in FOLLOW sets.",
        "",
        "Integrity checks: undefined " + _set_text(analysis.undefined)
        + "; unreachable " + _set_text(analysis.unreachable)
        + "; unproductive " + _set_text(analysis.unproductive)
        + "; duplicate production-ID pairs "
        + (", ".join(f"{a}/{b}" for a, b in analysis.duplicates) or "none") + ".",
        "",
        "## Nullable fixed point",
        "",
        "Initial set = left sides of explicit ε alternatives. Each later round adds "
        "A when every symbol of one of A's right sides is already nullable. "
        "Terminals never become nullable.",
        "",
    ]
    for number, values in enumerate(analysis.nullable_rounds):
        new = values - (analysis.nullable_rounds[number - 1] if number else frozenset())
        lines.append(f"- Round {number}: add {_set_text(new)}; cumulative {_set_text(values)}.")
    lines += ["", f"Final nullable count: **{len(nullable)}**.", "",
              "## Complete FIRST and FOLLOW sets", "",
              "FIRST includes ε exactly for nullable nonterminals. FOLLOW never includes ε.", "",
              "| Nonterminal | FIRST | FOLLOW |", "|---|---|---|"]
    for nt in grammar.nonterminals:
        lines.append(f"| {_code(nt)} | {_set_text(analysis.first[nt])} | {_set_text(analysis.follow[nt])} |")
    lines += ["", "## Alternatives and complete SELECT sets", "",
              "Each P identifier follows the exact alternative order of the frozen BNF. "
              "The source line is the line where the alternative begins. "
              "SELECT(A → α) = FIRST(α) − {ε}, plus FOLLOW(A) when α is nullable.", "",
              "| ID | Source line | Left side | Right side | FIRST(right side) | SELECT |",
              "|---|---:|---|---|---|---|"]
    for p in grammar.productions:
        first_rhs = first_sequence(p.rhs, analysis.first, nullable)
        lines.append(
            f"| {p.identifier} | {p.source_line} | {_code(p.lhs)} | "
            f"{_code(rhs_text(p.rhs))} | {_set_text(first_rhs)} | "
            f"{_set_text(analysis.select[p.identifier])} |"
        )
    lines += ["", "## Sparse predictive parsing table", "",
              "Each listed lookahead is one populated M[nonterminal, lookahead] cell. "
              "The value is the complete list of candidate production IDs; all unlisted cells "
              "are errors. Cells are grouped by row for readability.", "",
              "| Nonterminal | Populated lookahead → candidate IDs |", "|---|---|"]
    for nt in grammar.nonterminals:
        entries = [f"{_code(t)} → {', '.join(analysis.table[nt, t])}"
                   for t in sorted(grammar.terminals + (END_MARKER,))
                   if (nt, t) in analysis.table]
        lines.append(f"| {_code(nt)} | {'<br>'.join(entries) or 'none'} |")
    function_epsilon = analysis.table.get(("<function-list>", "START"), ())
    statement_epsilon = analysis.table.get(("<statement-list>", "}"), ())
    lines += ["", "Examples: "
              f"{_code('M[<function-list>, START]')} = {', '.join(function_epsilon)}; "
              f"{_code('M[<statement-list>, }]')} = {', '.join(statement_epsilon)}; "
              f"{_code('M[<expression>, )]')} is empty and therefore an error.", "",
              "## LL(1) conflict report", "",
              f"Populated cells: **{len(analysis.table)}**. "
              f"Conflicting cells: **{len(analysis.conflicts)}**. "
              f"Distinct conflicting production pairs: **{len(analysis.conflicting_pairs)}**.", ""]
    if analysis.conflicts:
        for (nt, terminal), ids in sorted(analysis.conflicts.items()):
            lines.append(f"- M[{nt}, {terminal}]: {', '.join(ids)}")
    else:
        lines.append("No predictive-table cell contains more than one production.")
    lines += ["", "## Predictive traces", "",
              "Stack top is displayed on the **right**. Input includes the explicit Sparq "
              "EOF token followed by the separate conceptual $ marker. "
              "These are grammar-symbol traces, not program execution or AST construction.", "",
              "### Valid: `START { } EOF $`", "", _trace_table(valid), "",
              f"Result: **{'accepted' if valid.accepted else 'rejected'}**.", "",
              "### Invalid: `START { SHOW ( ) ; } EOF $`", "", _trace_table(invalid), "",
              f"Result: **{'accepted' if invalid.accepted else 'rejected'}** at "
              f"{_code(invalid.steps[-1].action)}."]
    return "\n".join(lines)


def document_with_computed(document: str, computed: str) -> str:
    if document.count(GENERATED_START) != 1 or document.count(GENERATED_END) != 1:
        raise ValueError("Document needs exactly one generated-section marker pair")
    prefix, rest = document.split(GENERATED_START)
    _, suffix = rest.split(GENERATED_END)
    return prefix + GENERATED_START + "\n" + computed + "\n" + GENERATED_END + suffix


def main() -> int:
    options = argparse.ArgumentParser(description=__doc__)
    group = options.add_mutually_exclusive_group()
    group.add_argument("--write-doc", action="store_true", help="refresh only the marked computed section")
    group.add_argument("--check-doc", action="store_true", help="check the marked section without writing")
    args = options.parse_args()
    result = analyze(extract_frozen_grammar())
    if args.write_doc or args.check_doc:
        before = DOCUMENT.read_text(encoding="utf-8")
        expected = document_with_computed(before, render_computed(result))
        if args.write_doc:
            DOCUMENT.write_text(expected, encoding="utf-8", newline="\n")
        elif before != expected:
            print("LL1_ANALYSIS.md computed section is stale")
            return 1
    print(
        f"{len(result.grammar.nonterminals)} nonterminals, "
        f"{len(result.grammar.productions)} alternatives, "
        f"{len(result.nullable)} nullable, {len(result.table)} populated cells, "
        f"{len(result.conflicts)} conflicting cells"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
