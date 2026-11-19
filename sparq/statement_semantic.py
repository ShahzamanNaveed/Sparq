"""Sparq statement semantics with identity-owned analysis records."""

from __future__ import annotations

from dataclasses import dataclass, field

from sparq.ast_nodes import (
    ArrayAccess, ArrayDecl, AssignStmt, Block, CallStmt, CaseClause,
    DoWhileStmt, Expr, ForStmt, LiteralExpr, ReadStmt, ReturnStmt,
    ScalarDecl, SelectStmt, ShowStmt, SourceSpan, Stmt, UnaryExpr, VarRef,
    WhenStmt, WhileStmt,
)
from sparq.errors import SemanticError
from sparq.semantic import (
    ArgumentConversionSite, CallAnalysis, ConversionSite, ExpressionAnalysis,
    ExpressionAnalyzer, SemanticContext,
)
from sparq.symbols import (
    FunctionSymbol, ScalarType, Scope, SymbolKind, VariableSymbol, VoidType,
)
from sparq.token import TokenType
from sparq.type_rules import Compatibility, assignment_compatibility


_DEFAULTS: dict[ScalarType, object] = {
    ScalarType.INT: 0,
    ScalarType.FLOAT: 0.0,
    ScalarType.CHAR: "\0",
    ScalarType.STRING: "",
    ScalarType.BOOL: False,
}
_DECLARED_TYPES = {
    TokenType.INT: ScalarType.INT,
    TokenType.FLOAT: ScalarType.FLOAT,
    TokenType.CHAR: ScalarType.CHAR,
    TokenType.STRING: ScalarType.STRING,
    TokenType.BOOL: ScalarType.BOOL,
}


def _declared_type(kind: TokenType) -> ScalarType:
    try:
        return _DECLARED_TYPES[kind]
    except (KeyError, TypeError) as exc:
        raise ValueError("declaration must have a scalar type") from exc


def _snapshot_pairs(value: object, name: str) -> tuple[tuple[object, object], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be a list or tuple")
    pairs = []
    for entry in value:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise TypeError(f"{name} entries must be two-item lists or tuples")
        pairs.append((entry[0], entry[1]))
    return tuple(pairs)


def _snapshot_records(value: object, name: str, kind: type) -> tuple:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be a list or tuple")
    records = tuple(value)
    if any(not isinstance(record, kind) for record in records):
        raise TypeError(f"{name} contains an invalid record")
    return records


def _case_value(label: LiteralExpr | UnaryExpr) -> tuple[ScalarType, object]:
    """Decode only the CASE literal shapes admitted by the grammar."""
    if isinstance(label, UnaryExpr):
        literal = label.operand
        if (label.operator is not TokenType.MINUS or not isinstance(literal, LiteralExpr)
                or literal.kind is not TokenType.INT_LITERAL or type(literal.value) is not int
                or literal.value < 0):
            raise ValueError("CASE label must be a signed integer literal")
        return ScalarType.INT, -literal.value
    if isinstance(label, LiteralExpr):
        expected = {
            TokenType.INT_LITERAL: (ScalarType.INT, int),
            TokenType.CHAR_LITERAL: (ScalarType.CHAR, str),
            TokenType.STRING_LITERAL: (ScalarType.STRING, str),
        }.get(label.kind)
        if (expected is not None and type(label.value) is expected[1]
                and (label.kind is not TokenType.INT_LITERAL or label.value >= 0)
                and (label.kind is not TokenType.CHAR_LITERAL or len(label.value) == 1)):
            return expected[0], label.value
    raise ValueError("CASE label must be an INT, CHAR, or STRING literal")


@dataclass(frozen=True, slots=True, eq=False)
class StatementConversionSite:
    """One INT-to-FLOAT use in a declaration or assignment."""

    parent: ScalarDecl | ArrayDecl | AssignStmt
    operand: Expr
    role: str  # "initializer", "element", or "value"
    source_type: ScalarType
    destination_type: ScalarType
    element_index: int | None = None

    def __post_init__(self) -> None:
        if self.source_type is not ScalarType.INT or self.destination_type is not ScalarType.FLOAT:
            raise ValueError("only INT-to-FLOAT conversion is supported")
        if isinstance(self.parent, ScalarDecl):
            valid = (self.role == "initializer" and self.element_index is None
                     and self.parent.initializer is self.operand)
            destination_is_float = _declared_type(self.parent.type_name) is ScalarType.FLOAT
        elif isinstance(self.parent, ArrayDecl):
            elements = self.parent.initializers
            valid = (self.role == "element" and type(self.element_index) is int
                     and elements is not None and 0 <= self.element_index < len(elements)
                     and elements[self.element_index] is self.operand)
            destination_is_float = _declared_type(self.parent.element_type) is ScalarType.FLOAT
        elif isinstance(self.parent, AssignStmt):
            valid = (self.role == "value" and self.element_index is None
                     and self.parent.value is self.operand)
            destination_is_float = True  # Resolved target is checked by StatementAnalysis.
        else:
            raise TypeError("conversion parent must be a declaration or assignment")
        if not valid:
            raise ValueError("conversion operand, role, or element index does not match parent")
        if not destination_is_float:
            raise ValueError("conversion destination must match the declaration type")


@dataclass(frozen=True, slots=True, eq=False)
class DefaultInitialization:
    """Typed default value metadata; arrays use one descriptor plus length."""

    parent: ScalarDecl | ArrayDecl
    symbol: VariableSymbol
    element_value: object
    length: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, VariableSymbol):
            raise TypeError("default symbol must be a variable symbol")
        if isinstance(self.parent, ScalarDecl):
            valid = (self.parent.initializer is None
                     and self.symbol.kind is SymbolKind.VARIABLE
                     and self.length is None)
            declared = _declared_type(self.parent.type_name)
        elif isinstance(self.parent, ArrayDecl):
            valid = (self.parent.initializers is None
                     and self.symbol.kind is SymbolKind.ARRAY
                     and type(self.length) is int and self.length > 0
                     and self.length == self.symbol.array_length
                     and self.length == self.parent.size.value)
            declared = _declared_type(self.parent.element_type)
        else:
            raise TypeError("default parent must be a declaration")
        expected = _DEFAULTS[declared]
        if (not valid or self.symbol.name != self.parent.name
                or self.symbol.span != self.parent.span
                or self.symbol.type is not declared
                or type(self.element_value) is not type(expected)
                or self.element_value != expected):
            raise ValueError("default descriptor contradicts its declaration or symbol")


