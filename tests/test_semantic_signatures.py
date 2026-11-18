"""Signature and scope integration; no full semantic visitor is implied."""

from dataclasses import replace

import pytest

from sparq.ast_nodes import ArrayDecl, ScalarDecl
from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.symbols import ScalarType, SymbolKind, VoidType
from sparq.token import TokenType


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def test_signature_collection_preserves_order_and_both_return_forms():
    program = parse(
        "FUNC a(INT x, FLOAT y, CHAR c, STRING s, BOOL b) -> VOID {} "
        "FUNC b() -> INT { RETURN 1; } START {}"
    )
    context = SemanticContext()
    registry = context.collect_signatures(program)
    a, b = registry.require("a", program.span), registry.require("b", program.span)
    assert len(registry) == 2
    assert a.parameter_names == ("x", "y", "c", "s", "b")
    assert a.parameter_types == tuple(ScalarType)
    assert a.return_type is VoidType.VOID
    assert b.parameter_names == ()
    assert b.return_type is ScalarType.INT
    assert a.declaration is program.functions[0]
    assert a.id != b.id


def test_later_declarations_and_mutual_recursion_signatures_are_available():
    program = parse(
        "FUNC left() -> INT { RETURN right(); } "
        "FUNC right() -> INT { RETURN left(); } "
        "START { SHOW(left()); }"
    )
    registry = SemanticContext().collect_signatures(program)
    assert registry.resolve("right").return_type is ScalarType.INT
    assert registry.resolve("left").return_type is ScalarType.INT
    # Bodies above are parsed but no call or return validation is performed.


def test_duplicate_function_is_rejected_without_overloading():
    program = parse("FUNC f(INT x) -> VOID {} FUNC f(FLOAT y) -> INT {} START {}")
    with pytest.raises(SemanticError) as caught:
        SemanticContext().collect_signatures(program)
    assert (caught.value.category, caught.value.name) == ("DUPLICATE_FUNCTION", "f")
    assert (caught.value.line, caught.value.column) == (1, 26)


def test_duplicate_parameter_reports_second_parameter_position():
    program = parse("FUNC f(INT x, FLOAT x) -> VOID {} START {}")
    with pytest.raises(SemanticError) as caught:
        SemanticContext().collect_signatures(program)
    assert (caught.value.category, caught.value.name) == ("DUPLICATE_PARAMETER", "x")
    assert (caught.value.line, caught.value.column) == (1, 15)


def test_malformed_ast_void_parameter_has_controlled_diagnostic():
    program = parse("FUNC f(INT x) -> VOID {} START {}")
    parameter = replace(program.functions[0].params[0], type_name=TokenType.VOID)
    function = replace(program.functions[0], params=(parameter,))
    malformed = replace(program, functions=(function,))
    with pytest.raises(SemanticError) as caught:
        SemanticContext().collect_signatures(malformed)
    assert caught.value.category == "INVALID_TYPE"


def test_function_parameters_share_outer_body_scope_and_nested_shadowing():
    program = parse("FUNC f(INT x) -> VOID { INT x; { INT x; } } START {}")
    context = SemanticContext()
    context.collect_signatures(program)
    outer = context.begin_function(program.functions[0])
    parameter = outer.require("x", program.span)
    assert parameter.kind is SymbolKind.PARAMETER
    assert len(outer._symbols) == 1
    with pytest.raises(SemanticError) as caught:
        context.declare_scalar(program.functions[0].body.statements[0])
    assert caught.value.category == "REDECLARATION"
    nested_block = program.functions[0].body.statements[1]
    nested = context.enter_block()
    shadow = context.declare_scalar(nested_block.statements[0])
    assert shadow.id != parameter.id
    assert nested.resolve("x") is shadow
    assert context.exit_scope() is outer
    assert outer.resolve("x") is parameter
    assert context.exit_scope() is None


def test_start_and_repeat_scope_visibility_and_sibling_isolation():
    program = parse("START { REPEAT (INT i = 0; i < 2; i = i + 1) { INT body; } } ")
    loop = program.main.statements[0]
    context = SemanticContext()
    root = context.begin_start()
    repeat = context.enter_repeat()
    header = context.declare_scalar(loop.initializer)
    assert repeat.require("i", loop.span) is header
    body = context.enter_block()
    assert body.require("i", loop.span) is header
    body_symbol = context.declare_scalar(loop.body.statements[0])
    assert body.resolve("body") is body_symbol
    context.exit_scope()
    assert repeat.resolve("body") is None
    context.exit_scope()
    assert root.resolve("i") is None
    sibling = context.enter_block()
    assert sibling.resolve("i") is None
    context.exit_scope()
    context.exit_scope()


