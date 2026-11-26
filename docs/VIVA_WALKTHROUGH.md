# From a Sparq expression to machine instructions

Run the [README commands](../README.md#follow-the-compiler) from the repository root. The example prints one integer.

```sparq
START {
    INT x = 2 + 3 * 4;
    SHOW(x);
}
```

## 1. Recognize the tokens

[Lexer.tokenize](../sparq/lexer.py) scans the declaration from left to right. Each row gives the source span, token kind, original spelling, and decoded literal value.

```text
2:5-2:8 INT 'INT' None
2:9-2:10 IDENTIFIER 'x' None
2:11-2:12 EQUAL '=' None
2:13-2:14 INT_LITERAL '2' 2
2:15-2:16 PLUS '+' None
2:17-2:18 INT_LITERAL '3' 3
2:19-2:20 STAR '*' None
2:21-2:22 INT_LITERAL '4' 4
2:22-2:23 SEMICOLON ';' None
```

## 2. Build the syntax tree

In [Parser._parse_add](../sparq/parser.py), each operand comes from `_parse_mul`. When the parser reaches the right operand of the plus sign, that call consumes the entire product. The initializer tree, with source positions omitted, is:

```text
BinaryExpr(+)
  LiteralExpr(2)
  BinaryExpr(*)
    LiteralExpr(3)
    LiteralExpr(4)
```

The production parser uses recursive descent. The [LL(1) tool](../tools/ll1_analysis.py) checks the full Sparq grammar. The [LR tool](../tools/lr_analysis.py) uses smaller grammars to show how LR(0), SLR(1), CLR(1), and LALR(1) tables are constructed and where conflicts arise.

## 3. Check the types

The expression analyzer's [_infer](../sparq/semantic.py) determines each operand type and the result type. Multiplication of the two integer operands produces an INT. Adding the remaining integer also produces an INT, so the initializer fits the declared type of x. To demonstrate a semantic error, replace the initializer in a copy with the string literal `"fourteen"` and run the semantic command on that copy.

## 4. Generate and optimize TAC

The expression lowerer's [_value](../sparq/expression_lowering.py) emits the product before the sum. In the original listing, %t1 holds the product and %t2 holds the sum. In the [optimizer](../sparq/optimization.py), `_fold` evaluates arithmetic with known operands. Constant propagation carries 14 through to SHOW, so the temporary load can disappear.

```text
ORIGINAL TAC
START
  0000 BINARY operator=STAR, left=Constant(INT, 3), right=Constant(INT, 4), result=%t1:INT@RoutineId(START)
  0001 BINARY operator=PLUS, left=Constant(INT, 2), right=%t1:INT@RoutineId(START), result=%t2:INT@RoutineId(START)
  0002 INITSCALAR target=v1(x):INT@RoutineId(START), value=%t2:INT@RoutineId(START)
  0003 LOAD source=v1(x):INT@RoutineId(START), result=%t3:INT@RoutineId(START)
  0004 SHOW value=%t3:INT@RoutineId(START)
  0005 HALTSTART

OPTIMIZED TAC
START
  0000 INITSCALAR target=v1(x):INT@RoutineId(START), value=Constant(INT, 14)
  0001 SHOW value=Constant(INT, 14)
  0002 HALTSTART
```

## 5. Generate target code and run it

[generate_target](../sparq/target_codegen.py) translates TAC into instructions. Below is the listing with both optimization flags enabled. CONST puts 14 in register R0. INIT_SCALAR initializes x in its frame slot. SHOW prints the value in R0 and HALT ends execution.

```text
START
  frame: variable1(x):INT
  0000 CONST R0 Constant(INT, 14)
  0001 INIT_SCALAR variable1(x):INT R0
  0002 CONST R0 Constant(INT, 14)
  0003 SHOW R0
  0004 HALT
```

The VM prints `14`. To see why compile-time knowledge matters, replace the declaration with `INT n; READ(n); INT x = 2 + n * 4;` in a copy. With input 3 the result is still 14, but the optimizer must keep the arithmetic because n is supplied at runtime.

## A separate loop optimization

Run `python -m sparq.tac examples/optimization.spq --compare`. In the original listing, instruction 0017 branches on constant FALSE to L2 (loop body) or L3 (exit). The body contains a division, a SHOW, and a jump back to the condition. In the optimized listing, instruction 0010 jumps directly to L3. The body is unreachable and removed. This demonstrates constant-condition loop elimination. The current optimizer does not perform loop unrolling or loop-invariant code motion.
