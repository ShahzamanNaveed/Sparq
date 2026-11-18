# Sparq milestone status

| Milestone | Scope | Status |
|---|---|---|
| M1 | Language Specification and Grammar Design | Completed and approved |
| M2 | Lexical Analysis | Completed and accepted |
| M3 | Syntax Analysis and AST | Completed; ready for student-group acceptance |
| M4 | Syntax-Directed Translation and Semantic Analysis | In progress |
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

M3 Task 03: **Completed and verified.** The parser constructs complete Program ASTs, including function declarations, START, blocks, and every statement form in the frozen grammar. The complete suite passed (286 tests, including 69 new tests). No semantic analysis or later compiler phase was added.

M3 Task 03A: **Independent audit completed; conditional pass.** The read-only review found no confirmed grammar mismatch for lexer-produced programs. It identified missing ordering checks between token spans and unhandled recursion exhaustion in direct calls to public block and statement parsers.

M3 Task 03B: **Robustness corrections completed and verified.** Token streams require each token to start at or after its predecessor's exclusive end. All four public parser entry points convert recursion exhaustion to a controlled RESOURCE_LIMIT diagnostic. Regression tests passed with the full suite (308 passed, 0 failed, 0 skipped). The frozen specification and lexer were not changed.

M3 Task 04A: **Theory design reviewed and approved.** The student group approved the parser theory demonstration design.

M3 Task 04B: **FIRST/FOLLOW/SELECT and LL(1) demonstration accepted.** The complete frozen BNF was extracted and analyzed, with a sparse predictive table, conflict report, and valid and invalid predictive traces. Verification results are recorded in [LL1_ANALYSIS.md](LL1_ANALYSIS.md). The frozen specification and production parser were not changed.

M3 Task 04C: **Completed after audit and correction.** [PARSER_THEORY.md](PARSER_THEORY.md) documents illustrative left-recursion elimination, left factoring, dangling-else resolution, operator-precedence recognition, and a separate shift-reduce trace. Task 06 replaced manually selected unit reductions with a reproducible category-set closure. The production compiler remains unchanged.

M3 Task 04D: **LR(0) and SLR(1) demonstrations accepted after verification.** [LR_DEMONSTRATIONS.md](LR_DEMONSTRATIONS.md) records complete item sets, DFA transitions, ACTION/GOTO tables, FOLLOW sets, conflicts, and valid and invalid G0 traces. The production compiler remains unchanged.

M3 Task 04E: **Canonical LR(1) and LALR(1) demonstrations completed.** [LR_DEMONSTRATIONS.md](LR_DEMONSTRATIONS.md) records complete G1/G2 canonical and merged item sets, tables, conflicts, and traces. The production compiler remains unchanged.

M3 Task 05: **Independent final audit completed; conditional pass.** The production parser and AST had no confirmed defect. The audit identified manual unit reductions in the operator-precedence traces, an epsilon-reduction failure in the educational LR trace helper, and one outdated LR-document sentence.

M3 Task 06: **Corrections completed and verified.** A separate operator-precedence recognizer generates four complete traces using deterministic handle selection and exhaustive unit closure. It recognizes the illustrative arithmetic grammar; it does not construct a unique parse tree or parse the complete Sparq grammar. The educational LR trace handles zero-width reductions, and the LR document describes all three demonstration grammars. The complete suite passed (362 passed, 0 failed, 0 skipped), including 23 new test cases; LL(1), LR, and operator-precedence document checks passed. The frozen specification and production compiler were not changed.

M3 Task 07: **Final verification completed; ready for student-group acceptance.** Independently checked the four documented precedence traces and a new nested expression; confirmed LR epsilon reductions preserve the state stack and use GOTO. Final regression validation: **362 passed, 0 failed, 0 skipped**. The LL(1), LR, and operator-precedence documentation checks passed. M3 Tasks 01–07 were completed; student-group acceptance remained pending at that checkpoint. M4–M8 had not started then.

M4 Task 01: **Architecture approved.** The student group approved separate namespaces, lexical scopes, signature precollection, immutable ASTs, separate annotations, fail-fast diagnostics, and stable symbol IDs.

M4 Task 02: **Implemented; pending student-group review.** Scalar and return type representations, immutable variable/array/function symbols, hierarchical scopes, deterministic per-session IDs, controlled semantic diagnostics, and function-signature collection are in place. Focused infrastructure and integration tests passed. Full regression validation: **380 passed, 0 failed, 0 skipped** (the previous 362 tests remain passing). No complete semantic analyzer has been implemented.

M4 Task 02A: **Independent audit completed; conditional pass.** The read-only review confirmed three public-object invariant gaps: scalar positions could retain VOID in direct symbol construction, function signatures could retain caller-owned lists, and scope identities and parents could be reassigned. The full suite passed (380 passed, 0 failed, 0 skipped).

M4 Task 02B: **Invariant corrections implemented; pending student-group review.** Symbol constructors now enforce semantic type and signature collection invariants, and scope identity and ancestry are read-only while local declarations remain supported. New regression coverage includes these three corrections and selected scope-lifecycle cases. Full validation: **411 passed, 0 failed, 0 skipped**; the previous 380 tests remain passing.

M4 Tasks 03–08: **Not started.** M5–M8 remain not started.
