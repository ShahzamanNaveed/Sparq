# Sparq parser theory demonstrations — M3 Task 04C

## Purpose and boundaries

The production Sparq compiler uses recursive descent. The authoritative syntax
is the unchanged BNF in [SPARQ_LANGUAGE_SPEC.md](SPARQ_LANGUAGE_SPEC.md), §6;
its complete FIRST, FOLLOW, SELECT, and LL(1) analysis is in
[LL1_ANALYSIS.md](LL1_ANALYSIS.md). Every grammar labelled **illustrative** below
is a teaching example, not an extension to Sparq. `id` in such examples is a
generic identifier token. The arithmetic examples cover only `id`, `+`, `*`,
parentheses, and a separate end marker `$`; they are not Sparq's entire
expression grammar. No example executes a program.

The original semester assignment asks for left-recursion elimination, left
factoring, dangling-else resolution, operator-precedence parsing, and bottom-up
shift-reduce parsing. This chapter demonstrates those topics without adding a
second compiler or an LR-family parsing table.

## 1. Direct left recursion and its elimination

**Illustrative arithmetic grammar G₀** (start symbol `E`):

```text
L1  E → E + T | T
L2  T → T * F | F
L3  F → ( E ) | id
```

`E → E + T` and `T → T * F` are directly left recursive: their first
right-hand symbol is the same nonterminal as the left side. A naive procedure
for `E` that tries `E + T` first calls itself without consuming a token, and
may recurse indefinitely. For `A → A α₁ | … | A αₙ | β₁ | … | βₘ`, where no
`β` starts with `A` and every `α` is nonempty, the standard replacement is
`A → β₁ A′ | … | βₘ A′` and `A′ → α₁ A′ | … | αₙ A′ | ε`.

Applying it separately to `E` and `T` gives **illustrative G₁**:

```text
L1′ E  → T E′
L2′ E′ → + T E′ | ε
L3′ T  → F T′
L4′ T′ → * F T′ | ε
L5′ F  → ( E ) | id
```

`ε` consumes no token; it ends a repetition. Both grammars describe a `T`
followed by zero or more `+ T` groups, where each `T` is an `F` followed by
zero or more `* F` groups. For example, G₁ derives `id + id * id` by choosing
one `+ T` in `E′`, one `* F` in the second `T′`, then `ε` for both tails. It
derives `( id + id ) * id` by choosing `F → ( E )` for the first factor and
one `* F` after it.

| Token string | G₀ | G₁ | Reason |
|---|---|---|---|
| `id` | Accept | Accept | One factor; both tails empty in G₁. |
| `id + id * id` | Accept | Accept | A sum whose right term is a product. |
| `( id + id ) * id` | Accept | Accept | Parenthesized sum is a factor. |
| `id * id + id` | Accept | Accept | Product followed by another term. |
| `+ id` | Reject | Reject | No first factor. |
| `id + * id` | Reject | Reject | Missing factor after `+`. |

The algebraic transformation establishes the language relationship. As a
finite cross-check, an in-memory leftmost-derivation enumerator generated all
terminal strings of at most seven tokens from each grammar (with a 20-symbol
intermediate-form cap): both produced the same 60 strings. This finite check is
not a proof of equality for all lengths.

G₀ and G₁ have different derivation-tree shapes. The right-recursive G₁ tails
do **not** automatically produce left-associated ASTs. Sparq's frozen grammar
already uses non-left-recursive `<add-tail>` and `<mul-tail>` repetitions. Its
production parser's `_parse_add()` and `_parse_mul()` loops fold each new
operand into the accumulated left AST, so `a + b + c` becomes `(a + b) + c`.
The same approach is used for repeated `AND` and `OR` tails. No transformation
to the frozen BNF is needed.

## 2. Left factoring

**Illustrative unfactored identifier statement** (here `E` means an expression
and `ArgsOpt` means an optional argument list):

