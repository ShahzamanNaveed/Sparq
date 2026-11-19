# Semantic analysis architecture (M4 Tasks 02–06)

These checkpoints provide symbols, lexical scopes, diagnostics, a function-signature prepass, and expression-only type inference. They do **not** validate complete programs.

## Types and symbols

`ScalarType` contains exactly `INT`, `FLOAT`, `CHAR`, `STRING`, and `BOOL`. `VoidType.VOID` is a separate return-only value. `scalar_type(token_type, span)` rejects `VOID` and invalid scalar types with `SemanticError(INVALID_TYPE)`; `return_type` also accepts `VOID`.

`VariableSymbol` is immutable and records an ID, name, scalar or element type, kind (`VARIABLE`, `PARAMETER`, or `ARRAY`), declaring scope ID, source span, and optional array length. Array length is parsed metadata at this stage; positive size and initializer checks come later. `FunctionSymbol` is immutable and stores its ID, ordered parameter names/types, return type, source span, and original immutable `FunctionDecl`.

Both symbol constructors enforce type invariants directly: variable, parameter, and array-element types must be `ScalarType`; function parameters must also be `ScalarType`, while a function return may be `ScalarType` or `VoidType.VOID`. `FunctionSymbol` accepts tuple or list parameter collections, snapshots them as tuples, checks their contents, and requires matching name/type counts. Subsequent caller mutation cannot change the signature.

`SymbolIds` allocates monotonically increasing symbol and scope IDs per `SemanticContext`. They are deterministic for the same traversal order, independent of Python object addresses, and have no global mutable state. Symbol IDs identify declarations *within one analysis session*; the same numeric ID can recur in a fresh session.

## Namespaces and scopes

`FunctionRegistry` is the separate global function namespace. Variables exist only in `Scope` objects; there is no global variable scope. `Scope.declare` inserts locally and rejects a same-scope duplicate. `lookup_local` inspects one scope. `resolve` iteratively walks parents, returning the nearest symbol or `None`; `require` raises `UNDECLARED_NAME` when absent. `FunctionRegistry.resolve` likewise returns `None`, while `require` raises `UNKNOWN_FUNCTION`.

Each scope's public `id` and `parent` are read-only after creation, so identity and lexical ancestry remain stable. The local symbol map remains mutable through `declare`. Context-managed entry and exit move the current-scope reference without changing existing scopes.

`SemanticContext.begin_start()` creates START's outer scope. After `collect_signatures(program)`, `begin_function(function_decl)` creates one scope and registers parameters in it. Future analysis must process that function's outer body statements directly in this scope. `enter_block()` creates a child scope for a *nested* block, and `exit_scope()` returns to the parent. `enter_repeat()` creates a loop-header scope; `enter_block()` then creates its body scope. Exiting the body and loop scope prevents their names leaking outward.

```python
program = Parser(Lexer(source).tokenize()).parse()
context = SemanticContext()
functions = context.collect_signatures(program)  # all signatures, no body validation
function = functions.resolve("f")               # FunctionSymbol or None
scope = context.begin_start()
symbol = context.declare_scalar(program.main.statements[0])
same_symbol = scope.resolve(symbol.name)
context.exit_scope()
```

Declarations are registered in source order. Local variables are never precollected; function signatures are the explicit exception. A future initializer visitor must register a new declaration before visiting its initializer. The new symbol then shadows an outer symbol during that expression. The visitor must track initialization state separately and reject self-reads; Task 02 intentionally does not implement that check.

## Signature pass and diagnostics

`SemanticContext.collect_signatures(program)` visits `Program.functions` in source order, checks duplicate function and parameter names, converts signature types, and registers every valid signature before any future body analysis. This makes later functions and mutually recursive names available for lookup. It does not validate calls, arguments, or returns.

`SemanticError` is fail-fast and carries a category, message, 1-based `SourceSpan`, optional name, and optional expected/actual type text. Current categories are `INVALID_TYPE`, `REDECLARATION`, `UNDECLARED_NAME`, `DUPLICATE_FUNCTION`, `DUPLICATE_PARAMETER`, and `UNKNOWN_FUNCTION`. It leaves lexical and parser diagnostics unchanged.

Malformed direct symbol-constructor arguments raise `TypeError` or `ValueError`, as appropriate for API misuse. Ordinary source-language failures encountered through `SemanticContext` continue to raise controlled `SemanticError` diagnostics. Invalid scope lifecycle calls likewise retain their existing `ValueError` preconditions.

