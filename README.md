# Sparq

Sparq is a statically typed, procedural programming language designed for the CS4031 Compiler Construction semester project. This repository will contain a Python 3.11+ compiler for `.spq` source files. The approved language specification is [docs/SPARQ_LANGUAGE_SPEC.md](docs/SPARQ_LANGUAGE_SPEC.md).

The planned compiler phases are lexical analysis, recursive-descent syntax analysis and AST construction, semantic analysis, Three-Address Code generation, optimization, and code generation for a custom register-based virtual machine. Lexical analysis and complete program parsing are implemented; later phases are not.

## Structure

- `docs/`: frozen M1 specification and milestone tracker.
- `sparq/`: token model, lexical errors, manual lexer, immutable AST, and recursive-descent parser.
- `tests/`: pytest coverage for lexical and syntax behavior.
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

## Academic integrity

The assignment requires all three group members to participate in the language design, implementation, testing, and documentation; understand the complete project; and defend it in the viva. Plagiarism and sharing complete work between groups are prohibited. External tools, libraries, and code must be acknowledged. The group remains responsible for independently understanding and defending its work.
