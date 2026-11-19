"""Expression-only inference through real lexer and parser ASTs."""

from dataclasses import FrozenInstanceError

import pytest

from sparq.ast_nodes import BinaryExpr, LiteralExpr, VarRef
from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import (
    ConversionSite, ExpressionAnalysis, ExpressionAnalyzer,
    ExpressionAnnotations, SemanticContext,
)
from sparq.symbols import ScalarType as T, VoidType
from sparq.token import TokenType


def expression(source):
    return Parser(Lexer(source).tokenize()).parse_expression_only()


def program(source):
    return Parser(Lexer(source).tokenize()).parse()


def infer(source, context=None):
    return ExpressionAnalyzer(context or SemanticContext()).infer(expression(source))


@pytest.mark.parametrize("source, expected", [
    ("123", T.INT), ("3.5", T.FLOAT), ("'a'", T.CHAR),
    ('"a"', T.STRING), ("TRUE", T.BOOL), ("FALSE", T.BOOL),
])
def test_parsed_literal_types_come_from_token_kinds(source, expected):
    ast = expression(source)
    result = ExpressionAnalyzer(SemanticContext()).infer(ast)
    assert result.type is expected
    assert result.annotations.type_of(ast) is expected
    assert result.root is ast


def test_bool_and_int_and_char_and_string_remain_distinct():
    assert infer("TRUE").type is T.BOOL
    assert infer("1").type is T.INT
    assert infer("'a'").type is T.CHAR
    assert infer('"a"').type is T.STRING


@pytest.mark.parametrize("source, expected", [
    ("10 + 20", T.INT), ("10 + 2.5", T.FLOAT),
    ("2.5 * 10", T.FLOAT), ("10 / 3", T.INT),
    ("10 % 3", T.INT), ("10 < 2.5", T.BOOL),
    ("10 == 10.0", T.BOOL), ("'a' == 'b'", T.BOOL),
    ('"abc" != "xyz"', T.BOOL), ("TRUE == FALSE", T.BOOL),
    ("TRUE AND FALSE", T.BOOL), ("FALSE OR TRUE", T.BOOL),
    ("NOT FALSE", T.BOOL), ("-2", T.INT), ("-2.0", T.FLOAT),
])
def test_valid_parsed_operator_examples(source, expected):
    assert infer(source).type is expected


@pytest.mark.parametrize("source, operator, actual", [
    ("10 % 2.5", "%", "INT and FLOAT"),
    ("TRUE + 1", "+", "BOOL and INT"),
    ('"abc" + "def"', "+", "STRING and STRING"),
    ("'a' < 'b'", "<", "CHAR and CHAR"),
    ('"a" >= "b"', ">=", "STRING and STRING"),
    ("'a' == \"a\"", "==", "CHAR and STRING"),
    ("TRUE == 1", "==", "BOOL and INT"),
    ("1 AND TRUE", "AND", "INT and BOOL"),
    ("NOT 1", "NOT", "INT"),
    ("-TRUE", "-", "BOOL"),
])
def test_invalid_operator_diagnostics_are_controlled(source, operator, actual):
    with pytest.raises(SemanticError) as caught:
        infer(source)
    error = caught.value
    assert error.category == "INVALID_OPERAND_TYPE"
    assert error.name == operator
    assert error.actual == actual
    assert error.expected
    assert (error.line, error.column) == (1, 1)


def test_nested_conversions_mark_use_sites_without_changing_intrinsic_types():
    ast = expression("(1 + 2) * 3.5")
    result = ExpressionAnalyzer(SemanticContext()).infer(ast)
    inner = ast.left
    assert isinstance(inner, BinaryExpr)
    assert result.type is T.FLOAT
    assert result.annotations.type_of(inner) is T.INT
    assert result.annotations.type_of(inner.left) is T.INT
    assert result.annotations.type_of(inner.right) is T.INT
    assert result.annotations.conversions_for(inner) == ()
    conversion, = result.annotations.conversions_for(ast)
    assert (conversion.parent, conversion.operand, conversion.role) == (ast, inner, "left")
    assert (conversion.source_type, conversion.destination_type, conversion.context) == (
        T.INT, T.FLOAT, "*",
    )