```text
U1  Stmt → id = E ;
U2       | id [ E ] = E ;
U3       | id ( ArgsOpt ) ;
```

All three alternatives begin with `id`. On one-token lookahead `id`, a
predictive parser cannot choose among U1–U3. Factoring the shared prefix gives
an equivalent **illustrative** grammar:

```text
V1  Stmt     → id StmtTail
V2  StmtTail → = E ;
V3           | [ E ] = E ;
V4           | ( ArgsOpt ) ;
```

After consuming `id`, the next token is respectively `=`, `[`, or `(`. These
three FIRST sets are disjoint, so one-token selection now succeeds. Expanding
V1 with V2, V3, or V4 reproduces exactly U1, U2, or U3; factoring neither
adds nor removes a statement form.

This is the same shape as the **frozen Sparq** productions
`<identifier-statement> ::= IDENTIFIER <identifier-statement-tail>` and
`<identifier-statement-tail> ::= "=" <expression> ";" | "[" <expression>
"]" "=" <expression> ";" | "(" <arguments-opt> ")" ";"`.
Consequently `x = 1;`, `x[0] = 2;`, and `f();` are syntactically valid
identifier-led forms; `x[] = 1;` is invalid because the index expression is
missing. Name and type validity are later semantic questions. The parser
consumes the identifier once and chooses a call on `(` or an assignment on
`=`/`[`. It has not been changed by this example.

## 3. Dangling else

The following is an **illustrative ambiguous grammar**, not Sparq syntax:

```text
D1  Stmt → IF ( cond ) Stmt
D2       | IF ( cond ) Stmt ELSE Stmt
D3       | other
```

For `IF(c₁) IF(c₂) other ELSE other`, two structures are possible:

```text
Nearest unmatched IF: IF(c₁, IF(c₂, other, other), no-else)
Outer IF:             IF(c₁, IF(c₂, other, no-else), other)
```

The conventional policy for unbraced conditionals attaches `ELSE` to the
nearest unmatched `IF`. An extra rule or grammar transformation is needed to
enforce that policy for D1–D3.

**Sparq instead requires blocks.** Its actual rules are
`<if-statement> ::= WHEN "(" <expression> ")" <block> <else-opt>` and
`<else-opt> ::= OTHERWISE <block> | ε`, where `<block>` is `{ ... }`. These
two complete Sparq programs have different, explicit brace structures:

**A. `OTHERWISE` belongs to the inner `WHEN`:**

```sparq
START {
    WHEN (TRUE) {
        WHEN (FALSE) { SHOW(1); }
        OTHERWISE { SHOW(2); }
    }
}
```

```text
outer WHEN
├─ then block: inner WHEN
│  ├─ then block: SHOW(1)
│  └─ OTHERWISE block: SHOW(2)
└─ no OTHERWISE
```

**B. `OTHERWISE` belongs to the outer `WHEN`:**

```sparq
START {
    WHEN (TRUE) {
        WHEN (FALSE) { SHOW(1); }
    } OTHERWISE { SHOW(2); }
}
```

```text
outer WHEN
├─ then block: inner WHEN
│  ├─ then block: SHOW(1)
│  └─ no OTHERWISE
└─ OTHERWISE block: SHOW(2)
```

In A, `OTHERWISE` follows the inner `WHEN`'s closing block brace, so the
inner `<else-opt>` consumes it. In B, the next token after the inner block is
the outer block's `}`; the inner `<else-opt>` takes `ε`. The outer block then
closes, and the outer `<else-opt>` consumes `OTHERWISE`. Braces, not indentation,
fix both attachments. The existing lexer and parser were run on these exact
programs: A produced `inner.else_block` present and `outer.else_block` absent;
B produced the reverse. An unbraced `WHEN (TRUE) SHOW(1);` was rejected.

## 4. Formal operator-precedence grammar

Return to **illustrative G₀**, now numbered for reductions:

```text
O1  E → E + T
O2  E → T
O3  T → T * F
O4  T → F
O5  F → ( E )
O6  F → id
```

