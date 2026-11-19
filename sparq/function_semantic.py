"""Function-body validation and conservative structural RETURN guarantees."""

from __future__ import annotations

from dataclasses import dataclass

from sparq.ast_nodes import (
    Block, DoWhileStmt, ForStmt, FunctionDecl, ReturnStmt, SelectStmt,
    Stmt, WhenStmt, WhileStmt,
)
from sparq.errors import SemanticError
from sparq.semantic import SemanticContext
from sparq.statement_semantic import StatementAnalysis, StatementAnalyzer
from sparq.symbols import FunctionSymbol, Scope, SymbolKind, VariableSymbol, VoidType


def check_guaranteed_return(statement: Stmt) -> bool:
    """Apply the frozen conservative structural rules without evaluating values."""
    answers: dict[int, bool] = {}
    pending: list[tuple[Stmt, bool]] = [(statement, False)]
    while pending:
        node, ready = pending.pop()
        if not ready:
            pending.append((node, True))
            if isinstance(node, Block):
                pending.extend((child, False) for child in reversed(node.statements))
            elif isinstance(node, WhenStmt):
                pending.append((node.then_block, False))
                if node.else_block is not None:
                    pending.append((node.else_block, False))
            elif isinstance(node, SelectStmt):
                pending.extend((case.body, False) for case in reversed(node.cases))
                if node.default is not None:
                    pending.append((node.default, False))
            elif isinstance(node, DoWhileStmt):
                pending.append((node.body, False))
            continue
        if isinstance(node, ReturnStmt):
            result = True
        elif isinstance(node, Block):
            result = any(answers[id(child)] for child in node.statements)
        elif isinstance(node, WhenStmt):
            result = (node.else_block is not None
                      and answers[id(node.then_block)] and answers[id(node.else_block)])
        elif isinstance(node, SelectStmt):
            result = (node.default is not None
                      and answers[id(node.default)]
                      and all(answers[id(case.body)] for case in node.cases))
        elif isinstance(node, DoWhileStmt):
            result = answers[id(node.body)]
        elif isinstance(node, (WhileStmt, ForStmt)):
            result = False
        else:
            result = False
        answers[id(node)] = result
    return answers[id(statement)]


@dataclass(frozen=True, slots=True, eq=False)
class FunctionAnalysis:
    declaration: FunctionDecl
    function: FunctionSymbol
    scope: Scope
    parameters: tuple[VariableSymbol, ...]
    body: StatementAnalysis
    guarantees_return: bool

    def __post_init__(self) -> None:
        if (not isinstance(self.declaration, FunctionDecl)
                or not isinstance(self.function, FunctionSymbol)
                or self.function.declaration is not self.declaration
                or not isinstance(self.scope, Scope)
                or not isinstance(self.body, StatementAnalysis)
                or self.body.root is not self.declaration.body
                or self.body.scope_of(self.declaration.body) is not self.scope
                or self.body.function is not self.function):
            raise ValueError("function result metadata does not match its body")
        if not isinstance(self.parameters, (list, tuple)):
            raise TypeError("parameters must be a list or tuple")
        object.__setattr__(self, "parameters", tuple(self.parameters))
        if len(self.parameters) != len(self.function.parameter_types):
            raise ValueError("function parameter binding coverage is incomplete")
        for symbol, name, kind in zip(
            self.parameters, self.function.parameter_names, self.function.parameter_types,
        ):
            if (not isinstance(symbol, VariableSymbol)
                    or symbol.kind is not SymbolKind.PARAMETER
                    or symbol.name != name or symbol.type is not kind
                    or symbol.scope_id != self.scope.id
                    or self.scope.lookup_local(name) is not symbol):
                raise ValueError("function parameter binding contradicts its scope")
        if type(self.guarantees_return) is not bool:
            raise TypeError("return guarantee must be a bool")
        if self.guarantees_return != check_guaranteed_return(self.declaration.body):
            raise ValueError("return guarantee contradicts the function body")
        if self.function.return_type is not VoidType.VOID and not self.guarantees_return:
            raise ValueError("successful non-VOID function result must guarantee RETURN")


class FunctionAnalyzer:
    """Validate one function with supported statements after signature collection."""

    def __init__(self, context: SemanticContext) -> None:
        self.context = context

    def analyze_function(self, declaration: FunctionDecl) -> FunctionAnalysis:
        self.context._ensure_statement_usable()
        if self.context.current_scope is not None:
            raise ValueError("exit the active root scope before analyzing a function")
        scope = self.context.begin_function(declaration)
        function = self.context.active_function
        try:
            body = StatementAnalyzer(self.context).analyze_block(declaration.body)
            guaranteed = check_guaranteed_return(declaration.body)
            if function.return_type is not VoidType.VOID and not guaranteed:
                raise SemanticError(
                    "MISSING_RETURN", "function may reach its end without RETURN",
                    declaration.span, name=function.name,
                    expected=function.return_type.name,
                )
            parameters = tuple(scope.lookup_local(name) for name in function.parameter_names)
            return FunctionAnalysis(declaration, function, scope, parameters, body, guaranteed)
        except RecursionError as exc:
            self.context._statement_invalid = True
            raise SemanticError(
                "RESOURCE_LIMIT", "function analysis exceeds the available stack",
                declaration.span, name=declaration.name,
            ) from exc
        except Exception:
            self.context._statement_invalid = True
            raise
        finally:
            self.context.exit_scope()
