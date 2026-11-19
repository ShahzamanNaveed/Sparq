# Sparq Language Specification

**Version:** 1.0  
**Status:** Approved — M1 Frozen  
**Source extension:** .spq  
**Compiler implementation:** Python 3.11+

No language syntax, grammar, keyword, or semantic changes may be introduced without explicit student-group review and approval.

## 1. Language introduction and design objectives

Sparq is a statically typed procedural and imperative language designed for the CS4031 Compiler Construction semester project. Its C-like blocks and custom keywords support all mandatory constructs while permitting a recursive-descent parser. The planned compiler translates Sparq source through an AST and Three-Address Code (TAC) to a custom register-based virtual machine. This document defines the language; it does not claim that compiler functionality exists.

## 2. Language characteristics

Sparq source ends in .spq. A program has zero or more functions followed by exactly one START block. Names and keywords are case-sensitive. Variables have lexical block scope. Assignment is a statement, not an expression. Arrays are one-dimensional and fixed-size. Functions may return a scalar value or VOID. The primary parser strategy is recursive descent. Direct and mutual recursion are permitted.

## 3. Complete reserved keyword list

START, FUNC, RETURN, INT, FLOAT, CHAR, STRING, BOOL, VOID, WHEN, OTHERWISE, SELECT, CASE, DEFAULT, REPEAT, WHILE, DO, SHOW, READ, TRUE, FALSE, AND, OR, NOT.

These spellings are reserved exactly as shown and cannot be identifiers.

## 4. Operators and delimiters

Arithmetic: + - * / %. Ordered comparison: > < >= <=. Equality: == !=. Logical: AND OR NOT. Assignment: =. Return-type separator: ->. Grouping and calls: ( ). Blocks: { }. Array indexing: [ ]. Other delimiters: ; , :.

The language has no ++, --, compound assignment, or general assignment expressions.

## 5. Token recognition rules

| Category | Recognition |
|---|---|
| IDENTIFIER | [A-Za-z_][A-Za-z0-9_]*; check the complete lexeme against the reserved-word list |
| INT_LITERAL | [0-9]+; decimal, including spellings with leading zeroes |
| FLOAT_LITERAL | [0-9]+\.[0-9]+; no exponent, .5, or 5. form |
| CHAR_LITERAL | Single quotes around exactly one permitted raw Unicode scalar value or one supported escape |
| STRING_LITERAL | Double quotes around zero or more permitted raw Unicode scalar values or supported escapes |
| Escapes | \n, \t, \r, \\, \", \', \0 only |
| Line comment | // through the character before the next line break or EOF |
| Block comment | /* through the first subsequent */; nesting is unsupported |
| Whitespace | Spaces, tabs, LF, CRLF, and CR are ignored between tokens |
| EOF | Emitted once when the source is consumed |

Raw quote, backslash, or line break cannot occur unescaped inside its corresponding literal. Raw control characters in literals are disallowed; use the supported escapes. Other Unicode scalar values are allowed in CHAR and STRING, while identifiers remain ASCII-only. Invalid source encoding, characters, or escapes are lexical errors. Unterminated literals and block comments are lexical errors.

Longest-match recognition makes >=, <=, ==, !=, and -> single tokens and recognizes comment openers before /. A minus sign is always a separate token; -12 is unary minus followed by INT_LITERAL. Immediately adjacent malformed numeric sequences such as 12abc, 5., .5, and 1.2.3 are lexical errors, not valid token splits.

Positions are 1-based. LF, CRLF, and CR each advance one line; columns count Unicode scalar values, with a tab counting as one source column. Retain the numeric lexeme and decoded value. INT literals are decimal mathematical integers. A FLOAT literal decoding to a nonfinite binary64 value is a compile-time error.

## 6. Complete formal BNF grammar

Uppercase names are lexer tokens, quoted punctuation is literal, ε is empty, and EOF is the explicit lexer token. The following productions are preserved from M1.

