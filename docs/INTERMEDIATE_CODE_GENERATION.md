# Sparq M5 intermediate code generation: approved architecture and implementation status

**Status:** The student group approved the six Task 01/01A architecture decisions when authorizing Task 02. Core structural IR records and a controlled builder are implemented; Task 02 awaits independent audit. No source-to-TAC generator or complete IR verifier exists yet.

**Source of truth:** the frozen [Sparq language specification](SPARQ_LANGUAGE_SPEC.md), the CS4031 *Semester Project* handout (Phase 5, page 4), and the accepted M4 [semantic contract](SEMANTIC_ANALYSIS.md).
**Inspected baseline:** `f78313591a3702db6ba0dd59ea691b6370d64c0b` on `main`; local `origin/main` tracking ref matched it. That observation does not verify the live remote server. M4 is accepted and committed. M5 implementation has not started.

This document records the approved architecture for a complete, typed Three-Address Code (TAC) pipeline. The manually constructed Task 02 record API is documented in section 22. Worked TAC listings remain illustrative, not outputs of a generator.

## 1. Exact course requirements and phase boundaries

Phase 5 says students must **implement an intermediate code generator** translating their proposed language into **Three-Address Code (TAC)**. The generated code must demonstrate translation of the constructs below. Sparq's approved names `WHEN/OTHERWISE`, `SELECT/CASE/DEFAULT`, and `REPEAT` supply the handout's IF-ELSE, SWITCH-CASE, and FOR functionality.

| Handout Phase 5 requirement | Proposed deliverable and classification | Task | Verification |
|---|---|---:|---|
| Intermediate code generator producing TAC | Complete production lowering from `AnalysisResult`; readable TAC listing | 02–08 | End-to-end valid and invalid programs; deterministic listing and IR verification |
| Variable declarations | Production scalar/array initialization at each execution of the declaration | 04 | Defaults, explicit values, loop re-entry, shadowing |
| Arithmetic expressions | Production typed operations, precedence from AST, runtime-trap preservation | 03 | Operator and conversion matrices; representative traces |
| IF-ELSE and nested conditions | Production `WHEN/OTHERWISE` branches and nested/short-circuit expressions | 03, 05 | Branch traces, nested cases, skipped traps |
| SWITCH-CASE | Production `SELECT` with decoded `CASE`, `DEFAULT`, no fallthrough | 05 | All selector types, negative labels, default-only/empty forms |
| FOR, WHILE, DO-WHILE | Production `REPEAT`, `WHILE`, `DO-WHILE` | 05 | Order and loop re-entry checks |
| Function definitions and calls | Production routines, ordered by-value arguments, returns, recursion references | 06 | Forward/mutual calls, VOID/value calls, conversions |
| Array operations | Production allocation/init, indexing, checks, load/store, indexed READ | 04 | Check-before-RHS/input and element conversion checks |

The Phase 5 paragraph **does not explicitly require** quadruples, triples, indirect triples, or backpatching. It does not prescribe an opcode set, basic blocks, a control-flow graph, SSA, execution, or an IR data model. A quadruple-like in-memory structure is therefore an architectural proposal, while optional triple/indirect-triple and backpatching displays are educational unless the group or instructor adds a requirement. The required production deliverable remains TAC for the complete language.

Phase 4 supplies the accepted immutable AST, symbol/type/conversion facts, and educational SDD/SDT and DAG material. Phase 6 explicitly requires **basic blocks, a CFG, DAG optimization, constant folding and propagation, common-subexpression elimination, dead-code elimination, copy propagation, loop and global optimization, and machine-dependent optimization**, with original/optimized comparisons. Phase 7 explicitly requires target instruction design, instruction selection and cost, register allocation, temporary-to-register assignment, DAG-based code generation, and executable or simulated target instructions. The Phase 6 reference to machine-dependent optimization is a boundary ambiguity: the group should decide how to demonstrate it with the Phase 7 target without moving VM implementation into M5.

## 2. Candidate representation comparison

| Candidate | Readability and academic use | Types, identity, control flow, calls/arrays | M6/M7 suitability and cost |
|---|---|---|---|
| Text-only TAC | Familiar and easy to print | Requires reparsing strings to recover type, symbol identity, labels, ordered call arguments, and effects | Poor canonical form; cheap display |
| **Typed structured quadruple-style TAC** | Still prints as ordinary TAC/quadruples | Tagged operands and instructions retain types, IDs, labels, arrays, ordered arguments, source spans | Recommended: direct verification and later optimization/lowering; moderate effort |
| Triples | Useful textbook display with position references | Insertion/reordering changes positional references; branches, calls, and arrays need explicit conventions | Optional derived subset/display; unsuitable as sole production representation |
| Indirect triples | Position indirection makes some reordering easier | Still requires conventions for types, calls, arrays, effects, and labels | Optional educational view derived from canonical records |
| SSA | Clear def-use and optimization theory | Needs merges/phi nodes for Boolean values, loops, mutable variables, arrays, and calls | Unnecessary M5 complexity; no handout requirement |

**Approved direction:** one canonical typed instruction sequence per routine, with a future quadruple-style *display*. Task 02 implements tagged variants for calls, branches, arrays, and other non-four-field operations. Optional textbook displays will derive from that canonical sequence; no parallel authoritative instruction streams exist.

### Decision provenance

The following distinctions are deliberate. **Frozen** means prescribed by the approved Sparq specification; **handout** means the course's Phase 5 obligation; **design** means a group-approved implementation choice; **deferred** means a later-phase implementation decision.

| Subject | Provenance and decision |
|---|---|
| Production TAC for all required constructs | **Handout.** A complete generator is mandatory. |
| Runtime order, types, conversions, traps, scopes, calls, and I/O | **Frozen.** The IR must preserve these behaviors. |
| Typed structured quadruple-style canonical IR and tagged instruction variants | **Design.** The handout does not prescribe an in-memory format. |
| Ordered immutable CALL argument tuple, no shared pending buffer | **Design** chosen to preserve **frozen** left-to-right by-value call semantics. |
| Explicit `CHECK_BOUNDS` yielding a checked-element handle | **Design** chosen to make **frozen** check-before-access/RHS/input ordering visible. |
| Branch-based Boolean merge temp with no SSA/phi | **Design** chosen to preserve **frozen** short circuiting. |
| Routine-local symbolic labels, forward references, no production patch lists | **Design.** Target addressing is **deferred** to M7. |
| Restricted derived triple/indirect-triple and optional backpatching teaching views | **Design.** These names are not explicit **handout** Phase 5 requirements. |
| VM registers, frames, array layout, call-depth enforcement, instruction costs | **Deferred** to M7; the configurable initial depth of 1,000 and controlled error are **frozen**. |

## 3. Proposed program, routine, and construction boundaries

The Task 02 record shapes are:

```text
IRProgram(source_program: Program, semantic_owner: AnalysisResult,
          functions: tuple[IRFunction, ...], entry: IRRoutine)
IRFunction(function: FunctionRef, parameters: tuple[ParameterRef, ...],
           body: IRRoutine)
RoutineId = FunctionRoutine(FunctionSymbol.id) | StartRoutine
IRRoutine(owner: RoutineId, root_scope_id: int,
          parameters: tuple[ParameterRef, ...],
          local_symbols: tuple[VariableRef|ParameterRef|ArrayRef, ...],
          instructions: tuple[Instruction, ...])
Instruction = frozen tagged variant, each with owner: RoutineId and span: SourceSpan
```

`IRProgram` retains the exact `analysis.program` and its semantic owner for provenance, while every routine contains only its own instructions. A START routine has a distinct tagged owner, not a fake user function. Function routine IDs use the matching `FunctionSymbol.id` from the same M4 session; the type tag distinguishes them from symbols and START. Function signatures are collected before any routine is lowered, so calls may target later declarations and recursion. A completed program, routine, instruction, operand, and owned collection are immutable. Builders, current emission position, temporary/label counters, and pending forward-label references are mutable only during one generation call. Publication is all-or-nothing after structural verification. The source AST and sealed M4 scopes are never changed.

The record model must preserve the difference between *a source declaration* and *an execution of its initializer*. A declaration in a loop can run repeatedly. Frame-local symbol storage may be allocated by the future VM, but initialization instructions execute at the declaration site on every visit. Arrays use compact length/type metadata; M5 must never allocate their elements at compile time.

## 4. Typed operand taxonomy and identity

| Category | Required value and metadata | Identity, owner, and lifetime | Validation |
|---|---|---|---|
| `Constant` | Exact decoded value plus `ScalarType`; optional source lexeme/span | Value operand, no storage; INT arbitrary precision, FLOAT finite binary64, BOOL distinct from INT, CHAR distinct from STRING | Exact Python type checks (`type(v) is bool` versus `int`); finite FLOAT; CHAR one scalar |
| `VariableRef` | `VariableSymbol.id`, `scope_id`, scalar type, kind VARIABLE/PARAMETER | Session-local symbol identity; storage in owning call frame | Must match a retained symbol/snapshot and kind; no name-only lookup |
| `ArrayRef` | Array symbol ID, scope ID, element type, positive length | Array storage in owning frame; same symbol may initialize on each block entry | Must match ARRAY symbol and `array_length` |
| `Temporary` | Routine owner, positive local number, scalar type | Exists only during that routine invocation; cannot collide with source names | Definition/use and type checks; not a VM register |
| `BoolMergeTemp` | Routine owner, positive local number, BOOL type, merge tag | Scalar temp assigned on mutually exclusive true/false exits and read after their join | Both typed definitions must cover every reaching path; no SSA/phi |
| `CheckedElement` | Routine owner, guard number, resolved array identity, stabilized INT index | Non-scalar proof value produced by one explicit check; valid for one dynamic access path | Must be created by `CHECK_BOUNDS`, used with the same array/index and before any reinitialization of that array |
| `LabelRef` | Routine owner, positive local number | Compile-time branch target inside one routine | Exactly one definition, no cross-routine jump |
| `FunctionRef` | `FunctionSymbol.id`, parameter and return types | Global function namespace; independent of variables | Must match a collected signature |

Use structured IDs internally; `%t1`, `%g1`, `L1`, `v17(x)`, and `f3(name)` are diagnostic spellings only. An identifier literally named `t1` remains its own `VariableSymbol`. Two shadowing `x` declarations remain distinct symbol IDs. The same numeric temporary, guard, or label number may be reused in different routines because its owner is part of its identity. Independently generated IR sessions reset counters and do not share mutable builders. A guard is an IR check result, not a source-visible value or a speculative runtime object.