G₀ is an operator grammar: every right-hand side is nonempty and no right-hand
side contains adjacent nonterminals. The unit rules O2 and O4 are permitted by
those restrictions, but require care during handle recognition. This is an
illustrative arithmetic grammar, not Sparq's complete expression grammar.

### FIRSTVT and LASTVT

`FIRSTVT(A)` contains terminals that can be first in a string derived from A,
or immediately follow an initial nonterminal in a production of A. Likewise,
`LASTVT(A)` includes possible final terminals and terminals immediately before
a final nonterminal. These are **not** ordinary FIRST and FOLLOW sets. In
particular, `+ ∈ FIRSTVT(E)` because of `E → E + T`, even though no valid
expression begins with `+`.

Initialize from right-hand-side boundary terminals and adjacent
nonterminal/terminal pairs, then propagate through leading/trailing unit or
nonterminal occurrences until no set changes. For example, O1 puts `+` in
`FIRSTVT(E)` and `LASTVT(E)`; O3 puts `*` in both sets for `T`; O5 puts `(`
in `FIRSTVT(F)` and `)` in `LASTVT(F)`; O6 puts `id` in both for `F`.

| Nonterminal | FIRSTVT | LASTVT |
|---|---|---|
| `F` | `{ (, id }` | `{ ), id }` |
| `T` | `{ (, *, id }` | `{ ), *, id }` |
| `E` | `{ (, *, +, id }` | `{ ), *, +, id }` |

For a production containing adjacent terminals `a b`, set `a ≐ b`.
For `a B b`, set `a ≐ b`. For `a B`, set `a ⋖ t` for every
`t ∈ FIRSTVT(B)`. For `B a`, set `t ⋗ a` for every
`t ∈ LASTVT(B)`. Here `⋖` means *yields precedence* (shift toward a handle),
`≐` means *same handle boundary* (shift), and `⋗` means *takes precedence*
(reduce a handle). For the single end marker `$`, add `$ ⋖ FIRSTVT(E)`,
`LASTVT(E) ⋗ $`, and `$ ≐ $` for final acceptance. Preserve all relations in
each ordered terminal pair; a pair with more than one relation is a conflict.

The complete non-boundary sources are:

| Production | Relations it contributes |
|---|---|
| O1 `E → E + T` | `LASTVT(E) ⋗ +`; `+ ⋖ FIRSTVT(T)` |
| O3 `T → T * F` | `LASTVT(T) ⋗ *`; `* ⋖ FIRSTVT(F)` |
| O5 `F → ( E )` | `( ⋖ FIRSTVT(E)`; `( ≐ )`; `LASTVT(E) ⋗ )` |
| O2, O4, O6 | No adjacent-terminal relation; their effects propagate through FIRSTVT/LASTVT. |

### Complete operator-precedence relation table

Rows are the rightmost terminal on the stack (skip any nonterminal); columns
are the next input terminal. `⋖` and `≐` shift; `⋗` reduces. `—` is undefined
and signals an error if reached. This is **not** Sparq's LL(1) table.

| Stack terminal \ Input | `id` | `+` | `*` | `(` | `)` | `$` |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `id` | — | ⋗ | ⋗ | — | ⋗ | ⋗ |
| `+` | ⋖ | ⋗ | ⋖ | ⋖ | ⋗ | ⋗ |
| `*` | ⋖ | ⋗ | ⋗ | ⋖ | ⋗ | ⋗ |
| `(` | ⋖ | ⋖ | ⋖ | ⋖ | ≐ | — |
| `)` | — | ⋗ | ⋗ | — | ⋗ | ⋗ |
| `$` | ⋖ | ⋖ | ⋖ | ⋖ | — | ≐ |