~~~bnf
<program> ::= <function-list> START <block> EOF

<function-list> ::= <function> <function-list>
                  | ε

<function> ::= FUNC IDENTIFIER "(" <params-opt> ")"
               "->" <return-type> <block>

<return-type> ::= <type> | VOID

<type> ::= INT | FLOAT | CHAR | STRING | BOOL

<params-opt> ::= <param-list> | ε

<param-list> ::= <param> <param-tail>

<param-tail> ::= "," <param> <param-tail>
               | ε

<param> ::= <type> IDENTIFIER

<block> ::= "{" <statement-list> "}"

<statement-list> ::= <statement> <statement-list>
                   | ε


<statement> ::= <declaration>
              | <identifier-statement>
              | <if-statement>
              | <switch-statement>
              | <for-statement>
              | <while-statement>
              | <do-while-statement>
              | <show-statement>
              | <read-statement>
              | <return-statement>
              | <block>


<declaration> ::=
    <type> IDENTIFIER <declaration-tail> ";"

<declaration-tail> ::=
      "=" <expression>
    | "[" INT_LITERAL "]" <array-init-opt>
    | ε

<array-init-opt> ::=
      "=" "{" <arguments> "}"
    | ε


<identifier-statement> ::=
    IDENTIFIER <identifier-statement-tail>

<identifier-statement-tail> ::=
      "=" <expression> ";"
    | "[" <expression> "]" "=" <expression> ";"
    | "(" <arguments-opt> ")" ";"


<return-statement> ::=
    RETURN <return-value-opt> ";"

<return-value-opt> ::=
      <expression>
    | ε


<if-statement> ::=
    WHEN "(" <expression> ")" <block> <else-opt>

<else-opt> ::=
      OTHERWISE <block>
    | ε


<switch-statement> ::=
    SELECT "(" <expression> ")" "{"
        <case-list> <default-opt>
    "}"

<case-list> ::=
      <case-clause> <case-list>
    | ε

<case-clause> ::=
    CASE <case-literal> ":" <block>

<default-opt> ::=
      DEFAULT ":" <block>
    | ε

<case-literal> ::=
      INT_LITERAL
    | "-" INT_LITERAL
    | CHAR_LITERAL
    | STRING_LITERAL


<for-statement> ::=
    REPEAT "(" <for-init> ";"
               <for-condition> ";"
               <for-update> ")" <block>

<for-init> ::=
      <type> IDENTIFIER "=" <expression>
    | <assignment-core>
    | ε

<for-condition> ::=
      <expression>
    | ε

<for-update> ::=
      <assignment-core>
    | ε

<assignment-core> ::=
    IDENTIFIER <index-opt> "=" <expression>

<index-opt> ::=
      "[" <expression> "]"
    | ε


<while-statement> ::=
    WHILE "(" <expression> ")" <block>


<do-while-statement> ::=
    DO <block> WHILE "(" <expression> ")" ";"


<show-statement> ::=
    SHOW "(" <expression> ")" ";"

<read-statement> ::=
    READ "(" IDENTIFIER <index-opt> ")" ";"


<expression> ::= <or-expression>

<or-expression> ::=
    <and-expression> <or-tail>

<or-tail> ::=
      OR <and-expression> <or-tail>
    | ε

<and-expression> ::=
    <equality-expression> <and-tail>

<and-tail> ::=
      AND <equality-expression> <and-tail>
    | ε

<equality-expression> ::=
    <comparison-expression> <equality-tail>

<equality-tail> ::=
      "==" <comparison-expression>
    | "!=" <comparison-expression>
    | ε

<comparison-expression> ::=
    <add-expression> <comparison-tail>

<comparison-tail> ::=
      "<" <add-expression>
    | ">" <add-expression>
    | "<=" <add-expression>
    | ">=" <add-expression>
    | ε

<add-expression> ::=
    <mul-expression> <add-tail>

