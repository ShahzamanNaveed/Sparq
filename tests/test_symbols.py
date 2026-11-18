"""Infrastructure tests, not complete semantic program validation."""

from dataclasses import FrozenInstanceError

import pytest

from sparq.ast_nodes import Block, FunctionDecl, SourceSpan
from sparq.errors import SemanticError
from sparq.symbols import (
    FunctionSymbol, ScalarType, Scope, SymbolIds, SymbolKind, VariableSymbol,
    VoidType, scalar_type,
)
from sparq.token import TokenType


SPAN = SourceSpan(2, 3, 2, 8)


def variable(ids, scope, name, *, kind=SymbolKind.VARIABLE, length=None):
    return VariableSymbol(
        ids.symbol(), name, ScalarType.INT, kind, scope.id, SPAN, length,
    )


def test_scalar_type_representation_excludes_void_and_other_tokens():
    assert tuple(t.name for t in ScalarType) == ("INT", "FLOAT", "CHAR", "STRING", "BOOL")
    for kind in (TokenType.VOID, TokenType.START):
        with pytest.raises(SemanticError) as caught:
            scalar_type(kind, SPAN)
        assert caught.value.category == "INVALID_TYPE"
        assert (caught.value.line, caught.value.column) == (2, 3)


def test_distinct_declarations_and_shadowing_have_stable_identity():
    ids = SymbolIds()
    outer = Scope(ids.scope())
    first = outer.declare(variable(ids, outer, "x"))
    second = outer.declare(variable(ids, outer, "y"))
    inner = Scope(ids.scope(), outer)
    shadow = inner.declare(variable(ids, inner, "x"))
    assert len({first.id, second.id, shadow.id}) == 3
    assert inner.resolve("x") is shadow
    assert inner.resolve("x") is shadow
    assert inner.resolve("y") is second
    assert outer.resolve("x") is first
    assert outer.resolve("missing") is None


def test_ids_restart_in_fresh_sessions_without_shared_symbol_state():
    left, right = SymbolIds(), SymbolIds()
    left_scope, right_scope = Scope(left.scope()), Scope(right.scope())
    left_scope.declare(variable(left, left_scope, "left"))
    assert right_scope.lookup_local("left") is None
    assert right_scope.declare(variable(right, right_scope, "right")).id == 1
    assert (left_scope.id, right_scope.id) == (1, 1)


def test_duplicate_local_declaration_is_controlled_and_retains_first_symbol():
    ids = SymbolIds()
    scope = Scope(ids.scope())
    original = scope.declare(variable(ids, scope, "x"))
    with pytest.raises(SemanticError) as caught:
        scope.declare(variable(ids, scope, "x"))
    error = caught.value
    assert (error.category, error.name, error.line, error.column) == (
        "REDECLARATION", "x", 2, 3,
    )
    assert "x" in str(error)
    assert scope.lookup_local("x") is original


def test_child_and_sibling_names_do_not_leak():
    ids = SymbolIds()
    root = Scope(ids.scope())
    child = Scope(ids.scope(), root)
    nested = Scope(ids.scope(), child)
    symbol = nested.declare(variable(ids, nested, "local"))
    sibling = Scope(ids.scope(), root)
    assert nested.lookup_local("local") is symbol
    assert root.resolve("local") is None
    assert child.resolve("local") is None
    assert sibling.resolve("local") is None
    with pytest.raises(SemanticError) as caught:
        sibling.require("local", SPAN)
    assert (caught.value.category, caught.value.name) == ("UNDECLARED_NAME", "local")


def test_parent_resolution_is_iterative_at_deep_nesting():
    ids = SymbolIds()
    scope = Scope(ids.scope())
    root_symbol = scope.declare(variable(ids, scope, "root"))
    for _ in range(1200):
        scope = Scope(ids.scope(), scope)
    assert scope.resolve("root") is root_symbol


def test_array_metadata_is_distinct_from_scalar_type():
    ids = SymbolIds()
    scope = Scope(ids.scope())
    array = scope.declare(variable(ids, scope, "items", kind=SymbolKind.ARRAY, length=3))
    assert (array.kind, array.type, array.array_length) == (
        SymbolKind.ARRAY, ScalarType.INT, 3,
    )
    with pytest.raises(ValueError):
        variable(ids, scope, "bad", kind=SymbolKind.ARRAY)


def function_symbol(names=(), types=(), result=VoidType.VOID):
    declaration = FunctionDecl("f", (), TokenType.VOID, Block((), SPAN), SPAN)
    return FunctionSymbol(1, "f", names, types, result, SPAN, declaration)


