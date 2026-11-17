# Sparq LL(1) grammar analysis — M3 Task 04B

## Scope and source of truth

This document analyzes the **unchanged** `~~~bnf` block in
[SPARQ_LANGUAGE_SPEC.md](SPARQ_LANGUAGE_SPEC.md), section 6. It is a formal
grammar exercise, separate from Sparq source execution, type checking, and AST
construction. The production IDs, inventories, sets, sparse table, conflict
counts, and traces below are generated deterministically by
`python -m tools.ll1_analysis --write-doc`. Run
`python -m tools.ll1_analysis --check-doc` to check that this computed section
matches the current frozen BNF without writing files.

The utility extracts only the uniquely tagged BNF fence. It joins continued
right-hand sides, splits alternatives at unquoted `|`, keeps quoted punctuation
as terminal symbols, and stores each explicit `ε` alternative as an empty
right-hand side. The inventory gives each alternative an ID in source order and
its starting source line. This avoids a separately maintained transcription.
The fence hash and spot checks of multiline `<function>` and `<switch-statement>`
productions, same-line `<type>` alternatives, and epsilon alternatives make the
extraction auditable. The parser's Python implementation was not used to choose
grammar productions.

## Notation and calculations

Angle-bracketed names are nonterminals. Uppercase words and quoted punctuation
in the BNF are terminals; the tables display punctuation without quotes. `ε`
means the empty string and is **not** a terminal. `EOF` is an actual Sparq token
required by `<program>`. `$` is an additional conceptual end-of-input marker
used by FOLLOW and the predictive trace. The trace stack is shown with its top
at the **right**.

`nullable(A)` means that A derives `ε`. Start with the left sides of explicit
empty alternatives; repeatedly add A when every symbol of one of A's right
sides is nullable. `FIRST(α)` contains terminals that can begin strings derived
from α and contains `ε` if α can vanish. Scan a sequence from left to right:
include each symbol's FIRST terminals, continuing only while that symbol is
nullable. For each occurrence `A → α B β`, add `FIRST(β) − {ε}` to FOLLOW(B);
when β is nullable, also add FOLLOW(A). Initialize FOLLOW(`<program>`) with
`$`. No FOLLOW set contains `ε` because FOLLOW describes **following tokens**,
not an empty derivation. Iterate FIRST and FOLLOW until no set changes.

For every alternative `A → α`, SELECT is `FIRST(α) − {ε}` plus FOLLOW(A)
when α is nullable. Each terminal in SELECT enters `M[A, terminal]`. A cell with
two distinct production IDs is an LL(1) conflict. Unlisted cells are errors.
The program start symbol and every alternative are listed below; these counts
are calculated, not inserted as historical expected values.

## Worked calculations from the frozen productions

1. `<function-list> → <function> <function-list> | ε` begins with `FUNC` in its
   nonempty branch, so `FIRST(<function-list>) = {FUNC, ε}`. In
   `<program> → <function-list> START <block> EOF`, the next terminal is
   `START`, hence `FOLLOW(<function-list>) = {START}`. The empty branch is
   selected on `START`, never on `FUNC`.
2. `<statement-list> → <statement> <statement-list> | ε` has the following
   15 statement-start terminals: `INT`, `FLOAT`, `CHAR`, `STRING`, `BOOL`,
   `IDENTIFIER`, `WHEN`, `SELECT`, `REPEAT`, `WHILE`, `DO`, `SHOW`, `READ`,
   `RETURN`, or `{`. The empty branch contributes `ε`. The enclosing
   `<block> → "{" <statement-list> "}"` gives
   `FOLLOW(<statement-list>) = {"}"}`. Thus `}` chooses its empty branch.
3. `<declaration-tail> → "=" <expression> | "[" INT_LITERAL "]"
   <array-init-opt> | ε` gives `FIRST = {"=", "[", ε}`. In
   `<declaration> → <type> IDENTIFIER <declaration-tail> ";"`, the tail is
   followed directly by `;`, so `FOLLOW = {";"}`. These three lookaheads
   distinguish scalar initialization, array declaration, and a bare scalar.
4. `<expression> → <or-expression>` ultimately begins at `<primary>` or a
   unary prefix. Its FIRST terminals are `INT_LITERAL`, `FLOAT_LITERAL`,
   `CHAR_LITERAL`, `STRING_LITERAL`, `TRUE`, `FALSE`, `IDENTIFIER`, `(`,
   `NOT`, and `-`. Its leading unary or primary path cannot disappear, so
   `ε` is absent from `FIRST(<expression>)`.
5. `<or-tail> → OR <and-expression> <or-tail> | ε` has
   `FIRST = {OR, ε}`. Since it ends `<or-expression>`, FOLLOW(`<or-tail>`)
   receives FOLLOW(`<or-expression>`). Since `<expression>` consists only of
   `<or-expression>`, both inherit expression-ending tokens: `)`, `,`, `;`,
   `]`, and `}`. An `OR` continues the expression; one of those following
   tokens chooses ε.

The same suffix rules explain `FOLLOW(<params-opt>) = {")"}` from `<function>`,
`FOLLOW(<return-value-opt>) = {";"}` from `<return-statement>`, and
`FOLLOW(<else-opt>) = FOLLOW(<if-statement>)`. The latter contains statement
starters and `}`, because a WHEN statement can be followed by another
statement or end its block. It does **not** contain `OTHERWISE`; that token
selects the nonempty else branch. These explanations are manual derivations;
the complete sets below are the utility's computed results.

<!-- Computed grammar analysis: start -->
## Computed grammar inventory

BNF fence SHA-256 (UTF-8, normalized newlines): `6e37723f60006033a13fc0f8fcc7082f37be7c3ea8e86e89254b4ef0da67e268`.
Start symbol: `<program>`. Distinct nonterminals: **55**. Production alternatives: **117**. Distinct grammar terminals: **52**.