## 5. Instruction model and preliminary operation inventory

A plain `(op, arg1, arg2, result)` display fits unary/binary/move instructions, but not all semantics. The canonical in-memory model is a **closed tagged union** of frozen records: `InitScalar, Move, Load, Unary, Binary, Compare, Convert, InitArray, InitElement, CheckBounds, LoadElement, StoreElement, Label, Jump, BranchBool, Call, Return, ReadScalar, ReadElement, Show, HaltStart`. Every variant has `owner: RoutineId` and `span: SourceSpan`, then shape-specific typed fields. The spelling in the table is provisional; the variant and typed fields are canonical, while quadruple/text renderings are derived. A builder may use mutable drafts internally; no incomplete draft escapes into a completed routine. Each generated instruction uses its originating AST span; synthesized labels use their owning statement's span.

Representative *record shapes*, still conceptual:

```text
Binary(owner, span, op: arithmetic-op, left: typed-value,
       right: typed-value, result: Temporary)
Move(owner, span, destination: VariableRef|Temporary|BoolMergeTemp,
     source: typed-value)
CheckBounds(owner, span, array: ArrayRef, index: INT-value,
            result: CheckedElement)
LoadElement(owner, span, checked: CheckedElement, result: Temporary)
StoreElement(owner, span, checked: CheckedElement, value: typed-value)
Call(owner, span, function: FunctionRef, arguments: tuple[typed-value, ...],
     result: Temporary|None, discard_result: bool)
BranchBool(owner, span, condition: BOOL-value,
           true_target: LabelRef, false_target: LabelRef)
```

`typed-value` means Constant, scalar VariableRef, or scalar Temporary (including a BOOL merge temp); arrays, guards, labels, and functions are not scalar values. The Call fields distinguish VOID (no result and no discard flag), non-VOID expression (typed result), and non-VOID statement whose value is deliberately discarded (no result, discard flag true). All collections are immutable tuples in completed records.

| Family and example | Inputs → result; semantic preconditions | Possible runtime error / effect / flow |
|---|---|---|
| `INIT_SCALAR v, c` | Typed constant/value → resolved scalar declaration slot; exact or explicitly converted type | Storage write at every declaration visit; no branch |
| `MOVE v, x`, `LOAD t, v` | Typed value → same-type storage/temp; `LOAD` captures current value | Read/write mutable storage; no branch |
| `BINARY t, PLUS, a, b` | Two typed numeric operands → typed temp; operator/type rule from M4 | `/`, `%` may divide by zero; FLOAT arithmetic may become nonfinite; no branch |
| `UNARY t, MINUS, a`, `NOT t, a` | Valid M4 operand type → same numeric type or BOOL | FLOAT result can become nonfinite where applicable; no branch |
| `COMPARE t, LT/EQ/..., a, b` | M4-approved matching or promoted operands → BOOL | Conversion must already precede comparison; no branch |
| `TO_FLOAT t, a` | INT → FLOAT, only at an M4 conversion site | May fail if no finite binary64 result; no branch |
| `INIT_ARRAY a, length, default` | Resolved ARRAY symbol, positive length, typed default → array storage | Runtime allocation/storage effect; no large M5 allocation |
| `CHECK_BOUNDS g, a, i` | ArrayRef and stabilized INT index → `CheckedElement` guard `g` | May trap; guard carries this exact array/index relationship |
| `LOAD_ELEM t, g`; `STORE_ELEM g, x` | Guard from the prior check, typed element value → scalar temp or none | Array read/write; no second observable bounds check |
| `INIT_ELEM a, k, x` | ArrayRef and compile-time verified initializer position `k` → none | Array write at declaration execution; no dynamic index/check |
| `LABEL L`, `JUMP L`, `BRANCH_BOOL b, Lt, Lf` | Same-routine label refs; BOOL branch operand | Control-flow change; no implicit truthiness |
| `CALL t?, f, (a0,...)` | FunctionRef and ordered, already evaluated/converted scalar argument tuple → typed temp for expression call, absent for VOID/discarded statement call | Calls may do I/O, recurse, trap; control returns unless runtime error |
| `RETURN x?`; `HALT_START` | Compatible function result, or VOID; START terminates entry | Routine termination; return value transferred by value |
| `READ_SCALAR v`; `READ_ELEM g` | Resolved writable target or checked-element guard | Input consumption/parse errors; failed read does not change target |
| `SHOW x` | One evaluated scalar value | Output and formatting effect, exactly once |

`CALL` carries its own immutable ordered argument tuple rather than a global stream of `ARG` instructions. The builder evaluates and captures each argument before the next, applying each recorded conversion at that use site; a nested call completes its own CALL and result before its caller captures that argument. Verification requires the `FunctionRef` to match a collected `FunctionSymbol`, tuple length and each **post-conversion** operand type to match the ordered signature, and source call binding ownership to match. A VOID CALL must have no result; a non-VOID expression CALL must define a correctly typed temporary; a non-VOID call statement may deliberately discard its result. A CALL cannot accept an array parameter. No shared mutable pending-argument buffer exists.

Arithmetic can use one tagged opcode plus explicit operand/result types, rather than a separate Python class for every INT/FLOAT operation. The eventual VM may specialize `PLUS_INT` and `PLUS_FLOAT` during M7 selection. This avoids duplicated M5 lowering while retaining exact type rules. Division and remainder must never inherit Python's floor-division or modulo semantics by accident.

The effect contract should be **derived from validated instruction variants**, with no mutable user-supplied `pure` flag: reads/writes, I/O, calls, traps, and control flow are classified by opcode and operand types. `BINARY DIV`, `TO_FLOAT`, and `CHECK_BOUNDS` are potentially trapping even if their result is unused. `CALL` is conservatively effectful. Future M6 passes may prove narrower facts, but cannot erase or move an operation across an observable event or trap without proving equivalence.

## 6. Temporary, label, and forward-reference policy

Each routine builder starts separate temp, guard, and label counters at one. It allocates a fresh typed temporary only for a value that must be captured or computed; literals may remain immediates, and a direct variable operand is allowed only when its read time is unambiguous. Ordinary computation temps have one static defining instruction, although a loop may execute it repeatedly. A specifically tagged BOOL **merge temp** may have multiple mutually exclusive static MOVE definitions at the true and false exits, with the same BOOL type and a common join; its use requires a definition on every reaching path. Array guards have one defining check. Source variables remain mutable storage and are not subject to these temp rules. A separate namespace and structured owner prevent collisions with user identifiers and with other routines. Labels are symbolic routine-local IDs, allocated before emitting forward branches. The builder may hold unresolved symbolic destinations while emitting; the completed IR must contain only defined same-routine labels. This is simple deferred resolution; a textbook backpatching list is optional and not required by the handout. Duplicate definitions, undefined targets, or jumps across functions fail verification.

## 7. Exact M4-to-IR input contract

The production entry point should receive an accepted `AnalysisResult`, never an unvalidated AST. Each function uses its own `FunctionAnalysis.body` and START uses `result.start`. In particular, do not build one global AST-node-ID map: records are **occurrence and owner specific**, and manually shared AST objects can have different semantic owners.

| Required lowering fact | Existing record or accessor | Proposed use |
|---|---|---|
| Original AST, functions, START | `AnalysisResult.program`, `program.functions`, `program.main` | Traversal in source order |
| Signature and function owner | `result.signatures`, `result.functions`, `result.function_of(decl)`, `signature_of(name)` | Routine declarations and call targets |
| Ordered parameter symbols | `FunctionAnalysis.parameters` and `function` | Formal slots, signature validation |
| Scalar/array declaration symbol and array length | `StatementAnalysis.declaration_of(node)`, `VariableSymbol.kind/type/array_length` | Storage identity and initialization |
| Local symbol inventory, parent relationships | `result.scopes`, `result.scope_of(id)` (`ScopeSnapshot`) | Check references and frame-local slot layout |
| Lexical block and REPEAT header scope | `body.scope_of(block)`, `body.repeat_scope_of(for_stmt)` | Scope provenance; dynamic initialization placement |
| Expression type and variable/array binding | Owning `ExpressionAnalysis.annotations.type_of(expr)`, `binding_of(expr)` | Typed reads and operations |
| Expression use in declaration/assignment | `body.expressions` `ExpressionUse(parent, role, analysis, element_index)` | Select the exact owner for initializer, element, index, or RHS |
| Function call binding/argument conversions | Owning annotations `call_binding_of(call)`, `CallBinding.argument_types/conversions`; `body.call_of(stmt)` for call statement | Function identity, ordered value arguments |
| Binary conversion | `annotations.conversions_for(binary)` `ConversionSite(parent, operand, role,...)` | Insert conversion at left/right use |
| Initializer, array-element, assignment conversion | `body.conversions` `StatementConversionSite(parent, operand, role, element_index,...)` | Insert conversion at exact store use |
| Return conversion | `body.return_of(stmt)` `ReturnAnalysis.value/conversion` | Convert before RETURN |
| Assignment and READ targets | `body.target_of(assign)`, `body.read_of(read)` `WritableTarget(target, symbol, type, index_analysis)` | Store identity and ordered index check |
| Defaults | `body.defaults` `DefaultInitialization(parent, symbol, element_value, length)` | Exact scalar/array defaults without compile-time array allocation |
| Branch/loop condition | `body.condition_of(stmt)` | BOOL lowering, including short circuit |
| SELECT selector and decoded CASE labels | `body.selector_of(select)`, `body.labels_of(select)` `CaseLabelAnalysis(type,value,clause)` | Evaluate selector once; compare decoded typed constants |
| SHOW and RETURN expression | `body.show_of(show)`, `body.return_of(return_stmt).value` | Evaluate once with correct expression annotations |

`ExpressionAnnotations.all_conversions()` and `StatementAnalysis.all_conversions()` provide inspection/coverage, but their **static traversal order is not runtime instruction order** (notably REPEAT). Lowering uses each exact owner's records while following the frozen runtime order. No missing semantic fact was found for the supported AST categories. The implementation still must index existing tuple records by object identity and role efficiently; that is builder design, not a semantic-contract defect. `ScopeSnapshot` is detached and immutable; no completed `Scope.declare` call is permitted.

