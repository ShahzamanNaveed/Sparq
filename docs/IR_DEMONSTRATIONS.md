# Derived intermediate-code teaching views

Run `.venv\Scripts\python -B -m tools.ir_demonstrations` from the project root. The command parses and analyzes two small Sparq programs, lowers them with the existing production components, and derives the displayed tables from the emitted records. It does not execute or optimize IR.

The canonical typed TAC remains the only production instruction sequence. `quadruples(instructions)` supports `Binary`, `Compare`, `Unary`, `Convert`, `Load`, `InitScalar`, and `Move`. Each record retains all operands in `(operator, arg1, arg2, result)` form. `arg2` is `None` for one-operand instructions. Other instruction types raise `UnsupportedIRView`; the converter does not omit instructions silently.

`triples(instructions)` accepts only a straight-line sequence of `Binary` instructions from one routine. Operands must be constants or temporaries defined by an earlier `Binary` in the supplied sequence. Each temporary use becomes a `PositionRef` to its defining triple. Calls, labels, branches, array operations, I/O, conversions, and storage operations require additional conventions and are outside this teaching subset. Empty input yields an empty table. Neither utility changes its input records or order.

For `START { SHOW(1 + 2 * 3); }`, the canonical instruction types are `Binary(STAR), Binary(PLUS), Show`. The demo explicitly selects the two arithmetic records, yielding:

| Position | Quadruple operator | arg1 | arg2 | result | Triple |
|---:|---|---|---|---|---|
| 0 | STAR | 2 | 3 | %t1 | `STAR, 2, 3` |
| 1 | PLUS | 1 | %t1 | %t2 | `PLUS, 1, (0)` |

`indirect_triples(table, order)` retains the physical triple table and stores a separate permutation of its positions. The primary example uses pointer order `(0, 1)`. The command also derives two independent additions from `START { SHOW(1 + 2); SHOW(3 + 4); }` and displays the alternative pointer order `(1, 0)`. This is a representation example only: it neither reorders production instructions nor asserts that arbitrary pointer orders preserve execution behavior.

Production forward branches use symbolic labels and builder resolution. An explicit textbook backpatch-list demonstration was optional in the approved architecture and was not added. Task 08 must verify complete program ownership, every CALL target's exact identity in the owning `AnalysisResult`, path-aware temporary and guard availability, and approved reachability and termination properties. M7 still owns the allocation-error precedence decision.
