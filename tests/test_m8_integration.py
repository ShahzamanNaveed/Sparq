"""Independent source-backed acceptance probes for the three compiler paths."""

from dataclasses import replace
import io
import random

import pytest

from sparq.lexer import Lexer
from sparq.ir_verify import IRVerificationError, verify_program
from sparq.optimization import optimize_program
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.tac import generate_tac
from sparq.target import Op, Register, TargetInstruction
from sparq.target_codegen import generate_target
from sparq.target_optimization import optimize_target
from sparq.vm import VMErrorCode, VMRuntimeError, VirtualMachine, validate_target


def _paths(source):
    program = Parser(Lexer(source).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    original_ir = generate_tac(program, analysis)
    ordinary = generate_target(original_ir)
    return (
        ordinary,
        optimize_target(ordinary),
        optimize_target(generate_target(optimize_program(original_ir, analysis))),
    )


@pytest.mark.parametrize("source,input_text,expected,fields", [
    (
        "FUNC factorial(INT n) -> INT { WHEN (n == 0) { RETURN 1; } "
        "OTHERWISE { RETURN n * factorial(n - 1); } } "
        "START { SHOW(factorial(5)); }",
        "", "120\n", 0,
    ),
    (
        "START { INT a[3] = {4, 7, 9}; INT index[2] = {2, 0}; "
        "SHOW(a[index[0]]); SHOW(a[index[1]]); }",
        "", "9\n4\n", 0,
    ),
    (
        "START { INT x = 0; WHILE (x < 2) { x = x + 1; } "
        "DO { x = x + 1; } WHILE (x < 4); "
        "REPEAT (INT i = 0; i < 2; i = i + 1) { x = x + i; } "
        "WHEN (x == 5) { SELECT (x) { CASE 5: { SHOW(x); } "
        "DEFAULT: { SHOW(0); } } } OTHERWISE { SHOW(-1); } }",
        "", "5\n", 0,
    ),
    (
        "FUNC side() -> BOOL { SHOW(99); RETURN TRUE; } "
        "START { INT x = 7; WHEN (TRUE) { INT x = 2; SHOW(x); } "
        "SHOW(x); SHOW(FALSE AND side()); SHOW(TRUE OR side()); }",
        "", "2\n7\nFALSE\nTRUE\n", 0,
    ),
    (
        "START { FLOAT x = 2; INT y; READ(y); SHOW(x + y); "
        "SHOW(-23 / 7); SHOW(-23 % 7); }",
        "3", "5.0\n-3\n-2\n", 1,
    ),
])
def test_three_paths_match_independent_success_oracles(source, input_text, expected, fields):
    for target in _paths(source):
        assert validate_target(target) is target
        result = VirtualMachine(target, input_stream=input_text, max_steps=20_000).run()
        assert (result.output, result.consumed_fields) == (expected, fields)


@pytest.mark.parametrize("source,input_text,expected_output,fields,code", [
    ("START { SHOW(4); SHOW(1 / 0); }", "", "4\n", 0, VMErrorCode.DIVISION_BY_ZERO),
    ("START { INT a[1]; READ(a[2]); }", "8", "", 0, VMErrorCode.BOUNDS),
    ("START { INT a[1]; a[2] = 1 / 0; }", "", "", 0, VMErrorCode.BOUNDS),
    ("START { INT x; READ(x); SHOW(x); READ(x); }", "6", "6\n", 1,
     VMErrorCode.INPUT_EXHAUSTED),
])
def test_three_paths_preserve_error_precedence(source, input_text, expected_output, fields, code):
    for target in _paths(source):
        output = io.StringIO()
        machine = VirtualMachine(target, input_stream=input_text,
                                 output_stream=output, max_steps=20_000)
        with pytest.raises(VMRuntimeError) as error:
            machine.run()
        assert error.value.code is code
        assert (output.getvalue(), machine.consumed_fields) == (expected_output, fields)


@pytest.mark.parametrize("seed", [3, 11, 29, 47, 83])
def test_recorded_seed_arithmetic_oracle(seed):
    randomizer = random.Random(seed)
    left, right, divisor = (randomizer.randint(-100, 100),
                            randomizer.randint(-100, 100),
                            randomizer.randint(1, 9))
    source = (f"START {{ INT a = {left}; INT b = {right}; "
              f"SHOW(a + b * {divisor}); SHOW(a - b); }}")
    expected = f"{left + right * divisor}\n{left - right}\n"
    for target in _paths(source):
        assert VirtualMachine(target, max_steps=20_000).run().output == expected


def test_invalid_target_rejected_before_show():
    target = _paths("START { SHOW(1); }")[0]
    instructions = list(target.entry.instructions)
    instructions.insert(-1, TargetInstruction(target.entry.owner, Op.SHOW,
                                               (Register.R1,), instructions[-2].span))
    invalid = replace(target, entry=replace(target.entry,
                                            instructions=tuple(instructions)))
    output = io.StringIO()
    with pytest.raises(VMRuntimeError) as error:
        VirtualMachine(invalid, output_stream=output)
    assert error.value.code is VMErrorCode.INVALID_TARGET
    assert output.getvalue() == ""


def test_incomplete_source_backed_ir_rejected_before_target_generation():
    program = Parser(Lexer("START { SHOW(1); }").tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    ir = generate_tac(program, analysis)
    incomplete = replace(ir, entry=replace(ir.entry,
                                           instructions=ir.entry.instructions[:-1]))
    with pytest.raises(IRVerificationError):
        verify_program(incomplete)
    with pytest.raises((IRVerificationError, ValueError)):
        generate_target(incomplete)


def test_bounded_step_and_call_depth_errors():
    looping = _paths("START { WHILE (TRUE) { } }")[0]
    with pytest.raises(VMRuntimeError) as step:
        VirtualMachine(looping, max_steps=10).run()
    assert step.value.code is VMErrorCode.STEP_LIMIT

    recursive = _paths(
        "FUNC f(INT n) -> INT { WHEN (n == 0) { RETURN 0; } "
        "OTHERWISE { RETURN f(n - 1); } } START { SHOW(f(8)); }"
    )[0]
    with pytest.raises(VMRuntimeError) as depth:
        VirtualMachine(recursive, max_call_depth=3, max_steps=1000).run()
    assert depth.value.code is VMErrorCode.CALL_DEPTH
