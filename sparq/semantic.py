"""Semantic scopes, signatures, and expression-only type inference."""

from __future__ import annotations

from dataclasses import dataclass

from sparq.ast_nodes import (
    ArrayAccess, ArrayDecl, BinaryExpr, CallExpr, Expr, FunctionDecl,
    LiteralExpr, Parameter, Program, ScalarDecl, UnaryExpr, VarRef,
)
from sparq.errors import SemanticError
from sparq.symbols import (
    FunctionRegistry, FunctionSymbol, ScalarType, Scope, SymbolIds, SymbolKind,
    VariableSymbol, VoidType, return_type, scalar_type,
)
from sparq.token import TokenType
from sparq.type_rules import Compatibility, assignment_compatibility, binary_rule, unary_result


class SemanticContext:
    """One analysis session's function registry, IDs, and active lexical scope."""

    def __init__(self) -> None:
        self.ids = SymbolIds()
        self.functions = FunctionRegistry()
        self.current_scope: Scope | None = None
        self._active_function: FunctionSymbol | None = None
        self._initializing: set[int] = set()
        self._initialized: set[int] = set()
        self._statement_invalid = False

    def collect_signatures(self, program: Program) -> FunctionRegistry:
        """Precollect signatures in source order, without visiting any body."""
        self._ensure_statement_usable()
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
        self._ensure_statement_usable()
        if self.current_scope is not None:
            raise ValueError("exit the active scope before beginning another root")
        self.current_scope = Scope(self.ids.scope())
        return self.current_scope

    def begin_start(self) -> Scope:
        """Create START's independent outer variable scope."""
        scope = self._begin_root()
        self._active_function = None
        return scope

    def begin_function(self, declaration: FunctionDecl) -> Scope:
        """Create one shared parameter/outer-body scope; do not enter another block."""
        signature = self.functions.resolve(declaration.name)
        if signature is None or signature.declaration is not declaration:
            raise ValueError("collect function signatures before opening a function body")
        scope = self._begin_root()
        for parameter in declaration.params:
            self.declare_parameter(parameter)
        self._active_function = signature
        return scope

    def enter_block(self) -> Scope:
        """Enter a nested brace block (never the outermost function body)."""
        return self._enter_child()

    def enter_repeat(self) -> Scope:
        """Enter a REPEAT header scope; enter_block separately for its body."""
        return self._enter_child()

    def _enter_child(self) -> Scope:
        self._ensure_statement_usable()
        if self.current_scope is None:
            raise ValueError("begin START or a function before entering a child scope")
        self.current_scope = Scope(self.ids.scope(), self.current_scope)
        return self.current_scope

    def exit_scope(self) -> Scope | None:
        if self.current_scope is None:
            raise ValueError("there is no active scope to exit")
        self.current_scope = self.current_scope.parent
        if self.current_scope is None:
            self._active_function = None
        return self.current_scope

    @property
    def active_function(self) -> FunctionSymbol | None:
        return self._active_function

    def _scope(self) -> Scope:
        self._ensure_statement_usable()
        if self.current_scope is None:
            raise ValueError("there is no active variable scope")
        return self.current_scope

    def _ensure_statement_usable(self) -> None:
        if self._statement_invalid:
            raise ValueError("semantic context is invalid after failed statement analysis")

    def declare_parameter(self, parameter: Parameter) -> VariableSymbol:
        scope = self._scope()
        if scope.lookup_local(parameter.name) is not None:
            raise SemanticError(
                "DUPLICATE_PARAMETER", "parameter already declared",
                parameter.span, name=parameter.name,
            )
        symbol = scope.declare(VariableSymbol(
            self.ids.symbol(), parameter.name,
            scalar_type(parameter.type_name, parameter.span),
            SymbolKind.PARAMETER, scope.id, parameter.span,
        ))
        self._initialized.add(symbol.id)
        return symbol

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