def test_multiple_nested_promotions_attach_to_their_respective_parents():
    ast = expression("1 + 2 * 3.0")
    result = ExpressionAnalyzer(SemanticContext()).infer(ast)
    multiplication = ast.right
    assert result.type is T.FLOAT
    assert result.annotations.type_of(multiplication) is T.FLOAT
    inner_site, = result.annotations.conversions_for(multiplication)
    outer_site, = result.annotations.conversions_for(ast)
    assert inner_site.operand is multiplication.left and inner_site.role == "left"
    assert outer_site.operand is ast.left and outer_site.role == "left"
    assert result.annotations.type_of(ast.left) is T.INT


def test_comparison_and_unary_subexpression_types_are_synthesized():
    ast = expression("1 + 2.0 > 3")
    result = ExpressionAnalyzer(SemanticContext()).infer(ast)
    assert result.type is T.BOOL
    assert result.annotations.type_of(ast.left) is T.FLOAT
    site, = result.annotations.conversions_for(ast)
    assert site.operand is ast.right and site.role == "right"
    assert site.source_type is T.INT and site.destination_type is T.FLOAT
    assert infer("NOT (1 == 2)").type is T.BOOL
    minus = expression("-2 + 3.5")
    minus_result = ExpressionAnalyzer(SemanticContext()).infer(minus)
    assert minus_result.annotations.type_of(minus.left) is T.INT
    assert minus_result.annotations.conversions_for(minus)[0].operand is minus.left


def test_short_circuit_runtime_does_not_skip_right_operand_static_checks():
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as missing:
        infer("FALSE AND missing", context)
    assert missing.value.category == "UNDECLARED_NAME"
    assert (missing.value.line, missing.value.column) == (1, 11)
    with pytest.raises(SemanticError) as wrong:
        infer("TRUE OR (1 + TRUE)", context)
    assert wrong.value.category == "INVALID_OPERAND_TYPE"
    assert wrong.value.name == "+"


def test_left_child_diagnostic_precedes_right_child_diagnostic():
    context = SemanticContext()
    context.begin_start()
    with pytest.raises(SemanticError) as caught:
        infer("missing + (TRUE + 1)", context)
    assert caught.value.category == "UNDECLARED_NAME"
    assert caught.value.name == "missing"


def test_scalar_parameter_ancestor_shadow_and_function_namespace_resolution():
    ast = program("FUNC f(INT p) -> VOID { INT x; { FLOAT x; } } START { INT f; }")
    context = SemanticContext()
    context.collect_signatures(ast)
    outer = context.begin_function(ast.functions[0])
    context.declare_scalar(ast.functions[0].body.statements[0])
    analyzer = ExpressionAnalyzer(context)
    outer_x = expression("x")
    outer_result = analyzer.infer(outer_x)
    assert outer_result.type is T.INT
    assert outer_result.annotations.binding_of(outer_x) is outer.resolve("x")
    assert analyzer.infer(expression("p")).type is T.INT
    child = context.enter_block()
    context.declare_scalar(ast.functions[0].body.statements[1].statements[0])
    inner_x = expression("x")
    inner_result = analyzer.infer(inner_x)
    assert inner_result.type is T.FLOAT
    assert inner_result.annotations.binding_of(inner_x) is child.resolve("x")
    assert inner_result.annotations.binding_of(inner_x) is not outer_result.annotations.binding_of(outer_x)
    assert analyzer.infer(expression("p")).type is T.INT
    context.exit_scope()
    context.exit_scope()
    start = context.begin_start()
    context.declare_scalar(ast.main.statements[0])
    start_ref = expression("f")
    start_result = analyzer.infer(start_ref)
    assert start_result.annotations.binding_of(start_ref) is start.resolve("f")
    assert start.resolve("f") is not context.functions.resolve("f")
    with pytest.raises(SemanticError) as caught:
        analyzer.infer(expression("p"))
    assert caught.value.category == "UNDECLARED_NAME"


