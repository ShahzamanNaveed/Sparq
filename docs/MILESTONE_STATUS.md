# Sparq milestone status

| Milestone | Scope | Status |
|---|---|---|
| M1 | Language Specification and Grammar Design | Complete and approved |
| M2 | Lexical Analysis | Complete and accepted |
| M3 | Syntax Analysis and AST | Not started |
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
