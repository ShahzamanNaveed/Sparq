"""Independent checks of the educational attributes, action trace, and DAG."""

from dataclasses import FrozenInstanceError

import pytest

from sparq.errors import SemanticError
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import SemanticContext
from sparq.statement_semantic import StatementAnalyzer
from sparq.symbols import ScalarType
from tools.semantic_demonstrations import (
    ActionStep, DagExample, DagNode, DependencyGraph, EnvironmentEntry,
    SynthesizedExample, UnsupportedDemonstration,
    dag_from_program, declaration_trace, expression_dag, l_attribute_graph,
    render_dag, render_l, render_s, synthesized_expression,
)


def test_synthesized_mixed_numeric_attributes_and_promotions():
    example = synthesized_expression("1 + 2.5 * 3")
    assert [kind for _, kind in example.attributes] == [
        ScalarType.INT, ScalarType.FLOAT, ScalarType.INT,
        ScalarType.FLOAT, ScalarType.FLOAT,
    ]
    assert [(site.context, site.role) for site in example.analysis.annotations.all_conversions()] == [
        ("*", "right"), ("+", "left"),
    ]
    assert example.graph.accepts_order(example.graph.topological_order())
    assert ("n2.type", "n4.type") in example.graph.edges
    assert ("n4.type", "n5.type") in example.graph.edges


@pytest.mark.parametrize("source, expected", [
    ("1 + 2 * 3", ScalarType.INT),
    ("NOT FALSE OR TRUE", ScalarType.BOOL),
])
def test_synthesized_integer_and_boolean_examples(source, expected):
    example = synthesized_expression(source)
    assert example.analysis.type is expected
    assert example.analysis.annotations.all_conversions() == ()


def test_invalid_s_expression_uses_production_error_and_excludes_calls():
    with pytest.raises(SemanticError) as caught:
        synthesized_expression("TRUE + 1")
    assert caught.value.category == "INVALID_OPERAND_TYPE"
    with pytest.raises(UnsupportedDemonstration, match="S-attributed"):
        synthesized_expression("f()")


def test_dependency_graph_order_variants_snapshots_and_cycles():
    nodes = ["a", "b", "c"]
    edges = [["a", "c"], ["b", "c"]]
    graph = DependencyGraph(nodes, edges)
    nodes.clear(); edges[0].clear(); edges.clear()
    assert graph.nodes == ("a", "b", "c")
    assert graph.edges == (("a", "c"), ("b", "c"))
    assert graph.accepts_order(("a", "b", "c"))
    assert graph.accepts_order(("b", "a", "c"))
    assert not graph.accepts_order(("c", "a", "b"))
    with pytest.raises(ValueError, match="cycle"):
        DependencyGraph(("a", "b"), (("a", "b"), ("b", "a")))
    with pytest.raises(ValueError, match="unknown endpoint"):
        DependencyGraph(("a",), (("a", "missing"),))


def test_educational_record_collections_are_immutable_snapshots():
    entry = EnvironmentEntry("x", ScalarType.INT, 1, "initializing")
    environment = [entry]
    step = ActionStep("infer", environment)
    environment.clear()
    assert step.environment == (entry,)
    with pytest.raises(FrozenInstanceError):
        step.action = "complete"
    example = synthesized_expression("1")
    attributes = list(example.attributes)
    copied = SynthesizedExample(example.source, example.analysis, attributes, example.graph)
    attributes.clear()
    assert copied.attributes == example.attributes


def test_l_attributed_trace_registers_before_initializers_and_preserves_snapshots():
    example = declaration_trace()
    actions = [step.action for step in example.steps]
    assert actions == [
        "enter START", "register", "mark initializing", "infer initializer",
        "check compatibility", "complete declaration", "register", "mark initializing",
        "infer initializer", "record operand conversion", "check compatibility",
        "complete declaration", "infer SHOW",
    ]
    assert example.steps[1].environment[0].state == "registered"
    assert example.steps[2].environment[0].state == "initializing"
    assert example.steps[5].environment[0].state == "ready"
    assert example.steps[6].environment[1].state == "registered"
    assert [(entry.name, entry.type) for entry in example.steps[-1].environment] == [
        ("x", ScalarType.INT), ("y", ScalarType.FLOAT),
    ]
    program = Parser(Lexer(example.source).tokenize()).parse()
    y = program.main.statements[1]
    assert example.result.expressions[1].analysis.type is ScalarType.FLOAT
    assert example.graph.accepts_order(example.graph.topological_order())
    assert ("x.env_out", "Stmt0.env_out") in example.graph.edges
    assert ("Stmt0.env_out", "List1.env_in") in example.graph.edges
    assert ("List1.env_in", "Stmt1.env_in") in example.graph.edges
    assert ("Stmt1.env_in", "y.env_in") in example.graph.edges
    assert ("y.env_in", "y.registered") in example.graph.edges