## 8. Expression values, stabilization, and conversion sites

Conceptual `lower_value(expr, owning_analysis) -> typed operand` visits the AST's evaluated children in frozen left-to-right order. A literal returns its exact typed immediate. A scalar reference uses its resolved `VariableSymbol`; evaluating it reads the *current* value, which can be captured with `LOAD` before a later effect if needed. An array access evaluates the index, checks bounds, then loads one element. Unary and ordinary binary expressions emit typed operations into temps. A call evaluates each argument and required conversion left to right, captures by-value arguments, and emits one CALL with its ordered tuple.

Do not confuse recording `VariableRef(symbol_id)` with evaluating it. The current language has no globals, array parameters, or assignment expressions, so a callee cannot directly mutate caller-local scalar storage; calls can still perform observable I/O and trap. The safe initial rule is to stabilize a variable or array read before any later sibling/argument action that could reorder its observation, and to freeze each call argument before evaluating the next. Avoid unconditional temps for literal immediates. Array reads always execute their check and load at the source evaluation point. Future optimization may remove provably redundant copies without changing effects.

Seven required INT-to-FLOAT use contexts must materialize one explicit, potentially trapping `TO_FLOAT` at the exact site:

| Context | M4 owner metadata | Placement |
|---|---|---|
| Binary left/right | `ConversionSite(parent, operand, role)` | Immediately after the corresponding operand evaluation: left evaluation → left conversion → right evaluation → right conversion → parent operation. A failed left conversion prevents right evaluation |
| Scalar initializer | `StatementConversionSite(role='initializer')` | After initializer, before `INIT_SCALAR` |
| Array element initializer | `StatementConversionSite(role='element', element_index)` | After that element, before its `INIT_ELEM` |
| Scalar assignment | `StatementConversionSite(role='value')` | After RHS, before `MOVE` |
| Indexed assignment | Same `role='value'` | **After index bounds check** and RHS, before `STORE_ELEM` |
| Function argument | `ArgumentConversionSite(call, argument, index)` | Immediately after argument evaluation, before later arguments/CALL |
| RETURN | `ReturnAnalysis.conversion` | After returned expression, before RETURN |

For example, `FUNC f(FLOAT p) -> FLOAT { RETURN 1; } START { FLOAT a = 1 + 2.0; FLOAT b[1] = {1}; a = 1; b[0] = 1; SHOW(f(1)); }` produces distinct conversion occurrences for the binary left operand, array element, both assignments, call argument, and RETURN; the initializer of `a` needs no *additional* conversion because the binary result is already FLOAT. Replace it with `FLOAT a = 1;` to exhibit the separate scalar-initializer site. The proposed IR never computes the conversion during generation. It preserves intrinsic INT type until that use site; only the produced temporary has FLOAT type.

## 9. Arithmetic, comparison, and Boolean lowering

Use M4's `type_of` and conversion annotations, with no new type inference. INT remains arbitrary precision; FLOAT is finite binary64 with round-to-nearest, ties-to-even, subnormals and signed zero. INT division truncates toward zero and `a % b = a - trunc(a/b)*b`; the runtime must not use Python floor `//` or `%` for negative operands. Division/remainder by zero, nonfinite FLOAT operations, and failed finite INT-to-FLOAT conversion remain runtime errors at their execution points. M5 records operations and checks only; M7 implements arithmetic.

Separate conceptual `lower_value(expr)` and `lower_condition(expr, true_label, false_label)`. Comparisons and BOOL references can branch on a typed value. `NOT` swaps true/false labels in condition mode. `AND` branches to RHS only after a true left operand; `OR` branches to RHS only after a false left operand. In value mode, branch to true/false exits that assign one tagged BOOL merge temp and then join. This works for assignment, argument, RETURN, and SHOW as well as conditions. The verifier permits those mutually exclusive definitions only when the merge temp is initialized on every path reaching its use; ordinary temps retain one static definition. No SSA or phi node is introduced.

```text
// START { BOOL b = FALSE AND (1 / 0 == 0); SHOW(b); }
BRANCH_BOOL FALSE, Lrhs, Lfalse
LABEL Lrhs
t1:INT = BINARY DIV 1, 0         // reached only if left is TRUE
t2:BOOL = COMPARE EQ t1, 0
BRANCH_BOOL t2, Ltrue, Lfalse
LABEL Ltrue;  bval:BOOL = MOVE TRUE;  JUMP Ljoin
LABEL Lfalse; bval:BOOL = MOVE FALSE
LABEL Ljoin;  INIT_SCALAR v_b, bval; SHOW v_b

// OR condition skeleton
lower_condition(left, Ltrue, Lrhs)
LABEL Lrhs; lower_condition(right, Ltrue, Lfalse)
```

No M5 constant folding: even a known literal condition retains its branch structure, and unreachable trapping RHS code may remain in the listing but must not execute.

## 10. Declarations, assignments, arrays, and storage

`ScalarDecl` with an initializer lowers its expression, site conversion if recorded, then `INIT_SCALAR`. Without one, it uses the validated `DefaultInitialization.element_value`: INT `0`, FLOAT `0.0`, CHAR `'\0'`, STRING `""`, BOOL `FALSE`. `AssignStmt` uses `target_of` and emits a typed MOVE or array store. Assignment to a parameter writes only the callee's by-value frame slot. A nested block has its own symbol IDs even for shadowed spellings. Each dynamic visit to a declaration executes initialization again, including each loop iteration.

`ArrayDecl` uses the declaration symbol's positive `array_length` and element type. `INIT_ARRAY` records compact length/default metadata and executes at the declaration point. With explicit initializers, evaluate each expression left to right, apply only its recorded element conversion, then store at that position. No giant compile-time element list is created. Runtime storage belongs to the enclosing frame; nested block lifetime and reuse are M7 details, but repeating the declaration must give the specified fresh/default state on every visit.

For indexed reads in expressions, evaluate and stabilize index → `CHECK_BOUNDS` producing guard `g` → `LOAD_ELEM(g)`. For indexed assignment, stabilize index → `CHECK_BOUNDS` producing `g` → evaluate RHS → convert → `STORE_ELEM(g, value)`. For indexed READ, stabilize index → `CHECK_BOUNDS` producing `g` → `READ_ELEM(g)`, which consumes/validates input and stores only on success. The guard identifies the resolved array symbol and captured index; the checked array instance cannot be replaced between check and access in these templates. Sparq has no whole-array assignment, globals, array parameters, or assignment expressions, so an intervening RHS call cannot replace this caller's array. The verifier must reject reuse after array reinitialization or across a path where the check did not execute. A guard is an IR dependency, not an additional runtime value requirement. No later *observable* defensive recheck may be inserted after RHS/input: if a target VM instruction defensively validates, it must be provably redundant and incapable of changing the frozen error order. Checks are explicit TAC instructions to make trap order and future M6 safety visible. A future optimizer may combine them only with a proof that error order is unchanged.

## 11. WHEN, SELECT, and loop control flow

`WHEN(cond) then OTHERWISE else` uses `lower_condition(cond, Lthen, Lelse_or_join)`; each branch ends at a join unless it already RETURNs. Without OTHERWISE, false goes directly to the join. Nested WHEN receives fresh labels and ordinary recursive/iterative statement lowering. The static analyzer already validated both branches, including unreachable ones. M5 does not discard a branch because a condition appears constant.

`SELECT` first evaluates its INT/CHAR/STRING selector **once** into a stable typed operand. A simple chain compares that operand to each `CaseLabelAnalysis.value` in source order and branches to the matching body or the next comparison. It uses decoded CASE values, never lexeme parsing. Each nonreturning CASE and DEFAULT body jumps to the SELECT exit, so there is no fallthrough. Empty SELECT evaluates the selector once and exits; DEFAULT-only SELECT evaluates it once then executes DEFAULT. Negative integer labels, nested SELECT, CHAR/STRING exact type comparisons, and absent DEFAULT use the same scheme. No jump-table optimization in M5.

```text
WHILE:   LABEL Ltest
         lower_condition(cond, Lbody, Lexit)
         LABEL Lbody; lower_block(body); JUMP Ltest
         LABEL Lexit

DO:      LABEL Lbody; lower_block(body)
         lower_condition(cond, Lbody, Lexit)
         LABEL Lexit

REPEAT:  lower_optional_initializer_once
         LABEL Ltest
         lower_condition(cond, Lbody, Lexit)   // omitted cond: JUMP Lbody
         LABEL Lbody; lower_block(body)
         lower_optional_update
         JUMP Ltest
         LABEL Lexit
```

The REPEAT header scope covers initializer, condition, update, and body; the body is its own nested scope. The static annotation walk may have inspected update before body, but the runtime order is initializer → condition → body → update → condition. A RETURN inside a loop exits the routine immediately; no following update, condition, or join executes on that path. Sparq has no break or continue.

## 12. Functions, calls, returns, READ, and SHOW

For each `FunctionAnalysis`, lower the original `FunctionDecl.body` using its ordered `parameters` and signature. Formal parameter slots are frame-local. At a CALL, evaluate and capture each argument left to right, insert its argument conversion at that site, and emit one CALL with a fixed ordered tuple. The eventual VM copies scalar values into new parameter slots. A callee parameter assignment cannot mutate caller storage. Forward, direct recursive, and mutual recursive references work because all signatures exist before lowering. A VOID call has no value destination; a discarded non-VOID call may also omit one, but must still execute. An expression call with a value uses a typed temporary. A `ReturnStmt` lowers its expression, optional `ReturnAnalysis.conversion`, and RETURN. A VOID function that reaches its closing brace gets an explicit `RETURN` without a value; START ends with `HALT_START`. The M4 conservative non-VOID return guarantee is consumed, not recomputed.

M7 must implement activation records, return addresses/values, parameter value transfer, and frame-local variable/array storage. Its configurable initial maximum call depth is 1,000; exhaustion must be a controlled Sparq runtime error, not Python recursion failure. M5 only records calls and source locations.

`READ_SCALAR` and `READ_ELEM` are effectful. An indexed READ must check bounds *before* consuming a field. At runtime an invalid present field is consumed before a controlled error; exhausted input is a runtime error; neither changes the target. `SHOW` receives one already evaluated typed scalar and prints once. The eventual VM handles the frozen INT decimal, finite FLOAT shortest round-trip (including signed zero), CHAR, decoded STRING, and uppercase BOOL formatting. TAC debug printing is diagnostic output and must never be confused with a Sparq SHOW side effect. M5 consumes or prints no source-program I/O.

