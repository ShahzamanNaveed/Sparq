"""Types, stable symbol identities, and lexical name environments for Sparq."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from sparq.ast_nodes import FunctionDecl, SourceSpan
from sparq.errors import SemanticError
from sparq.token import TokenType


class ScalarType(Enum):
    INT = "INT"
    FLOAT = "FLOAT"
    CHAR = "CHAR"
    STRING = "STRING"
    BOOL = "BOOL"


class VoidType(Enum):
    VOID = "VOID"


ReturnType: TypeAlias = ScalarType | VoidType


def scalar_type(kind: TokenType, span: SourceSpan) -> ScalarType:
    """Convert an AST type token, rejecting VOID and malformed scalar types."""
    try:
        return ScalarType[kind.name]
    except (AttributeError, KeyError):
        actual = kind.name if isinstance(kind, TokenType) else repr(kind)
        raise SemanticError(
            "INVALID_TYPE", "a scalar type is required", span,
            expected="INT, FLOAT, CHAR, STRING, or BOOL", actual=actual,
        ) from None


def return_type(kind: TokenType, span: SourceSpan) -> ReturnType:
    return VoidType.VOID if kind is TokenType.VOID else scalar_type(kind, span)


class SymbolKind(Enum):
    VARIABLE = "VARIABLE"
    PARAMETER = "PARAMETER"
    ARRAY = "ARRAY"


@dataclass(frozen=True, slots=True)
class VariableSymbol:
    id: int
    name: str
    type: ScalarType
    kind: SymbolKind
    scope_id: int
    span: SourceSpan
    array_length: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.type, ScalarType):
            raise ValueError("variable and array element types must be scalar")
        if self.kind is SymbolKind.ARRAY:
            if type(self.array_length) is not int:
                raise ValueError("array symbols require an integer length")
        elif self.array_length is not None:
            raise ValueError("scalar symbols cannot have array lengths")


@dataclass(frozen=True, slots=True)
class FunctionSymbol:
    id: int
    name: str
    parameter_names: tuple[str, ...]
    parameter_types: tuple[ScalarType, ...]
    return_type: ReturnType
    span: SourceSpan
    declaration: FunctionDecl

    def __post_init__(self) -> None:
        for field_name in ("parameter_names", "parameter_types"):
            values = getattr(self, field_name)
            if not isinstance(values, (list, tuple)):
                raise TypeError(f"{field_name} must be a list or tuple")
            object.__setattr__(self, field_name, tuple(values))
        if len(self.parameter_names) != len(self.parameter_types):
            raise ValueError("parameter names and types must have matching lengths")
        if any(not isinstance(name, str) or not name for name in self.parameter_names):
            raise ValueError("parameter names must be nonempty strings")
        if any(not isinstance(kind, ScalarType) for kind in self.parameter_types):
            raise ValueError("parameter types must be scalar")
        if not (isinstance(self.return_type, ScalarType) or self.return_type is VoidType.VOID):
            raise ValueError("function return type must be scalar or VOID")


@dataclass(slots=True)
class SymbolIds:
    """Per-session monotonic IDs; no process-wide mutable counters."""

    _next_symbol: int = 1
    _next_scope: int = 1

    def symbol(self) -> int:
        result = self._next_symbol
        self._next_symbol += 1
        return result

    def scope(self) -> int:
        result = self._next_scope
        self._next_scope += 1
        return result


@dataclass(frozen=True, slots=True, eq=False)
class Scope:
    id: int
    parent: Scope | None = None
    _symbols: dict[str, VariableSymbol] = field(default_factory=dict, init=False, repr=False)
    _sealed: bool = field(default=False, init=False, repr=False)

    def _seal(self) -> None:
        """Finalize a scope after complete program validation."""
        object.__setattr__(self, "_sealed", True)

    def declare(self, symbol: VariableSymbol) -> VariableSymbol:
        """Insert locally; a same-scope duplicate is an error."""
        if self._sealed:
            raise ValueError("completed lexical scope is read-only")
        if symbol.scope_id != self.id:
            raise ValueError("symbol belongs to a different scope")
        if symbol.name in self._symbols:
            raise SemanticError(
                "REDECLARATION", "name already declared in this scope",
                symbol.span, name=symbol.name,
            )
        self._symbols[symbol.name] = symbol
        return symbol

    def lookup_local(self, name: str) -> VariableSymbol | None:
        return self._symbols.get(name)

    def resolve(self, name: str) -> VariableSymbol | None:
        """Return the nearest declaration, or None when the name is absent."""
        scope: Scope | None = self
        while scope is not None:
            found = scope.lookup_local(name)
            if found is not None:
                return found
            scope = scope.parent
        return None

    def require(self, name: str, span: SourceSpan) -> VariableSymbol:
        found = self.resolve(name)
        if found is None:
            raise SemanticError("UNDECLARED_NAME", "name is not declared", span, name=name)
        return found


@dataclass(slots=True)
class FunctionRegistry:
    """Global function namespace, independent of all variable scopes."""

    _functions: dict[str, FunctionSymbol] = field(default_factory=dict, init=False, repr=False)

    def register(self, symbol: FunctionSymbol) -> FunctionSymbol:
        if symbol.name in self._functions:
            raise SemanticError(
                "DUPLICATE_FUNCTION", "function already declared",
                symbol.span, name=symbol.name,
            )
        self._functions[symbol.name] = symbol
        return symbol

    def resolve(self, name: str) -> FunctionSymbol | None:
        return self._functions.get(name)

    def require(self, name: str, span: SourceSpan) -> FunctionSymbol:
        found = self.resolve(name)
        if found is None:
            raise SemanticError("UNKNOWN_FUNCTION", "function is not declared", span, name=name)
        return found

    def __len__(self) -> int:
        return len(self._functions)