Nonterminals in first-definition order: `<program>`, `<function-list>`, `<function>`, `<return-type>`, `<type>`, `<params-opt>`, `<param-list>`, `<param-tail>`, `<param>`, `<block>`, `<statement-list>`, `<statement>`, `<declaration>`, `<declaration-tail>`, `<array-init-opt>`, `<identifier-statement>`, `<identifier-statement-tail>`, `<return-statement>`, `<return-value-opt>`, `<if-statement>`, `<else-opt>`, `<switch-statement>`, `<case-list>`, `<case-clause>`, `<default-opt>`, `<case-literal>`, `<for-statement>`, `<for-init>`, `<for-condition>`, `<for-update>`, `<assignment-core>`, `<index-opt>`, `<while-statement>`, `<do-while-statement>`, `<show-statement>`, `<read-statement>`, `<expression>`, `<or-expression>`, `<or-tail>`, `<and-expression>`, `<and-tail>`, `<equality-expression>`, `<equality-tail>`, `<comparison-expression>`, `<comparison-tail>`, `<add-expression>`, `<add-tail>`, `<mul-expression>`, `<mul-tail>`, `<unary-expression>`, `<primary>`, `<primary-suffix>`, `<arguments-opt>`, `<arguments>`, `<argument-tail>`.

Terminals: `!=`, `%`, `(`, `)`, `*`, `+`, `,`, `-`, `->`, `/`, `:`, `;`, `<`, `<=`, `=`, `==`, `>`, `>=`, `AND`, `BOOL`, `CASE`, `CHAR`, `CHAR_LITERAL`, `DEFAULT`, `DO`, `EOF`, `FALSE`, `FLOAT`, `FLOAT_LITERAL`, `FUNC`, `IDENTIFIER`, `INT`, `INT_LITERAL`, `NOT`, `OR`, `OTHERWISE`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `START`, `STRING`, `STRING_LITERAL`, `TRUE`, `VOID`, `WHEN`, `WHILE`, `[`, `]`, `{`, `}`.

The explicit `EOF` is a grammar terminal. The conceptual `$` is separate and occurs only as the end marker and in FOLLOW sets.

Integrity checks: undefined ∅; unreachable ∅; unproductive ∅; duplicate production-ID pairs none.

## Nullable fixed point

Initial set = left sides of explicit ε alternatives. Each later round adds A when every symbol of one of A's right sides is already nullable. Terminals never become nullable.

- Round 0: add { `<add-tail>`, `<and-tail>`, `<argument-tail>`, `<arguments-opt>`, `<array-init-opt>`, `<case-list>`, `<comparison-tail>`, `<declaration-tail>`, `<default-opt>`, `<else-opt>`, `<equality-tail>`, `<for-condition>`, `<for-init>`, `<for-update>`, `<function-list>`, `<index-opt>`, `<mul-tail>`, `<or-tail>`, `<param-tail>`, `<params-opt>`, `<primary-suffix>`, `<return-value-opt>`, `<statement-list>` }; cumulative { `<add-tail>`, `<and-tail>`, `<argument-tail>`, `<arguments-opt>`, `<array-init-opt>`, `<case-list>`, `<comparison-tail>`, `<declaration-tail>`, `<default-opt>`, `<else-opt>`, `<equality-tail>`, `<for-condition>`, `<for-init>`, `<for-update>`, `<function-list>`, `<index-opt>`, `<mul-tail>`, `<or-tail>`, `<param-tail>`, `<params-opt>`, `<primary-suffix>`, `<return-value-opt>`, `<statement-list>` }.

Final nullable count: **23**.

## Complete FIRST and FOLLOW sets

FIRST includes ε exactly for nullable nonterminals. FOLLOW never includes ε.