_LITERAL_TYPES = {
    TokenType.INT_LITERAL: ScalarType.INT,
    TokenType.FLOAT_LITERAL: ScalarType.FLOAT,
    TokenType.CHAR_LITERAL: ScalarType.CHAR,
    TokenType.STRING_LITERAL: ScalarType.STRING,
    TokenType.TRUE: ScalarType.BOOL,
    TokenType.FALSE: ScalarType.BOOL,
}
_OPERATOR_TEXT = {
    TokenType.PLUS: "+", TokenType.MINUS: "-", TokenType.STAR: "*",
    TokenType.SLASH: "/", TokenType.PERCENT: "%",
    TokenType.LESS: "<", TokenType.GREATER: ">",
    TokenType.LESS_EQUAL: "<=", TokenType.GREATER_EQUAL: ">=",
    TokenType.EQUAL_EQUAL: "==", TokenType.BANG_EQUAL: "!=",
    TokenType.AND: "AND", TokenType.OR: "OR", TokenType.NOT: "NOT",
}


@dataclass(frozen=True, slots=True, eq=False)
class ConversionSite:
    """A conversion required at one particular parent/operand use site."""

    parent: BinaryExpr
    operand: Expr
    role: str  # "left" or "right"
    source_type: ScalarType
    destination_type: ScalarType
    context: str  # Numeric operator spelling.

    def __post_init__(self) -> None:
        if not isinstance(self.parent, BinaryExpr):
            raise TypeError("conversion parent must be a binary expression")
        if self.role not in ("left", "right"):
            raise ValueError("conversion role must be left or right")
        if self.operand is not getattr(self.parent, self.role):
            raise ValueError("conversion operand must match its parent and role")
        if self.source_type is not ScalarType.INT or self.destination_type is not ScalarType.FLOAT:
            raise ValueError("only INT-to-FLOAT conversion is supported")
        if self.context != _OPERATOR_TEXT.get(self.parent.operator):
            raise ValueError("conversion context must match its parent operator")
        other_type = ScalarType.FLOAT
        rule = (
            binary_rule(self.parent.operator, ScalarType.INT, other_type)
            if self.role == "left" else
            binary_rule(self.parent.operator, other_type, ScalarType.INT)
        )
        if rule is None or getattr(rule, f"{self.role}_conversion") is not ScalarType.FLOAT:
            raise ValueError("parent operator cannot require INT-to-FLOAT conversion")


@dataclass(frozen=True, slots=True, eq=False)
class ArgumentConversionSite:
    """One INT-to-FLOAT conversion at a specific function argument."""

    call: CallExpr
    function: FunctionSymbol
    argument: Expr
    index: int
    source_type: ScalarType
    destination_type: ScalarType

    def __post_init__(self) -> None:
        if not isinstance(self.call, CallExpr) or not isinstance(self.function, FunctionSymbol):
            raise TypeError("argument conversion needs a call and function symbol")
        if self.call.callee != self.function.name:
            raise ValueError("call and function names differ")
        if (type(self.index) is not int or not 0 <= self.index < len(self.call.args)
                or self.index >= len(self.function.parameter_types)
                or self.call.args[self.index] is not self.argument):
            raise ValueError("argument conversion occurrence is invalid")
        if (self.source_type is not ScalarType.INT
                or self.destination_type is not ScalarType.FLOAT
                or self.function.parameter_types[self.index] is not ScalarType.FLOAT):
            raise ValueError("argument conversion contradicts parameter type")