@dataclass(frozen=True, slots=True, eq=False)
class WritableTarget:
    target: VarRef | ArrayAccess
    symbol: VariableSymbol
    type: ScalarType
    index_analysis: ExpressionAnalysis | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, VariableSymbol):
            raise TypeError("writable target symbol must be a variable symbol")
        if not isinstance(self.target, (VarRef, ArrayAccess)):
            raise TypeError("writable target must be a variable or array access")
        if (self.symbol.name != self.target.name or self.type is not self.symbol.type):
            raise ValueError("writable target name or type contradicts its symbol")
        if isinstance(self.target, VarRef):
            valid = (self.symbol.kind in (SymbolKind.VARIABLE, SymbolKind.PARAMETER)
                     and self.index_analysis is None)
        elif isinstance(self.target, ArrayAccess):
            valid = (self.symbol.kind is SymbolKind.ARRAY
                     and isinstance(self.index_analysis, ExpressionAnalysis)
                     and self.index_analysis.root is self.target.index
                     and self.index_analysis.type is ScalarType.INT)
        if not valid:
            raise ValueError("writable target kind or index analysis is inconsistent")

    @property
    def span(self) -> SourceSpan:
        """Source span of the writable location."""
        return self.target.span


@dataclass(frozen=True, slots=True, eq=False)
class ExpressionUse:
    """One expression occurrence in one statement role and scope."""

    parent: ScalarDecl | ArrayDecl | AssignStmt
    role: str  # "initializer", "element", "target_index", or "value"
    analysis: ExpressionAnalysis
    element_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.analysis, ExpressionAnalysis):
            raise TypeError("expression use requires an expression analysis")
        if isinstance(self.parent, ScalarDecl):
            valid = (self.role == "initializer" and self.element_index is None
                     and self.parent.initializer is self.analysis.root)
        elif isinstance(self.parent, ArrayDecl):
            elements = self.parent.initializers
            valid = (self.role == "element" and type(self.element_index) is int
                     and elements is not None and 0 <= self.element_index < len(elements)
                     and elements[self.element_index] is self.analysis.root)
        elif isinstance(self.parent, AssignStmt):
            valid = (self.element_index is None and (
                (self.role == "value" and self.parent.value is self.analysis.root)
                or (self.role == "target_index"
                    and isinstance(self.parent.target, ArrayAccess)
                    and self.parent.target.index is self.analysis.root)
            ))
        else:
            raise TypeError("expression use parent must be a supported statement")
        if not valid:
            raise ValueError("expression use does not match its parent and role")


@dataclass(frozen=True, slots=True, eq=False)
class ReturnConversionSite:
    """INT-to-FLOAT conversion at a validated function RETURN."""

    statement: ReturnStmt
    function: FunctionSymbol
    operand: Expr
    source_type: ScalarType
    destination_type: ScalarType

    def __post_init__(self) -> None:
        if not isinstance(self.statement, ReturnStmt) or not isinstance(self.function, FunctionSymbol):
            raise TypeError("return conversion needs a RETURN and function symbol")
        if (self.statement.value is not self.operand
                or self.source_type is not ScalarType.INT
                or self.destination_type is not ScalarType.FLOAT
                or self.function.return_type is not ScalarType.FLOAT):
            raise ValueError("return conversion contradicts its function or operand")


@dataclass(frozen=True, slots=True, eq=False)
class ReturnAnalysis:
    statement: ReturnStmt
    function: FunctionSymbol
    value: ExpressionAnalysis | None
    conversion: ReturnConversionSite | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.statement, ReturnStmt) or not isinstance(self.function, FunctionSymbol):
            raise TypeError("return analysis needs a RETURN and function symbol")
        destination = self.function.return_type
        if destination is VoidType.VOID:
            if self.statement.value is not None or self.value is not None or self.conversion is not None:
                raise ValueError("VOID return must have no value or conversion")
            return
        if (not isinstance(self.value, ExpressionAnalysis)
                or self.statement.value is not self.value.root):
            raise ValueError("non-VOID return requires its own analyzed value")
        decision = assignment_compatibility(destination, self.value.type)
        if decision is Compatibility.INCOMPATIBLE:
            raise ValueError("return value type is incompatible with function")
        if decision is Compatibility.INT_TO_FLOAT:
            site = self.conversion
            if (not isinstance(site, ReturnConversionSite)
                    or site.statement is not self.statement or site.function is not self.function
                    or site.operand is not self.value.root):
                raise ValueError("return conversion is missing or inconsistent")
        elif self.conversion is not None:
            raise ValueError("exact return type must not have a conversion")


@dataclass(frozen=True, slots=True, eq=False)
class ConditionUse:
    owner: WhenStmt | WhileStmt | DoWhileStmt | ForStmt
    analysis: ExpressionAnalysis

    def __post_init__(self) -> None:
        if not isinstance(self.owner, (WhenStmt, WhileStmt, DoWhileStmt, ForStmt)):
            raise TypeError("condition owner must be a conditional or loop")
        if (not isinstance(self.analysis, ExpressionAnalysis)
                or self.owner.condition is not self.analysis.root
                or self.analysis.type is not ScalarType.BOOL):
            raise ValueError("condition requires its own BOOL expression analysis")


