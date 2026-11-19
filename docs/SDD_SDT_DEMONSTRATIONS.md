# Sparq syntax-directed and expression-DAG demonstrations

**Scope:** M4 Task 07 educational examples. The approved [Sparq specification](SPARQ_LANGUAGE_SPEC.md) and its LL(1) grammar are unchanged. `tools/semantic_demonstrations.py` reads the production lexer, parser, AST, type analysis, and statement analysis. It does not execute Sparq or produce TAC.

The course handout's Phase 4 asks for ASTs and DAGs, SDD/SDT, S- and L-attributed evaluation, symbol tables, scope management, type checking, conversion, and argument/return validation. The current production passes supply the latter semantic facts. The DAG in this document is a **representation-only teaching example**. Production DAG optimization belongs to a later phase.

## 1. Terminology and implementation relationship

| Concept | Meaning here |
|---|---|
| Syntax-directed definition (SDD) | Grammar productions paired with attribute equations and semantic constraints. |
| Syntax-directed translation scheme (SDT) | Grammar productions with actions written at specific positions among right-hand-side symbols. |
| Synthesized attribute | Flows from a symbol's children to that symbol, such as an expression's intrinsic type. |
| Inherited attribute | Supplied by a parent or an appropriate left sibling, such as the visible lexical environment. |
| Concrete parse tree | Contains every grammar-symbol and terminal occurrence in a derivation. The production parser does **not** retain one. |
| Abstract syntax tree (AST) | The production parser's immutable, punctuation-free structural result. |
| Dependency graph | Attribute occurrences as nodes, prerequisite-to-dependent arrows. It is neither a parse tree nor an expression DAG. |
| Expression DAG | A representation that may refer to one eligible structural node from multiple operand positions. It is not executed or optimized here. |

The actual compiler builds an immutable AST with handwritten recursive descent, then performs a **separate semantic traversal**. The formal SDD and embedded SDT below explain equivalent attribute and action ordering; they are not code installed in the production parser.

## 2. S-attributed expression definition

This **illustrative left-recursive arithmetic fragment** makes the attribute equations easy to see. It is *not* the frozen right-recursive LL(1) production grammar. The corresponding production AST has left-associated `BinaryExpr` nodes. `rule(op, left, right)` means the frozen `binary_rule` result or a semantic error. Every `E`, `T`, and `F` occurrence has synthesized `type` and **local** `conversions` attributes. A conversion belongs to this occurrence's operator uses, not to an intrinsically retyped child or an accumulated subtree list.

| Illustrative production | Synthesized rule |
|---|---|
| `E -> E1 + T` | `r = rule(+, E1.type, T.type); E.type = r.result; E.conversions = r.operand_conversions` |
| `E -> T` | `E.type = T.type; E.conversions = ()` |
| `T -> T1 * F` | `r = rule(*, T1.type, F.type); T.type = r.result; T.conversions = r.operand_conversions` |
| `T -> F` | `T.type = F.type; T.conversions = ()` |
| `F -> INT_LITERAL` | `F.type = INT; F.conversions = ()` |
| `F -> FLOAT_LITERAL` | `F.type = FLOAT; F.conversions = ()` |

Every attribute in this fragment is synthesized. Binary rules require child types before the parent result and its conversion-site attribute. An invalid rule raises an error; it cannot invent a valid type. The same principle covers actual Sparq unary and Boolean AST nodes: `NOT FALSE OR TRUE` has `BOOL` at every operator, while `TRUE + 1` produces `INVALID_OPERAND_TYPE`. There is no numeric truthiness, string concatenation, or FLOAT-to-INT promotion.

### Annotated illustrative parse tree: `1 + 2.5 * 3`

The `E/T/F` nodes below are **grammar symbols** from the illustrative fragment; tokens and `+`/`*` remain visible, so this is a concrete parse-tree example. Brackets mark the required use-site conversion.