@dataclass(frozen=True, slots=True, eq=False)
class CallBinding:
    """Validated function identity and ordered intrinsic argument types."""

    call: CallExpr
    function: FunctionSymbol
    argument_types: tuple[ScalarType, ...]
    conversions: tuple[ArgumentConversionSite, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.call, CallExpr) or not isinstance(self.function, FunctionSymbol):
            raise TypeError("call binding needs a call and function symbol")
        if self.call.callee != self.function.name:
            raise ValueError("call and function names differ")
        for name in ("argument_types", "conversions"):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)):
                raise TypeError(f"{name} must be a list or tuple")
            object.__setattr__(self, name, tuple(values))
        if len(self.call.args) != len(self.function.parameter_types) or len(self.argument_types) != len(self.call.args):
            raise ValueError("call binding argument count is inconsistent")
        required = []
        for index, (source, destination) in enumerate(zip(self.argument_types, self.function.parameter_types)):
            if not isinstance(source, ScalarType):
                raise ValueError("argument type must be scalar")
            decision = assignment_compatibility(destination, source)
            if decision is Compatibility.INCOMPATIBLE:
                raise ValueError("argument type is incompatible with parameter")
            if decision is Compatibility.INT_TO_FLOAT:
                required.append(index)
        if len(self.conversions) != len(required):
            raise ValueError("argument conversion coverage is incomplete")
        for site, index in zip(self.conversions, required):
            if (not isinstance(site, ArgumentConversionSite)
                    or site.call is not self.call or site.function is not self.function
                    or site.index != index or site.argument is not self.call.args[index]):
                raise ValueError("argument conversion does not match call binding")

    @property
    def return_type(self) -> ScalarType | VoidType:
        return self.function.return_type


class ExpressionAnnotations:
    """Identity-keyed facts; stored node references prevent ID reuse."""

    def __init__(self) -> None:
        self._types: dict[int, tuple[Expr, ScalarType]] = {}
        self._bindings: dict[int, tuple[Expr, VariableSymbol]] = {}
        self._conversions: dict[int, tuple[Expr, tuple[ConversionSite, ...]]] = {}
        self._calls: dict[int, tuple[CallExpr, CallBinding]] = {}
        self._conversion_order: list[ConversionSite | ArgumentConversionSite] = []

    def type_of(self, expression: Expr) -> ScalarType | None:
        entry = self._types.get(id(expression))
        return entry[1] if entry is not None and entry[0] is expression else None

    def binding_of(self, expression: Expr) -> VariableSymbol | None:
        entry = self._bindings.get(id(expression))
        return entry[1] if entry is not None and entry[0] is expression else None

    def conversions_for(self, expression: Expr) -> tuple[ConversionSite, ...]:
        entry = self._conversions.get(id(expression))
        return entry[1] if entry is not None and entry[0] is expression else ()

    def call_binding_of(self, call: CallExpr) -> CallBinding | None:
        entry = self._calls.get(id(call))
        return entry[1] if entry is not None and entry[0] is call else None

    def function_of(self, call: CallExpr) -> FunctionSymbol | None:
        binding = self.call_binding_of(call)
        return binding.function if binding is not None else None

    def all_conversions(self) -> tuple[ConversionSite | ArgumentConversionSite, ...]:
        """Return conversion occurrences in completed expression traversal order."""
        return tuple(self._conversion_order)

    def _type(self, expression: Expr, kind: ScalarType) -> ScalarType:
        self._types[id(expression)] = (expression, kind)
        return kind

    def _bind(self, expression: Expr, symbol: VariableSymbol) -> None:
        self._bindings[id(expression)] = (expression, symbol)

    def _convert(self, site: ConversionSite) -> None:
        key = id(site.parent)
        entry = self._conversions.get(key)
        previous = entry[1] if entry is not None and entry[0] is site.parent else ()
        self._conversions[key] = (site.parent, previous + (site,))
        self._conversion_order.append(site)

    def _call(self, call: CallExpr, binding: CallBinding) -> None:
        self._calls[id(call)] = (call, binding)

    def _argument_conversion(self, site: ArgumentConversionSite) -> None:
        self._conversion_order.append(site)


@dataclass(frozen=True, slots=True, eq=False)
class ExpressionAnalysis:
    """A successful inference result retaining its standalone expression AST."""

    root: Expr
    type: ScalarType
    annotations: ExpressionAnnotations

    def __post_init__(self) -> None:
        if not isinstance(self.type, ScalarType):
            raise ValueError("expression result type must be scalar")
        if not isinstance(self.annotations, ExpressionAnnotations):
            raise TypeError("expression annotations are required")
        if self.annotations.type_of(self.root) is not self.type:
            raise ValueError("root annotation must match the expression result type")


