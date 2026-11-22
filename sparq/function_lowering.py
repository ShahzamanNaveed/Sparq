"""Build one analyzed function routine; whole-program TAC remains a later step."""

from __future__ import annotations

from sparq.function_semantic import FunctionAnalysis
from sparq.ir import (
    ArrayRef, FunctionRef, IRFunction, ParameterRef, Return, RoutineId,
    VariableRef,
)
from sparq.ir_builder import IRBuilder
from sparq.statement_lowering import StatementLowerer
from sparq.symbols import SymbolKind, VoidType


def lower_function(analysis: FunctionAnalysis, **statement_limits: int) -> IRFunction:
    """Return a structurally completed routine using exact analyzed symbols."""
    if not isinstance(analysis, FunctionAnalysis):
        raise TypeError("FunctionAnalysis is required")
    owner = RoutineId.for_function(analysis.function)
    parameters = tuple(ParameterRef(owner, symbol) for symbol in analysis.parameters)
    locals_ = parameters + tuple(
        ArrayRef(owner, symbol) if symbol.kind is SymbolKind.ARRAY
        else VariableRef(owner, symbol)
        for _, symbol in analysis.body.declarations
    )
    builder = IRBuilder(owner, analysis.scope.id, parameters=parameters,
                        local_symbols=locals_)
    StatementLowerer(builder, **statement_limits).lower_block(analysis.body)
    if analysis.function.return_type is VoidType.VOID and not analysis.guarantees_return:
        builder.emit(Return(owner, analysis.declaration.body.span))
    return IRFunction(FunctionRef(analysis.function), parameters, builder.finish())