@dataclass(frozen=True, slots=True, eq=False)
class SelectorUse:
    owner: SelectStmt
    analysis: ExpressionAnalysis

    def __post_init__(self) -> None:
        if not isinstance(self.owner, SelectStmt):
            raise TypeError("selector owner must be SELECT")
        if (not isinstance(self.analysis, ExpressionAnalysis)
                or self.owner.selector is not self.analysis.root
                or self.analysis.type not in (ScalarType.INT, ScalarType.CHAR, ScalarType.STRING)):
            raise ValueError("SELECT requires its own INT, CHAR, or STRING selector")


@dataclass(frozen=True, slots=True, eq=False)
class CaseLabelAnalysis:
    owner: SelectStmt
    clause: CaseClause
    type: ScalarType
    value: object

    def __post_init__(self) -> None:
        if not isinstance(self.owner, SelectStmt) or not isinstance(self.clause, CaseClause):
            raise TypeError("CASE metadata needs a SELECT and CASE clause")
        if not any(case is self.clause for case in self.owner.cases):
            raise ValueError("CASE clause does not belong to SELECT")
        kind, decoded = _case_value(self.clause.label)
        if self.type is not kind or type(self.value) is not type(decoded) or self.value != decoded:
            raise ValueError("CASE metadata contradicts its decoded literal")