The calculation gives **30 populated ordered pairs, 6 undefined pairs, and
zero conflicting pairs**, so G₀ also meets the unique-relation requirement
for an operator-precedence grammar. For instance `+ ⋖ *` follows O1 because
`* ∈ FIRSTVT(T)`, while `* ⋗ +` follows O1 because `* ∈ LASTVT(E)`.
`( ≐ )` follows O5 directly. An undefined cell such as `id` followed by `id`
is a syntax error. A defined relation does not by itself prove an entire input
valid: the candidate handle must also match a grammar production.

### Why the former traces needed external choices

After reducing `id` by O6, the grammar also permits O4 (`T → F`) and
O2 (`E → T`). A terminal precedence relation identifies a handle boundary;
it has no information about which of these unit rules to apply. The former
tables selected `F`, `T`, or `E` for each `id` using knowledge of the
intended derivation. Those choices were valid for the examples, but the
relation table alone did not make the procedure reproducible. Applying every
promotion destructively would also lose a category needed by `T * F`.

### Deterministic operator-precedence recognition with unit closure

[The educational recognizer](../tools/operator_precedence.py) uses **the same
illustrative O1–O6 grammar and the relation table above**. It does not use
Sparq's production parser. Its stack contains terminals and a category set
for each reduced substring. For example, reducing `id` by O6 gives `{F}`;
the fixed-point closure of O4 and O2 gives `{F,T,E}`. Every available
category is retained. A set is a compact record of possible grammar
derivations for that substring, not a new grammar symbol or a choice of parse
tree. In the trace tables, `[F/T/E]` denotes this set.

At each step, compare the rightmost stack terminal with the next input
terminal. `<` and `=` shift; `>` locates the rightmost handle boundary by
scanning stack terminals leftward to the nearest `<`, passing any `=` or
`>` relations. Match that exact stack suffix against **every non-unit
production** O1, O3, O5, and O6. A nonterminal position matches when its
required category belongs to the suffix's category set. Collect all matching
left sides, then repeatedly apply the unit rules O4 and O2 until no category
is added. Replace the handle with that complete category set. If no
production matches, reject. An undefined relation also rejects. Accept only
when the input is `$` and the stack is `$ [categories]` with `E` present.

The precedence relation chooses each shift or reduction boundary; grammar
matching and unit closure validate the reduction. No unit promotion or
competing production is chosen silently. This is a deterministic
**recognizer**, not an AST constructor: it retains all derivable categories
instead of selecting one parse tree. The source grammar has no empty
productions or adjacent nonterminals; its 30 relation cells have no conflicts.
These facts make it an operator-precedence grammar. The four traces below
are generated from actual stack operations by the educational utility;
`python -m tools.operator_precedence --check-doc` checks them without
rewriting the document.

The category-set rule is sound by induction over reductions: a direct rule
adds its left side only when its terminal symbols and child categories match
the recognized handle; unit closure adds a category only when a listed unit
rule derives the previous category. Thus every retained category has a
grammar derivation for that reduced substring. The precedence relations
determine handle boundaries. Finite tests below additionally check the
recognizer against independent short derivations; they are not a proof that
every possible valid string will be recognized.

### Complete operator-precedence traces

The stack top is on the right. Trace symbols `<`, `=`, and `>` denote the
table's `⋖`, `≐`, and `⋗` relations. Each row records the stack and remaining
input **before** its action. A reduction row gives the exact terminal-bound handle
and all applied rule IDs. `O6, O4, O2` means O6 matched the handle, followed
by exhaustive unit closure. `$` is the analysis end marker.

<!-- Computed operator-precedence traces: start -->
#### Valid A: `id + id * id`

