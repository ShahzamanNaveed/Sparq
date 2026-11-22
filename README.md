# Sparq

Sparq is a statically typed, procedural programming language designed for the CS4031 Compiler Construction semester project. This repository will contain a Python 3.11+ compiler for `.spq` source files. The approved language specification is [docs/SPARQ_LANGUAGE_SPEC.md](docs/SPARQ_LANGUAGE_SPEC.md).

The planned compiler phases are lexical analysis, recursive-descent syntax analysis and AST construction, semantic analysis, Three-Address Code generation, optimization, and code generation for a custom register-based virtual machine. The lexer, parser, immutable AST, semantic analyzer, and typed TAC generator are complete. M5 was independently verified and accepted. The [optimization guide](docs/CODE_OPTIMIZATION.md) describes M6's implemented machine-independent passes and their pending independent audit. The full regression suite currently passes **1538 tests**. The handout's machine-dependent optimization requirement awaits the M7 target model. Target-code generation and VM execution have not started.

## Structure

- `docs/`: frozen M1 specification, milestone tracker, and compiler-theory and semantic guides.
- `sparq/`: lexer, recursive-descent parser, immutable AST, semantic analyzers, complete typed TAC generation and verification, and conservative optimization.
- `tools/`: separate educational parser-theory and semantic demonstrations.
- `tests/`: pytest coverage for lexical, syntax, semantic, typed TAC generation, verification, and optimization.
- `examples/`: reference Sparq source programs, which can be compiled to TAC but cannot yet be executed.

## Python environment

Use Python 3.11 or newer. A virtual environment is recommended. The project has no production dependencies. `pytest` is configured as an optional test dependency. After installing the test extra with `python -m pip install -e ".[test]"`, run tests with `python -m pytest -q`. In a restricted environment, use `python -m pytest -q --basetemp=.pytest_tmp` to keep temporary test files in the project.

## Lexer debugging

Run `python -m sparq.lexer examples/hello.spq` to print token type, original lexeme, decoded literal, and 1-based source span. End positions are exclusive. The command exits nonzero and prints a source diagnostic for a lexical error. It does not compile or execute Sparq programs.

The lexer reads the source into an indexed character buffer. `peek()` and `peek_next()` inspect one or two characters without consuming them; `advance()` consumes a character and updates the line and column. CRLF is consumed as one line break. Whitespace and comments are discarded. Recognition is fail-fast: the first lexical error raises `LexicalError` with a category, position, and offending text. Python callers can use `Lexer(source).tokenize()` or `Lexer.from_file(path).tokenize()`. Each call creates its own scanner state.

Identifiers are scanned completely before exact, case-sensitive keyword lookup. A contiguous number-like sequence is checked as a whole, distinguishing integers from decimal floats and rejecting malformed neighbors. Two-character operators are checked before one-character operators. Quoted literals are scanned before comment logic can affect their contents.

## Parser API

Use `Parser(Lexer(source).tokenize()).parse()` to construct a complete `Program` AST. It accepts zero or more function declarations followed by one `START` block and requires the final EOF token. `Parser(tokens).parse_expression_only()` remains available for parsing a single expression. Invalid syntax raises `ParseError` with a category and source position. Parsing does not resolve names, check types, or execute code.

`examples/hello.spq` can be tokenized, parsed, semantically checked, and compiled to a verified TAC listing. Source execution awaits the later VM milestone.

## Semantic analysis

Run `.venv\Scripts\python -m sparq.program_semantic examples/hello.spq` to lex, parse, and semantically validate a source file without executing it. Python callers can use `SemanticAnalyzer(program).analyze()` from `sparq.program_semantic`; the completed result retains the original AST, ordered function results, START analysis, and scope snapshots. See [docs/SEMANTIC_ANALYSIS.md](docs/SEMANTIC_ANALYSIS.md) for its annotation and TAC input contract.

## Typed TAC

Run `.venv\Scripts\python -m sparq.tac examples/hello.spq` to compile source through semantic analysis to a complete verified, readable Three-Address Code listing. Python callers can use `generate_tac(program, analysis)` or `TACGenerator(program, analysis).generate()` and `verify_program(ir_program)`; `format_tac(ir_program)` renders canonical IR. The generator requires the exact analyzed AST and does not execute the program. See [docs/INTERMEDIATE_CODE_GENERATION.md](docs/INTERMEDIATE_CODE_GENERATION.md) for ownership, path verification, and limitations.

## Code optimization

Run `.venv\Scripts\python -m sparq.tac examples/optimization.spq --compare` to display original and optimized verified TAC, or use `--optimize` for only the optimized listing. The default command remains unoptimized. Python callers can use `optimize_program(ir_program, analysis)` and `analyze_routine(routine)` from `sparq.optimization`. The optimizer does not execute source. See [docs/CODE_OPTIMIZATION.md](docs/CODE_OPTIMIZATION.md) for supported passes, safety limits, the handout requirement still pending, and the reproducible before/after example.

## Academic integrity

The assignment requires all three group members to participate in the language design, implementation, testing, and documentation; understand the complete project; and defend it in the viva. Plagiarism and sharing complete work between groups are prohibited. External tools, libraries, and code must be acknowledged. The group remains responsible for independently understanding and defending its work.
