"""Partial statement and control-flow lowering of validated occurrences.

The caller owns the shared builder and completes its routine. A failed lowerer
invalidates its construction session; discard the builder after any failure.
"""

from __future__ import annotations

from sparq.ast_nodes import (
    ArrayAccess, ArrayDecl, AssignStmt, Block, CallStmt, DoWhileStmt,
    ForStmt, ReadStmt, ReturnStmt, ScalarDecl, SelectStmt, ShowStmt,
    Stmt, VarRef, WhenStmt, WhileStmt,
)
from sparq.expression_lowering import (
    ExpressionLowerer, ExpressionLoweringError, LoweringMetadataError,
    emit_int_to_float,
)
from sparq.ir import (
    ArrayRef, BranchBool, CheckBounds, Compare, Constant, InitArray, InitElement,
    InitScalar, Jump, Move, ParameterRef, ReadElement, ReadScalar, Return,
    RoutineKind, Show,
    StoreElement, Temporary, VariableRef, _DEFAULTS,
)
from sparq.ir_builder import IRBuilder
from sparq.statement_semantic import (
    ExpressionUse, StatementAnalysis, StatementConversionSite, WritableTarget,
)
from sparq.symbols import ScalarType, SymbolKind, VariableSymbol
from sparq.token import TokenType


class StatementLoweringError(ValueError):
    """Controlled statement-lowering failure."""


class StatementInputError(StatementLoweringError):
    """Invalid direct API input or closed construction session."""


class DeferredStatementError(StatementLoweringError):
    """A valid statement belongs to a later checkpoint."""


class StatementMetadataError(StatementLoweringError):
    """Accepted semantic records contradict the requested occurrence."""


class StatementResourceError(StatementLoweringError):
    """Static statement traversal exceeds configured lowering resources."""


class StatementConstructionError(StatementLoweringError):
    """The shared IR builder rejected a statement fragment."""


_SUPPORTED = (ScalarDecl, ArrayDecl, AssignStmt, ReadStmt, ShowStmt, Block,
              WhenStmt, SelectStmt, WhileStmt, DoWhileStmt, ForStmt,
              CallStmt, ReturnStmt)