def test_declarations_are_sequential_and_new_name_shadows_before_initializer():
    program = parse("START { INT x = 1; { INT y = x; INT x = x; } } ")
    context = SemanticContext()
    outer = context.begin_start()
    first = context.declare_scalar(program.main.statements[0])
    child = context.enter_block()
    inner_statements = program.main.statements[1].statements
    assert child.resolve("x") is first
    assert child.resolve("y") is None
    context.declare_scalar(inner_statements[0])
    shadow = context.declare_scalar(inner_statements[1])
    assert child.resolve("x") is shadow
    assert shadow.id != first.id
    # The future initializer visitor will inspect the expression after registration.
    context.exit_scope()
    assert outer.resolve("x") is first


def test_function_and_variable_namespaces_are_independent():
    program = parse("FUNC f() -> VOID {} START { INT f; }")
    context = SemanticContext()
    context.collect_signatures(program)
    scope = context.begin_start()
    variable = context.declare_scalar(program.main.statements[0])
    assert scope.resolve("f") is variable
    assert context.functions.resolve("f").name == "f"
    assert variable.id != context.functions.resolve("f").id
    with pytest.raises(SemanticError) as caught:
        context.functions.require("missing", program.span)
    assert caught.value.category == "UNKNOWN_FUNCTION"


def test_parsed_array_has_kind_element_type_and_length_metadata_only():
    program = parse("START { INT numbers[3] = {1, 2, 3}; }")
    declaration = program.main.statements[0]
    assert isinstance(declaration, ArrayDecl)
    context = SemanticContext()
    context.begin_start()
    array = context.declare_array(declaration)
    assert (array.kind, array.type, array.array_length) == (
        SymbolKind.ARRAY, ScalarType.INT, 3,
    )


def test_fresh_contexts_have_independent_registry_and_ids():
    program = parse("FUNC f() -> VOID {} START { INT x; }")
    first, second = SemanticContext(), SemanticContext()
    first.collect_signatures(program)
    second.collect_signatures(program)
    assert first.functions.resolve("f") is not second.functions.resolve("f")
    assert first.functions.resolve("f").id == second.functions.resolve("f").id == 1
    assert first.begin_start().id == second.begin_start().id == 1
    assert first.declare_scalar(program.main.statements[0]).id == 2
    assert second.current_scope.resolve("x") is None


def test_function_parameters_and_locals_do_not_leak_to_other_functions_or_start():
    program = parse(
        "FUNC first(INT p) -> VOID { INT local; } "
        "FUNC second() -> VOID { INT own; } START { INT main_only; }"
    )
    context = SemanticContext()
    context.collect_signatures(program)
    first = context.begin_function(program.functions[0])
    parameter = first.require("p", program.span)
    local = context.declare_scalar(program.functions[0].body.statements[0])
    assert first.resolve("local") is local
    context.exit_scope()
    second = context.begin_function(program.functions[1])
    assert second.resolve("p") is None and second.resolve("local") is None
    context.declare_scalar(program.functions[1].body.statements[0])
    context.exit_scope()
    start = context.begin_start()
    assert start.resolve("p") is None and start.resolve("local") is None
    assert start.resolve("own") is None
    assert parameter.id != local.id
    context.exit_scope()


def test_nested_repeat_scopes_restore_header_visibility_after_exiting_inner_loop():
    program = parse(
        "START { REPEAT (INT i = 0; ; ) {"
        "REPEAT (INT j = 0; ; ) { INT local; }"
        "} }"
    )
    outer_loop = program.main.statements[0]
    inner_loop = outer_loop.body.statements[0]
    context = SemanticContext()
    root = context.begin_start()
    outer_header = context.enter_repeat()
    i = context.declare_scalar(outer_loop.initializer)
    outer_body = context.enter_block()
    inner_header = context.enter_repeat()
    j = context.declare_scalar(inner_loop.initializer)
    inner_body = context.enter_block()
    local = context.declare_scalar(inner_loop.body.statements[0])
    assert inner_body.resolve("i") is i
    assert inner_body.resolve("j") is j
    assert inner_body.resolve("local") is local
    context.exit_scope()
    context.exit_scope()
    assert outer_body.resolve("i") is i
    assert outer_body.resolve("j") is None
    assert outer_header.resolve("local") is None
    context.exit_scope()
    context.exit_scope()
    assert root.resolve("i") is None
    context.exit_scope()


def test_invalid_scope_lifecycle_calls_keep_existing_value_errors():
    program = parse("START { INT x; }")
    context = SemanticContext()
    with pytest.raises(ValueError, match="begin START"):
        context.enter_block()
    with pytest.raises(ValueError, match="no active.*scope"):
        context.declare_scalar(program.main.statements[0])
    with pytest.raises(ValueError, match="no active.*scope"):
        context.exit_scope()
    root = context.begin_start()
    with pytest.raises(ValueError, match="exit the active scope"):
        context.begin_start()
    assert context.current_scope is root
    context.exit_scope()