```text
E.type=FLOAT [left E: INT→FLOAT]
├─ E.type=INT; E.conversions=()
│  └─ T.type=INT
│     └─ F.type=INT ─ INT_LITERAL(1)
├─ +
└─ T.type=FLOAT [right F: INT→FLOAT]
   ├─ T.type=FLOAT
   │  └─ F.type=FLOAT ─ FLOAT_LITERAL(2.5)
   ├─ *
   └─ F.type=INT ─ INT_LITERAL(3)
```

The multiplication synthesizes `FLOAT` from `FLOAT * INT` and records a right-operand INT-to-FLOAT conversion on `3`. The addition synthesizes `FLOAT` from `INT + FLOAT` and records a left-operand conversion on `1`. Both INT literals retain intrinsic `INT` type. Pass-through and literal production occurrences have empty local conversion collections. No numeric multiplication or addition is evaluated.

### Corresponding production AST attribution

```text
BinaryExpr(PLUS)  type=FLOAT, left-use conversion INT→FLOAT
├─ LiteralExpr(1)  type=INT
└─ BinaryExpr(STAR) type=FLOAT, right-use conversion INT→FLOAT
   ├─ LiteralExpr(2.5) type=FLOAT
   └─ LiteralExpr(3)   type=INT
```

The actual parser does not retain the `E`, `T`, or `F` concrete-tree nodes. `ExpressionAnalyzer` produces the AST node types and conversion records shown above. The frozen grammar itself remains right-recursive with AST construction arranged to preserve left associativity.

### S-attributed dependency graph

For the **AST attribution**, postorder names are `n1=1`, `n2=2.5`, `n3=3`, `n4=2.5*3`, `n5=1+(2.5*3)`. Every arrow points from a prerequisite attribute to a dependent attribute:

```text
n2.type ─┐
         ├─→ n4.type ─┐
n3.type ─┘            ├─→ n5.type
n1.type ──────────────┘

n2.type, n3.type → n4.conversion
n1.type, n4.type → n5.conversion
```

The utility emits the exact edge pairs:

```text
(n2.type,n4.type) (n3.type,n4.type)
(n2.type,n4.conversion) (n3.type,n4.conversion)
(n1.type,n5.type) (n4.type,n5.type)
(n1.type,n5.conversion) (n4.type,n5.conversion)
```

One valid topological order is `n1.type, n2.type, n3.type, n4.type, n4.conversion, n5.type, n5.conversion`. The resulting types are `INT, FLOAT, INT, FLOAT, FLOAT`; conversion attributes identify `*:right INT→FLOAT` and `+:left INT→FLOAT`. Independent prerequisites can appear in another order. A dependency cycle is rejected rather than topologically evaluated.

Additional S examples: `1 + 2 * 3` synthesizes `INT` with no conversions. `NOT FALSE OR TRUE` synthesizes `BOOL` with no conversions. `TRUE + 1` reports `INVALID_OPERAND_TYPE` rather than a synthesized result. These outcomes are cross-checked through the production analyzer.

## 3. L-attributed lexical-environment definition

This second **illustrative fragment** models sequential statements; it is not a replacement for the frozen grammar. `env_in` is inherited on `List`, `Stmt`, `Decl`, `Show`, `Block`, and `Expr`. Their `env_out`, `Expr.type`, `Decl.checked`, and `Decl.conversion` are synthesized where applicable. An environment is a *symbolic immutable snapshot* of bindings and their `registered`/`initializing`/`ready` states, not a live production `Scope` object. `Decl.conversion` is either the required declaration-use `INT→FLOAT` promotion or empty; internal operand conversions remain expression facts.