## Scalar and operator rules (Task 03)

`sparq.type_rules.assignment_compatibility(destination, source)` returns `EXACT`, `INT_TO_FLOAT`, or `INCOMPATIBLE`. The five diagonal scalar pairs are exact; the only off-diagonal conversion is source `INT` to destination `FLOAT`. This pure helper does not validate any assignment statement yet.

| Operator group | Accepted operand types | Result | Conversion |
|---|---|---|---|
| `+`, `-`, `*`, `/` | Numeric pairs (`INT`, `FLOAT`) | `INT` for two `INT`s; otherwise `FLOAT` | Promote each `INT` operand in a mixed pair |
| `%` | `INT`, `INT` | `INT` | None |
| `<`, `>`, `<=`, `>=` | Numeric pairs | `BOOL` | Promote the `INT` in a mixed pair |
| `==`, `!=` | Matching scalar types, or mixed `INT`/`FLOAT` | `BOOL` | Promote the `INT` in a mixed numeric pair |
| `AND`, `OR` | `BOOL`, `BOOL` | `BOOL` | None |
| Unary `-` | `INT` or `FLOAT` | Operand type | None |
| `NOT` | `BOOL` | `BOOL` | None |

`binary_rule` returns a result type and optional conversion target for each operand; `unary_result` returns a scalar result. An invalid operand combination returns `None`. Malformed direct type-rule arguments may raise `ValueError` or `TypeError` according to the argument (for example, an unhashable operator raises `TypeError`). These rules do not evaluate expression values.

## Expression inference and annotations (Task 03)

`ExpressionAnalyzer(context).infer(expr)` accepts a parsed expression AST and returns `ExpressionAnalysis(root, type, annotations)` only when the entire requested expression succeeds. On failure, no partial result escapes. Each call creates an independent annotation owner, so the same analyzer can be reused after a failure or after entering another scope. The result retains the standalone root AST. Its annotations retain each visited node, preventing object-ID reuse while those facts exist.

The recursive expression walk may exhaust Python's analysis stack on a long parser-produced operator chain. The public `infer` boundary converts only `RecursionError` to `SemanticError(RESOURCE_LIMIT)` at the expression's 1-based start location; it does not return partial annotations. This is a compiler resource guard, not a Sparq grammar restriction. Completed earlier results remain valid, and the analyzer can be reused after the error.

```python
program = Parser(Lexer("START { INT x; SHOW(x + 2.5); }").tokenize()).parse()
context = SemanticContext()
context.begin_start()
context.declare_scalar(program.main.statements[0])
expression = program.main.statements[1].value
result = ExpressionAnalyzer(context).infer(expression)
assert result.type is ScalarType.FLOAT
symbol = result.annotations.binding_of(expression.left)
sites = result.annotations.conversions_for(expression)
```

The current variable scope is inherited information for `VarRef` and `ArrayAccess`. Literal kinds, resolved symbol types, and operator results synthesize expression types. `type_of(node)` returns the node's intrinsic scalar type; `binding_of(node)` returns a resolved variable or array symbol where applicable; `conversions_for(parent)` returns conversion sites on that parent's operands. Facts are keyed by object identity rather than AST structural equality. A conversion site retains its parent, exact operand occurrence, `left`/`right` role, source and destination types, and operator context. In `(1 + 2) * 3.5`, the inner addition remains `INT`; its *use as the outer left operand* receives the `INT` to `FLOAT` conversion.

Direct `ConversionSite` construction checks that the parent is a binary expression, the role is `left` or `right`, the operand is the identical child at that role, the conversion is `INT` to `FLOAT`, and the context matches an operator that can require it. Parent and role keep separate conversion occurrences distinct even if a manually constructed AST shares one child object. Direct `ExpressionAnalysis` construction requires a valid scalar result type and an annotation owner whose identity-keyed root type equals that result. Invalid direct records raise `TypeError` or `ValueError`; analyzer-produced records retain their frozen fields and established ownership policy.

Bare arrays and bare function names are not scalar values. Array access resolves an array symbol, infers its index as `INT`, and synthesizes the element type; the bound array symbol retains its declared length. Out-of-range indexes are runtime errors and are not evaluated here. The current pass also never performs arithmetic, integer division, floating conversion, or bounds checks. `AND` and `OR` visit both operands for static diagnostics; future TAC and VM stages must implement runtime left-to-right short circuiting and preserve side effects and traps.

