# Semantic analysis architecture (M4 Task 02)

This checkpoint provides symbols, lexical scopes, diagnostics, and a function-signature prepass. It does **not** validate complete programs.

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

Subsequent M4 tasks will traverse full statements and expressions, attach bindings and types in separate analysis data, check initializers and arrays, validate calls and return paths, and produce the SDD/SDT demonstrations. No AST node is mutated by this infrastructure.
