# Sparq M8 Task 01: final course compliance audit

## Scope, baseline, and verdict

The source of requirements is the four-page `Semester Project.pdf` handout. This audit checked the actual compiler and its separate educational tools against Phases 1–7. The starting branch was `main`, HEAD `51880230801fa8e062794fdde1809d1324b164e5`, with a clean working tree. The frozen specification SHA-256 was `5DBAB70E7776084A9092BCC96616F304DE732527B1B9C2E808970F07922CDB43`. The baseline suite passed **1662/1662**. After 17 independent integration cases were added, the suite passed **1679/1679**, with **0 failures and 0 skips**.

**Task 01 recommendation: CONDITIONAL PASS for final submission, PASS for a student-supervised technical demonstration.** No production defect was confirmed in the inspected and exercised paths. The compiler covers every Phase 1–7 functional category in the handout within the documented conservative optimization scope. The conditions concern human submission evidence: each student must review and defend the work, and the group must record accurate external-tool and AI-assistance acknowledgments. An isolated package build and target import succeeded; a fresh virtual-environment installation on the intended demonstration machine remains for the group. M8 remains in progress; this report does not confer final group acceptance.

Historical checkpoint wording in the frozen specification and milestone tracker describes the state *at those checkpoints*. It is not evidence that the present implementation is missing. The specification was not edited.

## Evidence key and classification

The matrices below use these abbreviations: `L` = `sparq/lexer.py`; `P` = `sparq/parser.py`; `S` = `sparq/program_semantic.py` plus `semantic.py`, `statement_semantic.py`, `function_semantic.py`, `type_rules.py`, and `symbols.py`; `I` = `sparq/tac.py`, the expression/statement/function lowerers, `ir.py`, `ir_builder.py`, and `ir_verify.py`; `O` = `sparq/optimization.py`; `T` = `sparq/target.py`, `target_codegen.py`, `target_optimization.py`, and `vm.py`. `E` = `tests/test_m8_integration.py`; other test filenames are given explicitly. **PASS** means implementation/demonstration, tests, and evaluable documentation were found. **N/A** is used only for a handout feature expressly conditional on language support. No mandatory Phase 1–7 row was classified FAIL. This is evidence from finite inspection and tests, not a proof that every program behaves correctly.

### Phase 1 — language specification and grammar

| Mandatory requirement | Location and test evidence | Status / evaluation note |
|---|---|---|
| Language name, syntax, semantics, keywords, identifiers | `SPARQ_LANGUAGE_SPEC.md` §§1–6; L/P/S; lexer, parser, semantic suites | PASS; Sparq's approved spellings are authoritative. |
| Five scalar types, literals, arithmetic/logical/relational/assignment operators | Spec §§2–5, 11–13; `test_lexer_numbers.py`, `test_type_rules.py`, E | PASS; INT, FLOAT, CHAR, STRING, BOOL are exercised. |
| Comments and delimiters | Spec §§4–5; `test_lexer_comments.py`, `test_lexer_operators.py` | PASS. |
| Declaration, initialization and assignment | Spec §§6, 12; P/S/I; `test_semantic_declarations.py`, `test_tac_statements.py` | PASS. |
| IF/ELSE/nested IF functionality | Sparq WHEN/OTHERWISE, spec §§6, 14; `test_parser_statements.py`, `test_tac_control_flow.py`, E | PASS; handout permits group-defined syntax. |
| SWITCH/CASE/DEFAULT functionality | Sparq SELECT/CASE/DEFAULT, spec §§6, 15; `test_semantic_select.py`, E | PASS. |
| FOR/WHILE/DO-WHILE functionality | Sparq REPEAT/WHILE/DO-WHILE, spec §§6, 16; `test_semantic_loops.py`, E | PASS; REPEAT is the approved FOR form. |
| Functions, parameters, returns, calls; arrays; READ/SHOW | Spec §§6, 17–19; `test_semantic_calls.py`, `test_tac_arrays.py`, `test_vm.py`, E | PASS. |
| Formal BNF, precedence/associativity, ambiguity resolution | Spec §§6–9; `tools/ll1_analysis.py --check-doc`; `PARSER_THEORY.md` | PASS; the 55-nonterminal, 117-alternative grammar check passed. |
| Chomsky classification with justification; compiler architecture | Spec §§10, 24; implemented pipeline in README and modules above | PASS; type-2 context-free grammar and complete phase path documented. |