## 13. Forward labels and backpatching

Allocate every forward target as a same-routine `LabelRef` before emission. Builder instructions may temporarily reference an as-yet-undefined label. On completion, define each exactly once and reject missing, duplicate, or foreign-routine labels. This symbolic approach gives the effect of backpatching without editing already emitted immutable instructions. If an instructor later requests explicit backpatching, an educational demonstration can show `truelist`/`falselist` and patch sites for a restricted Boolean fragment, then compare its resolved branches with the canonical label IR. The handout's Phase 5 does not require backpatching by name.

## 14. Structural IR validation and publication

A proposed verifier should check tagged instruction shapes, exact scalar/array kinds and types, symbol IDs against `AnalysisResult.scopes`, function IDs/signatures, argument order/count/types, call result and return types, array element/length compatibility, and source span ownership. It should check one definition per label, same-routine branch destinations, a valid entry and terminator, no unresolved placeholders, and no cross-routine temporary/guard/label use.

Temporary validation needs control-flow awareness. Ordinary typed temps and guards each have one static definition. A BOOL merge temp may be written by the two mutually exclusive true/false exits and read at their common join. A straight-line “defined earlier” check would wrongly reject it. A limited per-routine, forward definite-assignment calculation over label/jump edges checks that **every** temp or guard read is defined on **all** incoming paths; branch merge uses intersection of predecessor facts, with iteration to a fixed point for loops. The merge-temp validator also requires both definitions to have BOOL type and to occupy distinct exits that cannot execute sequentially before the join. It checks a guard's defining instruction is `CHECK_BOUNDS`, its array/index pair matches the consuming access, and no array reinitialization or loop backedge invalidates that check before use. This is an internal verifier calculation, not a public M6 CFG/basic-block model. Known array-initializer positions are verified statically against the declared length and use `INIT_ELEM`. Structural checks do not prove full runtime equivalence, termination, or absence of traps.

The builder snapshots immutable tuples only after all routines lower and verify successfully. An exception must not publish a partial `IRProgram`. A failed generation leaves the accepted M4 result unchanged and permits a new independent generation session.

## 15. Proposed public API, diagnostics, and resource policy

```python
program = Parser(Lexer(source).tokenize()).parse()
analysis = SemanticAnalyzer(program).analyze()
ir_program = TACGenerator(analysis).generate()  # proposed, not implemented
```

The proposal uses a separate `python -m sparq.tac SOURCE.spq` development CLI after Task 08. It would display TAC without executing the program. Exact module/class names need approval. Direct API construction with a non-`AnalysisResult` or inconsistent identity should raise a controlled `TypeError`/`ValueError`; an internal lowering/verifier failure should use an explicit compiler-internal diagnostic, not masquerade as a source semantic error. Lexical, parse, and semantic errors retain their existing types. Static resource exhaustion should yield a controlled generation resource diagnostic with a source span where possible. Runtime errors belong to M7. Avoid Python host `RecursionError` by an explicit traversal-depth/work limit or iterative lowering for deep trees; do not raise the process-wide recursion limit or create a new language restriction.

Diagnostic formatting must not call decimal `str()` on enormous INT values; retain full values and source lexemes in records, but print bounded human-readable previews. Avoid embedding unbounded strings or source-program values in error messages. Independent calls allocate fresh builders and produce stable IDs/listings for the same accepted input.

## 16. Academic representation demonstrations

The production requirement is TAC, which should have a readable listing for complete programs. A separate teaching view can show the same restricted arithmetic fragment as:

```text
Source: START { INT x = 1 + 2 * 3; }
TAC:    %t1 = MUL_INT 2, 3
        %t2 = ADD_INT 1, %t1
        INIT_SCALAR v_x, %t2
Quadruple display: (MUL, 2, 3, %t1), (ADD, 1, %t1, %t2)
Triple display:    0:(MUL, 2, 3), 1:(ADD, 1, (0))
Indirect triples:  pointer order [0, 1] over those triple records
```

The triple displays are **derived examples**, not a second production IR. Function calls, labels, trapping checks, and array operations need explicit extensions to be lossless; do not imply textbook three-field triples represent every complex instruction automatically. If the group wants complete triple or indirect-triple exports, it must approve an extension and tests. A separate backpatching trace is optional for the same reason. None of these demonstrations performs optimization.

## 17. M6 optimization compatibility

Typed IDs, explicit labels/branches, and ordered instruction tuples let M6 find basic blocks and build a CFG. Resolved symbol identities distinguish shadowed variables. Typed temporaries support propagation, CSE, DAG representation, and copy elimination. Explicit effects/traps keep dead-code elimination and motion honest: a discarded divide, bounds check, conversion, call, READ, or SHOW may remain observable. Short-circuit branches define reachable regions; a trap in a skipped region cannot be pulled into an executed one. Phase 6's required constant folding/propagation, CSE, DCE, copy propagation, loop/global/DAG optimization, and before/after comparisons can operate on the single canonical IR. No optimization runs in M5. Machine-dependent optimization should be demonstrated only after the M7 target model is agreed.

## 18. M7 target and VM compatibility

TAC temporaries are virtual compiler values, **not** assigned VM registers. M7 will select target instructions and calculate costs, allocate registers, map spills and frame slots, lower labels to branch addresses, and implement array storage, bounds checks, calls/returns, value copies, binary64 conversion/arithmetic, READ/SHOW, and controlled runtime diagnostics. The typed instruction effects guide code motion and register use. Phase 7 requires DAG-based code generation; M6's optimized DAGs or derived expression DAGs can inform selection without replacing the canonical program IR. The exact register count, bytecode encoding, activation-record layout, heap representation, allocation-failure policy, and instruction-cost model remain M7 decisions. This design does not define an executor.

## 19. Worked proposed TAC examples

These examples are **illustrative proposals**, not generator output. Each example is an independent program; `v_x`, `a_nums`, `%t1`, and `L1` are readable stand-ins for typed, owner-qualified IDs. A bare literal in TAC is a typed immediate, inferred from source/M4 facts. Each instruction also retains a source span even when omitted from the display. Operation spellings are provisional.

### 19.1 Arithmetic precedence

```sparq
START { INT x = 1 + 2 * 3; SHOW(x); }
```
```text
%t1:INT = BINARY STAR 2, 3
%t2:INT = BINARY PLUS 1, %t1
INIT_SCALAR v_x:INT, %t2
SHOW v_x
HALT_START
```
The parser's AST gives multiplication precedence; no M5 constant folding occurs.

### 19.2 Mixed numeric conversion

```sparq
START { FLOAT x = 1 + 2.5; SHOW(x); }
```
```text
%t1:FLOAT = TO_FLOAT 1:INT
%t2:FLOAT = BINARY PLUS %t1, 2.5:FLOAT
INIT_SCALAR v_x:FLOAT, %t2
SHOW v_x
HALT_START
```
The `ConversionSite` belongs to the binary left operand; the binary result itself needs no initializer conversion.

### 19.3 Lexical shadowing

```sparq
START { INT x = 1; { INT x = 2; SHOW(x); } SHOW(x); }
```
```text
INIT_SCALAR v_outer_x#1, 1
INIT_SCALAR v_inner_x#2, 2
SHOW v_inner_x#2
SHOW v_outer_x#1
HALT_START
```
The numbers only illustrate distinct semantic IDs; real IDs come from M4.

### 19.4 Short-circuit AND and OR

```sparq
START {
    BOOL a = FALSE AND (1 / 0 == 0);
    BOOL b = TRUE OR (1 / 0 == 0);
    SHOW(a);
    SHOW(b);
}
```
```text
BRANCH_BOOL FALSE, L_and_rhs, L_and_false
LABEL L_and_rhs; %t1:INT = BINARY SLASH 1, 0
%t2:BOOL = COMPARE EQ %t1, 0
BRANCH_BOOL %t2, L_and_true, L_and_false
LABEL L_and_true; MOVE %a_bool, TRUE; JUMP L_and_join
LABEL L_and_false; MOVE %a_bool, FALSE
LABEL L_and_join; INIT_SCALAR v_a, %a_bool
BRANCH_BOOL TRUE, L_or_true, L_or_rhs
LABEL L_or_rhs; %t3:INT = BINARY SLASH 1, 0
%t4:BOOL = COMPARE EQ %t3, 0
BRANCH_BOOL %t4, L_or_true, L_or_false
LABEL L_or_true; MOVE %b_bool, TRUE; JUMP L_or_join
LABEL L_or_false; MOVE %b_bool, FALSE
LABEL L_or_join; INIT_SCALAR v_b, %b_bool
SHOW v_a; SHOW v_b; HALT_START
```
Both divisions remain in the IR but are unreachable at runtime for this program. The example exercises value-context Boolean materialization.

### 19.5 WHEN/OTHERWISE and nested conditions

```sparq
START {
    BOOL x = TRUE;
    WHEN (x) {
        WHEN (FALSE) { SHOW(1); } OTHERWISE { SHOW(2); }
    } OTHERWISE { SHOW(3); }
}
```
```text
INIT_SCALAR v_x, TRUE
BRANCH_BOOL v_x, L_outer_true, L_outer_false
LABEL L_outer_true
BRANCH_BOOL FALSE, L_inner_true, L_inner_false
LABEL L_inner_true; SHOW 1; JUMP L_inner_end
LABEL L_inner_false; SHOW 2
LABEL L_inner_end; JUMP L_outer_end
LABEL L_outer_false; SHOW 3
LABEL L_outer_end; HALT_START
```
Each branch is statically validated; only its reached path executes.

### 19.6 SELECT with negative CASE and DEFAULT

```sparq
START {
    INT x = -1;
    SELECT (x) {
        CASE -1: { SHOW("minus"); }
        CASE 2: { SHOW("two"); }
        DEFAULT: { SHOW("other"); }
    }
}
```
```text
%t1:INT = UNARY MINUS 1
INIT_SCALAR v_x, %t1
%selector:INT = LOAD v_x
%c1:BOOL = COMPARE EQ %selector, -1:INT
BRANCH_BOOL %c1, L_case1, L_test2
LABEL L_test2; %c2:BOOL = COMPARE EQ %selector, 2:INT
BRANCH_BOOL %c2, L_case2, L_default
LABEL L_case1; SHOW "minus"; JUMP L_exit
LABEL L_case2; SHOW "two"; JUMP L_exit
LABEL L_default; SHOW "other"
LABEL L_exit; HALT_START
```
The selector is read once, and `-1` is the decoded CASE value from M4. No fallthrough.