def test_sdt_declaration_conversion_and_negative_production_cases():
    trace = declaration_trace("START { FLOAT y = 1; SHOW(y); }")
    actions = [step.action for step in trace.steps]
    assert actions.index("register") < actions.index("infer initializer")
    assert actions.index("check compatibility") < actions.index("record INT-to-FLOAT")
    assert actions.index("record INT-to-FLOAT") < actions.index("complete declaration")
    assert len(trace.result.conversions) == 1
    for source, category in [
        ("START { INT y = x; INT x = 10; }", "UNDECLARED_NAME"),
        ("START { INT x = x + 1; }", "READ_BEFORE_INITIALIZATION"),
        ("START { INT x = 10; { INT x = x + 1; } }", "READ_BEFORE_INITIALIZATION"),
    ]:
        program = Parser(Lexer(source).tokenize()).parse()
        context = SemanticContext(); context.begin_start()
        with pytest.raises(SemanticError) as caught:
            StatementAnalyzer(context).analyze_block(program.main)
        assert caught.value.category == category


def test_dag_shares_repeated_subexpression_without_execution():
    example = dag_from_program()
    assert example.tree_occurrences == 7
    assert len(example.nodes) == 4
    assert [node.label for node in example.nodes] == ["a", "b", "PLUS", "STAR"]
    assert example.nodes[2].children == (1, 2)
    assert example.nodes[3].children == (3, 3)
    assert example.root_id == 4


def test_dag_preserves_operand_order_and_intrinsic_promotions():
    ordered = dag_from_program("START { INT a; INT b; SHOW((a - b) + (b - a)); }")
    assert ordered.tree_occurrences == 7 and len(ordered.nodes) == 5
    assert ordered.nodes[2].children == (1, 2)
    assert ordered.nodes[3].children == (2, 1)
    mixed = dag_from_program("START { SHOW(1 + 2.5 * 3); }")
    assert [node.type for node in mixed.nodes] == [
        ScalarType.INT, ScalarType.FLOAT, ScalarType.INT,
        ScalarType.FLOAT, ScalarType.FLOAT,
    ]
    assert mixed.nodes[3].conversions == (("right", ScalarType.INT, ScalarType.FLOAT),)
    assert mixed.nodes[4].conversions == (("left", ScalarType.INT, ScalarType.FLOAT),)


def test_dag_distinguishes_literal_types_and_symbol_identities():
    assert dag_from_program("START { SHOW(TRUE); }").nodes[0].type is ScalarType.BOOL
    assert dag_from_program("START { SHOW(1); }").nodes[0].type is ScalarType.INT
    assert dag_from_program("START { SHOW('a'); }").nodes[0].type is ScalarType.CHAR
    assert dag_from_program('START { SHOW("a"); }').nodes[0].type is ScalarType.STRING
    source = "START { INT a; SHOW(a); { INT a; SHOW(a); } }"
    program = Parser(Lexer(source).tokenize()).parse()
    context = SemanticContext(); context.begin_start()
    result = StatementAnalyzer(context).analyze_block(program.main)
    outer = program.main.statements[1]
    inner = program.main.statements[2].statements[1]
    outer_node = expression_dag(outer.value, result.show_of(outer)).nodes[0]
    inner_node = expression_dag(inner.value, result.show_of(inner)).nodes[0]
    assert outer_node.label == inner_node.label == "a"
    assert outer_node.symbol_id != inner_node.symbol_id


@pytest.mark.parametrize("source, excluded", [
    ("FUNC f() -> INT { RETURN 1; } START { SHOW(f()); }", "CallExpr"),
    ("START { INT a[1]; SHOW(a[0]); }", "ArrayAccess"),
])
def test_dag_explicitly_declines_calls_and_array_accesses(source, excluded):
    with pytest.raises(UnsupportedDemonstration, match=excluded):
        dag_from_program(source)


def test_dag_records_validate_arity_edges_snapshots_and_immutability():
    children = [1, 1]
    node = DagNode(2, "binary", "PLUS", ScalarType.INT, children)
    children.clear()
    assert node.children == (1, 1)
    with pytest.raises(ValueError, match="earlier"):
        DagNode(2, "binary", "PLUS", ScalarType.INT, (1, 2))
    with pytest.raises(ValueError, match="arity"):
        DagNode(2, "binary", "PLUS", ScalarType.INT, (1,))
    with pytest.raises(ValueError, match="sequential"):
        DagExample((node,), 1, 2)
    with pytest.raises(FrozenInstanceError):
        node.label = "STAR"