def test_every_scalar_type_is_valid_for_variables_parameters_arrays_and_returns():
    for scalar in ScalarType:
        for kind, length in (
            (SymbolKind.VARIABLE, None),
            (SymbolKind.PARAMETER, None),
            (SymbolKind.ARRAY, 4),
        ):
            symbol = VariableSymbol(1, "x", scalar, kind, 1, SPAN, length)
            assert symbol.type is scalar
        assert function_symbol(("x",), (scalar,), scalar).return_type is scalar
    assert function_symbol().return_type is VoidType.VOID


@pytest.mark.parametrize("invalid", [VoidType.VOID, TokenType.INT, "INT", 1, True])
@pytest.mark.parametrize("kind, length", [
    (SymbolKind.VARIABLE, None),
    (SymbolKind.PARAMETER, None),
    (SymbolKind.ARRAY, 2),
])
def test_direct_symbol_construction_rejects_non_scalar_types(invalid, kind, length):
    with pytest.raises(ValueError, match="scalar"):
        VariableSymbol(1, "x", invalid, kind, 1, SPAN, length)


def test_function_symbol_snapshots_mutable_collections_and_preserves_order():
    names = ["first", "second"]
    types = [ScalarType.INT, ScalarType.FLOAT]
    symbol = function_symbol(names, types)
    names.append("third")
    types.append(ScalarType.BOOL)
    names[0] = "changed"
    types[0] = ScalarType.STRING
    assert symbol.parameter_names == ("first", "second")
    assert symbol.parameter_types == (ScalarType.INT, ScalarType.FLOAT)
    assert isinstance(symbol.parameter_names, tuple)
    assert isinstance(symbol.parameter_types, tuple)
    with pytest.raises(FrozenInstanceError):
        symbol.parameter_names = ()
    assert function_symbol(("x",), (ScalarType.CHAR,)).parameter_names == ("x",)
    assert function_symbol().parameter_types == ()


def test_function_symbol_rejects_mismatched_or_malformed_parameter_collections():
    with pytest.raises(ValueError, match="matching lengths"):
        function_symbol(("x", "y"), (ScalarType.INT,))
    for names, types in (("x", (ScalarType.INT,)), (("x",), "INT"),
                         (123, ()), ((), None)):
        with pytest.raises(TypeError, match="parameter_"):
            function_symbol(names, types)
    for names in (("",), (17,)):
        with pytest.raises(ValueError, match="names"):
            function_symbol(names, (ScalarType.INT,))


@pytest.mark.parametrize("invalid", [VoidType.VOID, TokenType.INT, "INT", 1])
def test_function_symbol_rejects_non_scalar_parameter_types(invalid):
    with pytest.raises(ValueError, match="parameter types"):
        function_symbol(("x",), (invalid,))


@pytest.mark.parametrize("invalid", [TokenType.VOID, "VOID", 1, True])
def test_function_symbol_rejects_invalid_return_representations(invalid):
    with pytest.raises(ValueError, match="return type"):
        function_symbol(result=invalid)


def test_scope_identity_and_parent_cannot_change_but_declaration_still_works():
    ids = SymbolIds()
    parent = Scope(ids.scope())
    unrelated = Scope(ids.scope())
    child = Scope(ids.scope(), parent)
    inherited = parent.declare(variable(ids, parent, "inherited"))
    unrelated.declare(variable(ids, unrelated, "secret"))
    original_id, original_parent = child.id, child.parent
    first = child.declare(variable(ids, child, "first"))
    with pytest.raises(FrozenInstanceError):
        child.id = unrelated.id
    with pytest.raises(FrozenInstanceError):
        child.parent = unrelated
    second = child.declare(variable(ids, child, "second"))
    assert child.id == original_id and child.parent is original_parent
    assert first.scope_id == second.scope_id == child.id
    assert child.resolve("inherited") is inherited
    assert child.resolve("secret") is None


def test_array_and_scalar_may_shadow_each_other_in_nested_scopes():
    ids = SymbolIds()
    outer = Scope(ids.scope())
    array = outer.declare(variable(ids, outer, "item", kind=SymbolKind.ARRAY, length=2))
    child = Scope(ids.scope(), outer)
    scalar = child.declare(variable(ids, child, "item"))
    grandchild = Scope(ids.scope(), child)
    nested_array = grandchild.declare(
        variable(ids, grandchild, "item", kind=SymbolKind.ARRAY, length=3)
    )
    assert grandchild.resolve("item") is nested_array
    assert child.resolve("item") is scalar
    assert outer.resolve("item") is array
