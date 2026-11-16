# Sparq milestone status

| Milestone | Scope | Status |
|---|---|---|
| M1 | Language Specification and Grammar Design | Complete and approved |
| M2 | Lexical Analysis | Complete and accepted |
| M3 | Syntax Analysis and AST | In progress; Task 03B pending group review |
| M4 | Syntax-Directed Translation and Semantic Analysis | Not started |
| M5 | Intermediate Code Generation | Not started |
| M6 | Code Optimization | Not started |
| M7 | Target Code Generation and VM | Not started |
| M8 | Integration, Testing, Documentation, Viva | Not started |

M2 Task 01: **Completed.** Project initialization established the approved grammar (55 nonterminals and 117 alternatives), Python configuration, and local Git repository. At that checkpoint pytest was unavailable and lexer work had not started.

M2 Task 02: **Completed.** Lexical analyzer, token infrastructure, diagnostics, development CLI, and automated lexical tests were implemented. Pytest was installed in the project-local .venv. The approved language specification was not changed.

M2 Task 03: **Completed.** Independent read-only lexer review gave a conditional pass and identified a large-integer token-display failure in the development CLI.

M2 Task 04: **Completed.** Large-integer token display was corrected and regression-tested. The lexer API and approved specification were not changed.

M2 Task 05: **Completed.** The student group accepted M2. Final validation passed (123 passed, 0 failed, 0 skipped), the hello example tokenized successfully, and the first local Git baseline was prepared. No M3 or later implementation has started.

M3 Task 01: **Architecture designed and approved.** Recursive-descent parser and AST architecture were reviewed as the basis for implementation.

M3 Task 02: **Completed and accepted.** All approved AST node records and the expression-only recursive-descent parser were implemented. At that checkpoint the complete suite passed (181 tests). The frozen specification and lexer were not changed.

M3 Task 02A: **Independent audit completed; conditional pass.** The read-only review identified mutable list inputs retained by tuple-annotated AST fields and malformed token payloads reaching parser construction and diagnostics.

M3 Task 02B: **Robustness corrections completed.** All six AST collection fields snapshot list inputs as tuples and reject other collection input types. Parser initialization validates essential token fields, and malformed-token diagnostics are bounded. Regression tests passed with the full suite (217 passed, 0 failed, 0 skipped), including all 123 original lexer tests. The frozen specification and lexer were not changed.

M3 Task 03: **Implemented and verified; pending student-group review.** The parser now constructs complete Program ASTs, including function declarations, START, blocks, and every statement form in the frozen grammar. The complete suite passed (286 tests, including 69 new tests). No semantic analysis or later compiler phase was added.

M3 Task 03A: **Independent audit completed; conditional pass.** The read-only review found no confirmed grammar mismatch for lexer-produced programs. It identified missing ordering checks between token spans and unhandled recursion exhaustion in direct calls to public block and statement parsers.

M3 Task 03B: **Robustness corrections implemented and verified; pending student-group review.** Token streams now require each token to start at or after its predecessor's exclusive end. All four public parser entry points convert recursion exhaustion to a controlled RESOURCE_LIMIT diagnostic. Regression tests passed with the full suite (308 passed, 0 failed, 0 skipped). The frozen specification and lexer were not changed.

M3 Task 04: **Not started.** Parser theory demonstrations.

M3 Task 05: **Not started.** Independent parser review.