### Phase 2 — lexical analysis

| Mandatory requirement | Location and test evidence | Status / evaluation note |
|---|---|---|
| Token regular expressions | Spec §5 gives identifier, INT, FLOAT and escape patterns; `NUMBER` in L; `test_lexer_numbers.py` | PASS. Literal/comment recognizers are stateful rather than one regex. |
| Finite-state recognition | L `_identifier`, `_number`, `_quoted`, `_skip_space_or_comment`; state summary below; lexer tests | PASS after this report supplied the previously missing explicit state demonstration. |
| Tokens, lexemes, keywords, operators, literals | L `tokenize`; `test_lexer_keywords.py`, `test_lexer_operators.py`, `test_lexer_strings_chars.py`, `test_tokens.py` | PASS; complete identifier lookup precedes keyword classification. |
| Input buffering and positions | Indexed source, `peek`/`peek_next`/`advance` in L; `test_lexer_positions.py`, `test_lexer_integration.py` | PASS; CR, LF and CRLF and long integers tested. |
| Lexical errors | L and `sparq/errors.py`; `test_lexer_errors.py`, `test_lexer_numbers.py` | PASS; malformed numbers, escapes, unterminated tokens and invalid characters have controlled categories and spans. |
| Manual scanner or LEX/Flex | Manual scanner in L | PASS; Flex is optional, so not required. |

The manual recognition state machines follow these transitions (error states are terminal): identifier `start → ASCII letter/underscore → identifier; identifier → ASCII letter/digit/underscore → identifier; otherwise accept and perform exact keyword lookup`. Numeric `start → digit → numeric run; numeric run → ASCII letter/digit/underscore/dot → numeric run; otherwise accept only if the whole run matches INT or FLOAT, else malformed-number/float error`. Quoted literal `opening quote → body; body → permitted scalar → body; body → backslash → escape; escape → approved escape → body; body → closing quote → accept`; line break/EOF, unsupported escape, invalid scalar, or a CHAR payload of other than one decoded scalar errors. Comment dispatcher `/ + / → line comment until line break/EOF`; `/ + * → block comment until first */`, with EOF before closure an error. Two-character operators are checked before single-character operators. This is a description of implemented control states, not a new lexer design or language change.

### Phase 3 — parsing and theory

| Mandatory requirement | Location and test evidence | Status / evaluation note |
|---|---|---|
| Recursive descent; all approved constructs; syntax errors | P; `test_parser_programs.py`, `test_parser_statements.py`, `test_parser_program_errors.py`, E | PASS; includes empty/nested blocks, functions, arrays, control flow, I/O and bounded parse failures. |
| LL(1), FIRST/FOLLOW, predictive table | `tools/ll1_analysis.py`, `LL1_ANALYSIS.md`, `test_ll1_analysis.py`; documentation check passed | PASS; complete frozen grammar analyzed, zero table conflicts. |
| Left-recursion elimination and left factoring | `PARSER_THEORY.md` §§1–2; `test_operator_precedence.py` and theory checks | PASS as explicit educational transformations; production grammar is already suitable for recursive descent. |
| Ambiguity and dangling else | Spec §8; `PARSER_THEORY.md` §3; parser tests | PASS; braces bind OTHERWISE unambiguously. |
| Operator precedence and shift-reduce | `tools/operator_precedence.py`, `PARSER_THEORY.md` §§4–5; `test_operator_precedence.py`; four trace check passed | PASS for the stated expression subset; not claimed as the production parser. |
| LR(0), SLR(1), CLR(1), LALR(1), tables | `tools/lr_analysis.py`, `LR_DEMONSTRATIONS.md`, `test_lr_analysis.py`, `test_lr1_analysis.py`; doc check passed | PASS for the explicitly stated educational grammars, including conflicts. |

### Phase 4 — semantic analysis and syntax-directed translation