| Production | Inherited and synthesized rules |
|---|---|
| `List -> Stmt List1` | `Stmt.env_in = List.env_in`; `List1.env_in = Stmt.env_out`; `List.env_out = List1.env_out` |
| `List -> ε` | `List.env_out = List.env_in` |
| `Stmt -> Decl` | `Decl.env_in = Stmt.env_in`; on success `Stmt.env_out = Decl.env_out` |
| `Stmt -> Show` | `Show.env_in = Stmt.env_in`; on success `Stmt.env_out = Show.env_out` |
| `Stmt -> Block` | `Block.env_in = Stmt.env_in`; on success `Stmt.env_out = Block.env_out` |
| `Decl -> Type Id = Expr ;` | `registered = register(Decl.env_in, Type.type, Id.name)`; `Expr.env_in = mark_initializing(registered, Id.name)`; `Expr.type = infer(Expr, Expr.env_in)` through the expression interface below; `Decl.checked = compatible(Type.type, Expr.type)`; on success `Decl.conversion = promotion(Decl.checked, Type.type, Expr.type)`; `Decl.env_out = mark_ready(Expr.env_in, Id.name)` after checking and conversion recording. |
| `Show -> SHOW ( Expr ) ;` | `Expr.env_in = Show.env_in`; infer and require scalar `Expr.type`; on success `Show.env_out = Show.env_in` after validation. |
| `Block -> { List }` | `List.env_in = child_scope(Block.env_in)`; on successful `List.env_out`, set `Block.env_out = Block.env_in`. Local declarations do not enter the enclosing environment. |
| `Type -> INT \| FLOAT \| CHAR \| STRING \| BOOL` | `Type.type` is the corresponding scalar type of its terminal. |
| `Id -> IDENTIFIER` | `Id.name` is the token's decoded identifier spelling. |

`Expr` is an **imported attribution component**, not an undefined production in this statement fragment. It consumes inherited `Expr.env_in`, resolves names in that lexical environment (rejecting absent names and reads of initializing bindings), and synthesizes intrinsic `Expr.type` plus internal operand-conversion facts. Incompatible operators or non-scalar uses raise a semantic error. The worked sources use the frozen Sparq expression syntax and production `ExpressionAnalyzer`; this table does not restate its full grammar. The `START { List }` worked example supplies an initially empty root environment; the nested `Block` production models additional lexical blocks. These environments describe **binding visibility**, not runtime variable values or assignments.

For `Decl`, the inherited attribute of right-hand-side `Expr` depends on the left-hand-side's inherited `env_in` and the **left siblings** `Type.type` and `Id.name`. `List1.env_in` depends on the left sibling `Stmt.env_out`. Each bridge passes its parent's inherited environment to its sole child; `Block` passes a child environment to `List`. No inherited attribute depends on a later right sibling. Synthesized `env_out` depends on inherited input and validated child results, so the equations are acyclic. A declaration is registered and marked initializing **before** its initializer is analyzed, matching Sparq's approved shadowing and self-read rules. Only the later `ready` transition depends on successful compatibility and conversion recording.

### Worked environment and action trace

```sparq
START {
    INT x = 10;
    FLOAT y = x + 2.5;
    SHOW(y);
}
```

`#1` and `#2` are deterministic symbol identities in this demonstration session. `registered` precedes the initializer marker; `initializing` is the state used while resolving that initializer.

| Stage | Visible immutable snapshot | Result |
|---|---|---|
| Enter START | `{}` | Empty incoming environment |
| Register `x` | `{x: INT#1 registered}` | `x` is now the nearest binding |
| Mark and infer `10`, check | `{x: INT#1 initializing}` | Initializer `INT`; exact compatibility |
| Complete `x` | `{x: INT#1 ready}` | Pass to next statement |
| Register `y` | `{x: INT#1 ready, y: FLOAT#2 registered}` | `x` remains visible |
| Mark `y` initializing | `{x: INT#1 ready, y: FLOAT#2 initializing}` | `y` is the nearest binding during its initializer |
| Infer `x + 2.5` | Same snapshot | `x` binds to #1; left INT operand needs FLOAT promotion; expression type `FLOAT` |
| Complete `y` | `{x: INT#1 ready, y: FLOAT#2 ready}` | Exact declaration compatibility |
| Infer `SHOW(y)` | Same ready snapshot | `y` binds to #2; scalar type `FLOAT` |

The generated trace spells out `register`, `mark initializing`, `infer initializer`, `record operand conversion`, `check compatibility`, and `complete declaration` in order. It is a **reconstruction from a successful production analysis result**, not a parser callback or a second symbol-table implementation.

### L-attributed dependency graph

