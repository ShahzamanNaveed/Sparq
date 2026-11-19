"""Complete, fail-fast program semantic analysis and its read-only result."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from sparq.ast_nodes import FunctionDecl, Program
from sparq.errors import LexicalError, SemanticError
from sparq.function_semantic import FunctionAnalysis, FunctionAnalyzer
from sparq.lexer import Lexer
from sparq.parser import ParseError, Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import StatementAnalysis, StatementAnalyzer
from sparq.symbols import FunctionSymbol, Scope, VariableSymbol


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    """Session-local lexical identity and declared symbols, detached from Scope."""

    id: int
    parent_id: int | None
    symbols: tuple[VariableSymbol, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.symbols, (list, tuple)):
            raise TypeError("scope symbols must be a list or tuple")
        object.__setattr__(self, "symbols", tuple(self.symbols))
        if (type(self.id) is not int or self.id < 1
                or self.parent_id is not None and (type(self.parent_id) is not int or self.parent_id < 1)
                or any(not isinstance(symbol, VariableSymbol) or symbol.scope_id != self.id
                       for symbol in self.symbols)
                or len({symbol.name for symbol in self.symbols}) != len(self.symbols)):
            raise ValueError("invalid scope snapshot")


def _scope_objects(functions: tuple[FunctionAnalysis, ...], start: StatementAnalysis) -> tuple[Scope, ...]:
    found: dict[int, Scope] = {}
    for body in (tuple(item.body for item in functions) + (start,)):
        for _, scope in body.scopes:
            found[scope.id] = scope
        for _, scope in body.repeat_scopes:
            found[scope.id] = scope
    for item in functions:
        found[item.scope.id] = item.scope
    pending = list(found.values())
    while pending:
        parent = pending.pop().parent
        if parent is not None and parent.id not in found:
            found[parent.id] = parent
            pending.append(parent)
    return tuple(scope for _, scope in sorted(found.items()))


def _scope_snapshots(functions: tuple[FunctionAnalysis, ...], start: StatementAnalysis) -> tuple[ScopeSnapshot, ...]:
    return tuple(
        ScopeSnapshot(scope.id, scope.parent.id if scope.parent else None,
                      tuple(scope._symbols.values()))
        for scope in _scope_objects(functions, start)
    )


@dataclass(frozen=True, slots=True, eq=False)
class AnalysisResult:
    """Complete program owner plus existing occurrence-specific semantic results."""

    program: Program
    signatures: tuple[FunctionSymbol, ...]
    functions: tuple[FunctionAnalysis, ...]
    start: StatementAnalysis
    start_scope: Scope
    scopes: tuple[ScopeSnapshot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.program, Program):
            raise TypeError("program AST is required")
        for name in ("signatures", "functions", "scopes"):
            value = getattr(self, name)
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"{name} must be a list or tuple")
            object.__setattr__(self, name, tuple(value))
        if (len(self.signatures) != len(self.program.functions)
                or len(self.functions) != len(self.program.functions)):
            raise ValueError("every function needs one signature and completed analysis")
        if (not isinstance(self.start, StatementAnalysis)
                or not isinstance(self.start_scope, Scope)
                or self.start.root is not self.program.main
                or self.start.function is not None
                or self.start.scope_of(self.program.main) is not self.start_scope
                or self.start_scope.parent is not None):
            raise ValueError("START result or root scope has the wrong owner")
        for declaration, signature, result in zip(
            self.program.functions, self.signatures, self.functions,
        ):
            if (not isinstance(signature, FunctionSymbol)
                    or not isinstance(result, FunctionAnalysis)
                    or signature.declaration is not declaration
                    or result.declaration is not declaration
                    or result.function is not signature
                    or result.scope.parent is not None):
                raise ValueError("function result or signature has the wrong owner")
        if (len({id(item) for item in self.signatures}) != len(self.signatures)
                or len({item.name for item in self.signatures}) != len(self.signatures)
                or len({item.id for item in self.signatures}) != len(self.signatures)):
            raise ValueError("function signatures must be distinct")
        if any(not isinstance(item, ScopeSnapshot) for item in self.scopes):
            raise TypeError("scope snapshots are required")
        by_id = {item.id: item for item in self.scopes}
        if len(by_id) != len(self.scopes):
            raise ValueError("scope identities must be unique")
        expected = _scope_snapshots(self.functions, self.start)
        if (self.scopes != expected
                or self.start_scope.id not in by_id
                or any(item.scope.id not in by_id for item in self.functions)
                or any(item.parent_id is not None and item.parent_id not in by_id
                       for item in self.scopes)):
            raise ValueError("scope snapshots do not match completed analyses")
        # Only a complete, validated program result finalizes the lower-level
        # scopes. Their public lookup APIs remain usable; declaration stops.
        for scope in _scope_objects(self.functions, self.start):
            scope._seal()

    def function_of(self, declaration: FunctionDecl) -> FunctionAnalysis | None:
        """Find by AST identity, never by an equal name or structural equality."""
        return next((item for item in self.functions if item.declaration is declaration), None)

    def signature_of(self, name: str) -> FunctionSymbol | None:
        return next((item for item in self.signatures if item.name == name), None)

    def scope_of(self, scope_id: int) -> ScopeSnapshot | None:
        return next((item for item in self.scopes if item.id == scope_id), None)


class SemanticAnalyzer:
    """Each analyze() call owns a fresh session; the Program AST is not copied."""

    def __init__(self, program: Program) -> None:
        if not isinstance(program, Program):
            raise TypeError("SemanticAnalyzer requires a Program AST")
        self.program = program

    def analyze(self) -> AnalysisResult:
        context = SemanticContext()
        try:
            context.collect_signatures(self.program)
            signatures = tuple(context.functions.require(item.name, item.span)
                               for item in self.program.functions)
            functions = tuple(FunctionAnalyzer(context).analyze_function(item)
                              for item in self.program.functions)
            start_scope = context.begin_start()
            try:
                start = StatementAnalyzer(context).analyze_block(self.program.main)
            finally:
                context.exit_scope()
            return AnalysisResult(self.program, signatures, functions, start,
                                  start_scope, _scope_snapshots(functions, start))
        except RecursionError as exc:
            raise SemanticError("RESOURCE_LIMIT", "program analysis exceeds the available stack",
                                self.program.span) from exc


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python -m sparq.program_semantic SOURCE.spq", file=sys.stderr)
        return 2
    try:
        source = Path(args[0]).read_text(encoding="utf-8")
        program = Parser(Lexer(source).tokenize()).parse()
        result = SemanticAnalyzer(program).analyze()
    except (OSError, UnicodeError, LexicalError, ParseError, SemanticError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Semantic analysis succeeded: {args[0]} | functions={len(result.functions)} | START valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