Source-level expression failures raise `SemanticError`, including `INVALID_OPERAND_TYPE`, `UNDECLARED_NAME`, `ARRAY_AS_SCALAR`, `FUNCTION_AS_SCALAR`, `WRONG_SYMBOL_KIND`, and `INDEX_TYPE`, with 1-based locations and relevant names or operators. Directly supplied malformed AST nodes may raise `TypeError` or `ValueError`. A current variable scope is required when resolving names.

At the Task 03 checkpoint, `CallExpr` was explicitly deferred. Task 05 now validates calls using precollected signatures, as described below.

Task 04 added partial validation of declarations, assignments, arrays, and supported blocks. Task 05 added calls, returns, and structural return guarantees. Task 06 validates all parser-produced statement categories. Tasks 07 and 08 added educational SDD/SDT demonstrations and complete program-level integration. No AST node is mutated by this infrastructure.

## Partial statement analysis (Task 04)

`StatementAnalyzer(context)` requires an active `SemanticContext` scope. `analyze_statement(stmt)` accepts every parser-produced statement category; a passed `Block` opens and closes a child scope. `analyze_block(block)` traverses an outer START or function body in the **already active** scope. Thus `begin_function(declaration)` first installs parameters, and `analyze_block(declaration.body)` shares their scope. Function-level guaranteed-return checking belongs to `FunctionAnalyzer`, not a standalone `StatementAnalyzer.analyze_block` call.

```python
program = Parser(Lexer("START { FLOAT total = 1; total = total + 2; }").tokenize()).parse()
context = SemanticContext()
context.begin_start()
result = StatementAnalyzer(context).analyze_block(program.main)
declaration, assignment = program.main.statements
symbol = result.declaration_of(declaration)
target = result.target_of(assignment)
assert target.symbol is symbol
sites = result.all_conversions()
```

Declarations are visited in source order. The analyzer validates a scalar type, registers the symbol in the current scope, then infers and checks its optional initializer. Registration before inference gives the new symbol its own name inside its initializer, including when it shadows an outer declaration. A set of initializing symbol IDs rejects direct or nested self-reads with `READ_BEFORE_INITIALIZATION`. The same rule applies to every array initializer element, including reads of an earlier element or self-reads in an index expression. Other previously declared symbols remain readable. The temporary initializing marker is removed in a `finally` block; after a successful declaration, the symbol ID enters the initialized set. Parameters are initialized when declared. This is compiler metadata, not runtime storage.

An omitted scalar initializer records a `DefaultInitialization` descriptor with the exact value for its declared type: `INT` `0`, `FLOAT` `0.0`, `CHAR` `\0`, `STRING` empty string, `BOOL` `False`. An omitted array initializer records one descriptor with that type's element default and the full declared length, without allocating a Python sequence proportional to the length. An explicit array initializer must have exactly the positive literal size; elements are checked left to right with normal assignment compatibility. A very large size remains exact metadata; count-mismatch diagnostic text is bounded.

`resolve_writable(target)` resolves a scalar variable, parameter, or array element as a location. It rejects undeclared names, function names without a local variable binding, whole arrays, indexed scalars, and non-`INT` array indexes. It returns the resolved symbol, element or scalar type, target AST, and optional index expression analysis. Assignment analysis resolves the target and index before inferring the RHS, checks exact compatibility or the sole implicit `INT` to `FLOAT` conversion, and records the target binding. It does not read the target's stored value. For indexed assignment, runtime code must evaluate the index and check bounds **before** evaluating the RHS. Semantic analysis leaves negative and out-of-range indexes, arithmetic traps, value conversion, mutation, and bounds checks to runtime; it does not constant-fold them.

`StatementAnalysis` is returned only on complete success. Its frozen tuple records retain declaration bindings, writable targets, `ExpressionUse` records, default descriptors, statement conversion sites, and block scope identities. Each expression use owns an independent `ExpressionAnalysis`, so a manually shared AST expression can be analyzed in different scopes without silently overwriting bindings. `StatementConversionSite` retains its declaration or assignment owner, identical source expression, role (`initializer`, `element`, or `value`), optional element index, and `INT`/`FLOAT` types; its constructor validates those structural links. `all_conversions()` combines these sites with inherited binary-operator sites per expression use. Intrinsic expression types remain unchanged by use-site conversion. Successful results stay valid after later analyses.