@dataclass(frozen=True, slots=True, eq=False)
class StatementAnalysis:
    """Successful statement result with immutable occurrence records."""

    root: Stmt
    declarations: tuple[tuple[ScalarDecl | ArrayDecl, VariableSymbol], ...]
    targets: tuple[tuple[AssignStmt, WritableTarget], ...]
    expressions: tuple[ExpressionUse, ...]
    defaults: tuple[DefaultInitialization, ...]
    conversions: tuple[StatementConversionSite, ...]
    scopes: tuple[tuple[Block, Scope], ...]
    calls: tuple[tuple[CallStmt, CallAnalysis], ...] = ()
    returns: tuple[ReturnAnalysis, ...] = ()
    function: FunctionSymbol | None = None
    conditions: tuple[ConditionUse, ...] = ()
    selectors: tuple[SelectorUse, ...] = ()
    case_labels: tuple[CaseLabelAnalysis, ...] = ()
    repeat_scopes: tuple[tuple[ForStmt, Scope], ...] = ()
    reads: tuple[tuple[ReadStmt, WritableTarget], ...] = ()
    shows: tuple[tuple[ShowStmt, ExpressionAnalysis], ...] = ()

    def __post_init__(self) -> None:
        # Snapshot both outer collections and caller-owned pair entries.
        object.__setattr__(self, "declarations", _snapshot_pairs(self.declarations, "declarations"))
        object.__setattr__(self, "targets", _snapshot_pairs(self.targets, "targets"))
        object.__setattr__(self, "scopes", _snapshot_pairs(self.scopes, "scopes"))
        object.__setattr__(self, "calls", _snapshot_pairs(self.calls, "calls"))
        object.__setattr__(self, "repeat_scopes", _snapshot_pairs(self.repeat_scopes, "repeat_scopes"))
        object.__setattr__(self, "reads", _snapshot_pairs(self.reads, "reads"))
        object.__setattr__(self, "shows", _snapshot_pairs(self.shows, "shows"))
        for name, kind in (
            ("expressions", ExpressionUse),
            ("defaults", DefaultInitialization),
            ("conversions", StatementConversionSite),
            ("returns", ReturnAnalysis),
            ("conditions", ConditionUse),
            ("selectors", SelectorUse),
            ("case_labels", CaseLabelAnalysis),
        ):
            object.__setattr__(
                self, name, _snapshot_records(getattr(self, name), name, kind),
            )

        # This walk checks coverage and ownership only. It never resolves names,
        # infers a type, executes an expression, or changes a scope.
        expected_declarations: list[tuple[ScalarDecl | ArrayDecl, Block | ForStmt | None]] = []
        expected_targets: list[AssignStmt] = []
        expected_expressions: list[tuple[Stmt, str, int | None, Expr]] = []
        expected_defaults: list[ScalarDecl | ArrayDecl] = []
        expected_scopes: list[tuple[Block, Block | ForStmt | None]] = []
        expected_calls: list[CallStmt] = []
        expected_returns: list[ReturnStmt] = []
        expected_conditions: list[WhenStmt | WhileStmt | DoWhileStmt | ForStmt] = []
        expected_selectors: list[SelectStmt] = []
        expected_labels: list[tuple[SelectStmt, CaseClause]] = []
        expected_repeats: list[tuple[ForStmt, Block | None]] = []
        expected_reads: list[ReadStmt] = []
        expected_shows: list[ShowStmt] = []
        pending: list[tuple[Stmt, Block | ForStmt | None]] = [(self.root, None)]
        while pending:
            statement, containing_block = pending.pop()
            if isinstance(statement, Block):
                expected_scopes.append((statement, containing_block))
                pending.extend((child, statement) for child in reversed(statement.statements))
            elif isinstance(statement, ScalarDecl):
                expected_declarations.append((statement, containing_block))
                if statement.initializer is None:
                    expected_defaults.append(statement)
                else:
                    expected_expressions.append(
                        (statement, "initializer", None, statement.initializer)
                    )
            elif isinstance(statement, ArrayDecl):
                expected_declarations.append((statement, containing_block))
                if statement.initializers is None:
                    expected_defaults.append(statement)
                else:
                    expected_expressions.extend(
                        (statement, "element", index, expression)
                        for index, expression in enumerate(statement.initializers)
                    )
            elif isinstance(statement, AssignStmt):
                expected_targets.append(statement)
                if isinstance(statement.target, ArrayAccess):
                    expected_expressions.append(
                        (statement, "target_index", None, statement.target.index)
                    )
                expected_expressions.append((statement, "value", None, statement.value))
            elif isinstance(statement, CallStmt):
                expected_calls.append(statement)
            elif isinstance(statement, ReturnStmt):
                expected_returns.append(statement)
            elif isinstance(statement, WhenStmt):
                expected_conditions.append(statement)
                branches = [statement.then_block]
                if statement.else_block is not None:
                    branches.append(statement.else_block)
                pending.extend((branch, containing_block) for branch in reversed(branches))
            elif isinstance(statement, SelectStmt):
                expected_selectors.append(statement)
                expected_labels.extend((statement, case) for case in statement.cases)
                branches = [case.body for case in statement.cases]
                if statement.default is not None:
                    branches.append(statement.default)
                pending.extend((branch, containing_block) for branch in reversed(branches))
            elif isinstance(statement, (WhileStmt, DoWhileStmt)):
                expected_conditions.append(statement)
                pending.append((statement.body, containing_block))
            elif isinstance(statement, ForStmt):
                expected_repeats.append((statement, containing_block if isinstance(containing_block, Block) else None))
                if statement.condition is not None:
                    expected_conditions.append(statement)
                pending.append((statement.body, statement))
                if statement.update is not None:
                    pending.append((statement.update, statement))
                if statement.initializer is not None:
                    pending.append((statement.initializer, statement))
            elif isinstance(statement, ReadStmt):
                expected_reads.append(statement)
            elif isinstance(statement, ShowStmt):
                expected_shows.append(statement)
            else:
                raise TypeError("completed result root contains an unsupported statement")

        if len(self.repeat_scopes) != len(expected_repeats):
            raise ValueError("REPEAT scope coverage is incomplete")
        repeat_by_id: dict[int, Scope] = {}
        used_scope_ids: set[int] = set()
        for (owner, scope), (repeat, _) in zip(self.repeat_scopes, expected_repeats):
            if owner is not repeat or not isinstance(scope, Scope) or scope.id in used_scope_ids:
                raise ValueError("REPEAT scope record has the wrong owner")
            repeat_by_id[id(repeat)] = scope
            used_scope_ids.add(scope.id)

        if len(self.scopes) != len(expected_scopes):
            raise ValueError("block scope coverage is incomplete")
        scope_by_id: dict[int, Scope] = {}
        for (owner, scope), (block, containing_block) in zip(self.scopes, expected_scopes):
            if owner is not block or not isinstance(scope, Scope) or scope.id in used_scope_ids:
                raise ValueError("block scope record does not match the result root")
            parent_scope = (repeat_by_id[id(containing_block)] if isinstance(containing_block, ForStmt)
                            else scope_by_id[id(containing_block)] if containing_block is not None else None)
            if parent_scope is not None and scope.parent is not parent_scope:
                raise ValueError("nested block scope has the wrong parent")
            scope_by_id[id(block)] = scope
            used_scope_ids.add(scope.id)

        for (repeat, parent), (_, scope) in zip(expected_repeats, self.repeat_scopes):
            if parent is not None and scope.parent is not scope_by_id[id(parent)]:
                raise ValueError("REPEAT header scope has the wrong parent")

        if len(self.declarations) != len(expected_declarations):
            raise ValueError("declaration binding coverage is incomplete")
        symbol_by_id: dict[int, VariableSymbol] = {}
        for (owner, symbol), (declaration, block) in zip(
            self.declarations, expected_declarations,
        ):
            if owner is not declaration or not isinstance(symbol, VariableSymbol):
                raise ValueError("declaration binding does not match the result root")
            declared = _declared_type(
                declaration.type_name if isinstance(declaration, ScalarDecl)
                else declaration.element_type
            )
            kind = SymbolKind.VARIABLE if isinstance(declaration, ScalarDecl) else SymbolKind.ARRAY
            if (symbol.name != declaration.name or symbol.kind is not kind
                    or symbol.type is not declared
                    or (block is not None and symbol.scope_id != (
                        repeat_by_id[id(block)].id if isinstance(block, ForStmt)
                        else scope_by_id[id(block)].id))):
                raise ValueError("declaration symbol contradicts its owner")
            if isinstance(declaration, ArrayDecl):
                size = declaration.size
                if (size.kind is not TokenType.INT_LITERAL or type(size.value) is not int
                        or size.value <= 0 or symbol.array_length != size.value
                        or (declaration.initializers is not None
                            and len(declaration.initializers) != size.value)):
                    raise ValueError("array binding contradicts size or initializer count")
            symbol_by_id[id(declaration)] = symbol

        if len(self.targets) != len(expected_targets):
            raise ValueError("writable target coverage is incomplete")
        target_by_id: dict[int, WritableTarget] = {}
        for (owner, target), assignment in zip(self.targets, expected_targets):
            if (owner is not assignment or not isinstance(target, WritableTarget)
                    or target.target is not assignment.target):
                raise ValueError("writable target does not match its assignment")
            target_by_id[id(assignment)] = target

        if len(self.defaults) != len(expected_defaults):
            raise ValueError("default initialization coverage is incomplete")
        for default, declaration in zip(self.defaults, expected_defaults):
            if (default.parent is not declaration
                    or default.symbol is not symbol_by_id[id(declaration)]):
                raise ValueError("default descriptor does not match its declaration binding")

        if len(self.expressions) != len(expected_expressions):
            raise ValueError("expression use coverage is incomplete")
        needed_conversions: list[tuple[Stmt, str, int | None, Expr]] = []
        for use, (owner, role, index, expression) in zip(
            self.expressions, expected_expressions,
        ):
            if (use.parent is not owner or use.role != role
                    or use.element_index != index or use.analysis.root is not expression):
                raise ValueError("expression use does not match source order and ownership")
            if role == "target_index":
                target = target_by_id[id(owner)]
                if (use.analysis is not target.index_analysis
                        or use.analysis.type is not ScalarType.INT):
                    raise ValueError("target index analysis is inconsistent")
                continue
            destination = (
                target_by_id[id(owner)].type if isinstance(owner, AssignStmt)
                else symbol_by_id[id(owner)].type
            )
            compatibility = assignment_compatibility(destination, use.analysis.type)
            if compatibility is Compatibility.INCOMPATIBLE:
                raise ValueError("expression use type is incompatible with its destination")
            if compatibility is Compatibility.INT_TO_FLOAT:
                needed_conversions.append((owner, role, index, expression))

        if len(self.conversions) != len(needed_conversions):
            raise ValueError("statement conversion coverage is incomplete")
        for site, (owner, role, index, expression) in zip(
            self.conversions, needed_conversions,
        ):
            if (site.parent is not owner or site.role != role
                    or site.element_index != index or site.operand is not expression):
                raise ValueError("statement conversion contradicts its expression use")

        if len(self.calls) != len(expected_calls):
            raise ValueError("call statement coverage is incomplete")
        for (owner, analysis), statement in zip(self.calls, expected_calls):
            if (owner is not statement or not isinstance(analysis, CallAnalysis)
                    or analysis.call is not statement.call):
                raise ValueError("call statement analysis does not match its owner")

        if len(self.returns) != len(expected_returns):
            raise ValueError("return statement coverage is incomplete")
        if self.function is not None and not isinstance(self.function, FunctionSymbol):
            raise TypeError("active function metadata must be a function symbol")
        for analysis, statement in zip(self.returns, expected_returns):
            if analysis.statement is not statement or analysis.function is not self.function:
                raise ValueError("return analysis does not match its function context")

        if len(self.conditions) != len(expected_conditions):
            raise ValueError("condition analysis coverage is incomplete")
        if {id(record.owner) for record in self.conditions} != {id(owner) for owner in expected_conditions}:
            raise ValueError("condition analysis has the wrong owner")

        if len(self.selectors) != len(expected_selectors):
            raise ValueError("SELECT selector coverage is incomplete")
        selector_by_id: dict[int, ScalarType] = {}
        for record, owner in zip(self.selectors, expected_selectors):
            if record.owner is not owner:
                raise ValueError("SELECT selector has the wrong owner")
            selector_by_id[id(owner)] = record.analysis.type

        if len(self.case_labels) != len(expected_labels):
            raise ValueError("CASE label coverage is incomplete")
        if {(id(record.owner), id(record.clause)) for record in self.case_labels} != {
            (id(owner), id(clause)) for owner, clause in expected_labels
        }:
            raise ValueError("CASE label has the wrong SELECT or clause")
        actual_by_owner: dict[int, list[CaseClause]] = {}
        for record in self.case_labels:
            actual_by_owner.setdefault(id(record.owner), []).append(record.clause)
        for selector in expected_selectors:
            actual = actual_by_owner.get(id(selector), [])
            if len(actual) != len(selector.cases) or any(
                clause is not expected for clause, expected in zip(actual, selector.cases)
            ):
                raise ValueError("CASE labels must follow their SELECT source order")
        seen_labels: dict[int, set[tuple[ScalarType, object]]] = {}
        for record in self.case_labels:
            if record.type is not selector_by_id[id(record.owner)]:
                raise ValueError("CASE label type contradicts selector")
            seen = seen_labels.setdefault(id(record.owner), set())
            key = (record.type, record.value)
            if key in seen:
                raise ValueError("successful SELECT has duplicate CASE labels")
            seen.add(key)

        if len(self.reads) != len(expected_reads):
            raise ValueError("READ target coverage is incomplete")
        for (owner, target), statement in zip(self.reads, expected_reads):
            if owner is not statement or not isinstance(target, WritableTarget) or target.target is not statement.target:
                raise ValueError("READ target does not match its statement")

        if len(self.shows) != len(expected_shows):
            raise ValueError("SHOW expression coverage is incomplete")
        for (owner, analysis), statement in zip(self.shows, expected_shows):
            if (owner is not statement or not isinstance(analysis, ExpressionAnalysis)
                    or analysis.root is not statement.value):
                raise ValueError("SHOW expression does not match its statement")

    def declaration_of(self, node: ScalarDecl | ArrayDecl) -> VariableSymbol | None:
        return next((symbol for owner, symbol in self.declarations if owner is node), None)

    def target_of(self, node: AssignStmt) -> WritableTarget | None:
        return next((target for owner, target in self.targets if owner is node), None)

    def scope_of(self, block: Block) -> Scope | None:
        return next((scope for owner, scope in self.scopes if owner is block), None)

    def call_of(self, node: CallStmt) -> CallAnalysis | None:
        return next((analysis for owner, analysis in self.calls if owner is node), None)

    def return_of(self, node: ReturnStmt) -> ReturnAnalysis | None:
        return next((analysis for analysis in self.returns if analysis.statement is node), None)

    def condition_of(self, node: WhenStmt | WhileStmt | DoWhileStmt | ForStmt) -> ExpressionAnalysis | None:
        return next((record.analysis for record in self.conditions if record.owner is node), None)

    def selector_of(self, node: SelectStmt) -> ExpressionAnalysis | None:
        return next((record.analysis for record in self.selectors if record.owner is node), None)

    def labels_of(self, node: SelectStmt) -> tuple[CaseLabelAnalysis, ...]:
        return tuple(record for record in self.case_labels if record.owner is node)

    def repeat_scope_of(self, node: ForStmt) -> Scope | None:
        return next((scope for owner, scope in self.repeat_scopes if owner is node), None)

    def read_of(self, node: ReadStmt) -> WritableTarget | None:
        return next((target for owner, target in self.reads if owner is node), None)

    def show_of(self, node: ShowStmt) -> ExpressionAnalysis | None:
        return next((analysis for owner, analysis in self.shows if owner is node), None)

    def all_conversions(
        self,
    ) -> tuple[ConversionSite | ArgumentConversionSite | StatementConversionSite | ReturnConversionSite, ...]:
        """Combine conversions in deterministic static statement traversal order."""
        uses: dict[int, list[ExpressionUse]] = {}
        for use in self.expressions:
            uses.setdefault(id(use.parent), []).append(use)
        calls = {id(owner): analysis for owner, analysis in self.calls}
        returns = {id(analysis.statement): analysis for analysis in self.returns}
        conditions = {id(record.owner): record.analysis for record in self.conditions}
        selectors = {id(record.owner): record.analysis for record in self.selectors}
        reads = {id(owner): target for owner, target in self.reads}
        shows = {id(owner): analysis for owner, analysis in self.shows}
        sites: list[
            ConversionSite | ArgumentConversionSite | StatementConversionSite | ReturnConversionSite
        ] = []
        pending: list[tuple[str, object]] = [("statement", self.root)]
        while pending:
            action, item = pending.pop()
            if action == "expression":
                sites.extend(item.annotations.all_conversions())
                continue
            statement = item
            if isinstance(statement, Block):
                pending.extend(("statement", child) for child in reversed(statement.statements))
                continue
            for use in uses.get(id(statement), ()):
                sites.extend(use.analysis.annotations.all_conversions())
                sites.extend(
                    site for site in self.conversions
                    if site.parent is use.parent and site.operand is use.analysis.root
                    and site.role == use.role and site.element_index == use.element_index
                )
            if isinstance(statement, CallStmt):
                sites.extend(calls[id(statement)].annotations.all_conversions())
            elif isinstance(statement, ReturnStmt):
                returned = returns[id(statement)]
                if returned.value is not None:
                    sites.extend(returned.value.annotations.all_conversions())
                if returned.conversion is not None:
                    sites.append(returned.conversion)
            elif isinstance(statement, WhenStmt):
                sites.extend(conditions[id(statement)].annotations.all_conversions())
                if statement.else_block is not None:
                    pending.append(("statement", statement.else_block))
                pending.append(("statement", statement.then_block))
            elif isinstance(statement, SelectStmt):
                sites.extend(selectors[id(statement)].annotations.all_conversions())
                if statement.default is not None:
                    pending.append(("statement", statement.default))
                pending.extend(("statement", case.body) for case in reversed(statement.cases))
            elif isinstance(statement, WhileStmt):
                sites.extend(conditions[id(statement)].annotations.all_conversions())
                pending.append(("statement", statement.body))
            elif isinstance(statement, DoWhileStmt):
                pending.append(("expression", conditions[id(statement)]))
                pending.append(("statement", statement.body))
            elif isinstance(statement, ForStmt):
                pending.append(("statement", statement.body))
                if statement.update is not None:
                    pending.append(("statement", statement.update))
                if statement.condition is not None:
                    pending.append(("expression", conditions[id(statement)]))
                if statement.initializer is not None:
                    pending.append(("statement", statement.initializer))
            elif isinstance(statement, ReadStmt):
                target = reads[id(statement)]
                if target.index_analysis is not None:
                    sites.extend(target.index_analysis.annotations.all_conversions())
            elif isinstance(statement, ShowStmt):
                sites.extend(shows[id(statement)].annotations.all_conversions())
        return tuple(sites)


