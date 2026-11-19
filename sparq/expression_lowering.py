"""Lower validated scalar expressions into one routine's typed IR builder.

This is an internal M5 checkpoint component, not a complete TAC generator.
Calls are deliberately deferred. A failed call invalidates the
lowerer; callers discard its builder rather than publishing partial output.
"""

from __future__ import annotations

from typing import cast

from sparq.ast_nodes import (
    ArrayAccess, BinaryExpr, CallExpr, Expr, LiteralExpr, SourceSpan,
    UnaryExpr, VarRef,
)
from sparq.ir import (
    ArrayRef, Binary, BoolMergeTemp, BranchBool, CheckBounds, Compare, Constant,
    Convert, Jump, LabelRef, Load, LoadElement, Move, ParameterRef, Temporary,
    Unary, Value, VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.semantic import ConversionSite, ExpressionAnalysis, ExpressionAnnotations
from sparq.symbols import ScalarType, SymbolKind, VariableSymbol
from sparq.token import TokenType
from sparq.type_rules import binary_rule, unary_result


class ExpressionLoweringError(ValueError):
    """Base class for controlled scalar-lowering failures."""


class LoweringInputError(ExpressionLoweringError):
    """The direct component API received an invalid argument or context."""


class DeferredExpressionError(ExpressionLoweringError):
    """A valid expression category belongs to a later M5 checkpoint."""


class LoweringMetadataError(ExpressionLoweringError):
    """The supplied semantic facts do not describe their expression tree."""


class LoweringResourceError(ExpressionLoweringError):
    """A static expression-lowering resource limit was reached."""


class LoweringConstructionError(ExpressionLoweringError):
    """The owning IR builder could not construct the requested fragment."""


_LITERAL_TYPES = {
    TokenType.INT_LITERAL: ScalarType.INT,
    TokenType.FLOAT_LITERAL: ScalarType.FLOAT,
    TokenType.CHAR_LITERAL: ScalarType.CHAR,
    TokenType.STRING_LITERAL: ScalarType.STRING,
    TokenType.TRUE: ScalarType.BOOL,
    TokenType.FALSE: ScalarType.BOOL,
}
_ARITHMETIC = frozenset({
    TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
    TokenType.PERCENT,
})
_COMPARISON = frozenset({
    TokenType.LESS, TokenType.GREATER, TokenType.LESS_EQUAL,
    TokenType.GREATER_EQUAL, TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL,
})
_SHORT_CIRCUIT = frozenset({TokenType.AND, TokenType.OR})
_EXPRESSION_TYPES = (LiteralExpr, VarRef, ArrayAccess, CallExpr, UnaryExpr, BinaryExpr)


def emit_int_to_float(
    builder: IRBuilder, operand: Value, source_type: ScalarType,
    destination_type: ScalarType, span: SourceSpan,
) -> Temporary:
    """Materialize one already validated conversion at its evaluated use site."""
    if (source_type is not ScalarType.INT or destination_type is not ScalarType.FLOAT
            or operand.type is not source_type or not isinstance(span, SourceSpan)):
        raise LoweringMetadataError("INT-to-FLOAT conversion contradicts its operand")
    result = builder.temp(ScalarType.FLOAT)
    builder.emit(Convert(builder.owner, span, operand, result))
    return result


class ExpressionLowerer:
    """Append one supported expression occurrence to an open, owned IRBuilder.

    ExpressionAnalysis must come from the owning accepted semantic session.
    The builder's local inventory must contain the exact resolved symbols.
    Pure literals have no symbol through which to independently prove session
    ownership; that is a caller precondition until whole-program integration.
    """

    def __init__(
        self, builder: IRBuilder, *, max_depth: int = 256, max_nodes: int = 10_000,
    ) -> None:
        if not isinstance(builder, IRBuilder) or builder.is_complete:
            raise LoweringInputError("an open IRBuilder is required")
        if type(max_depth) is not int or max_depth < 1:
            raise LoweringInputError("max_depth must be a positive integer")
        if type(max_nodes) is not int or max_nodes < 1:
            raise LoweringInputError("max_nodes must be a positive integer")
        self._builder = builder
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self._failed = False

    @property
    def builder(self) -> IRBuilder:
        return self._builder

    @property
    def failed(self) -> bool:
        return self._failed

    def lower_value(self, analysis: ExpressionAnalysis) -> Value:
        """Return a Constant, ordinary Temporary, or BOOL merge temporary."""
        return cast(Value, self._run(analysis, None))

    def lower_condition(
        self, analysis: ExpressionAnalysis, true_label: LabelRef, false_label: LabelRef,
    ) -> None:
        """Branch to caller-owned labels; the caller defines those destinations."""
        self._run(analysis, (true_label, false_label))

    def _run(
        self, analysis: ExpressionAnalysis, destinations: tuple[LabelRef, LabelRef] | None,
    ) -> Value | None:
        if self._failed:
            raise LoweringInputError("expression lowerer failed; discard its builder")
        try:
            if self.builder.is_complete:
                raise LoweringInputError("IR builder is already completed")
            if not isinstance(analysis, ExpressionAnalysis):
                raise LoweringInputError("ExpressionAnalysis is required")
            if destinations is not None:
                if analysis.type is not ScalarType.BOOL:
                    raise LoweringInputError("condition lowering requires a BOOL expression")
                if any(not isinstance(label, LabelRef)
                       or label.owner is not self.builder.owner for label in destinations):
                    raise LoweringInputError("condition labels must belong to the builder routine")
            self._preflight(analysis)
            if destinations is None:
                return self._value(analysis.root, analysis.annotations)
            self._condition(analysis.root, analysis.annotations, *destinations)
            return None
        except RecursionError as exc:
            self._failed = True
            raise LoweringResourceError("expression lowering exceeds the available stack") from exc
        except ExpressionLoweringError:
            self._failed = True
            raise
        except (TypeError, ValueError) as exc:
            self._failed = True
            raise LoweringConstructionError("cannot construct scalar IR fragment") from exc

    def _preflight(self, analysis: ExpressionAnalysis) -> None:
        """Check support and occurrence-specific facts before any emission."""
        facts = analysis.annotations
        stack: list[tuple[Expr, int]] = [(analysis.root, 1)]
        seen = 0
        while stack:
            node, depth = stack.pop()
            seen += 1
            if depth > self.max_depth or seen > self.max_nodes:
                raise LoweringResourceError("expression exceeds lowering resource limit")
            if not isinstance(node, _EXPRESSION_TYPES) or not isinstance(node.span, SourceSpan):
                raise LoweringMetadataError("expression node or source span is invalid")
            kind = facts.type_of(node)
            if not isinstance(kind, ScalarType):
                raise LoweringMetadataError("expression is missing an intrinsic type annotation")
            if isinstance(node, CallExpr):
                raise DeferredExpressionError("function call lowering belongs to a later M5 task")
            if isinstance(node, LiteralExpr):
                if _LITERAL_TYPES.get(node.kind) is not kind:
                    raise LoweringMetadataError("literal kind contradicts its semantic type")
                try:
                    Constant(kind, node.value, node.lexeme)
                except (TypeError, ValueError) as exc:
                    raise LoweringMetadataError("literal value contradicts its semantic type") from exc
            elif isinstance(node, VarRef):
                symbol = facts.binding_of(node)
                if (not isinstance(symbol, VariableSymbol) or symbol.name != node.name
                        or symbol.type is not kind
                        or symbol.kind not in (SymbolKind.VARIABLE, SymbolKind.PARAMETER)):
                    raise LoweringMetadataError("scalar reference lacks a matching semantic binding")
            elif isinstance(node, ArrayAccess):
                symbol = facts.binding_of(node)
                if (not isinstance(symbol, VariableSymbol) or symbol.name != node.name
                        or symbol.type is not kind or symbol.kind is not SymbolKind.ARRAY
                        or facts.type_of(node.index) is not ScalarType.INT):
                    raise LoweringMetadataError("array access lacks a matching array or INT index")
                stack.append((node.index, depth + 1))
            elif isinstance(node, UnaryExpr):
                operand_type = facts.type_of(node.operand)
                try:
                    expected = unary_result(node.operator, operand_type)
                except (TypeError, ValueError) as exc:
                    raise LoweringMetadataError("unary metadata is inconsistent") from exc
                if expected is not kind:
                    raise LoweringMetadataError("unary result contradicts semantic annotations")
                stack.append((node.operand, depth + 1))
            else:
                left_type = facts.type_of(node.left)
                right_type = facts.type_of(node.right)
                try:
                    rule = binary_rule(node.operator, left_type, right_type)
                except (TypeError, ValueError) as exc:
                    raise LoweringMetadataError("binary metadata is inconsistent") from exc
                if rule is None or rule.result_type is not kind:
                    raise LoweringMetadataError("binary result contradicts semantic annotations")
                required = tuple(
                    (role, operand, source, destination)
                    for role, operand, source, destination in (
                        ("left", node.left, left_type, rule.left_conversion),
                        ("right", node.right, right_type, rule.right_conversion),
                    ) if destination is not None
                )
                sites = facts.conversions_for(node)
                if len(sites) != len(required) or any(
                    not isinstance(site, ConversionSite)
                    or site.parent is not node or site.role != role
                    or site.operand is not operand or site.source_type is not source
                    or site.destination_type is not destination
                    for site, (role, operand, source, destination) in zip(sites, required)
                ):
                    raise LoweringMetadataError("binary conversion sites are incomplete or misplaced")
                stack.append((node.right, depth + 1))
                stack.append((node.left, depth + 1))

    def _value(self, node: Expr, facts: ExpressionAnnotations) -> Value:
        owner = self.builder.owner
        kind = facts.type_of(node)
        if isinstance(node, LiteralExpr):
            return Constant(kind, node.value, node.lexeme)
        if isinstance(node, VarRef):
            symbol = facts.binding_of(node)
            source = (ParameterRef(owner, symbol) if symbol.kind is SymbolKind.PARAMETER
                      else VariableRef(owner, symbol))
            result = self.builder.temp(kind)
            self.builder.emit(Load(owner, node.span, source, result))
            return result
        if isinstance(node, ArrayAccess):
            array = ArrayRef(owner, facts.binding_of(node))
            index = self._value(node.index, facts)
            if not isinstance(index, (Constant, Temporary)) or index.type is not ScalarType.INT:
                raise LoweringMetadataError("array index must be a captured INT value")
            guard = self.builder.guard(array, index)
            self.builder.emit(CheckBounds(owner, node.span, array, index, guard))
            result = self.builder.temp(kind)
            self.builder.emit(LoadElement(owner, node.span, guard, result))
            return result
        if isinstance(node, UnaryExpr):
            if (node.operator is TokenType.NOT and isinstance(node.operand, BinaryExpr)
                    and node.operand.operator in _SHORT_CIRCUIT):
                return self._materialize_bool(node, facts)
            operand = self._value(node.operand, facts)
            result = self.builder.temp(kind)
            self.builder.emit(Unary(owner, node.span, node.operator, operand, result))
            return result
        if isinstance(node, BinaryExpr):
            if node.operator in _SHORT_CIRCUIT:
                return self._materialize_bool(node, facts)
            sites = {site.role: site for site in facts.conversions_for(node)}
            left = self._value(node.left, facts)
            if "left" in sites:
                left = self._convert(left, sites["left"])
            right = self._value(node.right, facts)
            if "right" in sites:
                right = self._convert(right, sites["right"])
            result = self.builder.temp(kind)
            if node.operator in _ARITHMETIC:
                instruction = Binary(owner, node.span, node.operator, left, right, result)
            elif node.operator in _COMPARISON:
                instruction = Compare(owner, node.span, node.operator, left, right, result)
            else:
                raise LoweringMetadataError("unsupported binary operator annotation")
            self.builder.emit(instruction)
            return result
        raise LoweringMetadataError("expression category was not preflighted")

    def _convert(self, operand: Value, site: ConversionSite) -> Temporary:
        return emit_int_to_float(
            self.builder, operand, site.source_type, site.destination_type,
            site.operand.span,
        )

    def _condition(
        self, node: Expr, facts: ExpressionAnnotations,
        true_label: LabelRef, false_label: LabelRef,
    ) -> None:
        owner = self.builder.owner
        if isinstance(node, UnaryExpr) and node.operator is TokenType.NOT:
            self._condition(node.operand, facts, false_label, true_label)
        elif isinstance(node, BinaryExpr) and node.operator in _SHORT_CIRCUIT:
            rhs_label = self.builder.label()
            if node.operator is TokenType.AND:
                self._condition(node.left, facts, rhs_label, false_label)
            else:
                self._condition(node.left, facts, true_label, rhs_label)
            self.builder.define(rhs_label, node.span)
            self._condition(node.right, facts, true_label, false_label)
        else:
            value = self._value(node, facts)
            self.builder.emit(BranchBool(owner, node.span, value, true_label, false_label))

    def _materialize_bool(self, node: Expr, facts: ExpressionAnnotations) -> BoolMergeTemp:
        owner = self.builder.owner
        merge = self.builder.merge_temp()
        on_true, on_false, join = (self.builder.label() for _ in range(3))
        self._condition(node, facts, on_true, on_false)
        self.builder.define(on_true, node.span)
        self.builder.emit(Move(owner, node.span, merge, Constant(ScalarType.BOOL, True)))
        self.builder.emit(Jump(owner, node.span, join))
        self.builder.define(on_false, node.span)
        self.builder.emit(Move(owner, node.span, merge, Constant(ScalarType.BOOL, False)))
        self.builder.define(join, node.span)
        return merge
