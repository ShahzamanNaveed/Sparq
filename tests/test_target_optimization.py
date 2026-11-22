"""Executable safety and effectiveness checks for machine-dependent target passes."""

from dataclasses import replace
import io
from pathlib import Path

import pytest

from sparq.ir import Constant
from sparq.lexer import Lexer
from sparq.optimization import optimize_program
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.symbols import ScalarType
from sparq.tac import generate_tac
from sparq.target import Op, Register, TargetInstruction, format_target, instruction_cost
from sparq.target_codegen import generate_target, main as target_main
from sparq.target_optimization import (
    TargetOptimizationError, optimize_target, optimize_target_with_report,
)
from sparq.vm import VMErrorCode, VMRuntimeError, main as vm_main, run_target, validate_target


def target_for(source, *, optimized_ir=False):
    program = Parser(Lexer(source).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    ir = generate_tac(program, analysis)
    return generate_target(optimize_program(ir, analysis) if optimized_ir else ir)


def paths(source):
    ordinary = target_for(source)
    machine, report = optimize_target_with_report(ordinary)
    combined = optimize_target(target_for(source, optimized_ir=True))
    return ordinary, machine, combined, report


def test_dag_reuses_repeated_pure_expression_and_reduces_cost():
    source = "START { INT x = 2; INT y = 3; INT a = x + y; INT b = x + y; SHOW(a); SHOW(b); }"
    ordinary, machine, combined, report = paths(source)
    assert report.dag_reuses >= 1
    assert report.stages[-1].instructions < report.stages[0].instructions
    assert report.stages[-1].estimated_cost < report.stages[0].estimated_cost
    assert run_target(ordinary).output == run_target(machine).output == run_target(combined).output == "5\n5\n"
    assert machine.source_ir is ordinary.source_ir
    assert validate_target(machine) is machine


def test_shared_expression_dependencies_have_a_real_dag_hit():
    source = "START { INT x = 4; INT y = 5; INT z = (x + y) * (x + y); SHOW(z); }"
    ordinary, machine, _, report = paths(source)
    assert report.dag_reuses >= 1
    assert run_target(machine).output == run_target(ordinary).output == "81\n"
    assert report.stages[-1].estimated_cost < report.stages[0].estimated_cost


def test_register_reuse_and_unused_spill_rules_on_source_target():
    source = "START { INT x = 2; INT y = x; SHOW(y); }"
    ordinary, machine, _, report = paths(source)
    assert (report.redundant_loads + report.dead_register_definitions
            + report.unused_temporary_spills) > 0
    assert report.stages[-1].estimated_cost < report.stages[0].estimated_cost
    assert run_target(machine).output == run_target(ordinary).output == "2\n"


def test_adjacent_redundant_load_and_const_without_new_register():
    target = target_for("START { INT x = 2; SHOW(x); }")
    owner = target.entry.owner
    span = target.entry.instructions[0].span
    slot = next(slot for slot in target.entry.slots if slot.symbol is not None)
    items = list(target.entry.instructions)
    show = next(i for i, item in enumerate(items) if item.opcode is Op.SHOW)
    items[show:show] = [
        TargetInstruction(owner, Op.LOAD, (Register.R0, slot), span),
        TargetInstruction(owner, Op.LOAD, (Register.R0, slot), span),
    ]
    input_target = replace(target, entry=replace(target.entry, instructions=tuple(items)))
    optimized, report = optimize_target_with_report(input_target)
    assert report.redundant_loads >= 1
    assert run_target(optimized).output == run_target(input_target).output == "2\n"
    assert len(optimized.entry.instructions) < len(input_target.entry.instructions)


@pytest.mark.parametrize("source,expected", [
    ("FUNC f(INT n) -> INT { WHEN (n == 0) { RETURN 1; } "
     "OTHERWISE { RETURN n * f(n - 1); } } START { SHOW(f(5)); }", "120\n"),
    ("FUNC a(INT n) -> BOOL { WHEN (n == 0) { RETURN TRUE; } "
     "OTHERWISE { RETURN b(n - 1); } } "
     "FUNC b(INT n) -> BOOL { WHEN (n == 0) { RETURN FALSE; } "
     "OTHERWISE { RETURN a(n - 1); } } START { SHOW(a(4)); }", "TRUE\n"),
    ("FUNC pair(INT a, INT b) -> INT { RETURN a * 10 + b; } "
     "FUNC side(INT x) -> INT { SHOW(x); RETURN x; } "
     "START { SHOW(pair(side(1), side(2))); }", "1\n2\n12\n"),
    ("START { INT a[2] = {1, 2}; INT i = 0; a[i] = a[1] + 3; "
     "SHOW(a[i]); SHOW(a[1]); }", "5\n2\n"),
    ("START { INT x = 0; WHILE (x < 2) { "
     "WHEN (x == 0) { SHOW(1); } OTHERWISE { SHOW(2); } x = x + 1; } }", "1\n2\n"),
    ("START { BOOL b = TRUE OR FALSE; BOOL c = FALSE AND b; "
     "SHOW(b); SHOW(c); }", "TRUE\nFALSE\n"),
    ("START { INT x = 1; WHEN (TRUE) { INT x = 2; SHOW(x); } SHOW(x); }", "2\n1\n"),
])
def test_original_machine_and_combined_execution(source, expected):
    ordinary, machine, combined, report = paths(source)
    assert all(run_target(target).output == expected for target in (ordinary, machine, combined))
    assert report.stages[-1].estimated_cost <= report.stages[0].estimated_cost
    assert all(validate_target(target) is target for target in (machine, combined))


@pytest.mark.parametrize("source,input_text,expected_output,fields", [
    ("START { INT x; READ(x); SHOW(x + 1); }", "8", "9\n", 1),
    ("START { INT a[1]; READ(a[0]); SHOW(a[0]); }", "11", "11\n", 1),
    ("START { FLOAT x; READ(x); SHOW(x); }", "-0.0", "-0.0\n", 1),
])
def test_io_order_and_input_consumption(source, input_text, expected_output, fields):
    ordinary, machine, combined, _ = paths(source)
    for target in (ordinary, machine, combined):
        result = run_target(target, input_stream=input_text)
        assert (result.output, result.consumed_fields) == (expected_output, fields)


@pytest.mark.parametrize("source,input_text,error,prior_output", [
    ("START { SHOW(1); SHOW(1 / 0); }", "", VMErrorCode.DIVISION_BY_ZERO, "1\n"),
    ("START { SHOW(1); SHOW(1 % 0); }", "", VMErrorCode.REMAINDER_BY_ZERO, "1\n"),
    ("START { FLOAT f = 2.0; REPEAT (INT i = 0; i < 1024; i = i + 1) "
     "{ f = f * 2.0; } }", "", VMErrorCode.NONFINITE_FLOAT, ""),
    ("START { FLOAT f = " + "9" * 400 + "; }", "", VMErrorCode.INT_TO_FLOAT, ""),
    ("START { INT a[1]; a[2] = 1 / 0; }", "", VMErrorCode.BOUNDS, ""),
    ("START { INT a[1]; READ(a[3]); }", "7", VMErrorCode.BOUNDS, ""),
    ("START { SHOW(FALSE AND 1 / 0 == 1); SHOW(1 / 0); }",
     "", VMErrorCode.DIVISION_BY_ZERO, "FALSE\n"),
])
def test_deferred_traps_and_error_precedence(source, input_text, error, prior_output):
    ordinary, machine, combined, _ = paths(source)
    for target in (ordinary, machine, combined):
        output = io.StringIO()
        with pytest.raises(VMRuntimeError) as info:
            run_target(target, input_stream=input_text, output_stream=output)
        assert info.value.code is error
        assert output.getvalue() == prior_output


def test_guard_checks_calls_and_branch_joins_are_not_removed():
    source = (
        "FUNC side() -> INT { SHOW(3); RETURN 1; } "
        "START { INT a[1]; BOOL b = FALSE; "
        "WHEN (b) { a[0] = side(); } OTHERWISE { a[0] = 5; } "
        "SHOW(a[0]); }"
    )
    ordinary, machine, combined, _ = paths(source)
    for target in (ordinary, machine, combined):
        assert run_target(target).output == "5\n"
    for target in (ordinary, machine):
        ops = [item.opcode for item in target.entry.instructions]
        assert Op.CHECK_BOUNDS in ops and Op.CALL in ops and Op.BRANCH_BOOL in ops


def test_no_dag_reuse_across_effects_or_trapping_arithmetic():
    sources = [
        "START { INT x = 2; INT y = 3; SHOW(x + y); SHOW(x + y); }",
        "START { INT x; READ(x); SHOW(x / 1); SHOW(x / 1); }",
        "START { FLOAT x = 0.1; FLOAT a = x + x; FLOAT b = x + x; SHOW(a); SHOW(b); }",
        "START { INT a[1]; SHOW(a[0]); SHOW(a[0]); }",
    ]
    for source in sources:
        ordinary = target_for(source)
        machine, report = optimize_target_with_report(ordinary)
        assert report.dag_reuses == 0
        assert report.stages[-1].estimated_cost <= report.stages[0].estimated_cost
        if "READ" not in source:
            assert run_target(machine).output == run_target(ordinary).output


def test_unused_trapping_operation_and_bounds_check_are_retained():
    divide = target_for("START { SHOW(1 / 0); }")
    items = list(divide.entry.instructions)
    binary = next(i for i, item in enumerate(items) if item.opcode is Op.BINARY)
    shortened = replace(divide, entry=replace(
        divide.entry, instructions=tuple(items[:binary + 1] + [items[-1]])
    ))
    optimized = optimize_target(shortened)
    assert Op.BINARY in [item.opcode for item in optimized.entry.instructions]
    with pytest.raises(VMRuntimeError) as info:
        run_target(optimized)
    assert info.value.code is VMErrorCode.DIVISION_BY_ZERO

    array = target_for("START { INT a[1]; SHOW(a[2]); }")
    items = list(array.entry.instructions)
    check = next(i for i, item in enumerate(items) if item.opcode is Op.CHECK_BOUNDS)
    shortened = replace(array, entry=replace(
        array.entry, instructions=tuple(items[:check + 1] + [items[-1]])
    ))
    optimized = optimize_target(shortened)
    assert Op.CHECK_BOUNDS in [item.opcode for item in optimized.entry.instructions]
    with pytest.raises(VMRuntimeError) as info:
        run_target(optimized)
    assert info.value.code is VMErrorCode.BOUNDS


def test_register_pressure_source_spans_and_large_integer():
    digits = "9" * 4300
    source = "START { INT a = " + digits + "; INT b = a + 1; SHOW(b); }"
    ordinary, machine, combined, _ = paths(source)
    expected = "1" + "0" * 4300 + "\n"
    assert all(run_target(target).output == expected for target in (ordinary, machine, combined))
    original_spans = {item.span for item in ordinary.entry.instructions}
    for item in machine.entry.instructions:
        assert item.span in original_spans
        assert item.owner is ordinary.entry.owner
        assert all(operand in (Register.R0, Register.R1, Register.R2)
                   for operand in item.operands if isinstance(operand, Register))


@pytest.mark.parametrize("first,second,expected", [
    (-0.0, 0.0, "0.0\n"),
    (0.0, -0.0, "-0.0\n"),
])
def test_redundant_const_rule_preserves_float_signed_zero(first, second, expected):
    target = target_for("START { SHOW(0.0); }")
    owner = target.entry.owner
    span = target.entry.instructions[0].span
    items = (
        TargetInstruction(owner, Op.CONST,
                          (Register.R0, Constant(ScalarType.FLOAT, first)), span),
        TargetInstruction(owner, Op.CONST,
                          (Register.R0, Constant(ScalarType.FLOAT, second)), span),
        TargetInstruction(owner, Op.SHOW, (Register.R0,), span),
        TargetInstruction(owner, Op.HALT, (), span),
    )
    manual = replace(target, entry=replace(target.entry, instructions=items))
    optimized = optimize_target(manual)
    assert run_target(manual).output == run_target(optimized).output == expected
    assert sum(item.opcode is Op.CONST for item in optimized.entry.instructions) == 1


def test_determinism_input_immutability_and_invalid_input_rejection():
    source = "START { INT a = 2; INT b = 3; SHOW(a + b); }"
    original = target_for(source)
    before = format_target(original)
    first, report = optimize_target_with_report(original)
    second = optimize_target(original)
    assert format_target(first) == format_target(second)
    assert format_target(original) == before
    assert original.entry.instructions is not first.entry.instructions
    assert first.source_ir is original.source_ir
    assert report.stages[-1].estimated_cost <= report.stages[0].estimated_cost
    malformed = replace(original, entry=replace(original.entry,
                         instructions=original.entry.instructions[:-1]))
    with pytest.raises(TargetOptimizationError):
        optimize_target(malformed)


def test_representative_course_example_three_path_comparison():
    source = Path("examples/optimization.spq").read_text(encoding="utf-8")
    ordinary, machine, combined, report = paths(source)
    assert (report.stages[0].instructions, report.stages[0].estimated_cost) == (63, 84)
    assert (report.stages[-1].instructions, report.stages[-1].estimated_cost) == (48, 69)
    combined_items = [item for routine in (*combined.functions, combined.entry)
                      for item in routine.instructions]
    assert (len(combined_items), sum(instruction_cost(item) for item in combined_items)) == (28, 46)
    for target in (ordinary, machine, combined):
        result = run_target(target, input_stream="5")
        assert (result.output, result.consumed_fields) == ("14\n12\n0\n", 1)


def test_listing_and_vm_cli_optimization_modes(tmp_path, capsys, monkeypatch):
    path = tmp_path / "example.spq"
    path.write_text("START { INT x = 2; SHOW(x + 3); }", encoding="utf-8")
    assert target_main([str(path)]) == 0
    ordinary = capsys.readouterr().out
    assert target_main([str(path), "--target-optimize"]) == 0
    optimized = capsys.readouterr().out
    assert ordinary != optimized
    assert target_main([str(path), "--optimize", "--target-optimize"]) == 0
    assert "START" in capsys.readouterr().out
    assert target_main([str(path), "--compare-target"]) == 0
    compared = capsys.readouterr().out
    assert all(label in compared for label in ("A: ordinary", "B: machine-dependent", "C: optimized TAC"))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    for arguments in ([], ["--target-optimize"], ["--optimize", "--target-optimize"]):
        assert vm_main([str(path), *arguments]) == 0
        assert capsys.readouterr().out == "5\n"
