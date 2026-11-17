# Sparq LR(0) and SLR(1) demonstrations — M3 Task 04D

## Purpose, grammars, and notation

The production Sparq compiler still uses recursive descent over the frozen
[language specification](SPARQ_LANGUAGE_SPEC.md). The complete original BNF
was checked as LL(1) in [LL1_ANALYSIS.md](LL1_ANALYSIS.md); the related
grammar-transformation and shift-reduce explanations are in
[PARSER_THEORY.md](PARSER_THEORY.md). This chapter is an educational LR(0)/SLR(1)
exercise. [The small checker](../tools/lr_analysis.py) handles G0 and G1 below,
plus G2 in the CLR(1)/LALR(1) continuation. It does not parse `.spq` files or
replace the production parser.

**G0** is a *restricted Sparq assignment fragment*. It retains the shape of
Sparq's `IDENTIFIER = <expression> ;` statement, but restricts the value to
an identifier or integer literal. `id` stands for `IDENTIFIER`, `int` for
`INT_LITERAL`, and `=` and `;` are literal terminals. This fragment is not the
whole frozen Sparq grammar. **G1** is a standard illustrative assignment
grammar, not a Sparq production. In both, the new `S' → S` is the augmented
start rule. The analysis marker `$` is separate from Sparq's actual `EOF`
lexer token; neither demonstration grammar contains that `EOF` token.

The production identifiers `P0`, `P1`, ... are stable *within each grammar*;
`P0` always denotes augmentation, never an ordinary reduction. An LR(0) item
places `•` at one position of a production. A state is a **set** of items.
`CLOSURE(I)` repeatedly adds `B → • γ` for every item with `• B`, until no
item can be added. `GOTO(I,X)` moves `•` past `X` in every eligible item and
then closes the result. These operations are set based: duplicates do not make
extra states.

The checker numbers states by breadth-first discovery from `I0 =
CLOSURE({P0 S' → • S})`. At each state it tries **terminals first** in their
first right-hand-side appearance order, then non-augmented nonterminals in
first left-hand-side definition order. G0's edge order is `id`, `=`, `;`,
`int`, `S`, `V`; G1's is `=`, `*`, `id`, `S`, `L`, `R`. Empty GOTO results
make no edge. Items are displayed by production number, then dot position.
Thus state numbers do not depend on Python set iteration order.

## Worked CLOSURE and GOTO checks

For G0, start with `{P0 S' → • S}`. Since the dot precedes `S`, add its
single production with the dot at the start. No new dot is before a
nonterminal, so:

```text
I0 = { P0 S' → • S, P1 S → • id = V ; }
GOTO(I0, id) = I1 = { P1 S → id • = V ; }
```

After reading `id =`, moving the dot over `=` gives
`P1 S → id = • V ;`. Closure adds both `V` rules:

```text
I3 = { P1 S → id = • V ;, P2 V → • id, P3 V → • int }
GOTO(I3, V) = I6 = { P1 S → id = V • ; }
```

For G1, closure of `P0 S' → • S` adds both `S` rules. Their dots before
`L` and `R` add the two `L` rules and `R → • L`, respectively. Repetition
adds nothing further, giving the six-item `I0` shown below. Moving its dot
over `L` gives the particularly important state:

```text
GOTO(I0, L) = I4 = { P1 S → L • = R, P5 R → L • }
```

The first item requests a shift on `=`; the second is a completed reduction.
The full item sets and transitions below show that no reachable state or edge
was omitted.

## Table construction and FOLLOW reasoning

For every terminal edge `I →a J`, put `sJ` in `ACTION[I,a]`. A nonterminal
edge `I →A J` goes in `GOTO[I,A]`. In LR(0), every completed *non-augmented*
item `PK A → α •` puts `rK` in every grammar-terminal column **and** `$`.
In SLR(1), it puts `rK` only in `FOLLOW(A)`. Both methods use the **same**
LR(0) states and transitions. The sole `acc` entry comes from the completed
augmented `P0 S' → S •` on `$`. An empty ACTION cell is an error, not a
conflict. Every distinct candidate action is retained; a cell with two or
more candidates is a conflict.

G0's FOLLOW calculation is short. Augmentation gives `FOLLOW(S) = {$}`.
The `V` in `S → id = V ;` is followed immediately by `;`, so
`FOLLOW(V) = {;}`. Accordingly, LR(0) puts `r2` and `r3` under all five
lookaheads at their completed states, while SLR(1) puts them only under `;`.
The completed `S` rule gets `r1` under all five lookaheads in LR(0), but
only `$` in SLR(1). Neither G0 table has a conflicting cell. Both reject
`id = ; $` immediately after shifting `id =`, because the state then expects
`id` or `int`, not `;`.

For G1, augmentation gives `$ ∈ FOLLOW(S)`. From `S → L = R`, add `=` to
`FOLLOW(L)` and propagate `FOLLOW(S)` to `FOLLOW(R)`. The `R` at the end of
`L → * R` propagates `FOLLOW(L)` to `FOLLOW(R)`, adding `=` there. The
`L` at the end of `R → L` propagates `FOLLOW(R)` back to `FOLLOW(L)`.
At the fixed point, `FOLLOW(L) = FOLLOW(R) = {=, $}` and
`FOLLOW(S) = {$}`. The generated table also lists the augmented symbol's
conventional `$` FOLLOW value.