def test_bare_function_and_undeclared_variable_have_distinct_diagnostics():
    ast = program("FUNC f() -> INT { RETURN 1; } START {}")
    context = SemanticContext()
    context.collect_signatures(ast)
    context.begin_start()
    with pytest.raises(SemanticError) as bare:
        infer("f", context)
    assert bare.value.category == "FUNCTION_AS_SCALAR"
    assert bare.value.name == "f"
    with pytest.raises(SemanticError) as missing:
        infer("g", context)
    assert missing.value.category == "UNDECLARED_NAME"
    assert missing.value.name == "g"


def test_array_element_inference_and_runtime_bounds_boundary():
    ast = program("START { INT a[2]; SHOW(a[5] + 2.5); }")
    context = SemanticContext()
    context.begin_start()
    array = context.declare_array(ast.main.statements[0])
    expression_ast = ast.main.statements[1].value
    result = ExpressionAnalyzer(context).infer(expression_ast)
    access = expression_ast.left
    assert result.type is T.FLOAT
    assert result.annotations.type_of(access) is T.INT
    assert result.annotations.binding_of(access) is array
    assert array.array_length == 2
    assert result.annotations.conversions_for(expression_ast)[0].operand is access
    assert ExpressionAnalyzer(context).infer(expression("a[1 + 2]")).type is T.INT


@pytest.mark.parametrize("source, category, actual", [
    ("a[1.5]", "INDEX_TYPE", "FLOAT"),
    ("a[TRUE]", "INDEX_TYPE", "BOOL"),
    ('a["one"]', "INDEX_TYPE", "STRING"),
    ("missing[0]", "UNDECLARED_NAME", None),
    ("x[0]", "WRONG_SYMBOL_KIND", "VARIABLE"),
    ("a", "ARRAY_AS_SCALAR", "INT array"),
])
def test_array_and_symbol_kind_errors(source, category, actual):
    ast = program("START { INT a[2]; INT x; }")
    context = SemanticContext()
    context.begin_start()
    context.declare_array(ast.main.statements[0])
    context.declare_scalar(ast.main.statements[1])
    with pytest.raises(SemanticError) as caught:
        infer(source, context)
    assert caught.value.category == category
    assert caught.value.actual == actual
    assert caught.value.line == 1


def test_array_scalar_shadowing_changes_indexability():
    ast = program("START { INT a[2]; { INT a; } }")
    context = SemanticContext()
    context.begin_start()
    context.declare_array(ast.main.statements[0])
    analyzer = ExpressionAnalyzer(context)
    assert analyzer.infer(expression("a[0]")).type is T.INT
    context.enter_block()
    context.declare_scalar(ast.main.statements[1].statements[0])
    with pytest.raises(SemanticError) as caught:
        analyzer.infer(expression("a[0]"))
    assert caught.value.category == "WRONG_SYMBOL_KIND"
    context.exit_scope()
    assert analyzer.infer(expression("a[0]")).type is T.INT


def test_implicit_conversion_may_trap_only_when_expression_runs():
    huge = "9" * 5000
    result = infer(f"{huge} + 1.0")
    assert result.type is T.FLOAT
    conversion, = result.annotations.conversions_for(result.root)
    assert conversion.source_type is T.INT and conversion.destination_type is T.FLOAT
    assert infer("1 / 0").type is T.INT
    assert infer("1.0 / 0.0").type is T.FLOAT