| Nonterminal | FIRST | FOLLOW |
|---|---|---|
| `<program>` | { `FUNC`, `START` } | { `$` } |
| `<function-list>` | { `FUNC`, `ε` } | { `START` } |
| `<function>` | { `FUNC` } | { `FUNC`, `START` } |
| `<return-type>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING`, `VOID` } | { `{` } |
| `<type>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `IDENTIFIER`, `{` } |
| `<params-opt>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING`, `ε` } | { `)` } |
| `<param-list>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `)` } |
| `<param-tail>` | { `,`, `ε` } | { `)` } |
| `<param>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `)`, `,` } |
| `<block>` | { `{` } | { `BOOL`, `CASE`, `CHAR`, `DEFAULT`, `DO`, `EOF`, `FLOAT`, `FUNC`, `IDENTIFIER`, `INT`, `OTHERWISE`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `START`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<statement-list>` | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `ε` } | { `}` } |
| `<statement>` | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<declaration>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<declaration-tail>` | { `=`, `[`, `ε` } | { `;` } |
| `<array-init-opt>` | { `=`, `ε` } | { `;` } |
| `<identifier-statement>` | { `IDENTIFIER` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<identifier-statement-tail>` | { `(`, `=`, `[` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<return-statement>` | { `RETURN` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<return-value-opt>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE`, `ε` } | { `;` } |
| `<if-statement>` | { `WHEN` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<else-opt>` | { `OTHERWISE`, `ε` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<switch-statement>` | { `SELECT` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<case-list>` | { `CASE`, `ε` } | { `DEFAULT`, `}` } |
| `<case-clause>` | { `CASE` } | { `CASE`, `DEFAULT`, `}` } |
| `<default-opt>` | { `DEFAULT`, `ε` } | { `}` } |
| `<case-literal>` | { `-`, `CHAR_LITERAL`, `INT_LITERAL`, `STRING_LITERAL` } | { `:` } |
| `<for-statement>` | { `REPEAT` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<for-init>` | { `BOOL`, `CHAR`, `FLOAT`, `IDENTIFIER`, `INT`, `STRING`, `ε` } | { `;` } |
| `<for-condition>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE`, `ε` } | { `;` } |
| `<for-update>` | { `IDENTIFIER`, `ε` } | { `)` } |
| `<assignment-core>` | { `IDENTIFIER` } | { `)`, `;` } |
| `<index-opt>` | { `[`, `ε` } | { `)`, `=` } |
| `<while-statement>` | { `WHILE` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<do-while-statement>` | { `DO` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<show-statement>` | { `SHOW` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<read-statement>` | { `READ` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| `<expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `)`, `,`, `;`, `]`, `}` } |
| `<or-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `)`, `,`, `;`, `]`, `}` } |
| `<or-tail>` | { `OR`, `ε` } | { `)`, `,`, `;`, `]`, `}` } |
| `<and-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `)`, `,`, `;`, `OR`, `]`, `}` } |
| `<and-tail>` | { `AND`, `ε` } | { `)`, `,`, `;`, `OR`, `]`, `}` } |
| `<equality-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `)`, `,`, `;`, `AND`, `OR`, `]`, `}` } |
| `<equality-tail>` | { `!=`, `==`, `ε` } | { `)`, `,`, `;`, `AND`, `OR`, `]`, `}` } |
| `<comparison-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `!=`, `)`, `,`, `;`, `==`, `AND`, `OR`, `]`, `}` } |
| `<comparison-tail>` | { `<`, `<=`, `>`, `>=`, `ε` } | { `!=`, `)`, `,`, `;`, `==`, `AND`, `OR`, `]`, `}` } |
| `<add-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `!=`, `)`, `,`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| `<add-tail>` | { `+`, `-`, `ε` } | { `!=`, `)`, `,`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| `<mul-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `!=`, `)`, `+`, `,`, `-`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| `<mul-tail>` | { `%`, `*`, `/`, `ε` } | { `!=`, `)`, `+`, `,`, `-`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| `<unary-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `!=`, `%`, `)`, `*`, `+`, `,`, `-`, `/`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| `<primary>` | { `(`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `STRING_LITERAL`, `TRUE` } | { `!=`, `%`, `)`, `*`, `+`, `,`, `-`, `/`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| `<primary-suffix>` | { `(`, `[`, `ε` } | { `!=`, `%`, `)`, `*`, `+`, `,`, `-`, `/`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| `<arguments-opt>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE`, `ε` } | { `)` } |
| `<arguments>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `)`, `}` } |
| `<argument-tail>` | { `,`, `ε` } | { `)`, `}` } |

## Alternatives and complete SELECT sets

Each P identifier follows the exact alternative order of the frozen BNF. The source line is the line where the alternative begins. SELECT(A → α) = FIRST(α) − {ε}, plus FOLLOW(A) when α is nullable.