| Mandatory requirement | Location and test evidence | Status / evaluation note |
|---|---|---|
| AST and DAG construction | `sparq/ast_nodes.py`, P; `tools/semantic_demonstrations.py`, `SDD_SDT_DEMONSTRATIONS.md`; AST/DAG tests | PASS; DAG is a documented educational subset, with production optimization DAG separately in O/T. |
| SDD and SDT | `SDD_SDT_DEMONSTRATIONS.md` §§2–4, `tools/semantic_demonstrations.py`; demonstration command and tests passed | PASS. |
| S- and L-attributed definitions and evaluation | Same guide §§2–3; `test_semantic_demonstrations.py` | PASS; dependency/evaluation orders explicit. |
| Symbol tables and scope | S; `test_symbols.py`, `test_semantic_signatures.py`, `test_semantic_program.py` | PASS; identity-based ownership and lexical shadowing checked. |
| Type checking, equivalence and conversion | S; `test_type_rules.py`, `test_semantic_expressions.py`, `test_semantic_assignments.py` | PASS; seven approved conversion contexts covered by semantic/TAC tests. |
| Function arguments, return types, forward/recursive calls | S; `test_semantic_calls.py`, `test_semantic_returns.py`, E | PASS; structural guaranteed-return rule retained. |
| Undeclared/redeclared errors; arrays, conditions and I/O | S; `test_semantic_declarations.py`, `test_semantic_arrays.py`, `test_semantic_control_flow.py`, `test_semantic_io.py` | PASS; controlled diagnostics and source locations. |
| Function/operator overloading and polymorphism | Spec §11 and `SEMANTIC_ANALYSIS.md` Phase 4 mapping | N/A: handout says “where supported”; Sparq 1.0 expressly has none. |

### Phase 5 — intermediate code

| Mandatory requirement | Location and test evidence | Status / evaluation note |
|---|---|---|
| TAC translation of declarations and arithmetic | I; `test_tac_program.py`, `test_tac_expressions.py`, E | PASS; typed temporaries and source spans. |
| IF/ELSE and nested conditions | WHEN/OTHERWISE lowering in I; `test_tac_control_flow.py`, E | PASS; branch targets and short-circuit order. |
| SWITCH/CASE | SELECT lowering in I; `test_tac_control_flow.py`, E | PASS; selector once, no case fallthrough. |
| FOR, WHILE, DO-WHILE | REPEAT, WHILE, DO-WHILE lowering in I; `test_tac_control_flow.py`, E | PASS. |
| Functions and calls | I; `test_tac_calls.py`, E | PASS; ordered arguments and returns. |
| Array operations | I; `test_tac_arrays.py`, E | PASS; initialization, indexed access and bounds guards. |
| IR consistency and safe publication | `sparq/ir_verify.py`, `test_tac_program.py`, `test_ir_builder.py` | PASS; malformed/foreign symbolic and path availability cases tested; no partial valid result published. |

### Phase 6 — optimization

| Mandatory requirement | Location and test evidence | Status / evaluation note |
|---|---|---|
| Basic blocks and CFG | O `analyze_routine`; `test_optimization.py` | PASS; leaders, successors, reachability. |
| DAG optimization and common-subexpression elimination | O local DAG; T target DAG; `test_optimization.py`, `test_target_optimization.py` | PASS; block-local pure subset. |
| Constant folding and propagation | O `_fold`, `_constant_facts`; optimization tests | PASS; exact INT and cross-block must-constant subset; FLOAT arithmetic stays runtime. |
| Dead-code and copy propagation | O local aliases and dead pure definitions; optimization tests | PASS; effects/traps retained. |
| Loop and global optimization | O false-loop pruning and cross-block facts; optimization tests | PASS in conservative scope; no general loop motion or global CSE. |
| Machine-dependent optimization | `sparq/target_optimization.py`; `test_target_optimization.py`, E | PASS; DAG selection, same-register reuse, liveness and spill cleanup. |
| Before/after comparison and explanation | `CODE_OPTIMIZATION.md`; TAC `--compare`, target `--compare-target` | PASS; original/target-optimized/combined counts and stage explanations. |

### Phase 7 — target generation

| Mandatory requirement | Location and test evidence | Status / evaluation note |
|---|---|---|
| Target ISA and instruction selection | `sparq/target.py`, `target_codegen.py`; `test_target_codegen.py` | PASS; all 21 canonical IR instruction families translated. |
| Instruction cost calculation | `target.py:instruction_cost`; `test_target_codegen.py`, `test_target_optimization.py` | PASS; deterministic estimate, not elapsed time. |
| Register allocation and temporary assignment | Three-register spill-all policy, frame slots and liveness in T; target tests | PASS; conservative R0–R2 policy, no graph coloring required by handout. |
| DAG-based code generation | `target_optimization.py:_dag_select`; `test_target_optimization.py` | PASS; actual repeated-operation substitution, block-local pure subset. |
| Executable/simulated instructions | `sparq/vm.py`; `test_vm.py`, E | PASS; explicit frames, recursion, arrays, READ/SHOW and runtime errors. |
| Pre-execution validation | `vm.py:validate_target`; VM tests and E malformed-target probe | PASS; invalid reachable register use rejected before SHOW output. |