Task 04B strengthens direct record construction. `StatementConversionSite` also requires a `FLOAT` scalar or array declaration destination. An assignment's destination cannot be determined from the assignment AST alone: the completed `StatementAnalysis` checks its conversion against the retained `WritableTarget` type and the RHS's intrinsic `ExpressionAnalysis` type, without re-resolving a symbol. A standalone assignment conversion site therefore establishes ownership and direction, while completed-result construction establishes destination compatibility.

`DefaultInitialization` checks the declaration, symbol kind/type/name/span, exact type-aware default value, and scalar or array length metadata. In particular, Python `False` does not stand for Sparq `INT 0`, and a one-character `STRING` does not stand for `CHAR '\0'`. `WritableTarget` checks AST target kind, symbol kind/name/type, and the identical `INT` index-analysis root for array elements. `ExpressionUse` checks owner, role, element index, and the identical analyzed expression root. Malformed direct record construction raises `TypeError` or `ValueError`.

Direct `StatementAnalysis(...)` construction accepts list or tuple collections, snapshots outer collections and two-item binding pairs into tuples, and checks the complete structural coverage of supported statements and blocks. It verifies required declaration, target, expression-use, default, conversion, and scope records in source order. An empty block is valid with its scope record and empty remaining collections; a nonempty block cannot be represented by an empty successful result. This validation inspects AST relationships and existing type annotations only. It does not repeat symbol resolution, expression inference, runtime evaluation, or a full semantic pass. Results produced by `StatementAnalyzer` pass through the same constructor checks.

The traversal enters and exits nested block scopes in a balanced `finally` path. A failed statement analysis does not return partial results and marks its context invalid for further semantic analysis; start a fresh `SemanticContext` for another attempt. This prevents partially registered symbols from being mistaken for a validated block. The active scope is restored after a nested failure and temporary initializing markers are cleared. Deep statement nesting is reported as `SemanticError(RESOURCE_LIMIT)` at the public boundary. Source errors are fail-fast, 1-based `SemanticError` diagnostics. Direct malformed API arguments may raise `TypeError` or `ValueError`.

Task 06 extends this statement analyzer to every frozen statement category. It remains a per-statement, per-block, or per-function API rather than complete program-level validation.

## Function calls, returns, and function bodies (Task 05)

Call resolution uses `SemanticContext.collect_signatures(program)` before body analysis. `ExpressionAnalyzer.infer(call_expr)` resolves the global function namespace, compares argument count **before** analyzing arguments, then visits arguments left to right and checks each against its declared parameter type. An unknown name raises `UNKNOWN_FUNCTION`; wrong count raises `ARGUMENT_COUNT`; an incompatible argument raises `ARGUMENT_TYPE_MISMATCH` at that argument. `VOID_VALUE` is raised when a fully checked VOID call is used as a scalar value. The call's intrinsic scalar type comes from the declared function return type. A same-named local variable does not affect call resolution; a bare name still uses lexical variable lookup.

`ExpressionAnnotations.call_binding_of(call)` retains a `CallBinding` with the resolved `FunctionSymbol`, ordered intrinsic argument types, and `ArgumentConversionSite` records. `function_of(call)` returns that symbol directly. Each argument conversion retains the call and function identities, exact argument expression, zero-based argument index, and `INT` to `FLOAT` types. Nested binary and call conversions remain in the expression annotation owner. Count mismatch takes priority over errors within supplied arguments; among equal-count arguments, the first source-order error wins. No argument expression is executed during inference.

Conversion occurrences are recorded after analyzing each argument and before moving to the next. `ExpressionAnnotations.all_conversions()` and `StatementAnalysis.all_conversions()` preserve this supported source traversal order, including nested expression conversions and conversions in later statements. This ordering is metadata for future code generation, not runtime evaluation performed by the semantic pass.

`ExpressionAnalyzer.analyze_call(call)` validates a standalone call and returns `CallAnalysis` without demanding a scalar result. `StatementAnalyzer` uses it for `CallStmt`; both VOID and non-VOID results may be discarded. The retained binding's `return_type` records the declared type. `StatementAnalysis.call_of(stmt)` retrieves the completed call record. Declarations, assignments, array elements and indexes, and return expressions use normal `ExpressionAnalyzer.infer`, so VOID calls in those value positions fail.