### 19.7 WHILE

```sparq
START { INT i = 0; WHILE (i < 2) { SHOW(i); i = i + 1; } }
```
```text
INIT_SCALAR v_i, 0
LABEL L_test
%c:BOOL = COMPARE LT v_i, 2
BRANCH_BOOL %c, L_body, L_exit
LABEL L_body; SHOW v_i
%next:INT = BINARY PLUS v_i, 1
MOVE v_i, %next
JUMP L_test
LABEL L_exit; HALT_START
```
Condition evaluation precedes each body visit.

### 19.8 DO-WHILE

```sparq
START { INT i = 0; DO { SHOW(i); i = i + 1; } WHILE (i < 2); }
```
```text
INIT_SCALAR v_i, 0
LABEL L_body; SHOW v_i
%next:INT = BINARY PLUS v_i, 1
MOVE v_i, %next
%c:BOOL = COMPARE LT v_i, 2
BRANCH_BOOL %c, L_body, L_exit
LABEL L_exit; HALT_START
```
The body runs before the first condition test.

### 19.9 REPEAT

```sparq
START { REPEAT (INT i = 0; i < 2; i = i + 1) { SHOW(i); } }
```
```text
INIT_SCALAR v_i@repeat_header, 0
LABEL L_test
%c:BOOL = COMPARE LT v_i@repeat_header, 2
BRANCH_BOOL %c, L_body, L_exit
LABEL L_body; SHOW v_i@repeat_header
%next:INT = BINARY PLUS v_i@repeat_header, 1
MOVE v_i@repeat_header, %next
JUMP L_test
LABEL L_exit; HALT_START
```
The initializer executes once; the body is a child scope. With an omitted condition, `L_test` jumps to `L_body`.

### 19.10 Array access and indexed assignment

```sparq
START { INT nums[2] = {1, 2}; INT i = 0; nums[i] = nums[1] + 3; SHOW(nums[i]); }
```
```text
INIT_ARRAY a_nums:INT[2], default=0
INIT_ELEM a_nums, 0, 1
INIT_ELEM a_nums, 1, 2
INIT_SCALAR v_i, 0
%index:INT = LOAD v_i
%g1 = CHECK_BOUNDS a_nums, %index  // before RHS
%g2 = CHECK_BOUNDS a_nums, 1
%old:INT = LOAD_ELEM %g2
%sum:INT = BINARY PLUS %old, 3
STORE_ELEM %g1, %sum
%index2:INT = LOAD v_i
%g3 = CHECK_BOUNDS a_nums, %index2
%shown:INT = LOAD_ELEM %g3
SHOW %shown; HALT_START
```
Initializer positions are already known valid by length metadata and need no runtime checks; the verifier must confirm each such constant position is in range. The assignment's target check precedes every RHS operation.

### 19.11 Function call with argument conversion

```sparq
FUNC echo(FLOAT p) -> FLOAT { RETURN p; }
START { FLOAT x = echo(2); SHOW(x); }
```
```text
FUNC echo(p:FLOAT)
RETURN v_p
START
%arg:FLOAT = TO_FLOAT 2:INT
%call:FLOAT = CALL echo, (%arg)
INIT_SCALAR v_x, %call
SHOW v_x; HALT_START
```
The call tuple contains the converted value in parameter order; the callee receives a copy.

### 19.12 RETURN conversion

```sparq
FUNC one() -> FLOAT { RETURN 1; }
START { SHOW(one()); }
```
```text
FUNC one()
%ret:FLOAT = TO_FLOAT 1:INT
RETURN %ret
START
%call:FLOAT = CALL one, ()
SHOW %call; HALT_START
```
The conversion belongs to the `ReturnAnalysis` occurrence, not to the intrinsic INT literal.

### 19.13 READ and SHOW

```sparq
START { INT x; INT a[1]; READ(x); READ(a[0]); SHOW(x); SHOW(a[0]); }
```
```text
INIT_SCALAR v_x, 0
INIT_ARRAY a_a:INT[1], default=0
READ_SCALAR v_x
%g1 = CHECK_BOUNDS a_a, 0
READ_ELEM %g1
SHOW v_x
%g2 = CHECK_BOUNDS a_a, 0
%t:INT = LOAD_ELEM %g2
SHOW %t; HALT_START
```
The indexed check precedes input consumption. These instructions do not perform I/O during TAC generation.

## 20. Proposed module organization and staged M5 roadmap

Task 02 created `sparq/ir.py`, `sparq/ir_builder.py`, and focused tests. Paths for Tasks 03–08 remain proposed. Keep production records in `sparq/`; keep teaching displays in `tools/` and their explanation in `docs/`. Each checkpoint waits for its own group review.

| Task | Dependencies | Proposed deliverables and files | API boundary, tests, acceptance and independent review |
|---|---|---|---|
| **01/01A** Architecture | Accepted M4; exact handout/spec | This document, tracker, and README only | Group approves scope, typed IR, effects, guard/label/call protocol; no production source |
| **02** Core IR | Approved 01/01A | **Implemented and accepted after Task 02B corrections and group review.** `sparq/ir.py`, `sparq/ir_builder.py`, `tests/test_ir.py`, `tests/test_ir_builder.py`: typed operands, tagged instruction validation, guards, labels/branch skeleton, deterministic allocators | Constructors and completed records reject malformed identity/type/ownership; builder freezes a structural fragment; Task 02A findings remain recorded in Section 23 |
| **03** Scalar expressions | Accepted 02 | **Completed and accepted after Task 03A audit and Task 03B conversion-order clarification.** `sparq/expression_lowering.py`, `tests/test_tac_expressions.py`: literals, scalar refs, unary/arithmetic/comparison, binary conversions, Boolean value/condition modes | Internal lowering consumes owner-specific `ExpressionAnalysis`; tests cover scalar operators, short-circuit skipped traps, and merge paths. **ArrayAccess and CallExpr remain unsupported**, so this is not complete expression support |
| **04** Data, arrays, I/O | Accepted 03 | **Completed and accepted after Task 04A audit and Task 04B correction.** `sparq/statement_lowering.py`, `sparq/expression_lowering.py`, `tests/test_tac_statements.py`, `tests/test_tac_arrays.py`, `tests/test_tac_io.py`: declarations, assignments, guarded array access/index/initialization, READ/SHOW | Exact nested occurrence selection and straight-line lowering are covered; expressions containing calls remain unsupported until 06 |
| **05** Control flow | Accepted 03–04 | **Implemented, pending focused independent verification.** `sparq/statement_lowering.py`, `tests/test_tac_control_flow.py`: WHEN, SELECT, WHILE, DO-WHILE, REPEAT | Labels, decoded cases, no fallthrough, short-circuit and loop order are tested. Calls in conditions, selectors, and bodies remain deferred until 06 |
| **06** Functions and calls | Accepted 02–05 | **Implemented, pending independent verification.** `sparq/expression_lowering.py`, `sparq/statement_lowering.py`, `sparq/function_lowering.py`, `tests/test_tac_calls.py`: function routines, call expressions/statements, ordered captured args, RETURN | Calls work in expressions and statements, including nesting; forward/mutual recursion is symbolic. Task 08 still owns complete program generation and verification |
| **07** Academic IR views | Accepted 02–06 | **Implemented and self-verified, pending group review.** `tools/ir_demonstrations.py`, `docs/IR_DEMONSTRATIONS.md`, `tests/test_ir_demonstrations.py`: derived quadruple, restricted triple and indirect-triple views | Reproducible source-backed displays; unsupported opcodes fail explicitly; no second authoritative instruction stream or optimizer |
| **08** Program integration | 02–07 | `sparq/tac.py`, `sparq/ir_verify.py`, `tests/test_tac_program.py`, README/guide updates: public generator, complete verifier, formatter and CLI | End-to-end every AST category, invalid direct API, deterministic sessions, full regression; independent final audit. Publish only complete verified IR |

The suggested filenames may be consolidated when implementation starts; do not create modules solely to satisfy a table. Before Task 08, these are **internal, test-only partial lowering interfaces**, not a public complete `TACGenerator` or CLI. Unsupported *valid* AST categories at Tasks 03–05 should produce a clearly internal “checkpoint not implemented” result in focused tests, never a false source-language semantic error. One shared lowering context can own expression/statement dispatch and accept a Task 06 call-lowering callback; this avoids circular imports or separate instruction streams. Task 06 closes the call gap before Task 08 publishes complete program generation. Any additional educational requirement from the instructor must be clarified before claiming Task 07 complete.

## 21. Risks, design decisions, and architecture approval

| Design decision | Approved direction or later recommendation | Consequence |
|---|---|---|
| Canonical IR | Typed structured quadruple-style sequence with tagged variants | One production truth; readable TAC and derived displays |
| Call argument protocol | One CALL with an ordered, evaluated operand tuple | Nested calls stay isolated; verifier checks signature/order |
| Array bounds representation | Explicit `CHECK_BOUNDS` yields a routine-local checked-element guard consumed by load/store/READ | Makes error order and check/access identity visible; no late observable recheck |
| Boolean value merge | One branch-assigned BOOL temp/slot with path-aware verification | Avoids SSA/phi; verifier needs limited definite assignment |
| Symbol and generated identities | M4 symbol IDs plus routine-local structured temp/label IDs | Shadowing and source `t1` remain distinct |
| Forward branches/backpatching | Symbolic labels in production; explicit patch-list demo only if requested | Simpler generation without a second branch stream |
| Arithmetic op specialization | Typed generic op records, specialize in M7 if helpful | Keeps M5 small while preserving INT/FLOAT behavior |
| Diagnostic and depth policy | Controlled internal/resource diagnostics; bounded integer display | No host traceback or global recursion-limit change |
| Derived triple/indirect-triple scope | Restricted educational fragment unless separately required | No false claim that complex instructions fit textbook triples |
| Phase 6 machine-dependent optimization | Defer detailed target-specific form to M6/M7 planning | Avoids assuming an unapproved VM ISA in M5 |