## Independent execution and corrections

`E` tests each successful source through A: original TAC → ordinary target, B: original TAC → target optimization, and C: optimized TAC → target optimization. Handwritten oracles cover factorial recursion (`120`), nested array indexing (`9, 4`), all three loop forms plus WHEN/SELECT (`5`), lexical shadowing and short-circuited side-effect calls (`2, 7, FALSE, TRUE` with no side-effect output), mixed FLOAT/INT and signed division/remainder (`5.0, -3, -2`), and five recorded arithmetic seeds (3, 11, 29, 47, 83). Error oracles check prior SHOW output, input fields consumed, division by zero, bounds-before-READ and bounds-before-RHS, and input exhaustion. A source-backed IR with its terminator removed is rejected by the verifier and target generator; a malformed direct target is rejected before any output. Bounded step and call-depth errors are controlled. These cases add independent expected results rather than treating A/B/C agreement alone as evidence.

No production-source defect was confirmed. The original failures found during this Task 01 audit were documentation/reproducibility gaps: the frozen M1 traceability table still described an FSM demonstration as pending, and README's opening sentence used future tense for an implemented compiler. The FSM description above and the README correction address those without changing frozen text or semantics. There were no failing production regressions and no production correction. Historical M7 Task 02A/02B and other earlier corrections remain recorded in `MILESTONE_STATUS.md`; they were not rediscovered here.

`examples/optimization.spq` yielded ordinary **63 instructions/cost 84**, target-optimized **48/69**, and optimized-TAC-plus-target-optimized **28/46**; all VM paths with input `5` printed `14\n12\n0\n` and consumed one input field. These are static model costs, not measured speedups. The new integration cases and existing optimization tests found no incorrect removal, duplication or reordering of observable effects in the exercised paths. Finite testing does not prove formal equivalence.

## Reproducibility and remaining work

- Python `3.14.3` in the existing `.venv` satisfies `pyproject.toml`'s `>=3.11`; 29 production/tool modules parsed and key imports succeeded. No runtime package dependencies are declared; `pytest>=8` is the test extra. `pip show` found no installed Sparq distribution in that working environment. An initial isolated-copy install with `--no-build-isolation` and that `.venv` failed because the environment lacks `setuptools`, not because of project code. Repeating the isolated-copy wheel build and `--target` install with system Python 3.14 and its installed `setuptools 83` succeeded; an import from the target directory outside the repository succeeded. The group should still perform a fresh virtual-environment install on its intended demonstration machine.
- Lexer, semantic, TAC compare, target compare, VM ordinary/optimized, LL(1), LR, operator-precedence, semantic demonstration and educational IR commands exited successfully. Both example files were exercised. The lexer missing-file diagnostic exited 1; malformed argument parsing exited 1. Existing CLI tests cover lexical, syntax/semantic and runtime diagnostic categories.
- The handout's three-person participation, originality, understanding and viva performance require actual student evidence and cannot be inferred from tests. README states the policy but does not list the project's actual external tools, AI assistance, or individual contributions. The group should add an accurate acknowledgment and contribution record before submission; do not fabricate authorship or conceal assistance.
- Submission deliverables to verify manually: clean installation on the intended machine; source repository and required files; repeatable test command; original/optimized TAC and target listings; a live run of valid, invalid and runtime-error programs; theory/SDD demonstrations; accurate external-tool acknowledgments; and a three-student viva rehearsal. No Git publication was performed by this task.
- Nonblocking technical limits: local DAG reuse, restricted constant-loop/global transformations, three-register spill-all allocation, finite VM resource guards, model costs, and finite tests rather than a formal proof. No frozen language change is proposed.

M8 remains **audit/remediation in progress** until the student group completes the submission evidence and manual demonstration. This report is an engineering readiness assessment, not the group's final acceptance or a claim that the compiler is error-free.