`SemanticContext.begin_function(declaration)` requires precollected signatures, opens an independent root variable scope, registers parameters, and records a read-only `active_function`. Its outer body shares that parameter scope. Nested blocks preserve the active function; exiting the root clears it. `StatementAnalyzer` validates a `ReturnStmt` against this context: START returns raise `RETURN_OUTSIDE_FUNCTION`; VOID functions allow only bare `RETURN`; non-VOID functions require a compatible expression. An incompatible or missing value raises `TYPE_MISMATCH` or `INVALID_RETURN`. `ReturnAnalysis` retains the owning statement, function, and optional intrinsic expression analysis. `ReturnConversionSite` records a required `INT` to `FLOAT` return conversion without changing the expression's intrinsic type. `StatementAnalysis.return_of(stmt)` retrieves this record.

`FunctionAnalyzer(context).analyze_function(declaration)` requires signature precollection and no active root scope. It opens the parameter scope, validates the supported body statements in source order, applies the structural return check, and closes the root scope. A successful `FunctionAnalysis` retains the declaration, signature identity, parameter symbols, body scope and analysis, and return guarantee. A non-VOID function without that guarantee raises `MISSING_RETURN` at its declaration. VOID functions may fall through. Previously completed results remain valid. A failure invalidates the semantic context, while scope exit clears active function metadata; use a fresh context for another analysis. `RESOURCE_LIMIT` covers deep call or statement analysis. The structural return checker is iterative, so deeply nested direct AST blocks do not exhaust Python's recursion stack in that checker.

```python
from sparq.function_semantic import FunctionAnalyzer

program = Parser(Lexer("FUNC f(FLOAT x) -> FLOAT { RETURN x; } START {}").tokenize()).parse()
context = SemanticContext()
context.collect_signatures(program)
result = FunctionAnalyzer(context).analyze_function(program.functions[0])
assert result.guarantees_return
assert result.body.return_of(program.functions[0].body.statements[0]).function is result.function
```

`check_guaranteed_return(stmt)` is a separate structural query. `RETURN` guarantees return; a block does when a statement in sequence does; `WHEN` requires `OTHERWISE` and returning blocks on both sides; `SELECT` requires `DEFAULT` and every case/default block to return; `DO-WHILE` follows its body. `WHILE` and `REPEAT` alone do not guarantee return. It does not evaluate conditions, selectors, or function calls. Statements after a guaranteed return still receive static validation. Task 06 validates control-flow and I/O bodies before a successful function result can be published.

`CallBinding`, `CallAnalysis`, argument and return conversion records, `ReturnAnalysis`, `FunctionAnalysis`, and the extended `StatementAnalysis` validate their structural owners and required metadata. Accepted list inputs become tuples. Assignment and return destinations are checked against retained symbols; no constructor re-resolves a name in a later scope. These local checks cannot independently prove all source-language semantics; successful source validation still comes from the analyzer traversal. Malformed direct records raise `TypeError` or `ValueError`.

Task 05 performs no function execution, call-frame allocation, pass-by-value copying, numeric conversion, recursion-depth enforcement, arithmetic evaluation, or runtime bounds checking. Those execution rules remain for TAC and VM phases.

## Complete statement-category analysis (Task 06)

`StatementAnalyzer` now traverses every parser-produced statement category. Shared condition validation infers the intrinsic expression type and requires exactly `BOOL` for `WHEN`, `WHILE`, `DO-WHILE`, and a present `REPEAT` condition. A condition record retains its owning statement and independent `ExpressionAnalysis`; `condition_of(owner)` retrieves it. An omitted `REPEAT` condition has no expression record and denotes runtime TRUE. No constant condition skips static validation of a body or branch. Non-BOOL conditions raise `CONDITION_TYPE` at the expression. A VOID call, bare array, or undeclared name retains its established expression diagnostic.