In G1's `I4`, `P1 S → L • = R` causes `s8` under `=`, and completed
`P5 R → L •` causes `r5`. LR(0) places `r5` in every terminal column,
including `=`. SLR(1) **still** places it under `=` because
`= ∈ FOLLOW(R)`. Both tables therefore retain the single `s8/r5`
**shift/reduce conflict** in `ACTION[I4, =]`. There are no reduce/reduce
conflicts. This is a conflict in the illustrative grammar, not in Sparq's
LL(1) grammar. No precedence rule or arbitrary shift choice has been used to
hide it, and this chapter provides no deterministic G1 parsing trace through
that cell. The same critical LR(0)-item pattern and SLR conflict appear in
[University of Arizona's parsing lecture](https://www2.cs.arizona.edu/classes/cs453/fall10/LectureMaterials/NOTES/PDF/BottomUpParsing.pdf).

<!-- Computed LR(0)/SLR(1) results: start -->
## Computed G0 results

### Productions

| ID | Rule |
|---|---|
| P0 | `S' → S` |
| P1 | `S → id = V ;` |
| P2 | `V → id` |
| P3 | `V → int` |

### Canonical LR(0) collection (8 states)

**I0**

- `P0 S' → • S`
- `P1 S → • id = V ;`

**I1**

- `P1 S → id • = V ;`

**I2**

- `P0 S' → S •`

**I3**

- `P1 S → id = • V ;`
- `P2 V → • id`
- `P3 V → • int`

**I4**

- `P2 V → id •`

**I5**

- `P3 V → int •`

**I6**

- `P1 S → id = V • ;`

**I7**

- `P1 S → id = V ; •`

### Complete DFA transitions

| From | Symbol | To |
|---|---|---|
| I0 | `id` | I1 |
| I0 | `S` | I2 |
| I1 | `=` | I3 |
| I3 | `id` | I4 |
| I3 | `int` | I5 |
| I3 | `V` | I6 |
| I6 | `;` | I7 |

### FOLLOW sets for SLR(1)

| Nonterminal | FOLLOW |
|---|---|
| `S'` | `$` |
| `S` | `$` |
| `V` | `;` |

### Complete LR(0) ACTION/GOTO table

`sJ` shifts to state J, `rK` reduces by PK, `acc` accepts; `—` is an error. Multiple actions in one cell are retained and separated by `/`.

| State | ACTION `id` | ACTION `=` | ACTION `;` | ACTION `int` | ACTION `$` | GOTO `S` | GOTO `V` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| I0 | s1 | — | — | — | — | 2 | — |
| I1 | — | s3 | — | — | — | — | — |
| I2 | — | — | — | — | acc | — | — |
| I3 | s4 | — | — | s5 | — | — | 6 |
| I4 | r2 | r2 | r2 | r2 | r2 | — | — |
| I5 | r3 | r3 | r3 | r3 | r3 | — | — |
| I6 | — | — | s7 | — | — | — | — |
| I7 | r1 | r1 | r1 | r1 | r1 | — | — |

Conflicting ACTION cells: **0**.

No conflicting ACTION cells.

### Complete SLR(1) ACTION/GOTO table

`sJ` shifts to state J, `rK` reduces by PK, `acc` accepts; `—` is an error. Multiple actions in one cell are retained and separated by `/`.

| State | ACTION `id` | ACTION `=` | ACTION `;` | ACTION `int` | ACTION `$` | GOTO `S` | GOTO `V` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| I0 | s1 | — | — | — | — | 2 | — |
| I1 | — | s3 | — | — | — | — | — |
| I2 | — | — | — | — | acc | — | — |
| I3 | s4 | — | — | s5 | — | — | 6 |
| I4 | — | — | r2 | — | — | — | — |
| I5 | — | — | r3 | — | — | — | — |
| I6 | — | — | s7 | — | — | — | — |
| I7 | — | — | — | — | r1 | — | — |

Conflicting ACTION cells: **0**.

No conflicting ACTION cells.

### LR(0) valid trace: `id = int ; $`

| Step | State stack | Symbol stack | Remaining input | ACTION | Production | GOTO |
|---:|---|---|---|---|---|---:|
| 1 | `0` | `∅` | `id = int ; $` | s1 | — | — |
| 2 | `0 1` | `id` | `= int ; $` | s3 | — | — |
| 3 | `0 1 3` | `id =` | `int ; $` | s5 | — | — |
| 4 | `0 1 3 5` | `id = int` | `; $` | r3 | P3 | 6 |
| 5 | `0 1 3 6` | `id = V` | `; $` | s7 | — | — |
| 6 | `0 1 3 6 7` | `id = V ;` | `$` | r1 | P1 | 2 |
| 7 | `0 2` | `S` | `$` | accept | — | — |

Result: **accepted**.

### SLR(1) valid trace: `id = int ; $`

| Step | State stack | Symbol stack | Remaining input | ACTION | Production | GOTO |
|---:|---|---|---|---|---|---:|
| 1 | `0` | `∅` | `id = int ; $` | s1 | — | — |
| 2 | `0 1` | `id` | `= int ; $` | s3 | — | — |
| 3 | `0 1 3` | `id =` | `int ; $` | s5 | — | — |
| 4 | `0 1 3 5` | `id = int` | `; $` | r3 | P3 | 6 |
| 5 | `0 1 3 6` | `id = V` | `; $` | s7 | — | — |
| 6 | `0 1 3 6 7` | `id = V ;` | `$` | r1 | P1 | 2 |
| 7 | `0 2` | `S` | `$` | accept | — | — |

Result: **accepted**.

### LR(0) invalid trace: `id = ; $`

| Step | State stack | Symbol stack | Remaining input | ACTION | Production | GOTO |
|---:|---|---|---|---|---|---:|
| 1 | `0` | `∅` | `id = ; $` | s1 | — | — |
| 2 | `0 1` | `id` | `= ; $` | s3 | — | — |
| 3 | `0 1 3` | `id =` | `; $` | error: empty ACTION cell | — | — |

Result: **rejected**.

### SLR(1) invalid trace: `id = ; $`

| Step | State stack | Symbol stack | Remaining input | ACTION | Production | GOTO |
|---:|---|---|---|---|---|---:|
| 1 | `0` | `∅` | `id = ; $` | s1 | — | — |
| 2 | `0 1` | `id` | `= ; $` | s3 | — | — |
| 3 | `0 1 3` | `id =` | `; $` | error: empty ACTION cell | — | — |

Result: **rejected**.

## Computed G1 results

### Productions

| ID | Rule |
|---|---|
| P0 | `S' → S` |
| P1 | `S → L = R` |
| P2 | `S → R` |
| P3 | `L → * R` |
| P4 | `L → id` |
| P5 | `R → L` |

### Canonical LR(0) collection (10 states)

**I0**

- `P0 S' → • S`
- `P1 S → • L = R`
- `P2 S → • R`
- `P3 L → • * R`
- `P4 L → • id`
- `P5 R → • L`

**I1**

- `P3 L → • * R`
- `P3 L → * • R`
- `P4 L → • id`
- `P5 R → • L`

**I2**

- `P4 L → id •`

**I3**

- `P0 S' → S •`

**I4**

- `P1 S → L • = R`
- `P5 R → L •`

**I5**

- `P2 S → R •`

**I6**

- `P5 R → L •`

**I7**

- `P3 L → * R •`

**I8**

- `P1 S → L = • R`
- `P3 L → • * R`
- `P4 L → • id`
- `P5 R → • L`

**I9**

- `P1 S → L = R •`

### Complete DFA transitions

| From | Symbol | To |
|---|---|---|
| I0 | `*` | I1 |
| I0 | `id` | I2 |
| I0 | `S` | I3 |
| I0 | `L` | I4 |
| I0 | `R` | I5 |
| I1 | `*` | I1 |
| I1 | `id` | I2 |
| I1 | `L` | I6 |
| I1 | `R` | I7 |
| I4 | `=` | I8 |
| I8 | `*` | I1 |
| I8 | `id` | I2 |
| I8 | `L` | I6 |
| I8 | `R` | I9 |

### FOLLOW sets for SLR(1)

| Nonterminal | FOLLOW |
|---|---|
| `S'` | `$` |
| `S` | `$` |
| `L` | `$`, `=` |
| `R` | `$`, `=` |

### Complete LR(0) ACTION/GOTO table

`sJ` shifts to state J, `rK` reduces by PK, `acc` accepts; `—` is an error. Multiple actions in one cell are retained and separated by `/`.

| State | ACTION `=` | ACTION `*` | ACTION `id` | ACTION `$` | GOTO `S` | GOTO `L` | GOTO `R` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| I0 | — | s1 | s2 | — | 3 | 4 | 5 |
| I1 | — | s1 | s2 | — | — | 6 | 7 |
| I2 | r4 | r4 | r4 | r4 | — | — | — |
| I3 | — | — | — | acc | — | — | — |
| I4 | s8/r5 | r5 | r5 | r5 | — | — | — |
| I5 | r2 | r2 | r2 | r2 | — | — | — |
| I6 | r5 | r5 | r5 | r5 | — | — | — |
| I7 | r3 | r3 | r3 | r3 | — | — | — |
| I8 | — | s1 | s2 | — | — | 6 | 9 |
| I9 | r1 | r1 | r1 | r1 | — | — | — |

Conflicting ACTION cells: **1**.

- `ACTION[I4, =]` = **s8/r5** (shift/reduce); responsible items: `P1 S → L • = R`; `P5 R → L •`.

### Complete SLR(1) ACTION/GOTO table

`sJ` shifts to state J, `rK` reduces by PK, `acc` accepts; `—` is an error. Multiple actions in one cell are retained and separated by `/`.

| State | ACTION `=` | ACTION `*` | ACTION `id` | ACTION `$` | GOTO `S` | GOTO `L` | GOTO `R` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| I0 | — | s1 | s2 | — | 3 | 4 | 5 |
| I1 | — | s1 | s2 | — | — | 6 | 7 |
| I2 | r4 | — | — | r4 | — | — | — |
| I3 | — | — | — | acc | — | — | — |
| I4 | s8/r5 | — | — | r5 | — | — | — |
| I5 | — | — | — | r2 | — | — | — |
| I6 | r5 | — | — | r5 | — | — | — |
| I7 | r3 | — | — | r3 | — | — | — |
| I8 | — | s1 | s2 | — | — | 6 | 9 |
| I9 | — | — | — | r1 | — | — | — |

Conflicting ACTION cells: **1**.

- `ACTION[I4, =]` = **s8/r5** (shift/reduce); responsible items: `P1 S → L • = R`; `P5 R → L •`.
<!-- Computed LR(0)/SLR(1) results: end -->

## Comparison, verification, and limits

G0 has no conflict under either method. SLR(1) retains its shifts, GOTO
edges, and accept action while restricting reductions to actual FOLLOW
lookaheads; its valid and invalid traces therefore make the same decisions
on the demonstrated inputs. G1's single shift/reduce conflict remains after
FOLLOW restriction. This shows that SLR(1) can remove excess reduction
entries without always separating contexts that share a global FOLLOW set.
The checker deliberately stops at a conflicting table cell rather than
choosing one action.

The utility computes items, states, edges, FIRST/FOLLOW for these nonnullable
grammars, both tables, conflict lists, and traces from the production tuples
above. Focused tests compare selected states, edges, FOLLOW sets, and entries
to hand-checked checkpoints; they also verify every computed DFA edge by
recomputing GOTO, check every reduction cell against its completed item and
lookahead rule, retain a deliberately introduced reduce/reduce conflict,
check the sole augmented accept action, and compare the generated tables to
this document. The full Sparq regression suite is run separately. These
checks do not prove production-parser correctness or establish an LR method
for the complete Sparq BNF.

For a viva, derive G0 `I0`, `I3`, and `GOTO(I3,V)` by hand; explain why the
G0 LR(0) `r3` row has five lookaheads but the SLR(1) row has one; walk both
valid state-stack traces through `P3` and `P1`; explain the empty ACTION cell
for `id = ; $`; derive G1 `I4`, both FOLLOW sets, and `s8/r5`; and explain
why the same G1 item DFA is reused by SLR(1). State explicitly that these
two grammars are teaching fragments and the compiler remains recursive descent.

## Canonical LR(1) and LALR(1) — Task 04E

This continuation preserves the LR(0)/SLR(1) calculations above. **G0** remains
the restricted Sparq fragment; **G1** and the new **G2** are illustrative
teaching grammars. The `P0`–`P5` rules for G1 are unchanged. G2 has:

```text
P0  S' → S
P1  S  → a B c
P2  S  → b C c
P3  S  → a C d
P4  S  → b B d
P5  B  → e
P6  C  → e
```

G2 is **not** Sparq syntax. Its two `e` reductions illustrate a case where
canonical LR(1) works but merging equal LR(0) cores introduces ambiguity.
The same illustrative grammar and complementary-lookahead phenomenon appear
in [Stanford CS143's LALR parsing handout](https://web.stanford.edu/class/archive/cs/cs143/cs143.1128/handouts/140%20LALR%20Parsing.pdf);
our state numbering and tables below were calculated independently.
The complete calculated item sets, transitions, tables, and traces follow the
manual explanations below. Run `python -m tools.lr_analysis --check-doc` from
the project root to verify both generated sections without writing files.

### LR(1) items, FIRST, CLOSURE, and GOTO

An immutable LR(1) item is `[PK A → α • β, a]`: production ID, dot position,
and one lookahead terminal `a`. Its **LR(0) core** is only `(PK, dot)`. A
canonical LR(1) state is a set of complete LR(1) items, so two items with the
same core and different lookaheads are retained separately. Start from
`[P0 S' → • S, $]`; `$` is the analysis end marker, not Sparq's lexer `EOF`.

For `[A → α • B β, a]`, CLOSURE adds `[B → • γ, b]` for each `B → γ`
and each `b ∈ FIRST(β a)`, repeating to a fixed point. FIRST of a sequence
scans through nullable prefixes; if `β` can vanish, the inherited lookahead
`a` participates. `GOTO(I,X)` advances every dot before `X`, keeps that
item's lookahead, and closes the result. These rules use **local**
`FIRST(β a)`, not global FOLLOW(B). The checker has a nullable-aware FIRST
fixed point; although G1 and G2 have no empty rules, a focused synthetic test
checks the nullable-suffix case.

Two hand-derived closure checkpoints show the lookahead distinction:

1. In **G1's initial state**, `[P1 S → • L = R, $]` adds the two `L`
   starters with lookahead `=`, because `FIRST(= R $) = {=}`. The other
   branch `[P2 S → • R, $]` adds `[P5 R → • L, $]`, which adds the same
   two `L` starters with lookahead `$`. After `GOTO(I0,L)`, the canonical
   state `I4` contains `[P1 S → L • = R, $]` and
   `[P5 R → L •, $]`. It shifts `=`; its completed `R` item reduces **only**
   on `$`. The former SLR(1) `s8/r5` collision on `=` is absent.
2. In **G2 after `a`**, `[P1 S → a • B c, $]` adds
   `[P5 B → • e, c]` because `FIRST(c $)={c}`. Alongside it,
   `[P3 S → a • C d, $]` adds `[P6 C → • e, d]`. Thus `GOTO(I1,e)=I4`
   contains `[P5 B → e •, c]` and `[P6 C → e •, d]`. After `b`,
   `GOTO(I2,e)=I7` has the **opposite** lookaheads: B on `d`, C on `c`.
   Each canonical state has at most one reduction on either terminal.

Canonical states use breadth-first discovery, terminal edges first in
first-right-hand-side appearance order, then nonterminal edges in
first-definition order, just as in Task 04D. G1's edge order remains
`=, *, id, S, L, R`. G2's is `a, c, b, d, e, S, B, C`.
Stable state IDs follow that order; they need not match another textbook's
numbering. For each canonical state, terminal edges produce shifts,
nonterminal edges produce GOTO entries, and `[A → α •, a]` produces `rK`
**only under `a`**. Only `[P0 S' → S •, $]` produces `acc` on `$`.
All distinct candidate actions remain in a cell when a conflict occurs.

### LALR(1) merging and the two example outcomes

LALR grouping compares **entire LR(0) core sets**, not overlapping
productions or item counts. Groups receive `J0, J1, ...` in first canonical
state appearance order. Each merged state is the union of its source LR(1)
items, so matching core items acquire the union of their lookaheads. Every
outgoing canonical edge is redirected to a merged destination; the checker
raises an inconsistency if one merged state and symbol lead to different
destination groups. It then builds a fresh ACTION/GOTO table from the merged
items. No conflict is resolved automatically.

For **G1**, the 14 canonical states merge into 10. The groups with two states
are `I1/I9`, `I2/I10`, `I6/I11`, and `I7/I13`. Crucially, canonical `I4`
has no equal-core partner. Its reduction `[P5 R → L •, $]` therefore never
gains `=` and its LALR counterpart `J4` is conflict-free. Another merged
state may carry `R → L •` with both `$` and `=` but has no competing shift
on `=`. Both computed tables accept `id = id $` and `* id = id $`, and
both reject the missing-value input `id = $` at an empty ACTION cell.

For **G2**, canonical `I4` and `I7` share exactly the core set
`{(P5, dot 1), (P6, dot 1)}`. Their lookaheads are complementary:

| Canonical state | Completed B item | Completed C item |
|---|---|---|
| `I4` (after `a e`) | `[P5 B → e •, c]` | `[P6 C → e •, d]` |
| `I7` (after `b e`) | `[P5 B → e •, d]` | `[P6 C → e •, c]` |

Merging them creates `J4` with **both** lookaheads `{c,d}` on **both**
completed cores. Therefore `ACTION[J4,c]` and `ACTION[J4,d]` each retain
`r5/r6`: **two new reduce/reduce conflict cells**. No canonical G2 cell
conflicts. G2 has 14 canonical states and 13 merged states. Its four example
strings `a e c $`, `a e d $`, `b e c $`, and `b e d $` are all accepted by
the computed canonical table; representative complete traces below show
`a e c $` and `b e c $`. The malformed `a e $` reaches an empty canonical
ACTION cell and is rejected. A LALR trace of valid `a e c $` stops at the
unresolved `r5/r6` cell. That stop is a **table conflict**, not a claim that
the string is outside G2's language.

The trace tables show the ACTION lookup, shifted terminal, reduction rule,
number of grammar symbols and matching states popped, and GOTO after each
reduction. The symbol and state stacks are printed separately, with their
tops at the right. Acceptance is recorded only when the augmented start item
is complete with lookahead `$`.

<!-- Computed CLR(1)/LALR(1) results: start -->
## Computed G1 CLR(1) and LALR(1) results

### Production IDs

| ID | Rule |
|---|---|
| P0 | `S' → S` |
| P1 | `S → L = R` |
| P2 | `S → R` |
| P3 | `L → * R` |
| P4 | `L → id` |
| P5 | `R → L` |

### Complete CLR(1) item collection (14 states)

**I0**

- `[P0 S' → • S, $]`
- `[P1 S → • L = R, $]`
- `[P2 S → • R, $]`
- `[P3 L → • * R, $]`
- `[P3 L → • * R, =]`
- `[P4 L → • id, $]`
- `[P4 L → • id, =]`
- `[P5 R → • L, $]`

**I1**

- `[P3 L → • * R, $]`
- `[P3 L → • * R, =]`
- `[P3 L → * • R, $]`
- `[P3 L → * • R, =]`
- `[P4 L → • id, $]`
- `[P4 L → • id, =]`
- `[P5 R → • L, $]`
- `[P5 R → • L, =]`

**I2**

- `[P4 L → id •, $]`
- `[P4 L → id •, =]`

**I3**

- `[P0 S' → S •, $]`

**I4**

- `[P1 S → L • = R, $]`
- `[P5 R → L •, $]`

**I5**

- `[P2 S → R •, $]`

**I6**

- `[P5 R → L •, $]`
- `[P5 R → L •, =]`

**I7**

- `[P3 L → * R •, $]`
- `[P3 L → * R •, =]`

**I8**

- `[P1 S → L = • R, $]`
- `[P3 L → • * R, $]`
- `[P4 L → • id, $]`
- `[P5 R → • L, $]`

**I9**

- `[P3 L → • * R, $]`
- `[P3 L → * • R, $]`
- `[P4 L → • id, $]`
- `[P5 R → • L, $]`

**I10**

- `[P4 L → id •, $]`

**I11**

- `[P5 R → L •, $]`

**I12**

- `[P1 S → L = R •, $]`

**I13**

- `[P3 L → * R •, $]`

### Complete CLR(1) DFA transitions

| From | Symbol | To |
|---|---|---|
| I0 | `*` | I1 |
| I0 | `id` | I2 |
| I0 | `S` | I3 |
| I0 | `L` | I4 |
| I0 | `R` | I5 |
| I1 | `*` | I1 |
| I1 | `id` | I2 |
| I1 | `L` | I6 |
| I1 | `R` | I7 |
| I4 | `=` | I8 |
| I8 | `*` | I9 |
| I8 | `id` | I10 |
| I8 | `L` | I11 |
| I8 | `R` | I12 |
| I9 | `*` | I9 |
| I9 | `id` | I10 |
| I9 | `L` | I11 |
| I9 | `R` | I13 |

### Complete CLR(1) ACTION/GOTO table

`sJ` shifts to J; `rK` reduces by PK; `acc` accepts; `—` is an error. Multiple candidate actions remain visible, separated by `/`.

| State | ACTION `=` | ACTION `*` | ACTION `id` | ACTION `$` | GOTO `S` | GOTO `L` | GOTO `R` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| I0 | — | s1 | s2 | — | I3 | I4 | I5 |
| I1 | — | s1 | s2 | — | — | I6 | I7 |
| I2 | r4 | — | — | r4 | — | — | — |
| I3 | — | — | — | acc | — | — | — |
| I4 | s8 | — | — | r5 | — | — | — |
| I5 | — | — | — | r2 | — | — | — |
| I6 | r5 | — | — | r5 | — | — | — |
| I7 | r3 | — | — | r3 | — | — | — |
| I8 | — | s9 | s10 | — | — | I11 | I12 |
| I9 | — | s9 | s10 | — | — | I11 | I13 |
| I10 | — | — | — | r4 | — | — | — |
| I11 | — | — | — | r5 | — | — | — |
| I12 | — | — | — | r1 | — | — | — |
| I13 | — | — | — | r3 | — | — | — |

Conflicting ACTION cells: **0**.

No conflicting ACTION cells.

### Identical-core groups and LALR(1) numbering

Merged state Jk has ID k; canonical states are Ik. Groups are listed in first canonical-state appearance order.

| Merged state | Canonical source states | LR(0) core items |
|---|---|---|
| J0 | I0 | `P0 S' → • S`<br>`P1 S → • L = R`<br>`P2 S → • R`<br>`P3 L → • * R`<br>`P4 L → • id`<br>`P5 R → • L` |
| J1 | I1, I9 | `P3 L → • * R`<br>`P3 L → * • R`<br>`P4 L → • id`<br>`P5 R → • L` |
| J2 | I2, I10 | `P4 L → id •` |
| J3 | I3 | `P0 S' → S •` |
| J4 | I4 | `P1 S → L • = R`<br>`P5 R → L •` |
| J5 | I5 | `P2 S → R •` |
| J6 | I6, I11 | `P5 R → L •` |
| J7 | I7, I13 | `P3 L → * R •` |
| J8 | I8 | `P1 S → L = • R`<br>`P3 L → • * R`<br>`P4 L → • id`<br>`P5 R → • L` |
| J9 | I12 | `P1 S → L = R •` |

### Complete LALR(1) item collection (10 states)

**J0**

- `[P0 S' → • S, $]`
- `[P1 S → • L = R, $]`
- `[P2 S → • R, $]`
- `[P3 L → • * R, $]`
- `[P3 L → • * R, =]`
- `[P4 L → • id, $]`
- `[P4 L → • id, =]`
- `[P5 R → • L, $]`

**J1**

- `[P3 L → • * R, $]`
- `[P3 L → • * R, =]`
- `[P3 L → * • R, $]`
- `[P3 L → * • R, =]`
- `[P4 L → • id, $]`
- `[P4 L → • id, =]`
- `[P5 R → • L, $]`
- `[P5 R → • L, =]`

**J2**

- `[P4 L → id •, $]`
- `[P4 L → id •, =]`

**J3**

- `[P0 S' → S •, $]`

**J4**

- `[P1 S → L • = R, $]`
- `[P5 R → L •, $]`

**J5**

- `[P2 S → R •, $]`

**J6**

- `[P5 R → L •, $]`
- `[P5 R → L •, =]`

**J7**

- `[P3 L → * R •, $]`
- `[P3 L → * R •, =]`

**J8**

- `[P1 S → L = • R, $]`
- `[P3 L → • * R, $]`
- `[P4 L → • id, $]`
- `[P5 R → • L, $]`

**J9**

- `[P1 S → L = R •, $]`

### Complete LALR(1) DFA transitions

| From | Symbol | To |
|---|---|---|
| J0 | `*` | J1 |
| J0 | `id` | J2 |
| J0 | `S` | J3 |
| J0 | `L` | J4 |
| J0 | `R` | J5 |
| J1 | `*` | J1 |
| J1 | `id` | J2 |
| J1 | `L` | J6 |
| J1 | `R` | J7 |
| J4 | `=` | J8 |
| J8 | `*` | J1 |
| J8 | `id` | J2 |
| J8 | `L` | J6 |
| J8 | `R` | J9 |

### Complete LALR(1) ACTION/GOTO table

`sJ` shifts to J; `rK` reduces by PK; `acc` accepts; `—` is an error. Multiple candidate actions remain visible, separated by `/`.

| State | ACTION `=` | ACTION `*` | ACTION `id` | ACTION `$` | GOTO `S` | GOTO `L` | GOTO `R` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| J0 | — | s1 | s2 | — | J3 | J4 | J5 |
| J1 | — | s1 | s2 | — | — | J6 | J7 |
| J2 | r4 | — | — | r4 | — | — | — |
| J3 | — | — | — | acc | — | — | — |
| J4 | s8 | — | — | r5 | — | — | — |
| J5 | — | — | — | r2 | — | — | — |
| J6 | r5 | — | — | r5 | — | — | — |
| J7 | r3 | — | — | r3 | — | — | — |
| J8 | — | s1 | s2 | — | — | J6 | J9 |
| J9 | — | — | — | r1 | — | — | — |

Conflicting ACTION cells: **0**.

No conflicting ACTION cells.

### G1 CLR(1) valid: `id = id $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `id = id $` | `ACTION[I0, id]` → s2 | `id` | — | — | — |
| 2 | `0 2` | `id` | `= id $` | `ACTION[I2, =]` → r4 | — | P4 | 1 | I4 |
| 3 | `0 4` | `L` | `= id $` | `ACTION[I4, =]` → s8 | `=` | — | — | — |
| 4 | `0 4 8` | `L =` | `id $` | `ACTION[I8, id]` → s10 | `id` | — | — | — |
| 5 | `0 4 8 10` | `L = id` | `$` | `ACTION[I10, $]` → r4 | — | P4 | 1 | I11 |
| 6 | `0 4 8 11` | `L = L` | `$` | `ACTION[I11, $]` → r5 | — | P5 | 1 | I12 |
| 7 | `0 4 8 12` | `L = R` | `$` | `ACTION[I12, $]` → r1 | — | P1 | 3 | I3 |
| 8 | `0 3` | `S` | `$` | `ACTION[I3, $]` → accept | — | — | — | — |

Result: **accepted**.

### G1 LALR(1) valid: `id = id $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `id = id $` | `ACTION[J0, id]` → s2 | `id` | — | — | — |
| 2 | `0 2` | `id` | `= id $` | `ACTION[J2, =]` → r4 | — | P4 | 1 | J4 |
| 3 | `0 4` | `L` | `= id $` | `ACTION[J4, =]` → s8 | `=` | — | — | — |
| 4 | `0 4 8` | `L =` | `id $` | `ACTION[J8, id]` → s2 | `id` | — | — | — |
| 5 | `0 4 8 2` | `L = id` | `$` | `ACTION[J2, $]` → r4 | — | P4 | 1 | J6 |
| 6 | `0 4 8 6` | `L = L` | `$` | `ACTION[J6, $]` → r5 | — | P5 | 1 | J9 |
| 7 | `0 4 8 9` | `L = R` | `$` | `ACTION[J9, $]` → r1 | — | P1 | 3 | J3 |
| 8 | `0 3` | `S` | `$` | `ACTION[J3, $]` → accept | — | — | — | — |

Result: **accepted**.

### G1 CLR(1) dereference: `* id = id $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `* id = id $` | `ACTION[I0, *]` → s1 | `*` | — | — | — |
| 2 | `0 1` | `*` | `id = id $` | `ACTION[I1, id]` → s2 | `id` | — | — | — |
| 3 | `0 1 2` | `* id` | `= id $` | `ACTION[I2, =]` → r4 | — | P4 | 1 | I6 |
| 4 | `0 1 6` | `* L` | `= id $` | `ACTION[I6, =]` → r5 | — | P5 | 1 | I7 |
| 5 | `0 1 7` | `* R` | `= id $` | `ACTION[I7, =]` → r3 | — | P3 | 2 | I4 |
| 6 | `0 4` | `L` | `= id $` | `ACTION[I4, =]` → s8 | `=` | — | — | — |
| 7 | `0 4 8` | `L =` | `id $` | `ACTION[I8, id]` → s10 | `id` | — | — | — |
| 8 | `0 4 8 10` | `L = id` | `$` | `ACTION[I10, $]` → r4 | — | P4 | 1 | I11 |
| 9 | `0 4 8 11` | `L = L` | `$` | `ACTION[I11, $]` → r5 | — | P5 | 1 | I12 |
| 10 | `0 4 8 12` | `L = R` | `$` | `ACTION[I12, $]` → r1 | — | P1 | 3 | I3 |
| 11 | `0 3` | `S` | `$` | `ACTION[I3, $]` → accept | — | — | — | — |

Result: **accepted**.

### G1 LALR(1) dereference: `* id = id $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `* id = id $` | `ACTION[J0, *]` → s1 | `*` | — | — | — |
| 2 | `0 1` | `*` | `id = id $` | `ACTION[J1, id]` → s2 | `id` | — | — | — |
| 3 | `0 1 2` | `* id` | `= id $` | `ACTION[J2, =]` → r4 | — | P4 | 1 | J6 |
| 4 | `0 1 6` | `* L` | `= id $` | `ACTION[J6, =]` → r5 | — | P5 | 1 | J7 |
| 5 | `0 1 7` | `* R` | `= id $` | `ACTION[J7, =]` → r3 | — | P3 | 2 | J4 |
| 6 | `0 4` | `L` | `= id $` | `ACTION[J4, =]` → s8 | `=` | — | — | — |
| 7 | `0 4 8` | `L =` | `id $` | `ACTION[J8, id]` → s2 | `id` | — | — | — |
| 8 | `0 4 8 2` | `L = id` | `$` | `ACTION[J2, $]` → r4 | — | P4 | 1 | J6 |
| 9 | `0 4 8 6` | `L = L` | `$` | `ACTION[J6, $]` → r5 | — | P5 | 1 | J9 |
| 10 | `0 4 8 9` | `L = R` | `$` | `ACTION[J9, $]` → r1 | — | P1 | 3 | J3 |
| 11 | `0 3` | `S` | `$` | `ACTION[J3, $]` → accept | — | — | — | — |

Result: **accepted**.

### G1 CLR(1) invalid: `id = $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `id = $` | `ACTION[I0, id]` → s2 | `id` | — | — | — |
| 2 | `0 2` | `id` | `= $` | `ACTION[I2, =]` → r4 | — | P4 | 1 | I4 |
| 3 | `0 4` | `L` | `= $` | `ACTION[I4, =]` → s8 | `=` | — | — | — |
| 4 | `0 4 8` | `L =` | `$` | `ACTION[I8, $]` → error: empty ACTION cell | — | — | — | — |

Result: **rejected**.

### G1 LALR(1) invalid: `id = $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `id = $` | `ACTION[J0, id]` → s2 | `id` | — | — | — |
| 2 | `0 2` | `id` | `= $` | `ACTION[J2, =]` → r4 | — | P4 | 1 | J4 |
| 3 | `0 4` | `L` | `= $` | `ACTION[J4, =]` → s8 | `=` | — | — | — |
| 4 | `0 4 8` | `L =` | `$` | `ACTION[J8, $]` → error: empty ACTION cell | — | — | — | — |

Result: **rejected**.

## Computed G2 CLR(1) and LALR(1) results

### Production IDs

| ID | Rule |
|---|---|
| P0 | `S' → S` |
| P1 | `S → a B c` |
| P2 | `S → b C c` |
| P3 | `S → a C d` |
| P4 | `S → b B d` |
| P5 | `B → e` |
| P6 | `C → e` |

### Complete CLR(1) item collection (14 states)

**I0**

- `[P0 S' → • S, $]`
- `[P1 S → • a B c, $]`
- `[P2 S → • b C c, $]`
- `[P3 S → • a C d, $]`
- `[P4 S → • b B d, $]`

**I1**

- `[P1 S → a • B c, $]`
- `[P3 S → a • C d, $]`
- `[P5 B → • e, c]`
- `[P6 C → • e, d]`

**I2**

- `[P2 S → b • C c, $]`
- `[P4 S → b • B d, $]`
- `[P5 B → • e, d]`
- `[P6 C → • e, c]`

**I3**

- `[P0 S' → S •, $]`

**I4**

- `[P5 B → e •, c]`
- `[P6 C → e •, d]`

**I5**

- `[P1 S → a B • c, $]`

**I6**

- `[P3 S → a C • d, $]`

**I7**

- `[P5 B → e •, d]`
- `[P6 C → e •, c]`

**I8**

- `[P4 S → b B • d, $]`

**I9**

- `[P2 S → b C • c, $]`

**I10**

- `[P1 S → a B c •, $]`

**I11**

- `[P3 S → a C d •, $]`

**I12**

- `[P4 S → b B d •, $]`

**I13**

- `[P2 S → b C c •, $]`

### Complete CLR(1) DFA transitions

| From | Symbol | To |
|---|---|---|
| I0 | `a` | I1 |
| I0 | `b` | I2 |
| I0 | `S` | I3 |
| I1 | `e` | I4 |
| I1 | `B` | I5 |
| I1 | `C` | I6 |
| I2 | `e` | I7 |
| I2 | `B` | I8 |
| I2 | `C` | I9 |
| I5 | `c` | I10 |
| I6 | `d` | I11 |
| I8 | `d` | I12 |
| I9 | `c` | I13 |

### Complete CLR(1) ACTION/GOTO table

`sJ` shifts to J; `rK` reduces by PK; `acc` accepts; `—` is an error. Multiple candidate actions remain visible, separated by `/`.

| State | ACTION `a` | ACTION `c` | ACTION `b` | ACTION `d` | ACTION `e` | ACTION `$` | GOTO `S` | GOTO `B` | GOTO `C` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| I0 | s1 | — | s2 | — | — | — | I3 | — | — |
| I1 | — | — | — | — | s4 | — | — | I5 | I6 |
| I2 | — | — | — | — | s7 | — | — | I8 | I9 |
| I3 | — | — | — | — | — | acc | — | — | — |
| I4 | — | r5 | — | r6 | — | — | — | — | — |
| I5 | — | s10 | — | — | — | — | — | — | — |
| I6 | — | — | — | s11 | — | — | — | — | — |
| I7 | — | r6 | — | r5 | — | — | — | — | — |
| I8 | — | — | — | s12 | — | — | — | — | — |
| I9 | — | s13 | — | — | — | — | — | — | — |
| I10 | — | — | — | — | — | r1 | — | — | — |
| I11 | — | — | — | — | — | r3 | — | — | — |
| I12 | — | — | — | — | — | r4 | — | — | — |
| I13 | — | — | — | — | — | r2 | — | — | — |

Conflicting ACTION cells: **0**.

No conflicting ACTION cells.

### Identical-core groups and LALR(1) numbering

Merged state Jk has ID k; canonical states are Ik. Groups are listed in first canonical-state appearance order.

| Merged state | Canonical source states | LR(0) core items |
|---|---|---|
| J0 | I0 | `P0 S' → • S`<br>`P1 S → • a B c`<br>`P2 S → • b C c`<br>`P3 S → • a C d`<br>`P4 S → • b B d` |
| J1 | I1 | `P1 S → a • B c`<br>`P3 S → a • C d`<br>`P5 B → • e`<br>`P6 C → • e` |
| J2 | I2 | `P2 S → b • C c`<br>`P4 S → b • B d`<br>`P5 B → • e`<br>`P6 C → • e` |
| J3 | I3 | `P0 S' → S •` |
| J4 | I4, I7 | `P5 B → e •`<br>`P6 C → e •` |
| J5 | I5 | `P1 S → a B • c` |
| J6 | I6 | `P3 S → a C • d` |
| J7 | I8 | `P4 S → b B • d` |
| J8 | I9 | `P2 S → b C • c` |
| J9 | I10 | `P1 S → a B c •` |
| J10 | I11 | `P3 S → a C d •` |
| J11 | I12 | `P4 S → b B d •` |
| J12 | I13 | `P2 S → b C c •` |

### Complete LALR(1) item collection (13 states)

**J0**

- `[P0 S' → • S, $]`
- `[P1 S → • a B c, $]`
- `[P2 S → • b C c, $]`
- `[P3 S → • a C d, $]`
- `[P4 S → • b B d, $]`

**J1**

- `[P1 S → a • B c, $]`
- `[P3 S → a • C d, $]`
- `[P5 B → • e, c]`
- `[P6 C → • e, d]`

**J2**

- `[P2 S → b • C c, $]`
- `[P4 S → b • B d, $]`
- `[P5 B → • e, d]`
- `[P6 C → • e, c]`

**J3**

- `[P0 S' → S •, $]`

**J4**

- `[P5 B → e •, c]`
- `[P5 B → e •, d]`
- `[P6 C → e •, c]`
- `[P6 C → e •, d]`

**J5**

- `[P1 S → a B • c, $]`

**J6**

- `[P3 S → a C • d, $]`

**J7**

- `[P4 S → b B • d, $]`

**J8**

- `[P2 S → b C • c, $]`

**J9**

- `[P1 S → a B c •, $]`

**J10**

- `[P3 S → a C d •, $]`

**J11**

- `[P4 S → b B d •, $]`

**J12**

- `[P2 S → b C c •, $]`

### Complete LALR(1) DFA transitions

| From | Symbol | To |
|---|---|---|
| J0 | `a` | J1 |
| J0 | `b` | J2 |
| J0 | `S` | J3 |
| J1 | `e` | J4 |
| J1 | `B` | J5 |
| J1 | `C` | J6 |
| J2 | `e` | J4 |
| J2 | `B` | J7 |
| J2 | `C` | J8 |
| J5 | `c` | J9 |
| J6 | `d` | J10 |
| J7 | `d` | J11 |
| J8 | `c` | J12 |

### Complete LALR(1) ACTION/GOTO table

`sJ` shifts to J; `rK` reduces by PK; `acc` accepts; `—` is an error. Multiple candidate actions remain visible, separated by `/`.

| State | ACTION `a` | ACTION `c` | ACTION `b` | ACTION `d` | ACTION `e` | ACTION `$` | GOTO `S` | GOTO `B` | GOTO `C` |
|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| J0 | s1 | — | s2 | — | — | — | J3 | — | — |
| J1 | — | — | — | — | s4 | — | — | J5 | J6 |
| J2 | — | — | — | — | s4 | — | — | J7 | J8 |
| J3 | — | — | — | — | — | acc | — | — | — |
| J4 | — | r5/r6 | — | r5/r6 | — | — | — | — | — |
| J5 | — | s9 | — | — | — | — | — | — | — |
| J6 | — | — | — | s10 | — | — | — | — | — |
| J7 | — | — | — | s11 | — | — | — | — | — |
| J8 | — | s12 | — | — | — | — | — | — | — |
| J9 | — | — | — | — | — | r1 | — | — | — |
| J10 | — | — | — | — | — | r3 | — | — | — |
| J11 | — | — | — | — | — | r4 | — | — | — |
| J12 | — | — | — | — | — | r2 | — | — | — |

Conflicting ACTION cells: **2**.

- `ACTION[J4, c]` = **r5/r6** (reduce/reduce); responsible items: `[P5 B → e •, c]`; `[P6 C → e •, c]`.
- `ACTION[J4, d]` = **r5/r6** (reduce/reduce); responsible items: `[P5 B → e •, d]`; `[P6 C → e •, d]`.

### G2 CLR(1) valid: `a e c $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `a e c $` | `ACTION[I0, a]` → s1 | `a` | — | — | — |
| 2 | `0 1` | `a` | `e c $` | `ACTION[I1, e]` → s4 | `e` | — | — | — |
| 3 | `0 1 4` | `a e` | `c $` | `ACTION[I4, c]` → r5 | — | P5 | 1 | I5 |
| 4 | `0 1 5` | `a B` | `c $` | `ACTION[I5, c]` → s10 | `c` | — | — | — |
| 5 | `0 1 5 10` | `a B c` | `$` | `ACTION[I10, $]` → r1 | — | P1 | 3 | I3 |
| 6 | `0 3` | `S` | `$` | `ACTION[I3, $]` → accept | — | — | — | — |

Result: **accepted**.

### G2 CLR(1) valid: `b e c $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `b e c $` | `ACTION[I0, b]` → s2 | `b` | — | — | — |
| 2 | `0 2` | `b` | `e c $` | `ACTION[I2, e]` → s7 | `e` | — | — | — |
| 3 | `0 2 7` | `b e` | `c $` | `ACTION[I7, c]` → r6 | — | P6 | 1 | I9 |
| 4 | `0 2 9` | `b C` | `c $` | `ACTION[I9, c]` → s13 | `c` | — | — | — |
| 5 | `0 2 9 13` | `b C c` | `$` | `ACTION[I13, $]` → r2 | — | P2 | 3 | I3 |
| 6 | `0 3` | `S` | `$` | `ACTION[I3, $]` → accept | — | — | — | — |

Result: **accepted**.

### G2 CLR(1) invalid: `a e $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `a e $` | `ACTION[I0, a]` → s1 | `a` | — | — | — |
| 2 | `0 1` | `a` | `e $` | `ACTION[I1, e]` → s4 | `e` | — | — | — |
| 3 | `0 1 4` | `a e` | `$` | `ACTION[I4, $]` → error: empty ACTION cell | — | — | — | — |

Result: **rejected**.

### G2 LALR(1) unresolved: `a e c $`

| Step | State stack | Symbol stack | Remaining input | ACTION lookup/result | Shifted | Production | Popped symbols/states | GOTO |
|---:|---|---|---|---|---|---|---:|---:|
| 1 | `0` | `∅` | `a e c $` | `ACTION[J0, a]` → s1 | `a` | — | — | — |
| 2 | `0 1` | `a` | `e c $` | `ACTION[J1, e]` → s4 | `e` | — | — | — |
| 3 | `0 1 4` | `a e` | `c $` | `ACTION[J4, c]` → conflict: r5/r6 | — | — | — | — |

Result: **stopped at conflict**.
<!-- Computed CLR(1)/LALR(1) results: end -->

### Four-method comparison and verification

| Grammar | LR(0) states / conflicts | SLR(1) states / conflicts | CLR(1) states / conflicts | LALR(1) states / conflicts |
|---|---:|---:|---:|---:|
| G0 restricted Sparq fragment | 8 / 0 | 8 / 0 | 8 / 0 | 8 / 0 |
| G1 illustrative assignment | 10 / 1 | 10 / 1 | 14 / 0 | 10 / 0 |
| G2 illustrative merge counterexample | 13 / 6 | 13 / 2 | 14 / 0 | 13 / 2 |

The G0 and G1 LR(0)/SLR(1) values above come from the existing checker; its
new LR(1) functions also computed G0's CLR/LALR entries. G2's LR(0)/SLR(1)
values were computed with the same existing LR(0) functions for this
comparison. Counts refer to **conflicting ACTION cells**, not the number of
candidate pairs inside them. The zero-conflict canonical G2 table shows
that LALR merging can lose information needed to choose a reduction, even
though it does not change the grammar's strings. G1 shows the opposite
outcome: local LR(1) lookaheads remove the global-FOLLOW SLR conflict, and
its core merges retain that distinction where needed.

Verification uses hand-derived G1 `I0/I4` and G2 `I1/I2/I4/I7` checkpoints;
fixed-point FIRST including nullable suffixes; regenerated GOTO edges and
same-core checks; ACTION entries verified against completed items and their
lookaheads; explicit conflict retention and classification; and traces
replayed from the generated tables. Focused tests also preserve the 04D
LR(0)/SLR results and compare this document's generated sections with a fresh
calculation. The checker is a small educational driver for G0–G2, not an
implementation of Sparq's full compiler. It does not resolve G2's LALR
conflicts or infer any program semantics.

For a viva, derive `FIRST(= R $)`, the G1 `I4` item lookaheads, and the
absence of `r5` under `=`; derive G2's `I4/I7` items and demonstrate why
both reductions enter each `J4` conflict cell; trace one G1 reduction with
its stack pops and GOTO; explain canonical versus merged state counts; and
distinguish the illustrative grammars from the frozen Sparq grammar and its
recursive-descent parser.