| Step | Stack | Remaining input | Comparison | Action | Handle | Rules |
|---:|---|---|---|---|---|---|
| 1 | `$` | `id + id * id $` | `$ < id` | shift id | — | — |
| 2 | `$ id` | `+ id * id $` | `id > +` | reduce | `id` | O6, O4, O2 |
| 3 | `$ [F/T/E]` | `+ id * id $` | `$ < +` | shift + | — | — |
| 4 | `$ [F/T/E] +` | `id * id $` | `+ < id` | shift id | — | — |
| 5 | `$ [F/T/E] + id` | `* id $` | `id > *` | reduce | `id` | O6, O4, O2 |
| 6 | `$ [F/T/E] + [F/T/E]` | `* id $` | `+ < *` | shift * | — | — |
| 7 | `$ [F/T/E] + [F/T/E] *` | `id $` | `* < id` | shift id | — | — |
| 8 | `$ [F/T/E] + [F/T/E] * id` | `$` | `id > $` | reduce | `id` | O6, O4, O2 |
| 9 | `$ [F/T/E] + [F/T/E] * [F/T/E]` | `$` | `* > $` | reduce | `[F/T/E] * [F/T/E]` | O3, O2 |
| 10 | `$ [F/T/E] + [T/E]` | `$` | `+ > $` | reduce | `[F/T/E] + [T/E]` | O1 |
| 11 | `$ [E]` | `$` | `$ = $` | accept | — | — |

Result: **accepted**.

#### Valid B: `( id + id ) * id`

| Step | Stack | Remaining input | Comparison | Action | Handle | Rules |
|---:|---|---|---|---|---|---|
| 1 | `$` | `( id + id ) * id $` | `$ < (` | shift ( | — | — |
| 2 | `$ (` | `id + id ) * id $` | `( < id` | shift id | — | — |
| 3 | `$ ( id` | `+ id ) * id $` | `id > +` | reduce | `id` | O6, O4, O2 |
| 4 | `$ ( [F/T/E]` | `+ id ) * id $` | `( < +` | shift + | — | — |
| 5 | `$ ( [F/T/E] +` | `id ) * id $` | `+ < id` | shift id | — | — |
| 6 | `$ ( [F/T/E] + id` | `) * id $` | `id > )` | reduce | `id` | O6, O4, O2 |
| 7 | `$ ( [F/T/E] + [F/T/E]` | `) * id $` | `+ > )` | reduce | `[F/T/E] + [F/T/E]` | O1 |
| 8 | `$ ( [E]` | `) * id $` | `( = )` | shift ) | — | — |
| 9 | `$ ( [E] )` | `* id $` | `) > *` | reduce | `( [E] )` | O5, O4, O2 |
| 10 | `$ [F/T/E]` | `* id $` | `$ < *` | shift * | — | — |
| 11 | `$ [F/T/E] *` | `id $` | `* < id` | shift id | — | — |
| 12 | `$ [F/T/E] * id` | `$` | `id > $` | reduce | `id` | O6, O4, O2 |
| 13 | `$ [F/T/E] * [F/T/E]` | `$` | `* > $` | reduce | `[F/T/E] * [F/T/E]` | O3, O2 |
| 14 | `$ [T/E]` | `$` | `$ = $` | accept | — | — |

Result: **accepted**.

#### Valid C: `id * id + id`

| Step | Stack | Remaining input | Comparison | Action | Handle | Rules |
|---:|---|---|---|---|---|---|
| 1 | `$` | `id * id + id $` | `$ < id` | shift id | — | — |
| 2 | `$ id` | `* id + id $` | `id > *` | reduce | `id` | O6, O4, O2 |
| 3 | `$ [F/T/E]` | `* id + id $` | `$ < *` | shift * | — | — |
| 4 | `$ [F/T/E] *` | `id + id $` | `* < id` | shift id | — | — |
| 5 | `$ [F/T/E] * id` | `+ id $` | `id > +` | reduce | `id` | O6, O4, O2 |
| 6 | `$ [F/T/E] * [F/T/E]` | `+ id $` | `* > +` | reduce | `[F/T/E] * [F/T/E]` | O3, O2 |
| 7 | `$ [T/E]` | `+ id $` | `$ < +` | shift + | — | — |
| 8 | `$ [T/E] +` | `id $` | `+ < id` | shift id | — | — |
| 9 | `$ [T/E] + id` | `$` | `id > $` | reduce | `id` | O6, O4, O2 |
| 10 | `$ [T/E] + [F/T/E]` | `$` | `+ > $` | reduce | `[T/E] + [F/T/E]` | O1 |
| 11 | `$ [E]` | `$` | `$ = $` | accept | — | — |