**Risks to test before accepting an implementation:** owner-specific annotations accidentally mixed across AST occurrences; direct variable operands read too late; Boolean result not initialized on one path; a skipped RHS trap emitted on an executed path; indexed assignment/READ check moved after RHS/input; dynamic declaration initialized only once; call argument tuples reordered or aliased; negative CASE label reparsed rather than using decoded metadata; huge INT formatted unsafely; completed IR accepting unresolved labels or foreign symbols. No confirmed M4 metadata gap currently blocks lowering.

**Architecture approval record:**

- [x] One typed structured production TAC, tagged instruction variants, and a future derived readable quadruple-style listing.
- [x] Per-CALL immutable ordered argument tuples, exact signature/result validation, and by-value transfer.
- [x] Explicit bounds checks yielding checked-element guards, with no observable late recheck.
- [x] Branch-based short-circuiting, BOOL merge temps, and future path-aware definite-assignment verification without SSA.
- [x] Routine-local symbolic labels and completed-label validation, with no production patch-list machinery.
- [x] Restricted derived triple/indirect-triple displays and optional backpatching teaching examples.
- [x] Task 02–08 dependency plan and internal-only partial APIs before Task 08.

These six choices were approved with Task 02 authorization. The handout still does not explicitly require triples, indirect triples, or backpatching. Task 02 implements only structural records and a builder; Tasks 03–08 and all M6/M7 implementation remain not started.

## 22. Implemented M5 Task 02 structural API and limits

`sparq.ir` now provides frozen typed operands: `RoutineId`, `Constant`, `VariableRef`, `ParameterRef`, `ArrayRef`, `Temporary`, `BoolMergeTemp`, `CheckedElement`, `LabelRef`, and `FunctionRef`. `RoutineId.start()` and `RoutineId.for_function(signature)` create owner objects. Owners compare by **object identity**, so two independent START builders with numeric temporary 1 cannot exchange operands; textual numbers remain deterministic per routine. Ordinary and BOOL-merge temporaries share one routine-local number sequence but have distinct Python record types. Guards and labels have their own routine-local sequences. Source operands wrap the accepted immutable `VariableSymbol` or `FunctionSymbol`; they never resolve a name or hold a mutable `Scope`. Array operands retain element type and positive length. A guard stores the exact resolved array object and an already captured INT `Constant` or `Temporary`; a mutable source variable cannot itself be the guard index.

`Constant` requires an exact Python `int`, finite `float`, `bool`, or valid decoded Unicode scalar/text according to its existing `ScalarType`. `bool` cannot satisfy INT. CHAR and STRING remain different even though both use Python `str`. Full arbitrary-precision INT values and optional lexemes remain intact; debug `repr` bounds very large INT and array-length displays without changing records. The typed value is authoritative. A lexeme is optional source-provenance or display metadata: direct IR construction does not verify that it decodes to the supplied value. Future source lowering must preserve correct literal provenance, while synthetic constants may omit a lexeme. No arithmetic, conversion, or bounds check executes here.

The frozen tagged instruction classes are `InitScalar`, `Move`, `Load`, `Unary`, `Binary`, `Compare`, `Convert`, `InitArray`, `InitElement`, `CheckBounds`, `LoadElement`, `StoreElement`, `Label`, `Jump`, `BranchBool`, `Call`, `Return`, `ReadScalar`, `ReadElement`, `Show`, and `HaltStart`. Every instruction requires an owning `RoutineId` and immutable `SourceSpan`; test/manual synthetic operations supply a real span explicitly. Constructors check their local shape, normalized operand/result types, and owner. `Binary` and `Compare` do not insert conversions. Division by literal zero remains representable and potentially trapping at runtime. `CheckBounds` ties its guard to the *same* array and captured index objects; guarded operations consume that guard. `InitElement` is a deliberate refinement for known in-range initializer positions, avoiding a dynamic check while retaining a separate explicit check for runtime indexes. `Call` snapshots a list or tuple into its own immutable argument tuple and checks signature count, already-converted types, and VOID/value/discarded-result shapes. `Return` checks the owning function's declared return category; START uses `HaltStart`.

`effects(instruction)` derives conservative read/write, trap, input, output, call, and control effects from the validated instruction variant. It is not a caller-controlled purity flag or an optimization pass. `Binary` division/remainder, FLOAT arithmetic, `Convert`, `CheckBounds`, READ, CALL, and runtime array initialization remain conservatively effectful where appropriate.

`IRBuilder(owner, root_scope_id, *, parameters=(), local_symbols=())` snapshots and validates its header. Its public methods are `temp(type)`, `merge_temp()`, `guard(array, captured_index)`, `label()`, `emit(instruction)`, `define(label, span)`, `snapshot()`, and `finish()`. It rejects unallocated generated operands and foreign owners, preserves instruction order, and never appends a failed emit. An invalid local operation leaves the builder open and unchanged. `finish()` rejects referenced but undefined labels and snapshots an `IRRoutine`; failure leaves the builder usable so the label can be defined and finish retried. A successful finish is idempotent and closes allocation/emission. Unused allocated labels need not be defined.

`IRRoutine`, `IRFunction`, and `IRProgram` snapshot caller-owned lists and validate structural ownership. A routine checks unique local symbol identities, parameter/signature agreement, instruction ownership, label uniqueness/resolution, and duplicate ordinary-temp/guard definitions. A program retains the original `Program` and matching `AnalysisResult`, ordered function routines, and START routine. These records are immutable **structural fragments/containers**, not proof of executable control-flow correctness; no public `TACGenerator` or TAC CLI exists.

Task 02B completes the logical identity checks at the structural boundary. A temporary is keyed by its routine and shared temporary number; every definition and reference, including CALL arguments and a guard's captured index, must retain one category (ordinary or BOOL merge) and scalar type. Ordinary temporaries have at most one static definition, while repeated assignments to one consistent BOOL merge temporary remain representable. A guard is keyed by its routine and guard number; every reference must retain one resolved array symbol and captured INT index relationship, and a second `CheckBounds` definition of that number is rejected. Equivalent separately constructed temporary records with the same owner/number/type remain valid references. A completed function's parameter inventory and program association retain the exact analyzed `VariableSymbol` objects; separate IR wrappers around those symbols are valid. These checks do not establish executable-path availability.

**Deferred verifier obligations (Task 08):** path-aware temporary and merge initialization, guard definition before use on each executable path, guard lifetime across array reinitialization/backedges, reachability and termination, complete call resolution against the program, and full source-to-IR correspondence. Task 02's structural check does not prove any of those properties. The tests manually assemble arithmetic, explicit conversion, forward branches, a two-path BOOL merge, a guarded array operation, and nested CALL records without executing them. The focused suite added **42 passing cases**; the full regression result was **1232 passed, 0 failed, 0 skipped**. No accepted M4 production file, frozen specification, or existing test was modified.

## 23. Task 02A audit and Task 02B correction checkpoint

The independent Task 02A audit gave **CONDITIONAL PASS** and reproduced three structural defects: a directly constructed routine accepted one temporary number with conflicting type or category, accepted one guard number with conflicting array/index metadata, and a completed program accepted a value-equal clone of an analyzed parameter symbol. Task 02B corrected all three in the structural record checks; the builder's public API and allocation policy did not change. Focused permanent tests now cover those exact reproductions, nested uses, valid BOOL merge assignments, guard references, exact parameter identity, initializer positions, and per-instruction-family effects. **23 new tests** were added to the original 42 Task 02 cases. Full validation: **1255 passed, 0 failed, 0 skipped**. The correction is pending student-group review; Task 03 and later lowering have not started.

## 24. Implemented M5 Task 03 scalar expression lowering

The group reviewed the Task 02B corrections and authorized Task 03. `sparq.expression_lowering.ExpressionLowerer(builder, *, max_depth=256, max_nodes=10000)` is an **internal partial-lowering component**. Its `lower_value(ExpressionAnalysis)` returns a typed `Constant`, ordinary `Temporary`, or `BoolMergeTemp`; `lower_condition(ExpressionAnalysis, true_label, false_label)` appends branches and returns `None`. The caller allocates and later defines the destination labels. Both methods append to an open `IRBuilder` without calling `finish()`. A small read-only `IRBuilder.is_complete` property lets literal-only lowering reject an already closed builder; no existing builder allocation or instruction protocol changed.

The accepted `ExpressionAnalysis.root` and identity-keyed `annotations.type_of`, `binding_of`, and `conversions_for` supply all expression facts. The builder's local symbol inventory must contain the **exact analyzed** `VariableSymbol` objects for variable or parameter references. This component also accepts independently analyzed expression results under that same caller precondition. A pure literal has no symbol through which the component can independently prove semantic-session ownership; the later program generator will provide that boundary. Before emission, an iterative preflight checks supported AST categories, source spans, required intrinsic types and bindings, and binary conversion-site coverage against the accepted type rules. It verifies supplied facts; it does not resolve names, infer new conversions, or mutate semantic results. Distinct expression occurrences are never cached by structural AST equality.

Literals return immediate typed `Constant` records with decoded values and original lexemes, including arbitrary-precision INT, signed-zero FLOAT input, CHAR, STRING, and BOOL. Scalar variables and parameters emit an immediate `Load` into an ordinary temporary so later source mutations cannot change the value already evaluated. Numeric unary minus and ordinary value-context NOT emit `Unary`; arithmetic emits `Binary`; numeric ordering and same-type or normalized mixed-numeric equality emit `Compare`. The lowerer follows **left evaluation, left recorded conversion, right evaluation, right recorded conversion, final operation**. Each `ConversionSite` is matched by parent identity and left/right role, then emits one `Convert` from INT to FLOAT with the converted operand's span. A potentially failing conversion remains an instruction at its evaluated use site. No arithmetic, comparison, conversion, or constant folding executes during lowering.

In condition mode, `NOT` swaps the true/false labels. `AND` branches to an internally allocated RHS label only on a true left operand; `OR` reaches its RHS label only on a false left operand. Other BOOL expressions lower to a scalar value and one `BranchBool`. A short-circuit expression used as a value allocates one tagged BOOL merge temporary, branches to true/false labels, assigns the corresponding BOOL literal, jumps over the false assignment, and joins before returning the merge operand. A direct BOOL literal, loaded variable, or comparison result needs no merge. A value-context NOT directly around AND/OR uses the same branch-based materialization. Internal labels are defined by the component; enclosing destinations remain the caller's responsibility. These fragments are structurally checked by a later `builder.finish()`, not path-aware verified here.

