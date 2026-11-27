# Sparq

Sparq is a statically typed language built for the CS4031 Compiler Construction project. Its Python compiler translates a Sparq program into three-address code (TAC), generates instructions for a three-register machine, and runs them on a virtual machine.

## Try the marks program

Use Python 3.11 or newer. From the repository root, run the following command. On Windows, you can substitute `py` for `python`.

```sh
python -m sparq.vm examples/marks.spq
```

Enter `80 75 85` and press Enter. If the terminal is still waiting for input, signal end of input with Ctrl+Z then Enter on Windows, or Ctrl+D on Linux/macOS. The program prints

```text
240
Distinction
```

[Read the program](examples/marks.spq). It reads three integer marks (assumed to be out of 100) into an array, totals them with a `REPEAT` loop, and calls `grade`. Totals of 240 or higher earn a distinction, 150–239 earn a pass, and lower totals fail. A `SELECT` statement prints the corresponding message.

## Follow the compiler

These commands use a four-line program with no input. The [worked walkthrough](docs/VIVA_WALKTHROUGH.md) connects each listing to the Python functions that produce it.

```sh
python -m sparq.lexer examples/expression.spq
python -m sparq.program_semantic examples/expression.spq
python -m sparq.tac examples/expression.spq --compare
python -m sparq.target_codegen examples/expression.spq --optimize --target-optimize
python -m sparq.vm examples/expression.spq --optimize --target-optimize
```

## Project references

- [Language syntax and grammar](docs/SPARQ_LANGUAGE_SPEC.md)
- [Parsing theory](docs/PARSER_THEORY.md), [full Sparq LL(1) analysis](docs/LL1_ANALYSIS.md), and [LR table demonstrations](docs/LR_DEMONSTRATIONS.md)
- [Semantic analysis](docs/SEMANTIC_ANALYSIS.md) and [attribute evaluation](docs/SDD_SDT_DEMONSTRATIONS.md)
- [TAC generation](docs/INTERMEDIATE_CODE_GENERATION.md) and [worked TAC examples](docs/IR_DEMONSTRATIONS.md)
- [Optimization passes](docs/CODE_OPTIMIZATION.md) and [target machine](docs/TARGET_ARCHITECTURE.md)
- [Course requirement mapping](docs/FINAL_COMPLIANCE_AUDIT.md) and [milestone history](docs/MILESTONE_STATUS.md)

## Run the tests

```sh
python -m pip install -e ".[test]"
python -m pytest -q
```

## Academic integrity

The assignment requires all three group members to participate in the language design, implementation, testing, and documentation; understand the complete project; and defend it in the viva. Plagiarism and sharing complete work between groups are prohibited. External tools, libraries, and code must be acknowledged. The group remains responsible for independently understanding and defending its work.