def test_structurally_equal_nodes_and_fresh_results_have_distinct_bindings():
    ast = program("START { INT x; { FLOAT x; } }")
    context = SemanticContext()
    context.begin_start()
    outer = context.declare_scalar(ast.main.statements[0])
    first = expression("x")
    second = expression("x")
    assert first == second and first is not second
    analyzer = ExpressionAnalyzer(context)
    first_result = analyzer.infer(first)
    context.enter_block()
    inner = context.declare_scalar(ast.main.statements[1].statements[0])
    second_result = analyzer.infer(second)
    assert first_result.annotations.binding_of(first) is outer
    assert first_result.annotations.binding_of(second) is None
    assert second_result.annotations.binding_of(second) is inner
    assert second_result.annotations.binding_of(first) is None
    assert first_result.annotations.type_of(first) is T.INT
    assert second_result.annotations.type_of(second) is T.FLOAT
    separate = ExpressionAnalyzer(SemanticContext()).infer(expression("1"))
    assert separate.annotations.type_of(first) is None


def test_ast_remains_immutable_and_failed_inference_exposes_no_partial_result():
    ast = expression("1 + TRUE")
    context = SemanticContext()
    analyzer = ExpressionAnalyzer(context)
    with pytest.raises(SemanticError):
        analyzer.infer(ast)
    with pytest.raises(FrozenInstanceError):
        ast.left = expression("2")
    valid = analyzer.infer(expression("1 + 2"))
    assert valid.type is T.INT
    assert valid.annotations.type_of(ast) is None


def test_call_expression_validates_signature_arguments_and_function_binding():
    ast = program("FUNC f(INT x) -> INT { RETURN x; } START {}")
    context = SemanticContext()
    context.collect_signatures(ast)
    context.begin_start()
    valid = infer("f(1)", context)
    assert valid.type is T.INT
    assert valid.annotations.function_of(valid.root) is context.functions.resolve("f")
    for source, category in (("f()", "ARGUMENT_COUNT"),
                             ("f(TRUE)", "ARGUMENT_TYPE_MISMATCH"),
                             ("missing(1)", "UNKNOWN_FUNCTION")):
        with pytest.raises(SemanticError) as caught:
            infer(source, context)
        assert caught.value.category == category
        assert caught.value.name == source.split("(")[0]


def test_unsupported_direct_ast_literal_is_api_precondition_error():
    real = expression("1")
    malformed = LiteralExpr(TokenType.VOID, None, "VOID", real.span)
    with pytest.raises(ValueError, match="unsupported literal kind"):
        ExpressionAnalyzer(SemanticContext()).infer(malformed)


def test_long_valid_program_expression_reports_controlled_resource_limit():
    source = "START { SHOW(" + "1+" * 1000 + "1); }"
    parsed = program(source)
    root = parsed.main.statements[0].value
    context = SemanticContext()
    context.begin_start()
    analyzer = ExpressionAnalyzer(context)
    completed = analyzer.infer(expression("(1 + 2) * 3.5"))
    with pytest.raises(SemanticError) as caught:
        analyzer.infer(root)
    error = caught.value
    assert error.category == "RESOURCE_LIMIT"
    assert error.span == root.span
    assert error.line == 1 and error.column >= 1
    assert "analysis stack" in str(error)
    assert completed.type is T.FLOAT
    assert completed.annotations.type_of(completed.root) is T.FLOAT
    following = analyzer.infer(expression("NOT (1 == 2)"))
    assert following.type is T.BOOL
    assert following.annotations.type_of(root) is None


def test_deep_parser_expression_entry_has_same_controlled_boundary():
    root = expression("1*" * 1100 + "1")
    with pytest.raises(SemanticError) as caught:
        ExpressionAnalyzer(SemanticContext()).infer(root)
    assert caught.value.category == "RESOURCE_LIMIT"
    assert caught.value.span == root.span