The utility builds the **complete direct dependency graph at this statement-fragment interface** for the flat worked example, including `Stmt` bridges. It uses one node for each displayed attribute or semantic-rule intermediate. Here `x.init_env` denotes `Expr.env_in`, `x.expr_type` denotes `Expr.type`, and `x.conversion` denotes `Decl.conversion`. The imported expression component's internal operand dependencies are represented separately by the expression example above; its result type is the statement graph's interface node. Each arrow below is a direct rule input, not merely a transitive ordering constraint:

```text
List0.env_in → Stmt0.env_in → x.env_in
x.env_in, x.type, x.name → x.registered
x.registered, x.name → x.init_env → x.expr_type
x.type, x.expr_type → x.checked
x.checked, x.type, x.expr_type → x.conversion
x.conversion, x.init_env, x.name → x.env_out → Stmt0.env_out → List1.env_in
List1.env_in → Stmt1.env_in → y.env_in
y.env_in, y.type, y.name → y.registered
y.registered, y.name → y.init_env → y.expr_type
y.type, y.expr_type → y.checked
y.checked, y.type, y.expr_type → y.conversion
y.conversion, y.init_env, y.name → y.env_out → Stmt1.env_out → List2.env_in
List2.env_in → Stmt2.env_in → show2.env_in → show2.expr_env → show2.expr_type
show2.env_in, show2.expr_type → show2.env_out → Stmt2.env_out → List3.env_in
List3.env_in → List3.env_out
```

The CLI displays one valid deterministic topological order. Every prerequisite precedes its dependent. `x.init_env` and `y.init_env` contain the *initializing* declarations, which is why self-reads can be diagnosed without falling back to an outer symbol. The graph is complete for these flat `Decl`/`Show` instances; a nested-block instance would additionally use the `Block` equations above.

Negative source examples checked by the production analyzer:

| Source fragment inside START | Result and inherited environment |
|---|---|
| `INT y = x; INT x = 10;` | `UNDECLARED_NAME`: `x` is absent when `y`'s initializer is analyzed. |
| `INT x = x + 1;` | `READ_BEFORE_INITIALIZATION`: the new `x` is already registered but pending. |
| `INT x = 10; { INT x = x + 1; }` | `READ_BEFORE_INITIALIZATION`: the initializer resolves the new inner `x`, not the ready outer `x`. |

## 4. Embedded-action SDT illustration

The following is a **translation scheme on the illustrative declaration fragment**. Braces here denote educational semantic actions, not Sparq source braces:

```text
Decl → Type Id
       { register Id with Type.type in current scope }
       =
       { mark Id initializing }
       Expr
       { infer Expr.type and internal operand conversions;
         check assignment_compatibility(Type.type, Expr.type);
         record an INT→FLOAT declaration-use conversion if required;
         mark Id ready on success }
       ;
```

For `FLOAT y = 1;`, the action order is `register y`, `mark initializing`, `infer INT`, `check FLOAT←INT`, `record INT→FLOAT`, `complete y`. For `INT x = x + 1;`, name resolution sees the pending `x` and raises `READ_BEFORE_INITIALIZATION`; completion does not occur. This is an SDT because the actions have **positions** in the production. The SDD above states attribute equations without embedding execution positions. The production compiler implements the corresponding order in `StatementAnalyzer` after parsing, rather than embedding actions in `Parser`.

## 5. Educational expression DAG

The utility accepts one fully analyzed expression from a START block ending in `SHOW`. Its restricted subset is scalar literals, resolved scalar variable references, unary minus, and binary `+`, `-`, `*`. It declines calls, array accesses, logical operations, and other operators explicitly. The production AST and its annotations remain unchanged.

Nodes are built in deterministic postorder, with IDs `n1`, `n2`, and so on. A structural key includes literal kind and decoded value (binary64 bits for FLOAT), intrinsic type, or the resolved variable's scope and symbol ID. Operator keys include operator kind, **ordered** child IDs, result type, and operand-conversion roles and types. A repeated eligible structure reuses a node ID. A root node and every operand reference must point to valid earlier IDs, which makes the completed graph acyclic. Even when two operand positions reference the same node, their positions remain distinct.