def test_rendered_examples_are_deterministic_and_show_key_results():
    assert render_s() == render_s()
    assert "Result: FLOAT" in render_s()
    assert "x:INT#1:initializing" in render_l()
    assert "record operand conversion" in render_l()
    assert "DAG tree occurrences: 7" in render_dag()
    assert "DAG unique nodes: 4" in render_dag()


def test_direct_l_dependencies_include_rule_inputs_and_bridges():
    graph = l_attribute_graph()
    for edge in (
        ("List0.env_in", "Stmt0.env_in"),
        ("Stmt0.env_in", "x.env_in"),
        ("x.name", "x.init_env"),
        ("x.init_env", "x.env_out"),
        ("x.name", "x.env_out"),
        ("x.checked", "x.conversion"),
        ("x.conversion", "x.env_out"),
        ("x.env_out", "Stmt0.env_out"),
        ("show2.env_in", "show2.env_out"),
        ("show2.expr_type", "show2.env_out"),
    ):
        assert edge in graph.edges
    assert graph.accepts_order(graph.topological_order())


def test_graph_independent_nodes_self_loop_and_missing_endpoint():
    graph = DependencyGraph(("z", "a"), ())
    assert graph.topological_order() == ("z", "a")
    with pytest.raises(ValueError, match="cycle"):
        DependencyGraph(("a",), (("a", "a"),))
    with pytest.raises(ValueError, match="unknown endpoint"):
        DependencyGraph(("a",), (("a", "missing"),))


def test_dag_direct_conversion_records_validate_roles_and_child_types():
    left = DagNode(1, "literal", "1", ScalarType.INT, ())
    right = DagNode(2, "literal", "2.5", ScalarType.FLOAT, ())
    with pytest.raises(ValueError, match="contradictory"):
        DagNode(3, "binary", "PLUS", ScalarType.INT, (1, 2), (
            ("left", ScalarType.INT, ScalarType.FLOAT),
            ("left", ScalarType.INT, ScalarType.FLOAT),
        ))
    with pytest.raises(ValueError, match="invalid DAG conversion"):
        DagNode(3, "binary", "PLUS", ScalarType.FLOAT, (1, 2),
                (("left", ScalarType.FLOAT, ScalarType.INT),))
    with pytest.raises(ValueError, match="invalid DAG conversion"):
        DagNode(3, "binary", "PLUS", ScalarType.FLOAT, (1, 2),
                (("middle", ScalarType.INT, ScalarType.FLOAT),))
    valid = DagNode(3, "binary", "PLUS", ScalarType.FLOAT, (1, 2),
                    (("left", ScalarType.INT, ScalarType.FLOAT),))
    assert DagExample((left, right, valid), 3, 3).nodes[-1] is valid
    both_roles = DagNode(3, "binary", "PLUS", ScalarType.FLOAT, (1, 1), (
        ("left", ScalarType.INT, ScalarType.FLOAT),
        ("right", ScalarType.INT, ScalarType.FLOAT),
    ))
    assert both_roles.children == (1, 1)
    assert len(both_roles.conversions) == 2
    with pytest.raises(ValueError, match="contradicts operands"):
        DagExample((left, right, DagNode(3, "binary", "PLUS", ScalarType.FLOAT,
                                          (1, 2))), 3, 3)
    with pytest.raises(ValueError, match="contradicts operands"):
        DagExample((left, right, DagNode(3, "binary", "PLUS", ScalarType.FLOAT,
                                          (1, 2), (("right", ScalarType.INT,
                                                    ScalarType.FLOAT),))), 3, 3)


def test_dag_equal_decoded_literals_distinct_operators_and_nested_exclusions():
    same = dag_from_program("START { SHOW(1.0 + 1.00); }")
    assert same.tree_occurrences == 3 and len(same.nodes) == 2
    assert same.nodes[-1].children == (1, 1)
    different = dag_from_program(
        "START { INT a; INT b; SHOW((a + b) * (a - b)); }"
    )
    assert [node.label for node in different.nodes] == [
        "a", "b", "PLUS", "MINUS", "STAR",
    ]
    for source in (
        "FUNC f() -> INT { RETURN 1; } START { SHOW(1 + f()); }",
        "START { INT a[1]; SHOW(1 + a[0]); }",
    ):
        with pytest.raises(UnsupportedDemonstration):
            dag_from_program(source)


def test_s_literal_only_has_intrinsic_type_and_no_promotions():
    example = synthesized_expression("1")
    assert example.analysis.type is ScalarType.INT
    assert example.attributes == (("n1.type", ScalarType.INT),)
    assert example.analysis.annotations.all_conversions() == ()