<add-tail> ::=
      "+" <mul-expression> <add-tail>
    | "-" <mul-expression> <add-tail>
    | ε

<mul-expression> ::=
    <unary-expression> <mul-tail>

<mul-tail> ::=
      "*" <unary-expression> <mul-tail>
    | "/" <unary-expression> <mul-tail>
    | "%" <unary-expression> <mul-tail>
    | ε

<unary-expression> ::=
      NOT <unary-expression>
    | "-" <unary-expression>
    | <primary>

<primary> ::=
      INT_LITERAL
    | FLOAT_LITERAL
    | CHAR_LITERAL
    | STRING_LITERAL
    | TRUE
    | FALSE
    | IDENTIFIER <primary-suffix>
    | "(" <expression> ")"

<primary-suffix> ::=
      "(" <arguments-opt> ")"
    | "[" <expression> "]"
    | ε

<arguments-opt> ::=
      <arguments>
    | ε

<arguments> ::=
    <expression> <argument-tail>

<argument-tail> ::=
      "," <expression> <argument-tail>
    | ε
~~~

The array-size production contains INT_LITERAL, so positive size means a positive decimal integer literal. A general constant expression such as [1+2] is not array-size syntax.

## 7. Operator precedence and associativity

| Highest to lowest | Form | Associativity |
|---|---|---|
| 1 | Parentheses, function calls, array indexing | One suffix on an identifier |
| 2 | Unary minus, NOT | Right |
| 3 | *, /, % | Left |
| 4 | +, - | Left |
| 5 | <, >, <=, >= | Non-associative |
| 6 | ==, != | Non-associative |
| 7 | AND | Left |
| 8 | OR | Left |

Assignment is statement-level. Right-recursive additive, multiplicative, AND, and OR tails must produce left-associated ASTs: a-b-c means (a-b)-c.

## 8. Grammar ambiguity resolution

Mandatory WHEN and OTHERWISE blocks resolve dangling else. Identifier-led statements are factored after IDENTIFIER. Distinct longest-match tokens avoid character-prefix confusion among operators. Comparison and equality tails permit at most one operator at their respective levels. Empty SELECT is legal and has no effect.

## 9. FIRST/FOLLOW and LL(1) verification summary

Independent fixed-point analysis of the original grammar found 55 nonterminals, 117 alternatives, 23 nullable nonterminals, no undefined/unreachable/unproductive nonterminals, no direct or indirect left recursion, and no LL(1) selection-set conflicts. FIRST(program) is {FUNC, START}; FIRST(function-list) is {FUNC, ε}; FOLLOW(function-list) is {START}. FOLLOW(program) contains the conceptual end marker $ after the explicit EOF token. The complete calculated sets were reviewed in M1 Tasks 01 and 04. These are grammar results, not claims about an implemented parser.

## 10. Chomsky hierarchy classification

The syntax grammar is Type 2, context-free: every left side is a single nonterminal. Its LL(1) structure is deterministic context-free. Token patterns and nonnested comments are regular-language matters. Scope, types, bounds, returns, and CASE uniqueness are semantic constraints outside the BNF.

## 11. Type system

Scalar types are INT, FLOAT, CHAR, STRING, and BOOL. VOID is only a function return type. Arrays are typed collections, not scalar expressions. INT may implicitly convert to FLOAT during initialization, assignment, argument passing, array-element initialization, and returns. Other implicit conversions are prohibited. Equality accepts matching scalar types or mixed INT/FLOAT values; ordered comparisons accept numeric values only. Bare arrays and function names have no scalar value. A VOID call can be a statement but not a scalar expression.

## 12. Variable declarations and scope