Representative **actual record sequences** from source-backed tests (fields abbreviated, no textual TAC formatter):

```text
SHOW(a + b * 2.5)        Load(a), Convert(a), Load(b), Convert(b), Binary(STAR), Binary(PLUS)
SHOW(1 + 2.5)            Convert(1), Binary(PLUS)
SHOW(FALSE AND (1/0>0)) BranchBool(FALSE, Lrhs, Lfalse), Label(Lrhs), Binary(SLASH),
                          Compare(GREATER), BranchBool(...), Label(Ltrue), Move(merge, TRUE),
                          Jump(Ljoin), Label(Lfalse), Move(merge, FALSE), Label(Ljoin)
```

Every emitted instruction has an immutable `SourceSpan`: loads use their reference span, conversions use the converted operand span, ordinary operations and branches use the originating expression span, and synthetic RHS/merge labels, moves and jumps borrow the owning Boolean expression span. The lowerer does not fabricate unrelated locations.

`ArrayAccess` is deferred to Task 04 and `CallExpr` to Task 06, including when nested. Preflight raises `DeferredExpressionError` **before emission**. Invalid API/context, inconsistent semantic metadata, static depth/work limits, and IR-builder construction failures have distinct controlled lowering exceptions. The defaults are 256 AST levels and 10,000 visited occurrences; a host `RecursionError` is converted to `LoweringResourceError`, without changing Python's recursion limit or Sparq syntax. Any failed lowering call invalidates that lowerer. The caller must discard its builder because a later construction failure may leave a partial fragment; existing builder-local failure guarantees are unchanged. No failed call returns a successful operand. Runtime traps, including division by zero, FLOAT overflow and an unrepresentable INT-to-FLOAT conversion, remain deferred instructions.

This implementation checkpoint added **70 new tests**. Full validation at that point: **1325 passed, 0 failed, 0 skipped**. The component does not lower statements, arrays, calls, functions, or complete programs, and it does not provide TAC formatting, a full path-aware verifier, optimization, or execution. Task 04 must integrate array access and statement uses with the exact owning `StatementAnalysis`; Task 06 must extend expression dispatch for calls. Task 08 still owns complete program generation and verification. At this implementation checkpoint, Task 03 was pending independent audit.

## 25. Task 03A audit and approved conversion-order closure

The independent Task 03A audit found no confirmed scalar-lowering implementation defect and gave **CONDITIONAL PASS** because binary operand-conversion timing relative to later operand evaluation was not explicit in the frozen language rules. The student group approved immediate use-site conversion in Task 03B, and Section 13 of the frozen specification now records that narrow clarification. For non-short-circuit binary expressions, lower and convert the left operand before beginning the right subtree; lower and convert the right operand before the parent operation. A failure stops subsequent evaluation, preserving observable runtime-error precedence. AND and OR retain their branch-based short-circuit exception.

The existing `ExpressionLowerer._value` already emits this sequence; TAC generation itself performs no conversion or runtime trap. In the source-backed example `N + ((1 / 0) * 1.0)` with a 5,000-digit INT `N`, the records begin `Convert(N), Binary(SLASH), Convert(...), Binary(STAR), Binary(PLUS)`. If the conversion of `N` fails at runtime, the right subtree is skipped. The inverse example `((1 / 0) * 1.0) + 2` begins `Binary(SLASH)` and emits the conversion of the final right operand only after the left subtree. One focused permanent test records both orderings without executing them. Full validation: **1326 passed, 0 failed, 0 skipped**. Task 03 is completed and accepted after this clarification and verification; Task 04 and later checkpoints have not started.

## 26. Task 04 partial statement and array lowering

`sparq.statement_lowering.StatementLowerer(builder, *, max_depth=256, max_statements=10000, expression_max_depth=256, expression_max_nodes=10000)` appends supported statement occurrences to the same open `IRBuilder` used by its `ExpressionLowerer`. `lower_statement(StatementAnalysis, statement=None)` and `lower_block(StatementAnalysis, block=None)` return `None`; omitted occurrences select the analysis root. An explicitly selected occurrence must belong by identity to that result. The analysis must belong to the builder's START or function routine, and a root block must have the builder's root scope ID. The caller supplies a complete routine-local inventory containing the **exact analyzed** scalar, array, and parameter symbols; the builder checks every emitted reference. Neither lowerer calls `finish()`. The caller remains responsible for completing a routine, and Task 08 owns complete program construction and verification.

The lowerer consumes `declaration_of`, `target_of`, `read_of`, `show_of`, `scope_of`, ordered `expressions` (`ExpressionUse`) and `conversions` (`StatementConversionSite`), and `defaults` from the exact `StatementAnalysis`. It does not resolve names, infer types, choose conversions, or check declaration sizes again. Scalar declarations emit `InitScalar` after the retained initializer expression and its recorded conversion; declarations without initializers use their validated typed default descriptor. Scalar/parameter assignments emit `Move` after RHS evaluation and conversion, without loading the destination. Explicit nested blocks append their child statements in source order; lexical shadowing is carried by distinct analyzed symbol IDs. No block entry/exit opcode or runtime scope is added. Declaration initialization stays at its executable occurrence, so a later loop lowerer must place it inside the repeated body.

Arrays emit one compact `InitArray(array, length, default)` at the declaration occurrence, even for a very large default array. This is a runtime allocation/default-establishment operation, not Python allocation. An explicit initializer then emits each analyzed expression and conversion in source order followed by `InitElement(array, known_position, value)`. These known positions require no dynamic bounds guard. This chosen sequence makes a future runtime allocation failure occur before evaluation of explicit initializer expressions. The frozen specification requires left-to-right initializer evaluation and the approved IR architecture places `InitArray` first; the exact precedence of a future allocation-resource error against an initializer trap should be confirmed when M7 defines allocation errors. For example, `INT a[1] = {1 / 0};` could fail on allocation before division if allocation fails. Task 04 does not execute either operation or amend the frozen specification.

`ExpressionLowerer` now accepts semantically validated `ArrayAccess`: lower its annotated INT index into a captured `Constant` or `Temporary`, allocate a builder guard for the exact `ArrayRef` and index, emit `CheckBounds`, then `LoadElement` into an element-typed temporary. Nested accesses each receive independent guards. An access on a short-circuit RHS is emitted only behind the correct branch. Indexed assignment emits index evaluation, `CheckBounds`, RHS evaluation, recorded conversion, then `StoreElement` with the original guard; indexed READ emits index evaluation, check, then `ReadElement`, before any future input consumption. Scalar READ emits one `ReadScalar`; SHOW lowers the retained scalar expression and emits one `Show`. Compilation performs no READ, SHOW, bounds check, allocation, conversion, arithmetic, or source-program execution.

After Task 04, explicit `Convert` records cover five contexts: binary operand, scalar initializer, array initializer element, scalar assignment, and indexed assignment. `emit_int_to_float` is the small shared emission helper; it accepts only a validated INT operand and FLOAT destination and allocates an owned FLOAT temporary. Binary evaluation keeps Task 03B's exact order: left evaluation and conversion, then right evaluation and conversion, then operation. A left conversion may therefore precede a right bounds check; a left bounds check precedes right evaluation. Argument and RETURN conversions await Task 06.

Spans follow actual AST occurrences: `InitScalar` and `InitArray` use declaration spans; `InitElement` uses its element expression span; `Move`, `StoreElement`, `ReadScalar`, `ReadElement`, and `Show` use statement spans; `CheckBounds` for expression and writable-target accesses uses that access span; `LoadElement` uses its access span; `Convert` uses the converted expression span. Expression loads, operations, branches, and synthetic labels retain the Task 03 policy. No source locations are fabricated.

The statement traversal preflights support with an iterative walk and limits nesting to 256 levels and 10,000 visited statements by default; each expression retains its own 256-level/10,000-node limits. Positive integer limit configuration is required. These are compiler resource limits, not Sparq syntax restrictions. Deferred `CallExpr` still raises `DeferredExpressionError`. `CallStmt`, RETURN, WHEN/OTHERWISE, SELECT, WHILE, DO-WHILE, and REPEAT raise `DeferredStatementError`; a containing block cannot falsely report successful completion. Any failed statement call invalidates that `StatementLowerer`, and a failed expression also invalidates its shared `ExpressionLowerer`. The caller must discard the builder because prior emission may remain; immutable snapshots already obtained do not change. The builder's local failed-emit contract is unchanged. No block-wide rollback is promised. A completed builder rejects further lowering.

Representative **actual instruction sequence** from a source-backed START block (record fields abbreviated):

```text
INT x; FLOAT f = 1 + 2; INT a[2] = {1, 2};
x = a[1]; a[0] = x; READ(a[1]); SHOW(f);
{ INT x = 5; SHOW(x); }

InitScalar(x, 0), Binary(1+2), Convert(INT->FLOAT), InitScalar(f),
InitArray(a, 2, 0), InitElement(a, 0, 1), InitElement(a, 1, 2),
CheckBounds(a, 1, g1), LoadElement(g1), Move(x),
CheckBounds(a, 0, g2), Load(x), StoreElement(g2),
CheckBounds(a, 1, g3), ReadElement(g3), Load(f), Show(f),
InitScalar(inner x, 5), Load(inner x), Show(inner x)
```

This is a manually completed straight-line fragment, not a production TAC generator or proof of source-to-IR equivalence. The existing structural IR and builder checks are preserved. Three new focused test modules added **90 cases**, and two previous deferred-array cases were migrated to meaningful guarded-load and nested-call checks. Full regression validation at the Task 04 implementation checkpoint: **1416 passed, 0 failed, 0 skipped**. Task 04 then awaited independent audit. Task 08 still needs path-aware availability, array-instance/guard lifetime, full source correspondence, and complete routine/program verification. Task 05 handles control flow; Task 06 handles calls, RETURN, and their conversions. Optimization, target code, and VM execution remain later milestones.

## 27. Task 04A audit and Task 04B nested occurrence correction

