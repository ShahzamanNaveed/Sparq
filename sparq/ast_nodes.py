"""Syntax-only Sparq AST records.

All spans use 1-based positions and exclusive ends. These records do not
contain inferred types, resolved symbols, or runtime values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from sparq.token import Token, TokenType


def _collection_tuple(value: object, field: str) -> tuple:
    """Snapshot caller lists while keeping tuple-valued AST collections intact."""
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise TypeError(f"{field} must be a list or tuple")


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        start = (self.start_line, self.start_column)
        end = (self.end_line, self.end_column)
        if min(*start, *end) < 1 or end < start:
            raise ValueError("SourceSpan needs positive positions and end >= start")

    @classmethod
    def from_token(cls, token: Token) -> SourceSpan:
        return cls(token.line, token.column, token.end_line, token.end_column)


@dataclass(frozen=True, slots=True)
class Program:
    functions: tuple[FunctionDecl, ...]
    main: Block
    span: SourceSpan

    def __post_init__(self) -> None:
        object.__setattr__(self, "functions", _collection_tuple(self.functions, "functions"))


@dataclass(frozen=True, slots=True)
class FunctionDecl:
    name: str
    params: tuple[Parameter, ...]
    return_type: TokenType
    body: Block
    span: SourceSpan

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", _collection_tuple(self.params, "params"))


@dataclass(frozen=True, slots=True)
class Parameter:
    type_name: TokenType
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Block:
    statements: tuple[Stmt, ...]
    span: SourceSpan

    def __post_init__(self) -> None:
        object.__setattr__(self, "statements", _collection_tuple(self.statements, "statements"))


@dataclass(frozen=True, slots=True)
class ScalarDecl:
    type_name: TokenType
    name: str
    initializer: Expr | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ArrayDecl:
    element_type: TokenType
    name: str
    size: LiteralExpr
    initializers: tuple[Expr, ...] | None
    span: SourceSpan

    def __post_init__(self) -> None:
        if self.initializers is not None:
            object.__setattr__(
                self, "initializers", _collection_tuple(self.initializers, "initializers")
            )


@dataclass(frozen=True, slots=True)
class AssignStmt:
    target: VarRef | ArrayAccess
    value: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CallStmt:
    call: CallExpr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class WhenStmt:
    condition: Expr
    then_block: Block
    else_block: Block | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class SelectStmt:
    selector: Expr
    cases: tuple[CaseClause, ...]
    default: Block | None
    span: SourceSpan

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", _collection_tuple(self.cases, "cases"))


@dataclass(frozen=True, slots=True)
class CaseClause:
    label: LiteralExpr | UnaryExpr
    body: Block
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ForStmt:
    initializer: ScalarDecl | AssignStmt | None
    condition: Expr | None
    update: AssignStmt | None
    body: Block
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class WhileStmt:
    condition: Expr
    body: Block
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class DoWhileStmt:
    body: Block
    condition: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ReturnStmt:
    value: Expr | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ReadStmt:
    target: VarRef | ArrayAccess
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ShowStmt:
    value: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LiteralExpr:
    kind: TokenType
    value: object
    lexeme: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class VarRef:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ArrayAccess:
    name: str
    index: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CallExpr:
    callee: str
    args: tuple[Expr, ...]
    span: SourceSpan

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", _collection_tuple(self.args, "args"))


@dataclass(frozen=True, slots=True)
class UnaryExpr:
    operator: TokenType
    operand: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BinaryExpr:
    operator: TokenType
    left: Expr
    right: Expr
    span: SourceSpan


Expr: TypeAlias = LiteralExpr | VarRef | ArrayAccess | CallExpr | UnaryExpr | BinaryExpr
Stmt: TypeAlias = (
    Block | ScalarDecl | ArrayDecl | AssignStmt | CallStmt | WhenStmt
    | SelectStmt | ForStmt | WhileStmt | DoWhileStmt | ReturnStmt
    | ReadStmt | ShowStmt
)