def test_direct_conversion_site_validates_position_identity_type_and_context():
    parent = expression("1 + 2.0")
    valid = ConversionSite(parent, parent.left, "left", T.INT, T.FLOAT, "+")
    assert valid.operand is parent.left
    with pytest.raises(FrozenInstanceError):
        valid.role = "right"
    malformed = [
        (parent, parent.left, "right", T.INT, T.FLOAT, "+"),
        (parent, parent.left, "middle", T.INT, T.FLOAT, "+"),
        (parent, expression("1"), "left", T.INT, T.FLOAT, "+"),
        (parent, parent.left, "left", T.FLOAT, T.INT, "+"),
        (parent, parent.left, "left", T.INT, T.INT, "+"),
        (parent, parent.left, "left", T.INT, T.FLOAT, "*"),
    ]
    for arguments in malformed:
        with pytest.raises(ValueError):
            ConversionSite(*arguments)
    modulo = expression("1 % 2")
    with pytest.raises(ValueError, match="cannot require"):
        ConversionSite(modulo, modulo.left, "left", T.INT, T.FLOAT, "%")
    with pytest.raises(TypeError, match="binary"):
        ConversionSite(parent.left, parent.left, "left", T.INT, T.FLOAT, "+")


def test_direct_expression_analysis_requires_matching_root_annotation():
    root = expression("1 + 2.0")
    completed = ExpressionAnalyzer(SemanticContext()).infer(root)
    valid = ExpressionAnalysis(root, T.FLOAT, completed.annotations)
    assert valid.type is T.FLOAT and valid.annotations.type_of(root) is T.FLOAT
    with pytest.raises(ValueError, match="root annotation"):
        ExpressionAnalysis(root, T.FLOAT, ExpressionAnnotations())
    with pytest.raises(ValueError, match="root annotation"):
        ExpressionAnalysis(root, T.BOOL, completed.annotations)
    for invalid in (VoidType.VOID, "FLOAT"):
        with pytest.raises(ValueError, match="scalar"):
            ExpressionAnalysis(root, invalid, completed.annotations)
    with pytest.raises(TypeError, match="annotations"):
        ExpressionAnalysis(root, T.FLOAT, None)


def test_shared_ast_node_conversions_remain_distinct_by_parent_and_role():
    shared = expression("1")
    floating = expression("2.0")
    left = BinaryExpr(TokenType.PLUS, shared, floating, shared.span)
    right = BinaryExpr(TokenType.PLUS, floating, shared, shared.span)
    root = BinaryExpr(TokenType.EQUAL_EQUAL, left, right, shared.span)
    result = ExpressionAnalyzer(SemanticContext()).infer(root)
    first, = result.annotations.conversions_for(left)
    second, = result.annotations.conversions_for(right)
    assert first.parent is left and first.operand is shared and first.role == "left"
    assert second.parent is right and second.operand is shared and second.role == "right"
    assert result.annotations.type_of(shared) is T.INT
    assert result.annotations.conversions_for(root) == ()


def test_runtime_index_traps_and_nested_calls_use_real_types():
    parsed = program("FUNC f() -> INT { RETURN 1; } START { INT a[2]; }")
    context = SemanticContext()
    context.collect_signatures(parsed)
    context.begin_start()
    context.declare_array(parsed.main.statements[0])
    analyzer = ExpressionAnalyzer(context)
    for source in ("a[-1]", "a[5]", "a[1 / 0]"):
        assert analyzer.infer(expression(source)).type is T.INT
    for source in ("f() + 1", "a[f()]"):
        assert analyzer.infer(expression(source)).type is T.INT
    with pytest.raises(SemanticError) as caught:
        analyzer.infer(expression("TRUE OR f()"))
    assert caught.value.category == "INVALID_OPERAND_TYPE"


def test_reanalysis_after_scope_exit_retains_prior_binding_results():
    parsed = program("START { INT x; { FLOAT x; } }")
    context = SemanticContext()
    context.begin_start()
    outer = context.declare_scalar(parsed.main.statements[0])
    reference = expression("x")
    analyzer = ExpressionAnalyzer(context)
    before = analyzer.infer(reference)
    context.enter_block()
    inner = context.declare_scalar(parsed.main.statements[1].statements[0])
    inside = analyzer.infer(reference)
    context.exit_scope()
    after = analyzer.infer(reference)
    assert before.annotations.binding_of(reference) is outer
    assert inside.annotations.binding_of(reference) is inner
    assert after.annotations.binding_of(reference) is outer
    assert (before.type, inside.type, after.type) == (T.INT, T.FLOAT, T.INT)