The independent Task 04A audit confirmed the straight-line lowering behavior but found that explicit selection of an analyzed child inside deferred control flow raised `StatementInputError`. The Task 04B correction separates identity-based membership from supported-statement validation. Membership follows the actual AST children of WHEN/OTHERWISE, SELECT CASE/DEFAULT, WHILE, DO-WHILE, and REPEAT initializer/body/update. The second preflight still validates only the selected subtree and rejects a selected control-flow statement, CALL, or RETURN as deferred. Selecting a child does not emit its parent, condition, selector, or siblings; Task 05 must place that child under the correct branch or loop labels. Equal-but-distinct and foreign AST nodes remain invalid. An explicitly selected declaration uses its original semantic symbol and stays at its selected execution position.

Task 04B added **19 focused cases** for nested selection, isolation, symbol ownership, identity rejection, and direct deferred outcomes. The statement-lowering module passed **61 tests**; the full suite passed **1435, failed 0, skipped 0**. Syntax/import checks and the semantic CLI passed. The student group subsequently approved Task 04 and Task 04B, completing and accepting M5 Tasks 01–04. Tasks 05–08 have not started. The M7 allocation-error precedence question remains open; the frozen language specification was not changed.

## 28. Task 05 statement-level control-flow lowering

`StatementLowerer` now consumes the retained `condition_of`, `selector_of`, `labels_of`, and `repeat_scope_of` records, without new name resolution or CASE validation. It uses the same `ExpressionLowerer` and `IRBuilder` and selects analyzed children through the Task 04B `lower_block` and `lower_statement` API. All emitted labels are routine-local and defined; no runtime scope instruction is introduced.

WHEN branches to its true body and false body or join; the true body jumps over OTHERWISE. SELECT evaluates the selector once, compares its captured typed operand with each decoded CASE value in source order, branches into a matching body, and jumps to a shared exit without fallthrough. DEFAULT runs only after all comparisons fail. A DEFAULT-only or empty SELECT still evaluates the selector. WHILE defines its test before the body and jumps back after the body; DO-WHILE places its body before the first condition evaluation. REPEAT emits its optional initializer once, its test, body, optional update, and a backedge to the test; an omitted condition jumps directly to the body. Body declarations stay inside the emitted loop body.

Nested CALL and RETURN statements remain deferred. A deferred call expression can leave an incomplete builder fragment before raising, so the established failed-lowerer and caller-discard contract applies. Task 05 does not execute IR or provide complete program generation, path-aware verification, optimization, target code, or a VM. The M7 array allocation-error precedence question remains open; no frozen language rule changed. The implementation added **23 source-backed control-flow tests** and revised or replaced eight old deferred-control-flow expectations. Full validation: **1456 passed, 0 failed, 0 skipped**. Task 05 awaits focused independent verification; Task 06 has not started.

## 29. Task 05 acceptance and Task 06 function, CALL and RETURN lowering

The Task 05A independent control-flow audit passed, and the student group accepted Task 05 when authorizing Task 06. The earlier Task 05 description above records its historical checkpoint; CALL and RETURN are now implemented by Task 06.

`ExpressionLowerer.lower_value(ExpressionAnalysis)` now lowers value-producing `CallExpr` occurrences using `call_binding_of`. `ExpressionLowerer.lower_call(CallAnalysis)` lowers a standalone call without allocating a discarded result temporary. Both evaluate arguments in source order, capture each value, emit its recorded INT-to-FLOAT conversion immediately, then emit one `Call` with an immutable argument tuple and the exact resolved `FunctionRef`. A value call allocates a typed result temporary; a non-VOID standalone call marks its result discarded; a VOID call has no result. Calls nested in other expressions use the same routine-local builder, so short-circuit branches and earlier array checks retain their placement.

`StatementLowerer` consumes `call_of` and `return_of` for call statements and RETURN. A value RETURN lowers its retained expression, applies its recorded return conversion, then emits `Return`; a bare VOID RETURN emits no value. The new `sparq.function_lowering.lower_function(FunctionAnalysis, **statement_limits)` builds one `IRFunction` with exact analyzed parameter order and local inventory. It adds an implicit bare RETURN for possible VOID fallthrough, never a default non-VOID value, then structurally completes the routine. Forward, self-recursive, and mutual calls retain symbolic references without lowering callees at call sites.

The seven implemented INT-to-FLOAT conversion contexts are binary operands, scalar initializers, array initializer elements, scalar assignments, indexed assignments, function arguments, and RETURN. Task 07 still owns educational IR views; Task 08 still owns whole-program TAC generation and path-aware verification. No IR execution, optimizer, target generator, or VM is included. The M7 allocation-error precedence question remains open. Task 06 added **13 tests** and migrated prior deferred CALL/RETURN assertions in place; the full suite passed **1469, failed 0, skipped 0**. Task 06 awaits independent verification.

## 30. Task 06 acceptance and Task 07 derived educational views

The Task 06A focused independent audit passed, and the student group accepted Task 06 when authorizing Task 07. The preceding Task 06 section records its historical implementation checkpoint. [IR_DEMONSTRATIONS.md](IR_DEMONSTRATIONS.md) documents the new Task 07 view contracts and `.venv\Scripts\python -B -m tools.ir_demonstrations` command. The demo lowers actual source through the existing lexer, parser, semantic analyzer, and statement lowerer; quadruple and triple tables derive from its canonical arithmetic records. The indirect pointer table is separate display metadata and performs no reordering or optimization. Unsupported opcodes receive a controlled `UnsupportedIRView` outcome. An optional explicit backpatch-list teaching example was not added; production branches already use resolved symbolic labels.

Task 07 adds **five educational-view tests** and **two Task 06A coverage tests** for explicit bare VOID RETURN and nested CALL argument-tuple isolation. Full regression validation: **1476 passed, 0 failed, 0 skipped**. Task 07 is implemented and self-verified, pending group review. Task 08 still must check every CALL target against the exact owning `AnalysisResult`, path-aware temporary and guard availability, complete routine/program ownership, and approved reachability and termination properties. The M7 allocation-error precedence question remains open; Task 08 and M6–M8 have not started.

## 31. Task 07 acceptance and Task 08 complete TAC generation

The student group accepted Task 07 when authorizing Task 08. The prior section records the historical self-verification checkpoint.

`sparq.tac.TACGenerator(program, analysis).generate()` requires the exact `Program` owned by a complete `AnalysisResult`. `sparq.tac.generate_tac(program, analysis)` is the one-shot form. The generator lowers each analyzed function once through `lower_function`, retaining signature and parameter order; it builds START with its exact analyzed scope and all declarations, including nested blocks and REPEAT headers. START ends with `HaltStart`. It creates an `IRProgram`, runs `sparq.ir_verify.verify_program(ir_program)`, and returns only the verified result. No names or types are resolved again, and CALL sites retain symbolic function references. A generator caches its successful result; after a lowering or verification failure the session is invalid and must be discarded. `TACGenerationError` reports generation failure, while `IRVerificationError` reports a directly supplied malformed complete IR program.

`IRRoutine` and `IRProgram` constructors continue to enforce tagged instruction shape, types, routine ownership, unique ordinary definitions and guard definitions, consistent metadata, resolved labels, source-symbol registration, parameter correspondence, function order, and exact source/analysis ownership. The complete verifier additionally compares parameter and local inventories by **symbol object identity**, checks each CALL target against the exact `AnalysisResult.signatures` objects, and checks instruction spans within the owning source body. CALL count, argument types, result category and RETURN type are enforced by their instruction constructors. A structurally equal foreign-session `FunctionSymbol` is rejected.

For each routine, the verifier forms successors from textual fallthrough, `Jump`, `BranchBool`, `Return`, and `HaltStart`. It reaches instructions from entry without evaluating conditions. A definite-availability bitset is intersected at predecessor joins and iterated by worklist to a fixed point; ordinary temporaries, BOOL merge temporaries, and checked-element guards must be available at every reachable use. Two BOOL merge writes cannot execute sequentially before a use. `InitArray` kills earlier guards for that exact array; later element access therefore requires a fresh `CheckBounds`. The structural guard metadata contract binds each guard to its array and captured index. Reachable fallthrough beyond the last instruction is rejected. Unreachable source instructions and an infinite loop remain valid. This analysis does not execute source, prove runtime termination, prove absence of traps, or establish full source-to-IR equivalence. It is an internal control-flow calculation, not M6's production basic-block or optimization infrastructure.

`sparq.tac.format_tac(ir_program)` verifies and renders the canonical complete IR in function declaration order followed by START. The listing shows typed parameter and return signatures, shadow-distinguishing symbol IDs, ordered operands and argument tuples, labels, branches, conversions, array guards and accesses, READ, SHOW, RETURN, and `HaltStart`. Huge INT values and array lengths receive bounded previews; the IR retains their exact values and lexemes. `.venv\Scripts\python -m sparq.tac examples/hello.spq` runs lexer, parser, semantic analysis, generation, verification, and rendering. Invalid input returns a controlled nonzero exit without a partial successful listing. The CLI does not execute TAC.

All seven INT-to-FLOAT conversion sites remain represented: binary operand, scalar initializer, array initializer element, scalar assignment, indexed assignment, function argument, and RETURN. Source-backed integration covers all five scalar types, arrays, I/O, conditionals, loops, all eight REPEAT header combinations, forward and recursive calls, short-circuit evaluation, shadowed declarations, and a mixed program with functions, arrays, loops, conversions and I/O. Direct malformed-IR tests cover foreign CALL identity, missing temp and merge definitions, stale or branch-local guards, wrong guard association, invalid CALL shape, undefined labels, invalid RETURN, source span ownership, fallthrough, and unreachable/infinite paths. **33 focused tests** were added. The complete suite passed **1509, failed 0, skipped 0**. The only existing valid example, `examples/hello.spq`, produced `START`, `SHOW Constant(STRING, 'Hello from Sparq!')`, and `HALTSTART`. Semantic CLI and educational views succeeded. Task 08 is implemented and self-verified, pending final independent M5 verification. M6–M8 have not started. The M7 array allocation-error precedence question remains open.

## M7 target handoff

The historical M5 entries above retain their checkpoint status. [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) now specifies the three-register target mapping for every canonical instruction and resolves the deferred array allocation-error order: `InitArray`/`ALLOC_ARRAY` succeeds and default-fills before any explicit initializer expression executes; a controlled allocation error therefore occurs first. This is compatible with the frozen specification's left-to-right initializer rule. M7 Task 01 does not execute TAC or target code.