class StatementLowerer:
    """Append supported occurrences from one StatementAnalysis to one IRBuilder.

    The builder inventory must contain the exact analyzed routine symbols,
    including parameters. No method calls finish() or publishes a program.
    """

    def __init__(
        self, builder: IRBuilder, *, max_depth: int = 256,
        max_statements: int = 10_000,
        expression_max_depth: int = 256, expression_max_nodes: int = 10_000,
    ) -> None:
        if not isinstance(builder, IRBuilder) or builder.is_complete:
            raise StatementInputError("an open IRBuilder is required")
        if (type(max_depth) is not int or max_depth < 1
                or type(max_statements) is not int or max_statements < 1):
            raise StatementInputError("statement limits must be positive integers")
        self.builder = builder
        self.max_depth = max_depth
        self.max_statements = max_statements
        self.expressions = ExpressionLowerer(
            builder, max_depth=expression_max_depth, max_nodes=expression_max_nodes,
        )
        self._failed = False

    @property
    def failed(self) -> bool:
        return self._failed

    def lower_statement(self, analysis: StatementAnalysis, statement: Stmt | None = None) -> None:
        """Append one exact statement occurrence; defaults to the analysis root."""
        self._run(analysis, statement, require_block=False)

    def lower_block(self, analysis: StatementAnalysis, block: Block | None = None) -> None:
        """Append an exact block and its supported statements in source order."""
        self._run(analysis, block, require_block=True)

    def _run(
        self, analysis: StatementAnalysis, selected: Stmt | None, *, require_block: bool,
    ) -> None:
        if self._failed:
            raise StatementInputError("statement lowerer failed; discard its builder")
        try:
            if self.builder.is_complete:
                raise StatementInputError("IR builder is already completed")
            if not isinstance(analysis, StatementAnalysis):
                raise StatementInputError("StatementAnalysis is required")
            if (self.builder.owner.kind is RoutineKind.START and analysis.function is not None
                    or self.builder.owner.kind is RoutineKind.FUNCTION
                    and analysis.function is not self.builder.owner.function):
                raise StatementInputError("analysis belongs to another routine")
            node = analysis.root if selected is None else selected
            if require_block and not isinstance(node, Block):
                raise StatementInputError("lower_block requires a Block occurrence")
            self._preflight(analysis, node)
            if node is analysis.root and isinstance(node, Block):
                scope = analysis.scope_of(node)
                if scope is None or scope.id != self.builder.root_scope_id:
                    raise StatementInputError("builder root scope does not match analysis")
            self._emit(analysis, node)
        except RecursionError as exc:
            self._failed = True
            raise StatementResourceError("statement lowering exceeds the available stack") from exc
        except (StatementLoweringError, ExpressionLoweringError):
            self._failed = True
            raise
        except (TypeError, ValueError) as exc:
            self._failed = True
            raise StatementConstructionError("cannot construct statement IR fragment") from exc

    def _preflight(self, analysis: StatementAnalysis, selected: Stmt) -> None:
        """Find the exact occurrence, then validate only the selected subtree."""
        pending = [analysis.root]
        found = False
        while pending:
            node = pending.pop()
            if node is selected:
                found = True
                break
            if isinstance(node, Block):
                pending.extend(reversed(node.statements))
            elif isinstance(node, WhenStmt):
                if node.else_block is not None:
                    pending.append(node.else_block)
                pending.append(node.then_block)
            elif isinstance(node, SelectStmt):
                if node.default is not None:
                    pending.append(node.default)
                pending.extend(case.body for case in reversed(node.cases))
            elif isinstance(node, (WhileStmt, DoWhileStmt)):
                pending.append(node.body)
            elif isinstance(node, ForStmt):
                pending.append(node.body)
                if node.update is not None:
                    pending.append(node.update)
                if node.initializer is not None:
                    pending.append(node.initializer)
        if not found:
            raise StatementInputError("statement is not an occurrence in this analysis")
        pending = [(selected, 1)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if depth > self.max_depth or count > self.max_statements:
                raise StatementResourceError("statement exceeds lowering resource limit")
            if not isinstance(node, _SUPPORTED):
                raise StatementMetadataError("unsupported statement occurrence")
            if isinstance(node, Block):
                if analysis.scope_of(node) is None:
                    raise StatementMetadataError("block scope metadata is missing")
                pending.extend((child, depth + 1) for child in reversed(node.statements))
            elif isinstance(node, WhenStmt):
                if node.else_block is not None:
                    pending.append((node.else_block, depth + 1))
                pending.append((node.then_block, depth + 1))
            elif isinstance(node, SelectStmt):
                if node.default is not None:
                    pending.append((node.default, depth + 1))
                pending.extend((case.body, depth + 1) for case in reversed(node.cases))
            elif isinstance(node, (WhileStmt, DoWhileStmt)):
                pending.append((node.body, depth + 1))
            elif isinstance(node, ForStmt):
                pending.append((node.body, depth + 1))
                if node.update is not None:
                    pending.append((node.update, depth + 1))
                if node.initializer is not None:
                    pending.append((node.initializer, depth + 1))

    def _condition(self, analysis: StatementAnalysis, node, on_true, on_false) -> None:
        condition = analysis.condition_of(node)
        if condition is None or condition.root is not node.condition:
            raise StatementMetadataError("condition metadata is missing")
        self.expressions.lower_condition(condition, on_true, on_false)

    def _control(self, analysis: StatementAnalysis, node: Stmt) -> None:
        owner = self.builder.owner
        if isinstance(node, WhenStmt):
            on_true = self.builder.label()
            on_false = self.builder.label()
            join = self.builder.label() if node.else_block is not None else on_false
            self._condition(analysis, node, on_true, on_false)
            self.builder.define(on_true, node.then_block.span)
            self.lower_block(analysis, node.then_block)
            if node.else_block is not None:
                self.builder.emit(Jump(owner, node.span, join))
                self.builder.define(on_false, node.else_block.span)
                self.lower_block(analysis, node.else_block)
                self.builder.define(join, node.span)
            else:
                self.builder.define(on_false, node.span)
        elif isinstance(node, SelectStmt):
            selector = analysis.selector_of(node)
            if selector is None or selector.root is not node.selector:
                raise StatementMetadataError("SELECT metadata is missing")
            value = self.expressions.lower_value(selector)
            labels = analysis.labels_of(node)
            if len(labels) != len(node.cases) or any(
                label.clause is not case or label.type is not selector.type
                for label, case in zip(labels, node.cases)
            ):
                raise StatementMetadataError("CASE metadata is missing")
            join = self.builder.label()
            for case, label in zip(node.cases, labels):
                matched, next_case = self.builder.label(), self.builder.label()
                result = self.builder.temp(ScalarType.BOOL)
                self.builder.emit(Compare(owner, case.label.span, TokenType.EQUAL_EQUAL,
                                          value, Constant(label.type, label.value), result))
                self.builder.emit(BranchBool(owner, case.label.span, result, matched, next_case))
                self.builder.define(matched, case.body.span)
                self.lower_block(analysis, case.body)
                self.builder.emit(Jump(owner, case.body.span, join))
                self.builder.define(next_case, case.label.span)
            if node.default is not None:
                self.lower_block(analysis, node.default)
            self.builder.define(join, node.span)
        elif isinstance(node, WhileStmt):
            test, body, exit_label = (self.builder.label() for _ in range(3))
            self.builder.define(test, node.condition.span)
            self._condition(analysis, node, body, exit_label)
            self.builder.define(body, node.body.span)
            self.lower_block(analysis, node.body)
            self.builder.emit(Jump(owner, node.span, test))
            self.builder.define(exit_label, node.span)
        elif isinstance(node, DoWhileStmt):
            body, exit_label = self.builder.label(), self.builder.label()
            self.builder.define(body, node.body.span)
            self.lower_block(analysis, node.body)
            self._condition(analysis, node, body, exit_label)
            self.builder.define(exit_label, node.span)
        elif isinstance(node, ForStmt):
            if analysis.repeat_scope_of(node) is None:
                raise StatementMetadataError("REPEAT header scope metadata is missing")
            if node.initializer is not None:
                self.lower_statement(analysis, node.initializer)
            test, body, exit_label = (self.builder.label() for _ in range(3))
            self.builder.define(test, node.condition.span if node.condition is not None else node.span)
            if node.condition is None:
                self.builder.emit(Jump(owner, node.span, body))
            else:
                self._condition(analysis, node, body, exit_label)
            self.builder.define(body, node.body.span)
            self.lower_block(analysis, node.body)
            if node.update is not None:
                self.lower_statement(analysis, node.update)
            self.builder.emit(Jump(owner, node.span, test))
            self.builder.define(exit_label, node.span)

    @staticmethod
    def _use(analysis: StatementAnalysis, parent: Stmt, role: str,
             index: int | None = None) -> ExpressionUse:
        use = next((item for item in analysis.expressions
                    if item.parent is parent and item.role == role
                    and item.element_index == index), None)
        if use is None:
            raise StatementMetadataError("statement expression metadata is missing")
        return use

    @staticmethod
    def _site(analysis: StatementAnalysis, parent: Stmt, role: str,
              index: int | None = None) -> StatementConversionSite | None:
        return next((item for item in analysis.conversions
                     if item.parent is parent and item.role == role
                     and item.element_index == index), None)

    def _converted(self, analysis: StatementAnalysis, parent: Stmt, role: str,
                   use: ExpressionUse, destination: ScalarType,
                   index: int | None = None):
        operand = self.expressions.lower_value(use.analysis)
        site = self._site(analysis, parent, role, index)
        if site is None:
            if operand.type is not destination:
                raise StatementMetadataError("required statement conversion is missing")
            return operand
        if (site.operand is not use.analysis.root
                or site.source_type is not use.analysis.type
                or site.destination_type is not destination):
            raise StatementMetadataError("statement conversion contradicts its use")
        return emit_int_to_float(
            self.builder, operand, site.source_type, site.destination_type,
            use.analysis.root.span,
        )

    def _storage(self, symbol: VariableSymbol):
        owner = self.builder.owner
        if symbol.kind is SymbolKind.VARIABLE:
            return VariableRef(owner, symbol)
        if symbol.kind is SymbolKind.PARAMETER:
            return ParameterRef(owner, symbol)
        raise StatementMetadataError("scalar target has the wrong symbol kind")

    def _checked(self, target: WritableTarget):
        if (not isinstance(target.target, ArrayAccess)
                or target.index_analysis is None
                or target.index_analysis.root is not target.target.index):
            raise StatementMetadataError("indexed target is missing its analyzed index")
        array = ArrayRef(self.builder.owner, target.symbol)
        index = self.expressions.lower_value(target.index_analysis)
        if not isinstance(index, (Constant, Temporary)) or index.type is not ScalarType.INT:
            raise StatementMetadataError("index must be a captured INT value")
        guard = self.builder.guard(array, index)
        self.builder.emit(CheckBounds(
            self.builder.owner, target.target.span, array, index, guard,
        ))
        return guard

    def _emit(self, analysis: StatementAnalysis, root: Stmt) -> None:
        # Iterative block traversal keeps deeply nested valid ASTs controlled.
        pending = [root]
        owner = self.builder.owner
        while pending:
            node = pending.pop()
            if isinstance(node, Block):
                pending.extend(reversed(node.statements))
            elif isinstance(node, ScalarDecl):
                symbol = analysis.declaration_of(node)
                if symbol is None:
                    raise StatementMetadataError("scalar declaration binding is missing")
                target = VariableRef(owner, symbol)
                if node.initializer is None:
                    default = next((d for d in analysis.defaults if d.parent is node), None)
                    if default is None or default.symbol is not symbol:
                        raise StatementMetadataError("scalar default metadata is missing")
                    value = Constant(symbol.type, default.element_value)
                else:
                    use = self._use(analysis, node, "initializer")
                    value = self._converted(analysis, node, "initializer", use, symbol.type)
                self.builder.emit(InitScalar(owner, node.span, target, value))
            elif isinstance(node, ArrayDecl):
                symbol = analysis.declaration_of(node)
                if symbol is None:
                    raise StatementMetadataError("array declaration binding is missing")
                array = ArrayRef(owner, symbol)
                if node.initializers is None:
                    default = next((d for d in analysis.defaults if d.parent is node), None)
                    if default is None or default.symbol is not symbol or default.length != array.length:
                        raise StatementMetadataError("array default metadata is missing")
                    default_value = default.element_value
                else:
                    default_value = _DEFAULTS[array.element_type]
                self.builder.emit(InitArray(
                    owner, node.span, array, array.length,
                    Constant(array.element_type, default_value),
                ))
                if node.initializers is not None:
                    for position, expression in enumerate(node.initializers):
                        use = self._use(analysis, node, "element", position)
                        value = self._converted(
                            analysis, node, "element", use, array.element_type, position,
                        )
                        self.builder.emit(InitElement(
                            owner, expression.span, array, position, value,
                        ))
            elif isinstance(node, AssignStmt):
                target = analysis.target_of(node)
                if target is None or target.target is not node.target:
                    raise StatementMetadataError("assignment target metadata is missing")
                guard = self._checked(target) if isinstance(node.target, ArrayAccess) else None
                use = self._use(analysis, node, "value")
                value = self._converted(analysis, node, "value", use, target.type)
                if guard is None:
                    self.builder.emit(Move(owner, node.span, self._storage(target.symbol), value))
                else:
                    self.builder.emit(StoreElement(owner, node.span, guard, value))
            elif isinstance(node, ReadStmt):
                target = analysis.read_of(node)
                if target is None or target.target is not node.target:
                    raise StatementMetadataError("READ target metadata is missing")
                if isinstance(node.target, ArrayAccess):
                    self.builder.emit(ReadElement(owner, node.span, self._checked(target)))
                else:
                    self.builder.emit(ReadScalar(owner, node.span, self._storage(target.symbol)))
            elif isinstance(node, ShowStmt):
                expression = analysis.show_of(node)
                if expression is None or expression.root is not node.value:
                    raise StatementMetadataError("SHOW expression metadata is missing")
                value = self.expressions.lower_value(expression)
                self.builder.emit(Show(owner, node.span, value))
            elif isinstance(node, CallStmt):
                call = analysis.call_of(node)
                if call is None or call.call is not node.call:
                    raise StatementMetadataError("CALL statement metadata is missing")
                self.expressions.lower_call(call)
            elif isinstance(node, ReturnStmt):
                result = analysis.return_of(node)
                if (result is None or result.statement is not node
                        or result.function is not owner.function):
                    raise StatementMetadataError("RETURN metadata is missing or belongs to another function")
                value = None
                if result.value is not None:
                    value = self.expressions.lower_value(result.value)
                    if result.conversion is not None:
                        site = result.conversion
                        value = emit_int_to_float(self.builder, value, site.source_type,
                                                  site.destination_type, result.value.root.span)
                self.builder.emit(Return(owner, node.span, value))
            elif isinstance(node, (WhenStmt, SelectStmt, WhileStmt, DoWhileStmt, ForStmt)):
                self._control(analysis, node)
            else:
                raise StatementMetadataError("statement was not preflighted")