Result: **accepted**.

#### Invalid: `id + * id`

| Step | Stack | Remaining input | Comparison | Action | Handle | Rules |
|---:|---|---|---|---|---|---|
| 1 | `$` | `id + * id $` | `$ < id` | shift id | — | — |
| 2 | `$ id` | `+ * id $` | `id > +` | reduce | `id` | O6, O4, O2 |
| 3 | `$ [F/T/E]` | `+ * id $` | `$ < +` | shift + | — | — |
| 4 | `$ [F/T/E] +` | `* id $` | `+ < *` | shift * | — | — |
| 5 | `$ [F/T/E] + *` | `id $` | `* < id` | shift id | — | — |
| 6 | `$ [F/T/E] + * id` | `$` | `id > $` | reduce | `id` | O6, O4, O2 |
| 7 | `$ [F/T/E] + * [F/T/E]` | `$` | `* > $` | error: invalid handle | `* [F/T/E]` | — |

Result: **rejected**.
<!-- Computed operator-precedence traces: end -->

The first trace reduces `T * F` by O3 before `E + T` by O1, producing
`id + (id * id)`. The third reduces the product before shifting the outer
addition, producing `(id * id) + id`. These are precedence-recognition
results, separate from the actual Sparq grammar and recursive-descent AST.
A finite expression matrix in the focused tests covers repeated operators,
nested parentheses, invalid handles, and undefined relations; those tests
do not by themselves prove correctness for every possible input.

## 5. Separate general shift-reduce demonstration

This **illustrative grammar H** has start symbol `S` and does not involve the
operator-precedence table:

```text
H1  S → a S b
H2  S → a b
```

A **shift** moves the next input token onto the right end of the stack. A
**handle** is a stack suffix corresponding to the right-hand side used at that
point of a rightmost derivation. A **reduce** replaces that handle with the
rule's left side. **Accept** requires the start symbol and consumed input;
**error** means no valid continuation or handle exists. `$` is the end marker.

| Step | Stack before action | Remaining input | Action and handle |
|---:|---|---|---|
| 1 | `$` | `a a b b $` | Shift `a`. |
| 2 | `$ a` | `a b b $` | Shift `a`. |
| 3 | `$ a a` | `b b $` | Shift `b`. |
| 4 | `$ a a b` | `b $` | Reduce handle `a b` by H2 `S → a b`; stack becomes `$ a S`. |
| 5 | `$ a S` | `b $` | Shift `b`. |
| 6 | `$ a S b` | `$` | Reduce handle `a S b` by H1 `S → a S b`; stack becomes `$ S`. |
| 7 | `$ S` | `$` | Accept. |

The rightmost derivation is `S ⇒ a S b ⇒ a a b b`; the two reductions reverse
it. This is a hand-selected, valid handle-pruning trace, **not** an LR action
table or a claim that arbitrary shift/reduce choices are deterministic.

For invalid `a a b $`, shift `a`, shift `a`, shift `b`, then reduce the final
`a b` by H2. The stack is `$ a S` with `$` next. It is neither `$ S` nor a
suffix matching H1 or H2, and there is no token left to shift: **error**.

## 6. Connection to the actual Sparq compiler