@dataclass(frozen=True, slots=True, eq=False)
class CallAnalysis:
    """A validated standalone call, including a possible discarded result."""

    call: CallExpr
    binding: CallBinding
    annotations: ExpressionAnnotations

    def __post_init__(self) -> None:
        if not isinstance(self.binding, CallBinding) or self.binding.call is not self.call:
            raise ValueError("call analysis binding does not match its root")
        if not isinstance(self.annotations, ExpressionAnnotations):
            raise TypeError("call analysis annotations are required")
        if self.annotations.call_binding_of(self.call) is not self.binding:
            raise ValueError("call analysis is missing its function binding")
        for argument, kind in zip(self.call.args, self.binding.argument_types):
            if self.annotations.type_of(argument) is not kind:
                raise ValueError("call analysis is missing an argument type")


class ExpressionAnalyzer:
    """Infer supported expression types in one SemanticContext's current scope."""

    def __init__(self, context: SemanticContext) -> None:
        self.context = context

    def infer(self, expression: Expr) -> ExpressionAnalysis:
        """Return a complete result; failed, partial annotations never escape."""
        self.context._ensure_statement_usable()
        annotations = ExpressionAnnotations()
        try:
            result_type = self._infer(expression, annotations)
        except RecursionError as exc:
            raise SemanticError(
                "RESOURCE_LIMIT", "expression nesting exceeds the available analysis stack",
                expression.span,
            ) from exc
        return ExpressionAnalysis(expression, result_type, annotations)

    def analyze_call(self, call: CallExpr) -> CallAnalysis:
        """Validate a standalone call without requiring a scalar result."""
        self.context._ensure_statement_usable()
        if not isinstance(call, CallExpr):
            raise TypeError("expected a CallExpr AST node")
        annotations = ExpressionAnnotations()
        try:
            binding = self._infer_call(call, annotations, value_context=False)
        except RecursionError as exc:
            raise SemanticError(
                "RESOURCE_LIMIT", "call nesting exceeds the available analysis stack",
                call.span,
            ) from exc
        return CallAnalysis(call, binding, annotations)

    def _infer_call(
        self, call: CallExpr, facts: ExpressionAnnotations, *, value_context: bool,
    ) -> CallBinding:
        function = self.context.functions.resolve(call.callee)
        if function is None:
            raise SemanticError(
                "UNKNOWN_FUNCTION", "function is not declared", call.span,
                name=call.callee,
            )
        if len(call.args) != len(function.parameter_types):
            raise SemanticError(
                "ARGUMENT_COUNT", "incorrect number of function arguments", call.span,
                name=call.callee, expected=str(len(function.parameter_types)),
                actual=str(len(call.args)),
            )
        types = []
        conversions = []
        for index, (argument, destination) in enumerate(zip(call.args, function.parameter_types)):
            source = self._infer(argument, facts)
            types.append(source)
            decision = assignment_compatibility(destination, source)
            if decision is Compatibility.INCOMPATIBLE:
                raise SemanticError(
                    "ARGUMENT_TYPE_MISMATCH", f"argument {index + 1} has incompatible type",
                    argument.span, name=call.callee, expected=destination.name,
                    actual=source.name,
                )
            if decision is Compatibility.INT_TO_FLOAT:
                site = ArgumentConversionSite(
                    call, function, argument, index, source, destination,
                )
                conversions.append(site)
                facts._argument_conversion(site)
        binding = CallBinding(call, function, tuple(types), tuple(conversions))
        facts._call(call, binding)
        if value_context:
            if function.return_type is VoidType.VOID:
                raise SemanticError(
                    "VOID_VALUE", "VOID function call has no scalar value", call.span,
                    name=call.callee,
                )
            facts._type(call, function.return_type)
        return binding

    def _infer(self, expression: Expr, facts: ExpressionAnnotations) -> ScalarType:
        if isinstance(expression, LiteralExpr):
            kind = _LITERAL_TYPES.get(expression.kind)
            if kind is None:
                raise ValueError("unsupported literal kind in directly supplied AST")
            return facts._type(expression, kind)

        if isinstance(expression, VarRef):
            scope = self._current_scope()
            symbol = scope.resolve(expression.name)
            if symbol is None:
                if self.context.functions.resolve(expression.name) is not None:
                    raise SemanticError(
                        "FUNCTION_AS_SCALAR", "a function name has no scalar value",
                        expression.span, name=expression.name, expected="scalar variable",
                        actual="function",
                    )
                raise SemanticError(
                    "UNDECLARED_NAME", "name is not declared",
                    expression.span, name=expression.name,
                )
            if symbol.id in self.context._initializing:
                raise SemanticError(
                    "READ_BEFORE_INITIALIZATION", "name read during its own initialization",
                    expression.span, name=expression.name,
                )
            if symbol.kind is SymbolKind.ARRAY:
                raise SemanticError(
                    "ARRAY_AS_SCALAR", "a whole array has no scalar value",
                    expression.span, name=expression.name, expected="scalar variable",
                    actual=f"{symbol.type.name} array",
                )
            facts._bind(expression, symbol)
            return facts._type(expression, symbol.type)

        if isinstance(expression, ArrayAccess):
            symbol = self._current_scope().require(expression.name, expression.span)
            if symbol.id in self.context._initializing:
                raise SemanticError(
                    "READ_BEFORE_INITIALIZATION", "array read during its own initialization",
                    expression.span, name=expression.name,
                )
            if symbol.kind is not SymbolKind.ARRAY:
                raise SemanticError(
                    "WRONG_SYMBOL_KIND", "indexed expression requires an array",
                    expression.span, name=expression.name, expected="array",
                    actual=symbol.kind.name,
                )
            index_type = self._infer(expression.index, facts)
            if index_type is not ScalarType.INT:
                raise SemanticError(
                    "INDEX_TYPE", "array index must be INT",
                    expression.index.span, name=expression.name,
                    expected="INT", actual=index_type.name,
                )
            facts._bind(expression, symbol)
            return facts._type(expression, symbol.type)

        if isinstance(expression, UnaryExpr):
            operand_type = self._infer(expression.operand, facts)
            try:
                result = unary_result(expression.operator, operand_type)
            except ValueError as exc:
                raise ValueError("unsupported unary operator in directly supplied AST") from exc
            if result is None:
                operator = _OPERATOR_TEXT[expression.operator]
                expected = "BOOL" if expression.operator is TokenType.NOT else "INT or FLOAT"
                raise SemanticError(
                    "INVALID_OPERAND_TYPE", "invalid unary operator operand",
                    expression.span, name=operator, expected=expected,
                    actual=operand_type.name,
                )
            return facts._type(expression, result)

        if isinstance(expression, BinaryExpr):
            left_type = self._infer(expression.left, facts)
            right_type = self._infer(expression.right, facts)
            try:
                rule = binary_rule(expression.operator, left_type, right_type)
            except ValueError as exc:
                raise ValueError("unsupported binary operator in directly supplied AST") from exc
            if rule is None:
                operator = _OPERATOR_TEXT[expression.operator]
                if expression.operator in (TokenType.AND, TokenType.OR):
                    expected = "BOOL and BOOL"
                elif expression.operator is TokenType.PERCENT:
                    expected = "INT and INT"
                elif expression.operator in (TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL):
                    expected = "matching scalar types or mixed INT/FLOAT"
                else:
                    expected = "numeric operands"
                raise SemanticError(
                    "INVALID_OPERAND_TYPE", "invalid binary operator operands",
                    expression.span, name=operator, expected=expected,
                    actual=f"{left_type.name} and {right_type.name}",
                )
            for role, operand, source, destination in (
                ("left", expression.left, left_type, rule.left_conversion),
                ("right", expression.right, right_type, rule.right_conversion),
            ):
                if destination is not None:
                    facts._convert(ConversionSite(
                        expression, operand, role, source, destination,
                        _OPERATOR_TEXT[expression.operator],
                    ))
            return facts._type(expression, rule.result_type)

        if isinstance(expression, CallExpr):
            return self._infer_call(expression, facts, value_context=True).return_type

        raise TypeError("expected an expression AST node")

    def _current_scope(self) -> Scope:
        if self.context.current_scope is None:
            raise ValueError("begin START or a function before resolving names")
        return self.context.current_scope