`WHEN` validates its condition, then its block, then its optional `OTHERWISE` block. The two branch blocks are sibling child scopes of the enclosing scope. `SELECT` infers its selector once as `INT`, `CHAR`, or `STRING`; other scalar types raise `INVALID_SELECTOR_TYPE`. CASE labels use only the grammar's literal forms, including unary minus on an integer literal. Their type must exactly match the selector (`CASE_TYPE_MISMATCH`). Each label record retains the owning SELECT, exact clause, scalar type, and decoded value. A per-SELECT set of `(type, decoded value)` detects `DUPLICATE_CASE`, so `01` conflicts with `1` and `-0` with `0`; huge integers are never formatted for this diagnostic. Labels are checked in source order, each CASE body immediately after its label, followed by DEFAULT. Thus an earlier invalid body takes precedence over a later duplicate label. CASE and DEFAULT blocks have separate child scopes. An empty SELECT and a DEFAULT-only SELECT are valid. `selector_of(node)` and `labels_of(node)` expose the retained metadata.

`WHILE` validates its condition in the enclosing scope, then its body in a child scope. `DO-WHILE` statically validates its body first, exits that scope, then validates its trailing condition in the enclosing scope; body declarations are unavailable to that condition. `REPEAT` opens a header scope using `SemanticContext.enter_repeat()`. It validates an optional declaration or assignment initializer, optional BOOL condition, optional assignment update, then its child body scope. This static order makes header symbols available to the update while body-only declarations remain unavailable there. Runtime execution must still use initializer → condition → body → update → repeated condition. The header and body scopes close through `finally` paths, including on failure. `repeat_scope_of(node)` exposes the header scope; `scope_of(node.body)` exposes its child. Existing declaration, assignment, initialization, conversion, and RETURN rules apply inside all control-flow bodies.

`READ` reuses `resolve_writable`, accepting scalar variables, parameters, and indexed array elements while retaining the resolved symbol, type, and optional INT index analysis. `read_of(node)` retrieves the target. `SHOW` infers its single scalar expression and retains its full annotations through `show_of(node)`. Neither operation performs input or output during analysis. A future runtime must bounds-check indexed READ before consuming input. Negative and out-of-range indexes, arithmetic traps, and READ parsing remain runtime concerns.

`StatementAnalysis` extends its frozen occurrence records with conditions, selectors, CASE labels, REPEAT header scopes, READ targets, and SHOW expressions. Existing block scope records represent each branch and loop body. The completed-result constructor snapshots accepted lists and pairs, walks nested statement structure iteratively, and checks required condition, selector, label, branch scope, header scope, READ, SHOW, declaration, assignment, call, and RETURN coverage. It validates owner and expression identities, CASE type and duplicate consistency, and parent scope relationships using retained records; it does not rerun expression inference or execute source. Missing or contradictory direct records raise `TypeError` or `ValueError`. `all_conversions()` includes condition, selector, loop component, READ-index, SHOW, and nested statement expression conversions in deterministic static traversal order.

Function analysis now validates complete supported control-flow and I/O bodies before applying the unchanged conservative return checker. RETURN keeps the active function context through nested scopes; START still rejects it. Non-VOID bodies without a structural guarantee still raise `MISSING_RETURN`. A failed statement or function analysis publishes no successful result, invalidates its context, clears temporary initialization markers, and unwinds nested scopes. Deep statement traversal raises controlled `RESOURCE_LIMIT` at the public semantic boundary. Earlier completed results remain usable; new attempts require a fresh context.

This pass only records static facts. It performs no condition execution, branch selection, loop execution, SELECT dispatch, input consumption, output formatting, numeric conversion, bounds check, or VM work. Task 08 supplies complete program-level semantic orchestration.

## Educational attribute and DAG demonstrations (Task 07)

[SDD_SDT_DEMONSTRATIONS.md](SDD_SDT_DEMONSTRATIONS.md) gives reproducible SDD and SDT examples, synthesized expression types, inherited lexical environments, valid attribute dependency orders, and a restricted educational expression DAG. `tools/semantic_demonstrations.py` uses the production parser and semantic analysis results: expression types and conversions are synthesized facts; scope and initializing-state information illustrate inherited environments and left-to-right declaration visibility. Its action trace is an explanatory replay of validated metadata, not semantic actions inserted into the production parser. Its DAG shares immutable expression *representations* within one example; it performs no production optimization or runtime common-subexpression elimination.

## Complete program integration (Task 08)

`SemanticAnalyzer(program).analyze()` from `sparq.program_semantic` accepts the original parser `Program` AST. Each call creates a fresh session: collect all function signatures, analyze each function body in source order, and finally analyze START in an independent root scope. A fail-fast error at any stage prevents publication of `AnalysisResult`. Lexical and parser errors remain in their preceding phases. Repeat calls create independent, deterministic session-local IDs. Completed earlier results remain valid; root scopes are exited after analysis.