An uninitialized scalar receives 0, 0.0, '\0', "", or FALSE according to type. Same-scope redeclaration is an error; nested blocks may shadow. Each block creates a lexical variable scope. Function names occupy a unique global namespace separate from variables: f() resolves a function, while bare f resolves a variable. Parameters and the function's outermost block share a variable scope; duplicate parameters or local redeclaration of a parameter there are errors. START has its own outer scope. There are no global variables. A declaration shadows an outer name during its own initializer, but reading the new variable before its initialization is an error.

## 13. Arithmetic and logical semantics

INT is an arbitrary-precision signed integer. FLOAT is finite IEEE 754 binary64 using round-to-nearest, ties-to-even; subnormals and signed zero are permitted. INT arithmetic never passes through binary64. For +, -, and *, two INT operands produce INT; any FLOAT operand promotes INT to FLOAT and produces FLOAT. INT / INT produces INT, truncating toward zero. Otherwise / produces FLOAT. % accepts two INT operands only and produces INT. Signed remainder is a - trunc(a/b)*b. Unary - accepts INT or FLOAT and preserves type. Division or remainder by zero, including +0.0 and -0.0 divisors, is a runtime error.

Mixed numeric comparisons promote INT to FLOAT. Ordered comparisons produce BOOL and require numeric operands. Equality produces BOOL and permits equal scalar types or mixed numeric types; FLOAT equality compares represented values exactly. NOT, AND, and OR require BOOL and produce BOOL. Evaluate operands left to right; AND and OR short circuit and skip the right operand entirely when determined.

For binary expressions other than short-circuit AND and OR, evaluate the left operand and immediately perform any implicit conversion required at that operand's use site before evaluating the right operand. Evaluate the right operand and perform any required conversion before applying the binary operator. If operand evaluation or conversion fails, execution stops at that error; later operand evaluation and the binary operation do not occur.

INT-to-FLOAT conversion must yield a finite binary64 value. Failure raises an error when that conversion executes. FLOAT operations yielding nonfinite values raise runtime errors. Arithmetic constant folding must use these same rules and preserve the execution point of observable errors.

## 14. Conditional statements

WHEN tests one BOOL expression and executes its block when TRUE. OTHERWISE executes when FALSE if present. No truthiness conversion exists. Nested WHEN is permitted; every branch block has its own lexical scope.

## 15. Switch-case semantics

SELECT evaluates its INT, CHAR, or STRING selector once. CASE labels are the constant literal forms in the grammar and must match the selector type. Compare decoded values. Duplicate (type, value) labels are compile-time errors, so 01 conflicts with 1 and -0 conflicts with 0. Execute at most one matching CASE block, or DEFAULT if none matches. There is no fall-through. DEFAULT is optional and last. An empty SELECT is valid and does nothing.

## 16. FOR, WHILE, and DO-WHILE semantics

REPEAT initializes once, checks its BOOL condition before each iteration, executes its body, then its update. An omitted condition is TRUE. An initializer-declared variable belongs to a loop scope covering condition, update, and body, then disappears. WHILE tests its BOOL condition before each iteration. DO executes its body once before testing the trailing BOOL condition. Loop bodies are nested lexical scopes.

## 17. Function declarations, calls, and returns

All function declarations precede START. Collect signatures before body analysis; later-declared calls and direct or mutual recursion are allowed. Function names are globally unique. Evaluate arguments left to right, check count and types, and pass scalar values by value. Arrays are not parameters. A standalone call may discard its return value. A bare function name or VOID call cannot be a scalar expression.

RETURN in START is a semantic error. VOID functions may use RETURN; and implicitly return without a value at their closing brace. A value from a VOID function is an error. Non-VOID functions must return a compatible value on every path that can reach their exit. Conservatively: RETURN guarantees return; a block does when a reachable statement does; WHEN requires OTHERWISE and returning blocks on both sides; SELECT requires DEFAULT and returning blocks in every branch; DO does when its body does; WHILE and REPEAT alone do not guarantee return. VM stack exhaustion produces a controlled Sparq runtime error. The initial configurable maximum VM call depth is 1,000.

## 18. Array declarations and operations