| Topic | Frozen Sparq grammar and implementation | Role of this example |
|---|---|---|
| Left recursion | The expression BNF already uses non-left-recursive tails; the parser uses loops and constructs left-associated AST nodes. | G₀ → G₁ illustrates a transformation without changing Sparq. |
| Left factoring | `IDENTIFIER <identifier-statement-tail>` is already factored; the parser decides after consuming the name. | U → V explains that predictive choice. |
| Dangling else | `WHEN` and `OTHERWISE` require brace-delimited blocks; the parser stores either an inner or outer `else_block` according to braces. | D1–D3 show the ambiguity that mandatory blocks avoid. |
| Operator precedence | Sparq has more operators and precedence levels, encoded by its LL(1) expression nonterminals and recursive-descent methods. | G₀'s FIRSTVT/LASTVT table and bottom-up traces teach a different parsing technique. |
| Shift-reduce | The production compiler does not use a bottom-up parsing stack. | H shows handles and reductions on a small grammar. |

Grammar recognition, AST construction, name/type analysis, and execution are
different activities. These teaching traces recognize illustrative token
strings and do not implement Sparq parsing, semantics, TAC, or a VM.

## 7. Verification, limits, and viva checklist

- G₀/G₁ equivalence was checked algebraically through `T (+ T)*` and
  `F (* F)*`, then cross-checked by bounded enumeration of 60 strings up to
  seven tokens. G₁'s two valid derivations and two invalid examples were
  inspected separately.
- Factoring was checked by distributing V1 over V2–V4 and comparing each
  resulting right-hand side to U1–U3. The actual Sparq productions were read
  from the frozen BNF; valid/invalid forms were checked with the existing
  parser without modifying it.
- Both `WHEN` examples were tokenized and parsed. Their AST `else_block`
  placement matched the displayed brace structure; an unbraced variant was
  rejected.
- The separate educational recognizer computes FIRSTVT/LASTVT to a fixed
  point and retains **all** relation candidates per cell. It finds 30
  populated cells and zero conflicts. It generates all four complete traces
  above using stack actions and exhaustive unit closure; focused tests check
  the relation table, hand-derived handles, a varied expression matrix, 60
  bounded strings independently generated from G₀, and all 3,906 token
  strings of length at most five over the example alphabet. This utility is not
  part of the production Sparq compiler.
- H's reductions were checked against the displayed rightmost derivation;
  the invalid stack has neither an accepting state nor a valid handle.
- Finite examples do not prove full grammar equivalence or correctness for all
  possible inputs. The category-set closure gives a reproducible recognition
  rule for unit productions, but does not choose a unique parse tree. None of
  these demonstrations establishes correctness of the production Sparq parser;
  the accepted 04B LL(1) analysis addresses Sparq's predictive grammar choices.

For a viva, be able to reproduce the G₀ → G₁ rewrite and explain `ε`; factor
the `id` prefix; draw both `OTHERWISE` attachments using braces; derive
`FIRSTVT(T)` and `LASTVT(E)`; derive `+ ⋖ *`, `* ⋗ +`, and `( ≐ )` from O1/O5;
walk each terminal comparison and exact handle in the four traces; derive the
`{F,T,E}` closure after `id`; explain why `id + * id` fails at `* [F/T/E]`;
and reverse H's rightmost derivation. Explain
why none of these demonstrations executes Sparq source.

### References consulted

- The supplied `Semester Project.pdf`, Phase 3, for the required parser-theory topics (kept outside this repository).
- University of Maryland, [CMSC 430 parsing lecture slides](https://www.cs.umd.edu/class/spring2017/cmsc430/slides/03-lexing-parsing.pdf), for a conceptual cross-check of handles and shift/reduce actions.
- University at Buffalo, [CSE 443 parsing lecture slides](https://cse.buffalo.edu/faculty/alphonce/SP24/CSE443/slides/lec09.pdf), for the distinction between a matching right-hand side and a valid handle.
- University of Chicago, [operator-precedence parsing notes](https://people.cs.uchicago.edu/~jhr/courses/w2004-51086/docs/notes-04.pdf), for the operator-grammar restriction and terminal-boundary scan. The category-set unit closure above is this project's explicit recognition procedure.

All grammars, calculations, tables, traces, and explanations in this chapter
were prepared for this Sparq checkpoint; no external passage was copied.