The frozen `AnalysisResult` owns the original AST, ordered signatures and corresponding `FunctionAnalysis` records, START `StatementAnalysis`, its root scope, and detached immutable `ScopeSnapshot` records with scope IDs, parent IDs, and local symbols. Construction validates full function coverage and identity ownership, START ownership, and scope coverage, then **seals every retained lexical scope**. Public `Scope.declare(...)` raises `ValueError` on these completed scopes; public lookup remains available and agrees with the detached snapshots. The same rule covers START, function roots, nested blocks, branches, and REPEAT header/body scopes. `function_of(declaration)` uses AST identity, while `signature_of(name)` and `scope_of(id)` provide read-only lookups. The live `SemanticContext` is not part of the completed result. Standalone lower-level analysis still uses mutable scopes until a complete program result finalizes them. Future consumers should use the detached snapshots and validated occurrence records, not attempt new declarations.

```python
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer

program = Parser(Lexer("START { INT x; SHOW(x); }").tokenize()).parse()
result = SemanticAnalyzer(program).analyze()
symbol = result.start.declaration_of(program.main.statements[0])
show_type = result.start.show_of(program.main.statements[1]).type
root_scope = result.scope_of(result.start_scope.id)
```

Use the owning function's `body` or `result.start` to retrieve declarations, parameter symbols, defaults, writable targets, control-flow conditions and scopes, normalized CASE labels, calls, RETURN records, expression types and bindings, and `all_conversions()`. These existing records preserve operand, initializer, array-element, assignment, argument, and RETURN conversions. An owner-specific lookup avoids ambiguity for a manually shared AST node analyzed in different contexts. Symbols and scopes remain distinguishable after their analysis scope exits. IDs are session-local; they are not global across independent runs.

Run `.venv\Scripts\python -m sparq.program_semantic examples/hello.spq` to lex, parse, and validate without executing source. Ordinary lexical, syntax, and semantic errors print a diagnostic and return a nonzero exit.

### Future TAC input contract

M5 should consume the validated original AST with its matching function and START results. Existing symbol, sealed-scope snapshot, expression, conversion, target, default, call, return, and CASE records provide type and binding decisions; TAC need not repeat general type checking or lexical name resolution. Lowering must follow frozen **runtime** order rather than static annotation order: left-to-right operands and arguments, short-circuit logic, one SELECT selector evaluation without fallthrough, DO-WHILE body before condition, indexed assignment bounds check before RHS, indexed READ bounds check before input, and preservation of arithmetic traps and numeric conversion failures. INT remains arbitrary precision and FLOAT remains finite binary64; observable side effects and errors must retain their specified execution points.

REPEAT executes an optional initializer **once**, evaluates its condition before each iteration (omission means TRUE), exits on FALSE, otherwise executes the body, then its optional update, and repeats from the condition. Static semantic checking may inspect initializer, condition, update, then body; TAC and runtime must use initializer → condition → body → update.

Calls evaluate scalar arguments left to right, apply required INT-to-FLOAT use-site conversions, and pass the resulting scalar values **by value** into parameters. Assigning a parameter does not mutate the caller's scalar storage. Runtime frames and value transfer are future work; arrays are not parameters. The configurable initial VM call-depth maximum is **1,000**. Exceeding it must produce a controlled Sparq runtime error for stack exhaustion, not a Python recursion error; static analysis does not enforce that runtime limit. The frozen specification does not prescribe a particular diagnostic category string. No TAC instruction, temporary, label, basic block, frame, or runtime value is implemented here.

### Phase 4 requirement mapping

The course handout requires AST and DAG construction, SDD/SDT, S-/L-attributed evaluation, symbol tables and scopes, type checking and conversions, function argument and return validation, and semantic-error detection. The parser supplies the AST; the separate Task 07 guide and utility supply a restricted **educational** DAG and attribute demonstrations; the production semantic components and program coordinator supply complete static program validation. Function/operator overloading and polymorphism are conditional on language support and are not Sparq v1.0 features. Production DAG optimization belongs to a later phase. M4 implementation and final independent verification are complete and accepted by the student group. The last verified regression run passed **1190 tests**, with **0 failed** and **0 skipped**. M5 has not started.