Arrays are one-dimensional, fixed-size, and zero-indexed. Size is a positive INT_LITERAL. An uninitialized array receives the element type's default at every position. An explicit initializer has exactly the declared number of expressions, evaluated left to right and converted under the assignment rules. A new array cannot be read from its own initializer. An index has static type INT. For an indexed read, evaluate index, check 0 <= index < length, then fetch. For indexed assignment, evaluate index, check bounds, evaluate and convert the right-hand value, then store. A failed bounds check skips later stages. Out-of-range access is a runtime error. Whole-array assignment, bare-array scalar use, and array parameters are unsupported.

## 19. Input/output behavior

READ accepts a writable scalar variable or indexed array element and consumes one whitespace-delimited field. INT accepts optional sign and decimal digits. FLOAT accepts optional sign and the supported decimal float form, or integer-form input through INT-to-FLOAT conversion, rounded to binary64. BOOL accepts exactly TRUE or FALSE; CHAR accepts one Unicode scalar value; STRING accepts the field as raw text without quotes or escape decoding. An invalid present field is consumed before a controlled runtime error; input exhaustion is also a runtime error. Neither error changes the target. For an indexed target, evaluate and bounds-check the index before consuming input.

SHOW evaluates one scalar expression once and prints its value plus a newline. INT uses decimal; FLOAT uses canonical shortest round-trip decimal formatting, including -0.0 and integral values such as 2.0; CHAR prints its character; STRING prints decoded text; BOOL prints TRUE or FALSE. READ and SHOW are observable side effects. Optimizations preserve their count and order, as well as all potentially trapping computations. An optimizer must not raise a runtime error from code that execution would not reach.

## 20. Compile-time errors

Lexical and syntax errors; undeclared or same-scope redeclared names; incompatible assignment, argument, return, or operator types; non-BOOL conditions; RETURN in START; missing guaranteed non-VOID return; scalar misuse of arrays, function names, or VOID calls; invalid array size or initializer length; non-INT index; incompatible or duplicate CASE labels; and nonfinite FLOAT literals are compile-time errors. Diagnostic wording and recovery are implementation choices.

## 21. Runtime errors

Controlled Sparq runtime errors cover division or remainder by zero, array bounds failure, invalid or exhausted READ, failed INT-to-FLOAT conversion, a nonfinite FLOAT operation, and VM call-stack exhaustion. The implementation should report controlled diagnostics rather than unhandled host exceptions wherever practical. Potentially trapping operations cannot be removed or moved if that changes observable execution.

## 22. Representative valid programs

~~~sparq
FUNC add(INT a, INT b) -> INT {
    RETURN a + b;
}
START {
    FLOAT result = add(10, 20);
    WHEN (result >= 30.0) {
        SHOW("Success");
    } OTHERWISE {
        SHOW("Failure");
    }
}
~~~

Expected output: Success followed by a newline.

~~~sparq
START {
    INT numbers[3] = {10, 20, 30};
    REPEAT (INT i = 0; i < 3; i = i + 1) {
        SHOW(numbers[i]);
    }
}
~~~

Expected output: 10, 20, 30 on separate lines.

~~~sparq
START {
    CHAR grade = 'A';
    SELECT (grade) {
        CASE 'A': { SHOW("Excellent"); }
        DEFAULT: { SHOW("Other"); }
    }
}
~~~

Expected output: Excellent followed by a newline.

The Task 01 reference programs for function calls and conditionals, REPEAT, arrays, SELECT, and DO-WHILE remain compatible with these rules.

## 23. Representative invalid programs

~~~sparq
START { INT x = 1.5; }
~~~

Compile-time type error: FLOAT cannot implicitly become INT.

~~~sparq
FUNC score(BOOL ok) -> INT {
    WHEN (ok) { RETURN 1; }
}
START {}
~~~

Compile-time return error: a path can reach the end of score.