| ID | Source line | Left side | Right side | FIRST(right side) | SELECT |
|---|---:|---|---|---|---|
| P001 | 56 | `<program>` | `<function-list> START <block> EOF` | { `FUNC`, `START` } | { `FUNC`, `START` } |
| P002 | 58 | `<function-list>` | `<function> <function-list>` | { `FUNC` } | { `FUNC` } |
| P003 | 59 | `<function-list>` | `ε` | { `ε` } | { `START` } |
| P004 | 61 | `<function>` | `FUNC IDENTIFIER "(" <params-opt> ")" "->" <return-type> <block>` | { `FUNC` } | { `FUNC` } |
| P005 | 64 | `<return-type>` | `<type>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } |
| P006 | 64 | `<return-type>` | `VOID` | { `VOID` } | { `VOID` } |
| P007 | 66 | `<type>` | `INT` | { `INT` } | { `INT` } |
| P008 | 66 | `<type>` | `FLOAT` | { `FLOAT` } | { `FLOAT` } |
| P009 | 66 | `<type>` | `CHAR` | { `CHAR` } | { `CHAR` } |
| P010 | 66 | `<type>` | `STRING` | { `STRING` } | { `STRING` } |
| P011 | 66 | `<type>` | `BOOL` | { `BOOL` } | { `BOOL` } |
| P012 | 68 | `<params-opt>` | `<param-list>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } |
| P013 | 68 | `<params-opt>` | `ε` | { `ε` } | { `)` } |
| P014 | 70 | `<param-list>` | `<param> <param-tail>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } |
| P015 | 72 | `<param-tail>` | `"," <param> <param-tail>` | { `,` } | { `,` } |
| P016 | 73 | `<param-tail>` | `ε` | { `ε` } | { `)` } |
| P017 | 75 | `<param>` | `<type> IDENTIFIER` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } |
| P018 | 77 | `<block>` | `"{" <statement-list> "}"` | { `{` } | { `{` } |
| P019 | 79 | `<statement-list>` | `<statement> <statement-list>` | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{` } |
| P020 | 80 | `<statement-list>` | `ε` | { `ε` } | { `}` } |
| P021 | 83 | `<statement>` | `<declaration>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } |
| P022 | 84 | `<statement>` | `<identifier-statement>` | { `IDENTIFIER` } | { `IDENTIFIER` } |
| P023 | 85 | `<statement>` | `<if-statement>` | { `WHEN` } | { `WHEN` } |
| P024 | 86 | `<statement>` | `<switch-statement>` | { `SELECT` } | { `SELECT` } |
| P025 | 87 | `<statement>` | `<for-statement>` | { `REPEAT` } | { `REPEAT` } |
| P026 | 88 | `<statement>` | `<while-statement>` | { `WHILE` } | { `WHILE` } |
| P027 | 89 | `<statement>` | `<do-while-statement>` | { `DO` } | { `DO` } |
| P028 | 90 | `<statement>` | `<show-statement>` | { `SHOW` } | { `SHOW` } |
| P029 | 91 | `<statement>` | `<read-statement>` | { `READ` } | { `READ` } |
| P030 | 92 | `<statement>` | `<return-statement>` | { `RETURN` } | { `RETURN` } |
| P031 | 93 | `<statement>` | `<block>` | { `{` } | { `{` } |
| P032 | 97 | `<declaration>` | `<type> IDENTIFIER <declaration-tail> ";"` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } |
| P033 | 100 | `<declaration-tail>` | `"=" <expression>` | { `=` } | { `=` } |
| P034 | 101 | `<declaration-tail>` | `"[" INT_LITERAL "]" <array-init-opt>` | { `[` } | { `[` } |
| P035 | 102 | `<declaration-tail>` | `ε` | { `ε` } | { `;` } |
| P036 | 105 | `<array-init-opt>` | `"=" "{" <arguments> "}"` | { `=` } | { `=` } |
| P037 | 106 | `<array-init-opt>` | `ε` | { `ε` } | { `;` } |
| P038 | 110 | `<identifier-statement>` | `IDENTIFIER <identifier-statement-tail>` | { `IDENTIFIER` } | { `IDENTIFIER` } |
| P039 | 113 | `<identifier-statement-tail>` | `"=" <expression> ";"` | { `=` } | { `=` } |
| P040 | 114 | `<identifier-statement-tail>` | `"[" <expression> "]" "=" <expression> ";"` | { `[` } | { `[` } |
| P041 | 115 | `<identifier-statement-tail>` | `"(" <arguments-opt> ")" ";"` | { `(` } | { `(` } |
| P042 | 119 | `<return-statement>` | `RETURN <return-value-opt> ";"` | { `RETURN` } | { `RETURN` } |
| P043 | 122 | `<return-value-opt>` | `<expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P044 | 123 | `<return-value-opt>` | `ε` | { `ε` } | { `;` } |
| P045 | 127 | `<if-statement>` | `WHEN "(" <expression> ")" <block> <else-opt>` | { `WHEN` } | { `WHEN` } |
| P046 | 130 | `<else-opt>` | `OTHERWISE <block>` | { `OTHERWISE` } | { `OTHERWISE` } |
| P047 | 131 | `<else-opt>` | `ε` | { `ε` } | { `BOOL`, `CHAR`, `DO`, `FLOAT`, `IDENTIFIER`, `INT`, `READ`, `REPEAT`, `RETURN`, `SELECT`, `SHOW`, `STRING`, `WHEN`, `WHILE`, `{`, `}` } |
| P048 | 135 | `<switch-statement>` | `SELECT "(" <expression> ")" "{" <case-list> <default-opt> "}"` | { `SELECT` } | { `SELECT` } |
| P049 | 140 | `<case-list>` | `<case-clause> <case-list>` | { `CASE` } | { `CASE` } |
| P050 | 141 | `<case-list>` | `ε` | { `ε` } | { `DEFAULT`, `}` } |
| P051 | 144 | `<case-clause>` | `CASE <case-literal> ":" <block>` | { `CASE` } | { `CASE` } |
| P052 | 147 | `<default-opt>` | `DEFAULT ":" <block>` | { `DEFAULT` } | { `DEFAULT` } |
| P053 | 148 | `<default-opt>` | `ε` | { `ε` } | { `}` } |
| P054 | 151 | `<case-literal>` | `INT_LITERAL` | { `INT_LITERAL` } | { `INT_LITERAL` } |
| P055 | 152 | `<case-literal>` | `"-" INT_LITERAL` | { `-` } | { `-` } |
| P056 | 153 | `<case-literal>` | `CHAR_LITERAL` | { `CHAR_LITERAL` } | { `CHAR_LITERAL` } |
| P057 | 154 | `<case-literal>` | `STRING_LITERAL` | { `STRING_LITERAL` } | { `STRING_LITERAL` } |
| P058 | 158 | `<for-statement>` | `REPEAT "(" <for-init> ";" <for-condition> ";" <for-update> ")" <block>` | { `REPEAT` } | { `REPEAT` } |
| P059 | 163 | `<for-init>` | `<type> IDENTIFIER "=" <expression>` | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } | { `BOOL`, `CHAR`, `FLOAT`, `INT`, `STRING` } |
| P060 | 164 | `<for-init>` | `<assignment-core>` | { `IDENTIFIER` } | { `IDENTIFIER` } |
| P061 | 165 | `<for-init>` | `ε` | { `ε` } | { `;` } |
| P062 | 168 | `<for-condition>` | `<expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P063 | 169 | `<for-condition>` | `ε` | { `ε` } | { `;` } |
| P064 | 172 | `<for-update>` | `<assignment-core>` | { `IDENTIFIER` } | { `IDENTIFIER` } |
| P065 | 173 | `<for-update>` | `ε` | { `ε` } | { `)` } |
| P066 | 176 | `<assignment-core>` | `IDENTIFIER <index-opt> "=" <expression>` | { `IDENTIFIER` } | { `IDENTIFIER` } |
| P067 | 179 | `<index-opt>` | `"[" <expression> "]"` | { `[` } | { `[` } |
| P068 | 180 | `<index-opt>` | `ε` | { `ε` } | { `)`, `=` } |
| P069 | 184 | `<while-statement>` | `WHILE "(" <expression> ")" <block>` | { `WHILE` } | { `WHILE` } |
| P070 | 188 | `<do-while-statement>` | `DO <block> WHILE "(" <expression> ")" ";"` | { `DO` } | { `DO` } |
| P071 | 192 | `<show-statement>` | `SHOW "(" <expression> ")" ";"` | { `SHOW` } | { `SHOW` } |
| P072 | 195 | `<read-statement>` | `READ "(" IDENTIFIER <index-opt> ")" ";"` | { `READ` } | { `READ` } |
| P073 | 198 | `<expression>` | `<or-expression>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P074 | 201 | `<or-expression>` | `<and-expression> <or-tail>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P075 | 204 | `<or-tail>` | `OR <and-expression> <or-tail>` | { `OR` } | { `OR` } |
| P076 | 205 | `<or-tail>` | `ε` | { `ε` } | { `)`, `,`, `;`, `]`, `}` } |
| P077 | 208 | `<and-expression>` | `<equality-expression> <and-tail>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P078 | 211 | `<and-tail>` | `AND <equality-expression> <and-tail>` | { `AND` } | { `AND` } |
| P079 | 212 | `<and-tail>` | `ε` | { `ε` } | { `)`, `,`, `;`, `OR`, `]`, `}` } |
| P080 | 215 | `<equality-expression>` | `<comparison-expression> <equality-tail>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P081 | 218 | `<equality-tail>` | `"==" <comparison-expression>` | { `==` } | { `==` } |
| P082 | 219 | `<equality-tail>` | `"!=" <comparison-expression>` | { `!=` } | { `!=` } |
| P083 | 220 | `<equality-tail>` | `ε` | { `ε` } | { `)`, `,`, `;`, `AND`, `OR`, `]`, `}` } |
| P084 | 223 | `<comparison-expression>` | `<add-expression> <comparison-tail>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P085 | 226 | `<comparison-tail>` | `"<" <add-expression>` | { `<` } | { `<` } |
| P086 | 227 | `<comparison-tail>` | `">" <add-expression>` | { `>` } | { `>` } |
| P087 | 228 | `<comparison-tail>` | `"<=" <add-expression>` | { `<=` } | { `<=` } |
| P088 | 229 | `<comparison-tail>` | `">=" <add-expression>` | { `>=` } | { `>=` } |
| P089 | 230 | `<comparison-tail>` | `ε` | { `ε` } | { `!=`, `)`, `,`, `;`, `==`, `AND`, `OR`, `]`, `}` } |
| P090 | 233 | `<add-expression>` | `<mul-expression> <add-tail>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P091 | 236 | `<add-tail>` | `"+" <mul-expression> <add-tail>` | { `+` } | { `+` } |
| P092 | 237 | `<add-tail>` | `"-" <mul-expression> <add-tail>` | { `-` } | { `-` } |
| P093 | 238 | `<add-tail>` | `ε` | { `ε` } | { `!=`, `)`, `,`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| P094 | 241 | `<mul-expression>` | `<unary-expression> <mul-tail>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P095 | 244 | `<mul-tail>` | `"*" <unary-expression> <mul-tail>` | { `*` } | { `*` } |
| P096 | 245 | `<mul-tail>` | `"/" <unary-expression> <mul-tail>` | { `/` } | { `/` } |
| P097 | 246 | `<mul-tail>` | `"%" <unary-expression> <mul-tail>` | { `%` } | { `%` } |
| P098 | 247 | `<mul-tail>` | `ε` | { `ε` } | { `!=`, `)`, `+`, `,`, `-`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| P099 | 250 | `<unary-expression>` | `NOT <unary-expression>` | { `NOT` } | { `NOT` } |
| P100 | 251 | `<unary-expression>` | `"-" <unary-expression>` | { `-` } | { `-` } |
| P101 | 252 | `<unary-expression>` | `<primary>` | { `(`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `STRING_LITERAL`, `TRUE` } | { `(`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `STRING_LITERAL`, `TRUE` } |
| P102 | 255 | `<primary>` | `INT_LITERAL` | { `INT_LITERAL` } | { `INT_LITERAL` } |
| P103 | 256 | `<primary>` | `FLOAT_LITERAL` | { `FLOAT_LITERAL` } | { `FLOAT_LITERAL` } |
| P104 | 257 | `<primary>` | `CHAR_LITERAL` | { `CHAR_LITERAL` } | { `CHAR_LITERAL` } |
| P105 | 258 | `<primary>` | `STRING_LITERAL` | { `STRING_LITERAL` } | { `STRING_LITERAL` } |
| P106 | 259 | `<primary>` | `TRUE` | { `TRUE` } | { `TRUE` } |
| P107 | 260 | `<primary>` | `FALSE` | { `FALSE` } | { `FALSE` } |
| P108 | 261 | `<primary>` | `IDENTIFIER <primary-suffix>` | { `IDENTIFIER` } | { `IDENTIFIER` } |
| P109 | 262 | `<primary>` | `"(" <expression> ")"` | { `(` } | { `(` } |
| P110 | 265 | `<primary-suffix>` | `"(" <arguments-opt> ")"` | { `(` } | { `(` } |
| P111 | 266 | `<primary-suffix>` | `"[" <expression> "]"` | { `[` } | { `[` } |
| P112 | 267 | `<primary-suffix>` | `ε` | { `ε` } | { `!=`, `%`, `)`, `*`, `+`, `,`, `-`, `/`, `;`, `<`, `<=`, `==`, `>`, `>=`, `AND`, `OR`, `]`, `}` } |
| P113 | 270 | `<arguments-opt>` | `<arguments>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P114 | 271 | `<arguments-opt>` | `ε` | { `ε` } | { `)` } |
| P115 | 274 | `<arguments>` | `<expression> <argument-tail>` | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } | { `(`, `-`, `CHAR_LITERAL`, `FALSE`, `FLOAT_LITERAL`, `IDENTIFIER`, `INT_LITERAL`, `NOT`, `STRING_LITERAL`, `TRUE` } |
| P116 | 277 | `<argument-tail>` | `"," <expression> <argument-tail>` | { `,` } | { `,` } |
| P117 | 278 | `<argument-tail>` | `ε` | { `ε` } | { `)`, `}` } |

## Sparse predictive parsing table

Each listed lookahead is one populated M[nonterminal, lookahead] cell. The value is the complete list of candidate production IDs; all unlisted cells are errors. Cells are grouped by row for readability.

| Nonterminal | Populated lookahead → candidate IDs |
|---|---|
| `<program>` | `FUNC` → P001<br>`START` → P001 |
| `<function-list>` | `FUNC` → P002<br>`START` → P003 |
| `<function>` | `FUNC` → P004 |
| `<return-type>` | `BOOL` → P005<br>`CHAR` → P005<br>`FLOAT` → P005<br>`INT` → P005<br>`STRING` → P005<br>`VOID` → P006 |
| `<type>` | `BOOL` → P011<br>`CHAR` → P009<br>`FLOAT` → P008<br>`INT` → P007<br>`STRING` → P010 |
| `<params-opt>` | `)` → P013<br>`BOOL` → P012<br>`CHAR` → P012<br>`FLOAT` → P012<br>`INT` → P012<br>`STRING` → P012 |
| `<param-list>` | `BOOL` → P014<br>`CHAR` → P014<br>`FLOAT` → P014<br>`INT` → P014<br>`STRING` → P014 |
| `<param-tail>` | `)` → P016<br>`,` → P015 |
| `<param>` | `BOOL` → P017<br>`CHAR` → P017<br>`FLOAT` → P017<br>`INT` → P017<br>`STRING` → P017 |
| `<block>` | `{` → P018 |
| `<statement-list>` | `BOOL` → P019<br>`CHAR` → P019<br>`DO` → P019<br>`FLOAT` → P019<br>`IDENTIFIER` → P019<br>`INT` → P019<br>`READ` → P019<br>`REPEAT` → P019<br>`RETURN` → P019<br>`SELECT` → P019<br>`SHOW` → P019<br>`STRING` → P019<br>`WHEN` → P019<br>`WHILE` → P019<br>`{` → P019<br>`}` → P020 |
| `<statement>` | `BOOL` → P021<br>`CHAR` → P021<br>`DO` → P027<br>`FLOAT` → P021<br>`IDENTIFIER` → P022<br>`INT` → P021<br>`READ` → P029<br>`REPEAT` → P025<br>`RETURN` → P030<br>`SELECT` → P024<br>`SHOW` → P028<br>`STRING` → P021<br>`WHEN` → P023<br>`WHILE` → P026<br>`{` → P031 |
| `<declaration>` | `BOOL` → P032<br>`CHAR` → P032<br>`FLOAT` → P032<br>`INT` → P032<br>`STRING` → P032 |
| `<declaration-tail>` | `;` → P035<br>`=` → P033<br>`[` → P034 |
| `<array-init-opt>` | `;` → P037<br>`=` → P036 |
| `<identifier-statement>` | `IDENTIFIER` → P038 |
| `<identifier-statement-tail>` | `(` → P041<br>`=` → P039<br>`[` → P040 |
| `<return-statement>` | `RETURN` → P042 |
| `<return-value-opt>` | `(` → P043<br>`-` → P043<br>`;` → P044<br>`CHAR_LITERAL` → P043<br>`FALSE` → P043<br>`FLOAT_LITERAL` → P043<br>`IDENTIFIER` → P043<br>`INT_LITERAL` → P043<br>`NOT` → P043<br>`STRING_LITERAL` → P043<br>`TRUE` → P043 |
| `<if-statement>` | `WHEN` → P045 |
| `<else-opt>` | `BOOL` → P047<br>`CHAR` → P047<br>`DO` → P047<br>`FLOAT` → P047<br>`IDENTIFIER` → P047<br>`INT` → P047<br>`OTHERWISE` → P046<br>`READ` → P047<br>`REPEAT` → P047<br>`RETURN` → P047<br>`SELECT` → P047<br>`SHOW` → P047<br>`STRING` → P047<br>`WHEN` → P047<br>`WHILE` → P047<br>`{` → P047<br>`}` → P047 |
| `<switch-statement>` | `SELECT` → P048 |
| `<case-list>` | `CASE` → P049<br>`DEFAULT` → P050<br>`}` → P050 |
| `<case-clause>` | `CASE` → P051 |
| `<default-opt>` | `DEFAULT` → P052<br>`}` → P053 |
| `<case-literal>` | `-` → P055<br>`CHAR_LITERAL` → P056<br>`INT_LITERAL` → P054<br>`STRING_LITERAL` → P057 |
| `<for-statement>` | `REPEAT` → P058 |
| `<for-init>` | `;` → P061<br>`BOOL` → P059<br>`CHAR` → P059<br>`FLOAT` → P059<br>`IDENTIFIER` → P060<br>`INT` → P059<br>`STRING` → P059 |
| `<for-condition>` | `(` → P062<br>`-` → P062<br>`;` → P063<br>`CHAR_LITERAL` → P062<br>`FALSE` → P062<br>`FLOAT_LITERAL` → P062<br>`IDENTIFIER` → P062<br>`INT_LITERAL` → P062<br>`NOT` → P062<br>`STRING_LITERAL` → P062<br>`TRUE` → P062 |
| `<for-update>` | `)` → P065<br>`IDENTIFIER` → P064 |
| `<assignment-core>` | `IDENTIFIER` → P066 |
| `<index-opt>` | `)` → P068<br>`=` → P068<br>`[` → P067 |
| `<while-statement>` | `WHILE` → P069 |
| `<do-while-statement>` | `DO` → P070 |
| `<show-statement>` | `SHOW` → P071 |
| `<read-statement>` | `READ` → P072 |
| `<expression>` | `(` → P073<br>`-` → P073<br>`CHAR_LITERAL` → P073<br>`FALSE` → P073<br>`FLOAT_LITERAL` → P073<br>`IDENTIFIER` → P073<br>`INT_LITERAL` → P073<br>`NOT` → P073<br>`STRING_LITERAL` → P073<br>`TRUE` → P073 |
| `<or-expression>` | `(` → P074<br>`-` → P074<br>`CHAR_LITERAL` → P074<br>`FALSE` → P074<br>`FLOAT_LITERAL` → P074<br>`IDENTIFIER` → P074<br>`INT_LITERAL` → P074<br>`NOT` → P074<br>`STRING_LITERAL` → P074<br>`TRUE` → P074 |
| `<or-tail>` | `)` → P076<br>`,` → P076<br>`;` → P076<br>`OR` → P075<br>`]` → P076<br>`}` → P076 |
| `<and-expression>` | `(` → P077<br>`-` → P077<br>`CHAR_LITERAL` → P077<br>`FALSE` → P077<br>`FLOAT_LITERAL` → P077<br>`IDENTIFIER` → P077<br>`INT_LITERAL` → P077<br>`NOT` → P077<br>`STRING_LITERAL` → P077<br>`TRUE` → P077 |
| `<and-tail>` | `)` → P079<br>`,` → P079<br>`;` → P079<br>`AND` → P078<br>`OR` → P079<br>`]` → P079<br>`}` → P079 |
| `<equality-expression>` | `(` → P080<br>`-` → P080<br>`CHAR_LITERAL` → P080<br>`FALSE` → P080<br>`FLOAT_LITERAL` → P080<br>`IDENTIFIER` → P080<br>`INT_LITERAL` → P080<br>`NOT` → P080<br>`STRING_LITERAL` → P080<br>`TRUE` → P080 |
| `<equality-tail>` | `!=` → P082<br>`)` → P083<br>`,` → P083<br>`;` → P083<br>`==` → P081<br>`AND` → P083<br>`OR` → P083<br>`]` → P083<br>`}` → P083 |
| `<comparison-expression>` | `(` → P084<br>`-` → P084<br>`CHAR_LITERAL` → P084<br>`FALSE` → P084<br>`FLOAT_LITERAL` → P084<br>`IDENTIFIER` → P084<br>`INT_LITERAL` → P084<br>`NOT` → P084<br>`STRING_LITERAL` → P084<br>`TRUE` → P084 |
| `<comparison-tail>` | `!=` → P089<br>`)` → P089<br>`,` → P089<br>`;` → P089<br>`<` → P085<br>`<=` → P087<br>`==` → P089<br>`>` → P086<br>`>=` → P088<br>`AND` → P089<br>`OR` → P089<br>`]` → P089<br>`}` → P089 |
| `<add-expression>` | `(` → P090<br>`-` → P090<br>`CHAR_LITERAL` → P090<br>`FALSE` → P090<br>`FLOAT_LITERAL` → P090<br>`IDENTIFIER` → P090<br>`INT_LITERAL` → P090<br>`NOT` → P090<br>`STRING_LITERAL` → P090<br>`TRUE` → P090 |
| `<add-tail>` | `!=` → P093<br>`)` → P093<br>`+` → P091<br>`,` → P093<br>`-` → P092<br>`;` → P093<br>`<` → P093<br>`<=` → P093<br>`==` → P093<br>`>` → P093<br>`>=` → P093<br>`AND` → P093<br>`OR` → P093<br>`]` → P093<br>`}` → P093 |
| `<mul-expression>` | `(` → P094<br>`-` → P094<br>`CHAR_LITERAL` → P094<br>`FALSE` → P094<br>`FLOAT_LITERAL` → P094<br>`IDENTIFIER` → P094<br>`INT_LITERAL` → P094<br>`NOT` → P094<br>`STRING_LITERAL` → P094<br>`TRUE` → P094 |
| `<mul-tail>` | `!=` → P098<br>`%` → P097<br>`)` → P098<br>`*` → P095<br>`+` → P098<br>`,` → P098<br>`-` → P098<br>`/` → P096<br>`;` → P098<br>`<` → P098<br>`<=` → P098<br>`==` → P098<br>`>` → P098<br>`>=` → P098<br>`AND` → P098<br>`OR` → P098<br>`]` → P098<br>`}` → P098 |
| `<unary-expression>` | `(` → P101<br>`-` → P100<br>`CHAR_LITERAL` → P101<br>`FALSE` → P101<br>`FLOAT_LITERAL` → P101<br>`IDENTIFIER` → P101<br>`INT_LITERAL` → P101<br>`NOT` → P099<br>`STRING_LITERAL` → P101<br>`TRUE` → P101 |
| `<primary>` | `(` → P109<br>`CHAR_LITERAL` → P104<br>`FALSE` → P107<br>`FLOAT_LITERAL` → P103<br>`IDENTIFIER` → P108<br>`INT_LITERAL` → P102<br>`STRING_LITERAL` → P105<br>`TRUE` → P106 |
| `<primary-suffix>` | `!=` → P112<br>`%` → P112<br>`(` → P110<br>`)` → P112<br>`*` → P112<br>`+` → P112<br>`,` → P112<br>`-` → P112<br>`/` → P112<br>`;` → P112<br>`<` → P112<br>`<=` → P112<br>`==` → P112<br>`>` → P112<br>`>=` → P112<br>`AND` → P112<br>`OR` → P112<br>`[` → P111<br>`]` → P112<br>`}` → P112 |
| `<arguments-opt>` | `(` → P113<br>`)` → P114<br>`-` → P113<br>`CHAR_LITERAL` → P113<br>`FALSE` → P113<br>`FLOAT_LITERAL` → P113<br>`IDENTIFIER` → P113<br>`INT_LITERAL` → P113<br>`NOT` → P113<br>`STRING_LITERAL` → P113<br>`TRUE` → P113 |
| `<arguments>` | `(` → P115<br>`-` → P115<br>`CHAR_LITERAL` → P115<br>`FALSE` → P115<br>`FLOAT_LITERAL` → P115<br>`IDENTIFIER` → P115<br>`INT_LITERAL` → P115<br>`NOT` → P115<br>`STRING_LITERAL` → P115<br>`TRUE` → P115 |
| `<argument-tail>` | `)` → P117<br>`,` → P116<br>`}` → P117 |

Examples: `M[<function-list>, START]` = P003; `M[<statement-list>, }]` = P020; `M[<expression>, )]` is empty and therefore an error.

## LL(1) conflict report

Populated cells: **350**. Conflicting cells: **0**. Distinct conflicting production pairs: **0**.

No predictive-table cell contains more than one production.

## Predictive traces

Stack top is displayed on the **right**. Input includes the explicit Sparq EOF token followed by the separate conceptual $ marker. These are grammar-symbol traces, not program execution or AST construction.

### Valid: `START { } EOF $`

| Step | Stack (top at right) | Remaining input | Action |
|---:|---|---|---|
| 1 | `$ <program>` | `START { } EOF $` | `P001: <program> → <function-list> START <block> EOF` |
| 2 | `$ EOF <block> START <function-list>` | `START { } EOF $` | `P003: <function-list> → ε` |
| 3 | `$ EOF <block> START` | `START { } EOF $` | `match START` |
| 4 | `$ EOF <block>` | `{ } EOF $` | `P018: <block> → "{" <statement-list> "}"` |
| 5 | `$ EOF } <statement-list> {` | `{ } EOF $` | `match {` |
| 6 | `$ EOF } <statement-list>` | `} EOF $` | `P020: <statement-list> → ε` |
| 7 | `$ EOF }` | `} EOF $` | `match }` |
| 8 | `$ EOF` | `EOF $` | `match EOF` |
| 9 | `$` | `$` | `accept` |

Result: **accepted**.

### Invalid: `START { SHOW ( ) ; } EOF $`

| Step | Stack (top at right) | Remaining input | Action |
|---:|---|---|---|
| 1 | `$ <program>` | `START { SHOW ( ) ; } EOF $` | `P001: <program> → <function-list> START <block> EOF` |
| 2 | `$ EOF <block> START <function-list>` | `START { SHOW ( ) ; } EOF $` | `P003: <function-list> → ε` |
| 3 | `$ EOF <block> START` | `START { SHOW ( ) ; } EOF $` | `match START` |
| 4 | `$ EOF <block>` | `{ SHOW ( ) ; } EOF $` | `P018: <block> → "{" <statement-list> "}"` |
| 5 | `$ EOF } <statement-list> {` | `{ SHOW ( ) ; } EOF $` | `match {` |
| 6 | `$ EOF } <statement-list>` | `SHOW ( ) ; } EOF $` | `P019: <statement-list> → <statement> <statement-list>` |
| 7 | `$ EOF } <statement-list> <statement>` | `SHOW ( ) ; } EOF $` | `P028: <statement> → <show-statement>` |
| 8 | `$ EOF } <statement-list> <show-statement>` | `SHOW ( ) ; } EOF $` | `P071: <show-statement> → SHOW "(" <expression> ")" ";"` |
| 9 | `$ EOF } <statement-list> ; ) <expression> ( SHOW` | `SHOW ( ) ; } EOF $` | `match SHOW` |
| 10 | `$ EOF } <statement-list> ; ) <expression> (` | `( ) ; } EOF $` | `match (` |
| 11 | `$ EOF } <statement-list> ; ) <expression>` | `) ; } EOF $` | `error: M[<expression>, )] is empty` |

Result: **rejected** at `error: M[<expression>, )] is empty`.
<!-- Computed grammar analysis: end -->

## Relation to the recursive-descent compiler parser

The [production parser](../sparq/parser.py) realizes predictive choices with
token tests and method calls. Its `parse()` loop chooses another function on
`FUNC` and ends the function list on `START`. `parse_block()` repeats statements
until `RBRACE`, matching the nullable statement-list choice. Declaration
parsing distinguishes `=`, `[`, and `;`; identifier-led statements distinguish
`=`, `[`, and `(` after the identifier. `_parse_when()` consumes `OTHERWISE`
only when present. `_parse_repeat()` recognizes an omitted initializer on the
first `;`, an omitted condition on the second `;`, and an omitted update on
`)`. Expression methods implement the precedence nonterminals. Loops for
repeated tails avoid unnecessary Python recursion and build left-associated
AST nodes where the language specifies it.

The table proves that every grammar choice has at most one production for a
single lookahead **if the computed conflict count is zero**. It does not prove
that every branch of the Python parser is implemented correctly. The trace
simulates grammar symbols only; it does not build an AST, resolve names, check
types, or execute `SHOW`. Those require separate implementation tests and later
compiler phases.

## Verification and viva guide

The utility checks undefined, unreachable, unproductive, and duplicate
productions. It retains all candidates in each table cell, counts conflicting
cells and distinct production pairs, and generates both traces from the full
grammar. Tests cover nullable prefixes, FOLLOW propagation, EOF versus `$`,
determinism, and an intentionally conflicting **illustrative** grammar. They
also compare this document's generated block with a fresh calculation.

For a hand demonstration, derive the five selected sets above directly from
the frozen BNF; explain why a nullable right-hand side adds FOLLOW(A) to its
SELECT set; locate a populated cell and an error cell in the sparse table;
then walk the valid trace until the explicit `EOF` is matched and the separate
`$` accepts. In the invalid trace, `SHOW ( )` reaches an empty table cell for
`<expression>` on `)`. No semantic conclusion follows from either trace.