@dataclass(slots=True)
class _Build:
    declarations: list[tuple[ScalarDecl | ArrayDecl, VariableSymbol]] = field(default_factory=list)
    targets: list[tuple[AssignStmt, WritableTarget]] = field(default_factory=list)
    expressions: list[ExpressionUse] = field(default_factory=list)
    defaults: list[DefaultInitialization] = field(default_factory=list)
    conversions: list[StatementConversionSite] = field(default_factory=list)
    scopes: list[tuple[Block, Scope]] = field(default_factory=list)
    calls: list[tuple[CallStmt, CallAnalysis]] = field(default_factory=list)
    returns: list[ReturnAnalysis] = field(default_factory=list)
    conditions: list[ConditionUse] = field(default_factory=list)
    selectors: list[SelectorUse] = field(default_factory=list)
    case_labels: list[CaseLabelAnalysis] = field(default_factory=list)
    repeat_scopes: list[tuple[ForStmt, Scope]] = field(default_factory=list)
    reads: list[tuple[ReadStmt, WritableTarget]] = field(default_factory=list)
    shows: list[tuple[ShowStmt, ExpressionAnalysis]] = field(default_factory=list)

    def finish(self, root: Stmt, function: FunctionSymbol | None) -> StatementAnalysis:
        return StatementAnalysis(
            root, tuple(self.declarations), tuple(self.targets),
            tuple(self.expressions), tuple(self.defaults),
            tuple(self.conversions), tuple(self.scopes),
            tuple(self.calls), tuple(self.returns), function,
            tuple(self.conditions), tuple(self.selectors), tuple(self.case_labels),
            tuple(self.repeat_scopes), tuple(self.reads), tuple(self.shows),
        )


