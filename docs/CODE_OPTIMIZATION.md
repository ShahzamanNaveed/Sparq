# Sparq M6 code optimization

## Course requirements and present scope

The original semester-project handout's Phase 6 requires basic-block identification, CFG construction, DAG-based optimization, constant folding and propagation, common-subexpression elimination, dead-code elimination, copy propagation, loop optimization, global optimization, machine-dependent optimization, and a comparison of original and optimized intermediate code. Phase 7 separately requires target instruction design, instruction selection and cost, register allocation, and DAG-based target generation. The handout does not define a target instruction set or register count.

| Handout item | M6 implementation |
|---|---|
| Basic blocks and CFG | `analyze_routine` identifies leaders, fallthrough, branch and return edges, predecessors, reachable instructions, and structural backward edges. |
| DAG optimization and CSE | A per-block expression DAG hash-conses pure arithmetic, comparisons, and unary operations over captured temporaries/constants. It shares repeated scalar loads only until a storage mutation or effect barrier. |
| Constant folding | Exact bounded INT arithmetic, signed truncating division and remainder with nonzero divisors, non-FLOAT comparisons, BOOL NOT, and exactly representable INT-to-FLOAT conversion. |
| Constant propagation | Forward must-constant facts for scalar storage and temporaries meet by equality at CFG joins. Mutable storage facts are invalidated by CALL and READ. Loop backedges participate in the worklist fixed point. |
| Dead-code elimination | Backward liveness removes only unused, pure ordinary temporary definitions; potentially trapping and observable instructions remain. |
| Copy propagation | Stable temporary aliases from redundant local loads and DAG hits are substituted within their basic block. |
| Loop optimization | Constant-condition loop branches are simplified; unreachable bodies of `WHILE(FALSE)` are removed. Dynamic loops retain their condition/update order. |
| Global optimization | Constant facts cross basic blocks when every incoming path agrees; branch pruning uses those facts. |
| Machine-dependent optimization | **Pending.** The M7 target ISA, register count, and cost model are not yet defined. No target-specific optimization is claimed. This mandatory handout item prevents claiming full M6 course completion at this checkpoint. |

Algebraic INT identities (`x+0`, `x-0`, `x*1`, `x/1`) and unreachable-instruction cleanup are additional conservative transformations. FLOAT identities, `x*0`, speculative division, array-guard removal, and motion of effects or traps are unsupported. The local DAG does not perform global CSE, loop-invariant code motion, strength reduction, or instruction selection.

## API and pass order

`sparq.optimization.optimize_program(ir_program, analysis=None)` accepts a complete verified canonical `IRProgram`. If supplied, `analysis` must be its exact `AnalysisResult`. It returns a new immutable `IRProgram` retaining the original semantic owner, routine owners, function order, source symbols, CALL targets, arguments, and source spans. It verifies the input and every pass result with `verify_program`. `OptimizationError` reports invalid input or failure without publishing partial output. The input remains unchanged. `analyze_routine(routine)` returns immutable `ControlFlowGraph` and `BasicBlock` records; `pass_names()` exposes the fixed order.

1. Remove CFG-unreachable instructions.
2. Propagate constants globally and fold only operations proved safe. Simplify eligible INT identities and constant branches.
3. Remove branches made unreachable by those decisions, including constant-false loop bodies.
4. Perform local expression-DAG CSE and temporary copy propagation.
5. Eliminate dead pure temporary definitions using backward liveness until no more instructions are removed.
6. Perform final unreachable cleanup.

The worklist constant analysis computes intersection of agreeing facts at joins. It does not interpret a branch condition while solving the original CFG. READ and CALL invalidate mutable scalar facts; array contents are never constant-propagated. A per-routine work limit produces a controlled error if the dataflow calculation does not converge promptly. Dead-code cleanup strictly decreases instruction count on each repeated pass. Each pass retains the same typed IR representation and is reverified before the next pass.

INT folding uses arbitrary-precision integer operations and explicitly computes truncation-toward-zero division and `a - quotient*b` remainder. A zero divisor is left as a `Binary` instruction at its original source position. A 4,096-bit result budget limits compile-time work without changing runtime semantics. FLOAT arithmetic is never folded, so nonfinite results and signed-zero behavior stay at their original runtime operation. INT-to-FLOAT is folded only for integers within the exact binary64 integer range, where conversion cannot fail or round. All potentially failing conversions remain. Pure arithmetic CSE uses captured values within one block, so it neither moves an operand evaluation nor duplicates a trap. `InitArray`, bounds checks, array accesses, CALL, READ, SHOW, FLOAT arithmetic, division/remainder, and potentially failing conversion are retained whenever reachable, even if their result is unused.

## Reproducible before/after demonstration

Run `.venv\Scripts\python -m sparq.tac examples/optimization.spq --compare`. `--optimize` displays only the verified optimized listing; the default command still displays unoptimized TAC. The [example](../examples/optimization.spq) is a valid source program, and both listings derive from actual canonical IR. It initializes `x` from `2 + 3 * 4`, copies through `y`, reads `z`, computes `(z + 1) + (z + 1)`, contains an unreachable `WHILE(FALSE)` body with a division by zero, and finally checks and reads an array element.

| Stage | START instructions | Observed change |
|---|---:|---|
| Original | 28 | Full source-order TAC. |
| Initial reachability | 28 | All instructions initially have a syntactic CFG path. |
| Constant propagation/folding | 28 | Replaces exact arithmetic with constants and the constant loop branch with `Jump`. |
| Branch/loop pruning | 24 | Removes the unreachable loop body and its division. |
| Local DAG/CSE | 24 | Replaces the second scalar load and duplicate `z + 1` with copies of the first results. |
| Dead-code/copy cleanup | 17 | Removes unused pure definitions and copies; retains source-visible work. |
| Final cleanup | 17 | No further change. |

Representative original fragment:

```text
BINARY STAR 3, 4 -> %t1
BINARY PLUS 2, %t1 -> %t2
INITSCALAR x, %t2
LOAD z -> %t6
BINARY PLUS %t6, 1 -> %t7
LOAD z -> %t8
BINARY PLUS %t8, 1 -> %t9
```

Representative optimized fragment:

```text
INITSCALAR x, Constant(INT, 14)
INITSCALAR y, Constant(INT, 14)
SHOW Constant(INT, 14)
READSCALAR z
LOAD z -> %t6
BINARY PLUS %t6, 1 -> %t7
BINARY PLUS %t7, %t7 -> %t10
```

The actual listing retains `READSCALAR`, `INITARRAY`, `CHECKBOUNDS`, `LOADELEMENT`, both reachable SHOW operations after READ, and `HALTSTART`. The division is removed only because `WHILE(FALSE)` cannot execute its body. These counts are structural instruction counts, not measured runtime speedups. The example executes no IR or VM instructions during compilation.

## Validation and limits

The optimized CLI follows lexer, parser, semantic analysis, TAC generation, optimization, verification, then rendering. Invalid input produces a controlled nonzero exit without a partial successful listing. The optimizer does not infer source types again, execute source, or prove full semantic equivalence. The verifier checks IR ownership and path availability; preserving side effects and trap order depends on the stated conservative pass rules and regression tests. Future target-specific optimizations require M7's approved machine model and reverification of their output.

At the M6 implementation checkpoint, focused tests cover exact INT folding, joins, loops, CSE, copies, effect barriers, traps, guards, calls, source spans, determinism, immutability, and CLI behavior. Full regression results are recorded in [MILESTONE_STATUS.md](MILESTONE_STATUS.md). The M7 array allocation-error precedence question remains open; this optimizer preserves runtime `InitArray` and does not decide that precedence.
