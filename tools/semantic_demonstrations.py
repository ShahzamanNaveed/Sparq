"""Reproducible SDD/SDT and expression-DAG teaching examples for Sparq.

This module reads production AST and semantic facts. It neither executes Sparq
nor changes the parser, semantic analyzer, or future intermediate code.
"""

from __future__ import annotations

import argparse
import heapq
import struct
from dataclasses import dataclass

from sparq.ast_nodes import BinaryExpr, Expr, LiteralExpr, ScalarDecl, ShowStmt, UnaryExpr, VarRef
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.semantic import ExpressionAnalysis, ExpressionAnalyzer, SemanticContext
from sparq.statement_semantic import StatementAnalysis, StatementAnalyzer
from sparq.symbols import ScalarType
from sparq.token import TokenType
from sparq.type_rules import Compatibility, assignment_compatibility, binary_rule, unary_result


S_SOURCE = "1 + 2.5 * 3"
L_SOURCE = "START { INT x = 10; FLOAT y = x + 2.5; SHOW(y); }"
DAG_SOURCE = "START { INT a; INT b; SHOW((a + b) * (a + b)); }"
_DAG_BINARY = frozenset({TokenType.PLUS, TokenType.MINUS, TokenType.STAR})


class UnsupportedDemonstration(ValueError):
    """The input is valid Sparq but outside this educational fragment."""


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Attribute dependencies oriented prerequisite -> dependent."""

    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, (list, tuple)) or not isinstance(self.edges, (list, tuple)):
            raise TypeError("attribute graph needs node and edge collections")
        if any(not isinstance(edge, (list, tuple)) or len(edge) != 2 for edge in self.edges):
            raise TypeError("attribute edges must be endpoint pairs")
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(tuple(edge) for edge in self.edges))
        if any(not isinstance(n, str) or not n for n in self.nodes):
            raise ValueError("attribute graph nodes must be nonempty names")
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("attribute graph nodes must be unique names")
        names = set(self.nodes)
        if any(len(edge) != 2 or edge[0] not in names or edge[1] not in names for edge in self.edges):
            raise ValueError("attribute edge has an unknown endpoint")
        if len(set(self.edges)) != len(self.edges):
            raise ValueError("attribute edges must be unique")
        self.topological_order()

    def topological_order(self) -> tuple[str, ...]:
        """Use declaration order to break ties; reject cyclic dependencies."""
        index = {name: i for i, name in enumerate(self.nodes)}
        indegree = {name: 0 for name in self.nodes}
        outgoing = {name: [] for name in self.nodes}
        for before, after in self.edges:
            indegree[after] += 1
            outgoing[before].append(after)
        ready = [index[name] for name in self.nodes if indegree[name] == 0]
        heapq.heapify(ready)
        order = []
        while ready:
            name = self.nodes[heapq.heappop(ready)]
            order.append(name)
            for after in outgoing[name]:
                indegree[after] -= 1
                if indegree[after] == 0:
                    heapq.heappush(ready, index[after])
        if len(order) != len(self.nodes):
            raise ValueError("attribute dependency graph contains a cycle")
        return tuple(order)

    def accepts_order(self, order: tuple[str, ...] | list[str]) -> bool:
        """Check any proposed complete order, not just the chosen stable order."""
        if len(order) != len(self.nodes) or set(order) != set(self.nodes):
            return False
        position = {name: i for i, name in enumerate(order)}
        return all(position[before] < position[after] for before, after in self.edges)


def _postorder(root: Expr, *, dag_subset: bool) -> tuple[Expr, ...]:
    """Traverse parser-produced expression trees without Python recursion."""
    result = []
    pending = [(root, False)]
    while pending:
        node, ready = pending.pop()
        if ready:
            result.append(node)
            continue
        if isinstance(node, LiteralExpr):
            children = ()
        elif isinstance(node, VarRef) and dag_subset:
            children = ()
        elif isinstance(node, UnaryExpr) and (not dag_subset or node.operator is TokenType.MINUS):
            children = (node.operand,)
        elif isinstance(node, BinaryExpr) and (not dag_subset or node.operator in _DAG_BINARY):
            children = (node.left, node.right)
        else:
            raise UnsupportedDemonstration(
                f"{type(node).__name__} is outside the {'DAG' if dag_subset else 'S-attributed'} fragment"
            )
        pending.append((node, True))
        pending.extend((child, False) for child in reversed(children))
    return tuple(result)


def _children(node: Expr) -> tuple[Expr, ...]:
    if isinstance(node, UnaryExpr):
        return (node.operand,)
    if isinstance(node, BinaryExpr):
        return (node.left, node.right)
    return ()


@dataclass(frozen=True, slots=True)
class SynthesizedExample:
    source: str
    analysis: ExpressionAnalysis
    attributes: tuple[tuple[str, ScalarType], ...]
    graph: DependencyGraph

    def __post_init__(self) -> None:
        if not isinstance(self.attributes, (list, tuple)):
            raise TypeError("synthesized attributes must be a list or tuple")
        object.__setattr__(self, "attributes", tuple(tuple(item) for item in self.attributes))
        if (not isinstance(self.analysis, ExpressionAnalysis)
                or not isinstance(self.graph, DependencyGraph)
                or any(len(item) != 2 or not isinstance(item[0], str)
                       or not isinstance(item[1], ScalarType) for item in self.attributes)):
            raise ValueError("synthesized example metadata is invalid")


def synthesized_expression(source: str = S_SOURCE) -> SynthesizedExample:
    """Annotate a literal-only expression with production-inferred types."""
    root = Parser(Lexer(source).tokenize()).parse_expression_only()
    nodes = _postorder(root, dag_subset=False)
    context = SemanticContext()
    context.begin_start()
    analysis = ExpressionAnalyzer(context).infer(root)
    labels = {id(node): f"n{index}.type" for index, node in enumerate(nodes, 1)}
    attributes = tuple((labels[id(node)], analysis.annotations.type_of(node)) for node in nodes)
    graph_nodes = []
    edges = []
    for node in nodes:
        name = labels[id(node)]
        graph_nodes.append(name)
        for child in _children(node):
            edges.append((labels[id(child)], name))
        if isinstance(node, BinaryExpr) and analysis.annotations.conversions_for(node):
            conversion_name = name.replace(".type", ".conversion")
            graph_nodes.append(conversion_name)
            edges.extend((labels[id(child)], conversion_name) for child in _children(node))
    graph = DependencyGraph(tuple(graph_nodes), tuple(edges))
    return SynthesizedExample(source, analysis, attributes, graph)


@dataclass(frozen=True, slots=True)
class EnvironmentEntry:
    name: str
    type: ScalarType
    symbol_id: int
    state: str  # registered, initializing, or ready

    def __post_init__(self) -> None:
        if (not isinstance(self.name, str) or not self.name
                or not isinstance(self.type, ScalarType)
                or type(self.symbol_id) is not int or self.symbol_id <= 0
                or self.state not in ("registered", "initializing", "ready")):
            raise ValueError("invalid educational environment state")


@dataclass(frozen=True, slots=True)
class ActionStep:
    action: str
    environment: tuple[EnvironmentEntry, ...]
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.environment, (list, tuple)):
            raise TypeError("action environment must be a list or tuple")
        object.__setattr__(self, "environment", tuple(self.environment))
        if (not isinstance(self.action, str) or not self.action
                or not isinstance(self.detail, str)
                or any(not isinstance(item, EnvironmentEntry) for item in self.environment)):
            raise ValueError("action step metadata is invalid")


@dataclass(frozen=True, slots=True)
class DeclarationExample:
    source: str
    result: StatementAnalysis
    steps: tuple[ActionStep, ...]
    graph: DependencyGraph

    def __post_init__(self) -> None:
        if not isinstance(self.steps, (list, tuple)):
            raise TypeError("action steps must be a list or tuple")
        object.__setattr__(self, "steps", tuple(self.steps))
        if (not isinstance(self.result, StatementAnalysis)
                or not isinstance(self.graph, DependencyGraph)
                or any(not isinstance(step, ActionStep) for step in self.steps)):
            raise ValueError("declaration example metadata is invalid")


def l_attribute_graph(
    statements: tuple[ScalarDecl | ShowStmt, ...] | None = None,
) -> DependencyGraph:
    """Build a left-to-right attribute graph for the flat teaching fragment."""
    if statements is None:
        statements = Parser(Lexer(L_SOURCE).tokenize()).parse().main.statements
    nodes = ["List0.env_in"]
    edges = []
    for index, statement in enumerate(statements):
        incoming = f"List{index}.env_in"
        outgoing = f"List{index + 1}.env_in"
        stmt_in = f"Stmt{index}.env_in"
        stmt_out = f"Stmt{index}.env_out"
        nodes.append(stmt_in)
        edges.append((incoming, stmt_in))
        if isinstance(statement, ScalarDecl):
            prefix = statement.name
            pieces = tuple(f"{prefix}.{name}" for name in (
                "env_in", "type", "name", "registered", "init_env",
                "expr_type", "checked", "conversion", "env_out",
            ))
            nodes.extend(pieces)
            decl_in, declared_type, identifier, registered, init_env, expr_type, checked, conversion, env_out = pieces
            edges.extend((
                (stmt_in, decl_in), (decl_in, registered), (declared_type, registered),
                (identifier, registered), (registered, init_env),
                (identifier, init_env),
                (init_env, expr_type), (expr_type, checked),
                (declared_type, checked), (checked, conversion),
                (declared_type, conversion), (expr_type, conversion),
                (conversion, env_out), (init_env, env_out),
                (identifier, env_out), (env_out, stmt_out),
            ))
        elif isinstance(statement, ShowStmt):
            prefix = f"show{index}"
            show_in, expr_env, expr_type, show_out = (
                f"{prefix}.{part}" for part in ("env_in", "expr_env", "expr_type", "env_out")
            )
            nodes.extend((show_in, expr_env, expr_type, show_out))
            edges.extend(((stmt_in, show_in), (show_in, expr_env),
                          (expr_env, expr_type), (expr_type, show_out),
                          (show_in, show_out), (show_out, stmt_out)))
        else:
            raise UnsupportedDemonstration("L-attributed graph needs scalar declarations or SHOW")
        nodes.append(stmt_out)
        edges.append((stmt_out, outgoing))
        nodes.append(outgoing)
    end = f"List{len(statements)}.env_out"
    nodes.append(end)
    edges.append((f"List{len(statements)}.env_in", end))
    return DependencyGraph(tuple(nodes), tuple(edges))


def declaration_trace(source: str = L_SOURCE) -> DeclarationExample:
    """Replay successful production facts as immutable educational snapshots.

    This is an explanatory trace reconstructed after validation, not an action
    hook installed in the production parser or semantic analyzer.
    """
    program = Parser(Lexer(source).tokenize()).parse()
    if program.functions or any(
        not isinstance(stmt, (ScalarDecl, ShowStmt))
        or isinstance(stmt, ScalarDecl) and stmt.initializer is None
        for stmt in program.main.statements
    ):
        raise UnsupportedDemonstration("trace supports initialized scalar declarations and SHOW in START")
    context = SemanticContext()
    context.begin_start()
    result = StatementAnalyzer(context).analyze_block(program.main)
    environment: tuple[EnvironmentEntry, ...] = ()
    steps = [ActionStep("enter START", environment)]
    for statement in program.main.statements:
        if isinstance(statement, ScalarDecl):
            symbol = result.declaration_of(statement)
            environment += (EnvironmentEntry(symbol.name, symbol.type, symbol.id, "registered"),)
            steps.append(ActionStep("register", environment, symbol.name))
            environment = environment[:-1] + (
                EnvironmentEntry(symbol.name, symbol.type, symbol.id, "initializing"),
            )
            steps.append(ActionStep("mark initializing", environment, symbol.name))
            use = next(use for use in result.expressions if use.parent is statement)
            steps.append(ActionStep("infer initializer", environment, f"{symbol.name}: {use.analysis.type.name}"))
            for site in use.analysis.annotations.all_conversions():
                steps.append(ActionStep(
                    "record operand conversion", environment,
                    f"{site.context}:{site.role} {site.source_type.name}->{site.destination_type.name}",
                ))
            decision = assignment_compatibility(symbol.type, use.analysis.type)
            steps.append(ActionStep("check compatibility", environment, decision.name))
            if decision is Compatibility.INT_TO_FLOAT:
                steps.append(ActionStep("record INT-to-FLOAT", environment, symbol.name))
            environment = environment[:-1] + (
                EnvironmentEntry(symbol.name, symbol.type, symbol.id, "ready"),
            )
            steps.append(ActionStep("complete declaration", environment, symbol.name))
        else:
            analysis = result.show_of(statement)
            steps.append(ActionStep("infer SHOW", environment, analysis.type.name))
    return DeclarationExample(source, result, tuple(steps), l_attribute_graph(program.main.statements))


@dataclass(frozen=True, slots=True)
class DagNode:
    id: int
    kind: str
    label: str
    type: ScalarType
    children: tuple[int, ...]
    conversions: tuple[tuple[str, ScalarType, ScalarType], ...] = ()
    symbol_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.children, (list, tuple)) or not isinstance(self.conversions, (list, tuple)):
            raise TypeError("DAG operands and conversions must be collections")
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "conversions", tuple(tuple(item) for item in self.conversions))
        if type(self.id) is not int or self.id <= 0 or not isinstance(self.type, ScalarType):
            raise ValueError("DAG node needs a positive ID and intrinsic scalar type")
        arity = {"literal": 0, "variable": 0, "unary": 1, "binary": 2}
        if (self.kind not in arity or len(self.children) != arity[self.kind]
                or not isinstance(self.label, str) or not self.label):
            raise ValueError("DAG node kind, label, or operand arity is invalid")
        if (self.kind == "variable" and (type(self.symbol_id) is not int or self.symbol_id <= 0)
                or self.kind != "variable" and self.symbol_id is not None):
            raise ValueError("only a variable DAG node has a symbol ID")
        if any(type(child) is not int or child <= 0 or child >= self.id for child in self.children):
            raise ValueError("DAG operands must refer to earlier nodes")
        if self.conversions and self.kind != "binary":
            raise ValueError("only binary DAG nodes record operand promotions")
        if (self.kind == "unary" and self.label != "MINUS"
                or self.kind == "binary" and self.label not in {"PLUS", "MINUS", "STAR"}):
            raise ValueError("DAG operator is outside the supported subset")
        if any(len(item) != 3 or item[0] not in ("left", "right")
               or item[1] is not ScalarType.INT or item[2] is not ScalarType.FLOAT
               for item in self.conversions):
            raise ValueError("invalid DAG conversion metadata")
        if (len({item[0] for item in self.conversions}) != len(self.conversions)
                or self.conversions and self.type is not ScalarType.FLOAT):
            raise ValueError("contradictory DAG conversion metadata")


@dataclass(frozen=True, slots=True)
class DagExample:
    nodes: tuple[DagNode, ...]
    root_id: int
    tree_occurrences: int

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, (list, tuple)):
            raise TypeError("DAG nodes must be a list or tuple")
        object.__setattr__(self, "nodes", tuple(self.nodes))
        if any(not isinstance(node, DagNode) or node.id != index for index, node in enumerate(self.nodes, 1)):
            raise ValueError("DAG IDs must be sequential postorder IDs")
        if (not self.nodes or type(self.root_id) is not int or self.root_id != len(self.nodes)
                or type(self.tree_occurrences) is not int or self.tree_occurrences < len(self.nodes)):
            raise ValueError("invalid DAG root or tree occurrence count")
        for node in self.nodes:
            if node.kind == "unary":
                expected = unary_result(TokenType.MINUS, self.nodes[node.children[0] - 1].type)
                if expected is not node.type:
                    raise ValueError("DAG unary result contradicts operand type")
            elif node.kind == "binary":
                left, right = (self.nodes[child - 1].type for child in node.children)
                rule = binary_rule(TokenType[node.label], left, right)
                expected = () if rule is None else tuple(
                    (role, ScalarType.INT, target)
                    for role, target in (("left", rule.left_conversion),
                                         ("right", rule.right_conversion)) if target is not None
                )
                if rule is None or node.type is not rule.result_type or node.conversions != expected:
                    raise ValueError("DAG binary type or conversion contradicts operands")


def _literal_key(value: object) -> object:
    return struct.pack("!d", value) if type(value) is float else value


def _short(lexeme: str) -> str:
    return lexeme if len(lexeme) <= 40 else f"{lexeme[:20]}... ({len(lexeme)} chars)"


def expression_dag(root: Expr, analysis: ExpressionAnalysis) -> DagExample:
    """Share eligible AST representations within one validated expression."""
    if analysis.root is not root:
        raise ValueError("DAG analysis must belong to the identical root AST")
    occurrences = _postorder(root, dag_subset=True)
    keys: dict[tuple, int] = {}
    ids: dict[int, int] = {}
    nodes = []
    for expression in occurrences:
        kind = analysis.annotations.type_of(expression)
        if not isinstance(kind, ScalarType):
            raise ValueError("DAG expression lacks a validated intrinsic type")
        children = tuple(ids[id(child)] for child in _children(expression))
        conversions = tuple(
            (site.role, site.source_type, site.destination_type)
            for site in analysis.annotations.conversions_for(expression)
        )
        symbol_id = None
        if isinstance(expression, LiteralExpr):
            key = ("literal", expression.kind, _literal_key(expression.value), kind)
            label = _short(expression.lexeme)
            node_kind = "literal"
        elif isinstance(expression, VarRef):
            symbol = analysis.annotations.binding_of(expression)
            if symbol is None:
                raise ValueError("DAG variable lacks its resolved symbol")
            symbol_id = symbol.id
            key = ("variable", symbol.scope_id, symbol.id, kind)
            label = expression.name
            node_kind = "variable"
        else:
            key = ("operator", expression.operator, children, kind, conversions)
            label = expression.operator.name
            node_kind = "unary" if isinstance(expression, UnaryExpr) else "binary"
        if key not in keys:
            node_id = len(nodes) + 1
            nodes.append(DagNode(node_id, node_kind, label, kind, children, conversions, symbol_id))
            keys[key] = node_id
        ids[id(expression)] = keys[key]
    return DagExample(tuple(nodes), ids[id(root)], len(occurrences))


def dag_from_program(source: str = DAG_SOURCE) -> DagExample:
    """Analyze declarations and one final SHOW, then build an educational DAG."""
    program = Parser(Lexer(source).tokenize()).parse()
    if not program.main.statements or not isinstance(program.main.statements[-1], ShowStmt):
        raise UnsupportedDemonstration("DAG example requires a START block ending in SHOW")
    context = SemanticContext()
    context.collect_signatures(program)
    context.begin_start()
    result = StatementAnalyzer(context).analyze_block(program.main)
    statement = program.main.statements[-1]
    return expression_dag(statement.value, result.show_of(statement))


def render_s() -> str:
    example = synthesized_expression()
    attrs = ", ".join(f"{name}={kind.name}" for name, kind in example.attributes)
    conversions = ", ".join(
        f"{site.context}:{site.role} INT->FLOAT"
        for site in example.analysis.annotations.all_conversions()
    )
    return "\n".join((
        f"S expression: {example.source}", f"Attributes: {attrs}",
        f"Dependencies: {example.graph.edges}",
        f"Order: {example.graph.topological_order()}",
        f"Conversions: {conversions}", f"Result: {example.analysis.type.name}",
    ))


def render_l() -> str:
    example = declaration_trace()
    lines = ["L program: " + example.source]
    for step in example.steps:
        env = ",".join(
            f"{entry.name}:{entry.type.name}#{entry.symbol_id}:{entry.state}"
            for entry in step.environment
        ) or "empty"
        lines.append(f"{step.action}: [{env}] {step.detail}".rstrip())
    lines.append("Attribute order: " + ", ".join(example.graph.topological_order()))
    return "\n".join(lines)


def render_dag() -> str:
    example = dag_from_program()
    lines = [
        f"DAG tree occurrences: {example.tree_occurrences}",
        f"DAG unique nodes: {len(example.nodes)}",
    ]
    for node in example.nodes:
        sites = ",".join(f"{role}:INT->FLOAT" for role, _, _ in node.conversions) or "none"
        lines.append(
            f"n{node.id} {node.kind} {node.label} {node.type.name} "
            f"children={node.children} conversions={sites} symbol={node.symbol_id}"
        )
    lines.append(f"DAG root: n{example.root_id}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", choices=("s", "l", "dag", "all"), nargs="?", default="all")
    args = parser.parse_args()
    parts = []
    if args.example in ("s", "all"):
        parts.append(render_s())
    if args.example in ("l", "all"):
        parts.append(render_l())
    if args.example in ("dag", "all"):
        parts.append(render_dag())
    print("\n\n".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