class StatementAnalyzer:
    """Validate all parser-produced statement categories without executing them."""

    def __init__(self, context: SemanticContext) -> None:
        self.context = context
        self.expressions = ExpressionAnalyzer(context)

    def analyze_statement(self, statement: Stmt) -> StatementAnalysis:
        """Analyze one supported statement; a Block here creates a child scope."""
        return self._run(statement, block_root=False)

    def analyze_block(self, block: Block) -> StatementAnalysis:
        """Analyze a START or function outer body in the already active scope."""
        if not isinstance(block, Block):
            raise TypeError("expected a Block AST node")
        return self._run(block, block_root=True)

    def _run(self, root: Stmt, *, block_root: bool) -> StatementAnalysis:
        self.context._ensure_statement_usable()
        self.context._scope()  # Public operation requires an active lexical scope.
        facts = _Build()
        try:
            if block_root:
                self._visit_block(root, facts, child=False)
            else:
                self._visit(root, facts)
            return facts.finish(root, self.context.active_function)
        except RecursionError as exc:
            self.context._statement_invalid = True
            raise SemanticError(
                "RESOURCE_LIMIT", "statement nesting exceeds the available analysis stack",
                root.span,
            ) from exc
        except Exception:
            self.context._statement_invalid = True
            raise

    def resolve_writable(self, target: VarRef | ArrayAccess) -> WritableTarget:
        """Resolve a location without reading its stored value or checking bounds."""
        scope = self.context._scope()
        if isinstance(target, VarRef):
            symbol = scope.resolve(target.name)
            if symbol is None:
                if self.context.functions.resolve(target.name) is not None:
                    raise SemanticError(
                        "FUNCTION_AS_TARGET", "function name is not a writable variable",
                        target.span, name=target.name,
                    )
                raise SemanticError(
                    "UNDECLARED_NAME", "name is not declared", target.span,
                    name=target.name,
                )
            if symbol.kind is SymbolKind.ARRAY:
                raise SemanticError(
                    "WHOLE_ARRAY_ASSIGNMENT", "whole-array assignment is unsupported",
                    target.span, name=target.name,
                )
            return WritableTarget(target, symbol, symbol.type)
        if isinstance(target, ArrayAccess):
            symbol = scope.require(target.name, target.span)
            if symbol.kind is not SymbolKind.ARRAY:
                raise SemanticError(
                    "WRONG_SYMBOL_KIND", "indexed assignment requires an array",
                    target.span, name=target.name, expected="array",
                    actual=symbol.kind.name,
                )
            index_analysis = self.expressions.infer(target.index)
            if index_analysis.type is not ScalarType.INT:
                raise SemanticError(
                    "INDEX_TYPE", "array index must be INT", target.index.span,
                    name=target.name, expected="INT", actual=index_analysis.type.name,
                )
            return WritableTarget(target, symbol, symbol.type, index_analysis)
        raise TypeError("expected a variable or array-element target")

    def _visit(self, statement: Stmt, facts: _Build) -> None:
        if isinstance(statement, ScalarDecl):
            self._scalar(statement, facts)
        elif isinstance(statement, ArrayDecl):
            self._array(statement, facts)
        elif isinstance(statement, AssignStmt):
            self._assignment(statement, facts)
        elif isinstance(statement, Block):
            self._visit_block(statement, facts, child=True)
        elif isinstance(statement, CallStmt):
            facts.calls.append((statement, self.expressions.analyze_call(statement.call)))
        elif isinstance(statement, ReturnStmt):
            self._return(statement, facts)
        elif isinstance(statement, WhenStmt):
            self._condition(statement, facts)
            self._visit_block(statement.then_block, facts, child=True)
            if statement.else_block is not None:
                self._visit_block(statement.else_block, facts, child=True)
        elif isinstance(statement, SelectStmt):
            self._select(statement, facts)
        elif isinstance(statement, WhileStmt):
            self._condition(statement, facts)
            self._visit_block(statement.body, facts, child=True)
        elif isinstance(statement, DoWhileStmt):
            self._visit_block(statement.body, facts, child=True)
            self._condition(statement, facts)
        elif isinstance(statement, ForStmt):
            self._repeat(statement, facts)
        elif isinstance(statement, ReadStmt):
            facts.reads.append((statement, self.resolve_writable(statement.target)))
        elif isinstance(statement, ShowStmt):
            facts.shows.append((statement, self.expressions.infer(statement.value)))
        else:
            raise TypeError("expected a supported statement AST node")

    def _visit_block(self, block: Block, facts: _Build, *, child: bool) -> None:
        if child:
            scope = self.context.enter_block()
        else:
            scope = self.context._scope()
        facts.scopes.append((block, scope))
        try:
            for statement in block.statements:
                self._visit(statement, facts)
        finally:
            if child:
                self.context.exit_scope()

    def _condition(
        self, statement: WhenStmt | WhileStmt | DoWhileStmt | ForStmt, facts: _Build,
    ) -> None:
        if statement.condition is None:
            raise ValueError("condition analysis requires a present expression")
        analysis = self.expressions.infer(statement.condition)
        if analysis.type is not ScalarType.BOOL:
            raise SemanticError(
                "CONDITION_TYPE", "condition must be BOOL", statement.condition.span,
                name=type(statement).__name__, expected="BOOL", actual=analysis.type.name,
            )
        facts.conditions.append(ConditionUse(statement, analysis))

    def _select(self, statement: SelectStmt, facts: _Build) -> None:
        selector = self.expressions.infer(statement.selector)
        if selector.type not in (ScalarType.INT, ScalarType.CHAR, ScalarType.STRING):
            raise SemanticError(
                "INVALID_SELECTOR_TYPE", "SELECT requires INT, CHAR, or STRING",
                statement.selector.span, expected="INT, CHAR, or STRING",
                actual=selector.type.name,
            )
        facts.selectors.append(SelectorUse(statement, selector))
        labels: set[tuple[ScalarType, object]] = set()
        for clause in statement.cases:
            kind, decoded = _case_value(clause.label)
            if kind is not selector.type:
                raise SemanticError(
                    "CASE_TYPE_MISMATCH", "CASE label must match selector type",
                    clause.label.span, expected=selector.type.name, actual=kind.name,
                )
            key = (kind, decoded)
            if key in labels:
                raise SemanticError(
                    "DUPLICATE_CASE", "CASE label repeats a decoded value",
                    clause.label.span, name="CASE label",
                )
            labels.add(key)
            facts.case_labels.append(CaseLabelAnalysis(statement, clause, kind, decoded))
            self._visit_block(clause.body, facts, child=True)
        if statement.default is not None:
            self._visit_block(statement.default, facts, child=True)

    def _repeat(self, statement: ForStmt, facts: _Build) -> None:
        header_scope = self.context.enter_repeat()
        facts.repeat_scopes.append((statement, header_scope))
        try:
            if statement.initializer is not None:
                if not isinstance(statement.initializer, (ScalarDecl, AssignStmt)):
                    raise TypeError("REPEAT initializer must be a declaration or assignment")
                self._visit(statement.initializer, facts)
            if statement.condition is not None:
                self._condition(statement, facts)
            if statement.update is not None:
                if not isinstance(statement.update, AssignStmt):
                    raise TypeError("REPEAT update must be an assignment")
                self._visit(statement.update, facts)
            self._visit_block(statement.body, facts, child=True)
        finally:
            self.context.exit_scope()

    def _scalar(self, declaration: ScalarDecl, facts: _Build) -> None:
        symbol = self.context.declare_scalar(declaration)
        facts.declarations.append((declaration, symbol))
        if declaration.initializer is None:
            facts.defaults.append(DefaultInitialization(
                declaration, symbol, _DEFAULTS[symbol.type],
            ))
        else:
            self.context._initializing.add(symbol.id)
            try:
                analysis = self.expressions.infer(declaration.initializer)
                facts.expressions.append(ExpressionUse(declaration, "initializer", analysis))
                self._compatible(
                    declaration, declaration.initializer, symbol.type, analysis.type,
                    "initializer", None, facts, symbol.name,
                )
            finally:
                self.context._initializing.discard(symbol.id)
        self.context._initialized.add(symbol.id)

    def _array(self, declaration: ArrayDecl, facts: _Build) -> None:
        size = declaration.size
        if size.kind is not TokenType.INT_LITERAL or type(size.value) is not int or size.value <= 0:
            raise SemanticError(
                "INVALID_ARRAY_SIZE", "array size must be a positive INT literal",
                size.span, name=declaration.name, expected="positive INT",
                actual=size.lexeme,
            )
        symbol = self.context.declare_array(declaration)
        facts.declarations.append((declaration, symbol))
        if declaration.initializers is None:
            facts.defaults.append(DefaultInitialization(
                declaration, symbol, _DEFAULTS[symbol.type], symbol.array_length,
            ))
        else:
            elements = declaration.initializers
            if len(elements) != symbol.array_length:
                raise SemanticError(
                    "ARRAY_INITIALIZER_COUNT", "array initializer length differs from size",
                    declaration.span, name=symbol.name,
                    expected=(size.lexeme if len(size.lexeme) <= 40 else
                              f"{size.lexeme[:20]}... ({len(size.lexeme)} digits)"),
                    actual=str(len(elements)),
                )
            self.context._initializing.add(symbol.id)
            try:
                for index, expression in enumerate(elements):
                    analysis = self.expressions.infer(expression)
                    facts.expressions.append(ExpressionUse(
                        declaration, "element", analysis, index,
                    ))
                    self._compatible(
                        declaration, expression, symbol.type, analysis.type,
                        "element", index, facts, symbol.name,
                    )
            finally:
                self.context._initializing.discard(symbol.id)
        self.context._initialized.add(symbol.id)

    def _assignment(self, statement: AssignStmt, facts: _Build) -> None:
        target = self.resolve_writable(statement.target)
        facts.targets.append((statement, target))
        if target.index_analysis is not None:
            facts.expressions.append(ExpressionUse(
                statement, "target_index", target.index_analysis,
            ))
        value = self.expressions.infer(statement.value)
        facts.expressions.append(ExpressionUse(statement, "value", value))
        self._compatible(
            statement, statement.value, target.type, value.type,
            "value", None, facts, target.symbol.name,
        )

    def _return(self, statement: ReturnStmt, facts: _Build) -> None:
        function = self.context.active_function
        if function is None:
            raise SemanticError(
                "RETURN_OUTSIDE_FUNCTION", "RETURN is not allowed in START",
                statement.span,
            )
        destination = function.return_type
        if destination is VoidType.VOID:
            if statement.value is not None:
                raise SemanticError(
                    "INVALID_RETURN", "VOID function cannot return a value",
                    statement.span, name=function.name, expected="VOID",
                )
            facts.returns.append(ReturnAnalysis(statement, function, None))
            return
        if statement.value is None:
            raise SemanticError(
                "INVALID_RETURN", "non-VOID function requires a return value",
                statement.span, name=function.name, expected=destination.name,
            )
        value = self.expressions.infer(statement.value)
        decision = assignment_compatibility(destination, value.type)
        if decision is Compatibility.INCOMPATIBLE:
            raise SemanticError(
                "TYPE_MISMATCH", "return value type is incompatible",
                statement.value.span, name=function.name,
                expected=destination.name, actual=value.type.name,
            )
        conversion = (
            ReturnConversionSite(statement, function, statement.value, value.type, destination)
            if decision is Compatibility.INT_TO_FLOAT else None
        )
        facts.returns.append(ReturnAnalysis(statement, function, value, conversion))

    @staticmethod
    def _compatible(
        owner: ScalarDecl | ArrayDecl | AssignStmt, expression: Expr,
        destination: ScalarType, source: ScalarType, role: str,
        index: int | None, facts: _Build, name: str,
    ) -> None:
        decision = assignment_compatibility(destination, source)
        if decision is Compatibility.INCOMPATIBLE:
            detail = f"array initializer element {index}" if index is not None else role
            raise SemanticError(
                "TYPE_MISMATCH", f"incompatible {detail} type",
                expression.span, name=name,
                expected=destination.name, actual=source.name,
            )
        if decision is Compatibility.INT_TO_FLOAT:
            facts.conversions.append(StatementConversionSite(
                owner, expression, role, source, destination, index,
            ))
