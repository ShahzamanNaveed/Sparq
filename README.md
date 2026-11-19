# Sparq

Sparq is a statically typed, procedural programming language designed for the CS4031 Compiler Construction semester project. This repository will contain a Python 3.11+ compiler for `.spq` source files. The approved language specification is [docs/SPARQ_LANGUAGE_SPEC.md](docs/SPARQ_LANGUAGE_SPEC.md).

The planned compiler phases are lexical analysis, recursive-descent syntax analysis and AST construction, semantic analysis, Three-Address Code generation, optimization, and code generation for a custom register-based virtual machine. The lexer, parser, immutable AST, and parser-theory demonstrations are complete. Semantic analysis now integrates signatures, every function body, and START into a complete program result; educational SDD, SDT, attribute, and expression-DAG demonstrations are also available. M4 implementation and final independent verification are complete and accepted by the student group. M5 Tasks 01–04 are completed and accepted. The [M5 intermediate-code architecture](docs/INTERMEDIATE_CODE_GENERATION.md), core typed IR records and builder, scalar-expression lowering, and partial straight-line statement, array, READ, and SHOW lowering are in place. Task 04A's conditional audit found a nested-occurrence selection issue, corrected in Task 04B and approved by the student group. Tasks 05–08 have not started; control-flow lowering, calls, RETURN lowering, and complete TAC generation remain future work. The latest verified regression baseline is 1435 passed, 0 failed, 0 skipped. Optimization, target-code generation, and VM execution have not started.

## Structure

- `docs/`: frozen M1 specification, milestone tracker, and compiler-theory and semantic guides.
- `sparq/`: lexer, recursive-descent parser, immutable AST, semantic analyzers, and partial typed IR lowering components.
- `tools/`: separate educational parser-theory and semantic demonstrations.
- `tests/`: pytest coverage for lexical, syntax, semantic, and partial IR lowering behavior.
- `examples/`: reference Sparq source programs, which cannot yet be executed.

## Python environment

Use Python 3.11 or newer. A virtual environment is recommended. The project has no production dependencies. `pytest` is configured as an optional test dependency. After installing the test extra with `python -m pip install -e ".[test]"`, run tests with `python -m pytest -q`. In a restricted environment, use `python -m pytest -q --basetemp=.pytest_tmp` to keep temporary test files in the project.

## Lexer debugging

Run `python -m sparq.lexer examples/hello.spq` to print token type, original lexeme, decoded literal, and 1-based source span. End positions are exclusive. The command exits nonzero and prints a source diagnostic for a lexical error. It does not compile or execute Sparq programs.

The lexer reads the source into an indexed character buffer. `peek()` and `peek_next()` inspect one or two characters without consuming them; `advance()` consumes a character and updates the line and column. CRLF is consumed as one line break. Whitespace and comments are discarded. Recognition is fail-fast: the first lexical error raises `LexicalError` with a category, position, and offending text. Python callers can use `Lexer(source).tokenize()` or `Lexer.from_file(path).tokenize()`. Each call creates its own scanner state.

Identifiers are scanned completely before exact, case-sensitive keyword lookup. A contiguous number-like sequence is checked as a whole, distinguishing integers from decimal floats and rejecting malformed neighbors. Two-character operators are checked before one-character operators. Quoted literals are scanned before comment logic can affect their contents.

## Parser API

Use `Parser(Lexer(source).tokenize()).parse()` to construct a complete `Program` AST. It accepts zero or more function declarations followed by one `START` block and requires the final EOF token. `Parser(tokens).parse_expression_only()` remains available for parsing a single expression. Invalid syntax raises `ParseError` with a category and source position. Parsing does not resolve names, check types, or execute code.

No command to compile or run Sparq source exists yet. `examples/hello.spq` can be tokenized and parsed through the Python API.

## Semantic analysis

Run `.venv\Scripts\python -m sparq.program_semantic examples/hello.spq` to lex, parse, and semantically validate a source file without executing it. Python callers can use `SemanticAnalyzer(program).analyze()` from `sparq.program_semantic`; the completed result retains the original AST, ordered function results, START analysis, and scope snapshots. See [docs/SEMANTIC_ANALYSIS.md](docs/SEMANTIC_ANALYSIS.md) for its annotation and future TAC input contract.

## Academic integrity

The assignment requires all three group members to participate in the language design, implementation, testing, and documentation; understand the complete project; and defend it in the viva. Plagiarism and sharing complete work between groups are prohibited. External tools, libraries, and code must be acknowledged. The group remains responsible for independently understanding and defending its work.
