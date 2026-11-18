"""Foundational semantic context; no whole-program validation yet."""

from __future__ import annotations

from sparq.ast_nodes import ArrayDecl, FunctionDecl, Parameter, Program, ScalarDecl
from sparq.errors import SemanticError
from sparq.symbols import (
    FunctionRegistry, FunctionSymbol, Scope, SymbolIds, SymbolKind,
    VariableSymbol, return_type, scalar_type,
)


class SemanticContext:
    """One analysis session's function registry, IDs, and active lexical scope."""

    def __init__(self) -> None:
        self.ids = SymbolIds()
        self.functions = FunctionRegistry()
        self.current_scope: Scope | None = None

    def collect_signatures(self, program: Program) -> FunctionRegistry:
        """Precollect signatures in source order, without visiting any body."""
        for declaration in program.functions:
            if self.functions.resolve(declaration.name) is not None:
                raise SemanticError(
                    "DUPLICATE_FUNCTION", "function already declared",
                    declaration.span, name=declaration.name,
                )
            seen: set[str] = set()
            parameter_types = []
            for parameter in declaration.params:
                if parameter.name in seen:
                    raise SemanticError(
                        "DUPLICATE_PARAMETER", "parameter already declared",
                        parameter.span, name=parameter.name,
                    )
                seen.add(parameter.name)
                parameter_types.append(scalar_type(parameter.type_name, parameter.span))
            result_type = return_type(declaration.return_type, declaration.span)
            self.functions.register(FunctionSymbol(
                self.ids.symbol(), declaration.name,
                tuple(parameter.name for parameter in declaration.params),
                tuple(parameter_types), result_type, declaration.span, declaration,
            ))
        return self.functions

    def _begin_root(self) -> Scope:
        if self.current_scope is not None:
            raise ValueError("exit the active scope before beginning another root")
        self.current_scope = Scope(self.ids.scope())
        return self.current_scope

    def begin_start(self) -> Scope:
        """Create START's independent outer variable scope."""
        return self._begin_root()

    def begin_function(self, declaration: FunctionDecl) -> Scope:
        """Create one shared parameter/outer-body scope; do not enter another block."""
        signature = self.functions.resolve(declaration.name)
        if signature is None or signature.declaration is not declaration:
            raise ValueError("collect function signatures before opening a function body")
        scope = self._begin_root()
        for parameter in declaration.params:
            self.declare_parameter(parameter)
        return scope

    def enter_block(self) -> Scope:
        """Enter a nested brace block (never the outermost function body)."""
        return self._enter_child()

    def enter_repeat(self) -> Scope:
        """Enter a REPEAT header scope; enter_block separately for its body."""
        return self._enter_child()

    def _enter_child(self) -> Scope:
        if self.current_scope is None:
            raise ValueError("begin START or a function before entering a child scope")
        self.current_scope = Scope(self.ids.scope(), self.current_scope)
        return self.current_scope

    def exit_scope(self) -> Scope | None:
        if self.current_scope is None:
            raise ValueError("there is no active scope to exit")
        self.current_scope = self.current_scope.parent
        return self.current_scope

    def _scope(self) -> Scope:
        if self.current_scope is None:
            raise ValueError("there is no active variable scope")
        return self.current_scope

    def declare_parameter(self, parameter: Parameter) -> VariableSymbol:
        scope = self._scope()
        if scope.lookup_local(parameter.name) is not None:
            raise SemanticError(
                "DUPLICATE_PARAMETER", "parameter already declared",
                parameter.span, name=parameter.name,
            )
        return scope.declare(VariableSymbol(
            self.ids.symbol(), parameter.name,
            scalar_type(parameter.type_name, parameter.span),
            SymbolKind.PARAMETER, scope.id, parameter.span,
        ))

    def declare_scalar(self, declaration: ScalarDecl) -> VariableSymbol:
        """Register before inspecting its initializer in a later semantic pass."""
        scope = self._scope()
        return scope.declare(VariableSymbol(
            self.ids.symbol(), declaration.name,
            scalar_type(declaration.type_name, declaration.span),
            SymbolKind.VARIABLE, scope.id, declaration.span,
        ))

    def declare_array(self, declaration: ArrayDecl) -> VariableSymbol:
        """Store parsed size metadata; positivity/initializer checks come later."""
        scope = self._scope()
        return scope.declare(VariableSymbol(
            self.ids.symbol(), declaration.name,
            scalar_type(declaration.element_type, declaration.span),
            SymbolKind.ARRAY, scope.id, declaration.span,
            declaration.size.value,
        ))