Direct `DagNode` construction validates supported operator labels and at most one promotion per operand role. The completed `DagExample` additionally validates operator result types and exact promotions against its referenced child-node types using Sparq's type rules. A direct record cannot claim an INT result for a mixed promoted arithmetic operation. These checks cover this educational arithmetic subset; they do not create a production intermediate representation. The two positions of a binary node may still reference the same child ID.

### Example A: repeated subexpression

For `START { INT a; INT b; SHOW((a + b) * (a + b)); }`, the original expression tree has **7 occurrences**: two `a`, two `b`, two `+`, and one `*`. The representation DAG has **4 unique nodes**:

```text
n1 = a                 INT, symbol #1
n2 = b                 INT, symbol #2
n3 = PLUS(n1,n2)       INT
n4 = STAR(n3,n3)       INT  ← root; left and right positions both retained
```

### Example B: operand order

`(a - b) + (b - a)` has 7 tree occurrences and **5** DAG nodes: `a`, `b`, `MINUS(a,b)`, `MINUS(b,a)`, and the root `PLUS`. The subtraction nodes remain distinct because their ordered operands differ. No operator is silently made commutative.

### Example C: intrinsic types and promotions

`1 + 2.5 * 3` has five literal/operator tree occurrences and five DAG nodes. The `STAR` node is intrinsically `FLOAT` and retains `right INT→FLOAT`; the root `PLUS` is `FLOAT` and retains `left INT→FLOAT`. INT and BOOL, and CHAR and STRING, remain distinct literal types. A variable with the same spelling but a different resolved symbol identity gets a distinct key.

### Example D: explicitly excluded inputs

`SHOW(f())` and `SHOW(a[0])` are valid scalar-expression shapes when their declarations are valid, but the teaching DAG raises `UnsupportedDemonstration` for `CallExpr` or `ArrayAccess`. It does not present a misleading optimized graph for them.

**Representation sharing is not runtime common-subexpression elimination.** Sparq variables can change, calls have effects, arithmetic and conversion may trap, array access bounds may fail, and logical operators short circuit. This example neither executes shared nodes once nor crosses statement boundaries. Future production optimization must preserve all observable effects and errors; this teaching utility proves no such optimization safe.

## 6. Evaluation orders and reproduction

Parsing reads source according to the frozen grammar and constructs an AST. An S-attributed dependency graph can be evaluated in a child-before-parent topological order. The L-attributed environment model proceeds left to right through statement siblings. Production semantic analysis traverses the AST and checks all branches, including constant-false branches. Future runtime evaluation is different: logical operators short circuit, DO-WHILE executes its body before its condition, and REPEAT executes body before update even though static validation checks update before body. DAG sharing here changes only a representation.

From the project root, with the existing virtual environment:

```powershell
.venv\Scripts\python -m tools.semantic_demonstrations s
.venv\Scripts\python -m tools.semantic_demonstrations l
.venv\Scripts\python -m tools.semantic_demonstrations dag
.venv\Scripts\python -m tools.semantic_demonstrations all
.venv\Scripts\python -m pytest -q tests/test_semantic_demonstrations.py --basetemp=.pytest_tmp
```

The `s` command prints `Result: FLOAT`, `*:right INT->FLOAT`, `+:left INT->FLOAT`, and the seven-attribute topological order listed above. The `l` command prints registered/initializing/ready snapshots and the `record operand conversion` step for `y`. The `dag` command prints `DAG tree occurrences: 7`, `DAG unique nodes: 4`, and `n4` with `children=(3, 3)`. `all` concatenates the three deterministic demonstrations. The pytest command checks independent expected values, graph order and cycles, declaration timing, error cases, DAG identity, and unsupported constructs.

This checkpoint does not implement complete program-level semantic orchestration, TAC, production DAG optimization, constant folding, code generation, or VM execution. The frozen language has no function overloading or object-oriented polymorphism; its built-in operator compatibility and INT-to-FLOAT promotion are **not** user-defined operator overloading. The course handout asks for overloading or polymorphism demonstrations only where supported by the proposed language.