~~~sparq
START { INT a[2] = {1, 2, 3}; }
~~~

Compile-time error: initializer length differs from array size.

~~~sparq
START { INT a[2]; SHOW(a[2]); }
~~~

Compiles, then raises a runtime bounds error.

~~~sparq
START {
    INT x = 1;
    SELECT (x) {
        CASE 01: {}
        CASE 1: {}
    }
}
~~~

Compile-time error: duplicate decoded CASE value.

The 33 M1 Task 02 validation examples remain classified as documented there: accepted 1–4, 7, 10, 12, 16, 19, 21, 27–29, 31; compile-time semantic errors 5–6, 8, 11, 13–15, 17–18, 20, 24–26; runtime errors after acceptance 9, 22–23, 30; lexical errors 32–33. This is specification review, not executed compiler testing.

## 24. Compiler architecture overview

The planned sequence is .spq source → lexer with source positions → recursive-descent parser and AST → symbol-table and semantic analysis → TAC → basic blocks, control-flow graph, DAG and required optimizations → target instruction selection and register allocation → custom register-based VM. Later course demonstrations include FIRST/FOLLOW, operator precedence and bottom-up parsing, LR-family tables, SDD/SDT and attributes. None of these implementation components exists at project initialization.

## 25. Approved decisions and change control

M1 Task 03's 26-section language design and M1 Task 04's numeric, error, evaluation-order, recursion, array, and I/O clarifications were approved by the student group for version 1.0. The initial VM maximum call depth is configurable and defaults to 1,000. No language syntax, grammar, keyword, or semantic changes may be introduced without explicit student-group review and approval. Implementation details that do not alter language behavior can be resolved during development and documented.

M5 Task 03B: The student group approved the immediate binary operand-conversion timing stated in Section 13 to resolve the previously ambiguous precedence of conversion errors and later operand evaluation. This is a narrow clarification within version 1.0; it changes no grammar, operator, type-compatibility, or implicit-conversion rule.

## 26. Requirements traceability table

| Assignment requirement | Specification sections | Implementation status |
|---|---|---|
| Language identity, keywords, identifiers, literals, operators, delimiters | 1–5 | Documented only |
| Five scalar data types | 2, 5, 11 | Documented only |
| Declarations, initialization, assignment | 6, 11–12 | Documented only |
| Arithmetic, relational, logical operators | 4, 6–7, 13 | Documented only |
| IF, ELSE, nested IF | 6, 14 | Documented only |
| SWITCH, CASE, DEFAULT | 6, 15 | Documented only |
| FOR, WHILE, DO-WHILE | 6, 16 | Documented only |
| Functions, parameters, returns, calls | 6, 17 | Documented only |
| Arrays | 6, 18 | Documented only |
| Input/output and comments | 5–6, 19 | Documented only |
| Formal BNF, precedence, ambiguity, Chomsky classification | 6–10 | Documented only |
| Lexer regex/FSM, buffering, errors | 5, 20 | Rules documented; implementation and FSM pending |
| Recursive descent, LL(1), FIRST/FOLLOW, factoring, left recursion | 8–9, 24 | Grammar verified; parser pending |
| Operator precedence, shift-reduce, LR(0), SLR(1), CLR(1), LALR(1) | 7, 24 | Demonstrations pending |
| AST, DAG, SDD, SDT, attributes, scopes, type checking | 11–18, 24 | Rules documented; implementation pending |
| TAC | 24 | Planned |
| Basic blocks, CFG, optimizations | 24 | Planned |
| Target instructions, costs, registers, VM | 24 | Planned |

## Verification record

The original grammar's 55 nonterminals and 117 alternatives, 23 nullable symbols, and zero LL(1) conflicts were independently recalculated in memory during M1 Tasks 03 and 04. The language semantics and M1 Task 04 clarifications are approved as source-of-truth rules, but no compiler behavior has been executed or verified. The example programs are reference source, not executable project tests.

