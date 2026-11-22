"""Source-backed optimizer safety and observable TAC transformations."""

from dataclasses import replace
from pathlib import Path

import pytest

from sparq.ir import (
    Binary, BranchBool, Call, CheckBounds, Constant, Convert, IRProgram,
    InitArray, Jump, Load, ReadScalar, Show, Temporary,
)
from sparq.ir_verify import verify_program
from sparq.lexer import Lexer
from sparq.optimization import (
    OptimizationError, analyze_routine, optimize_program, pass_names,
)
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.symbols import ScalarType as T
from sparq.tac import format_tac, generate_tac, main
from sparq.token import TokenType


ROOT = Path(__file__).resolve().parents[1]


def _compiled(source):
    program = Parser(Lexer(source).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    original = generate_tac(program, analysis)
    optimized = optimize_program(original, analysis)
    assert verify_program(optimized) is optimized
    return original, optimized


def _instructions(result):
    return tuple(item for routine in (result.entry, *(f.body for f in result.functions))
                 for item in routine.instructions)


def test_reproducible_demo_reduces_instructions_and_preserves_effects():
    source = (ROOT / "examples" / "optimization.spq").read_text(encoding="utf-8")
    original, optimized = _compiled(source)
    assert len(original.entry.instructions) == 28
    assert len(optimized.entry.instructions) == 17
    assert sum(isinstance(item, ReadScalar) for item in optimized.entry.instructions) == 1
    assert sum(isinstance(item, CheckBounds) for item in optimized.entry.instructions) == 1
    assert sum(isinstance(item, InitArray) for item in optimized.entry.instructions) == 1
    assert not any(isinstance(item, Binary) and item.operator is TokenType.SLASH
                   for item in optimized.entry.instructions)
    assert [item.value.value for item in optimized.entry.instructions
            if isinstance(item, Show) and isinstance(item.value, Constant)] == [14]
    assert format_tac(original) == format_tac(generate_tac(original.source_program,
                                                            original.semantic_owner))


@pytest.mark.parametrize("expression,expected", [
    ("2 + 3 * 4", 14), ("-7 / 3", -2), ("-7 % 3", -1),
    ("7 / -3", -2), ("7 % -3", 1), ("NOT FALSE", True),
])
def test_exact_safe_folding(expression, expected):
    _, optimized = _compiled(f"START {{ SHOW({expression}); }}")
    show = next(item for item in optimized.entry.instructions if isinstance(item, Show))
    assert isinstance(show.value, Constant) and show.value.value == expected


def test_scalar_propagation_and_integer_algebraic_identity():
    _, optimized = _compiled("START { INT x = 3; INT y = x + 0; SHOW(y); }")
    assert not any(isinstance(item, Binary) for item in optimized.entry.instructions)
    assert next(item for item in optimized.entry.instructions if isinstance(item, Show)).value.value == 3
    _, unknown = _compiled("START { INT x; READ(x); SHOW(x + 0); }")
    assert not any(isinstance(item, Binary) for item in unknown.entry.instructions)
    assert any(isinstance(item, Load) for item in unknown.entry.instructions)


def test_local_dag_cse_and_copy_propagation_preserve_single_read():
    original, optimized = _compiled("START { INT x; READ(x); SHOW((x + 1) + (x + 1)); }")
    assert len(optimized.entry.instructions) < len(original.entry.instructions)
    assert sum(isinstance(item, Load) for item in optimized.entry.instructions) == 1
    assert sum(isinstance(item, Binary) for item in optimized.entry.instructions) == 2
    plus = [item for item in optimized.entry.instructions if isinstance(item, Binary)]
    assert plus[1].left == plus[1].right == plus[0].result


def test_read_and_call_invalidate_mutable_storage_facts():
    _, read = _compiled("START { INT x = 4; READ(x); SHOW(x); }")
    assert isinstance(next(item for item in read.entry.instructions if isinstance(item, Show)).value,
                      Temporary)
    _, called = _compiled("FUNC f() -> VOID { RETURN; } START { INT x = 4; f(); SHOW(x); }")
    assert any(isinstance(item, Call) for item in called.entry.instructions)
    assert isinstance(next(item for item in called.entry.instructions if isinstance(item, Show)).value,
                      Temporary)


def test_branch_join_propagates_only_equal_constants():
    equal = "START { BOOL b; READ(b); INT x = 0; WHEN (b) { x = 5; } OTHERWISE { x = 5; } SHOW(x); }"
    different = equal.replace("OTHERWISE { x = 5; }", "OTHERWISE { x = 6; }")
    _, same_result = _compiled(equal)
    _, different_result = _compiled(different)
    same = next(item for item in same_result.entry.instructions if isinstance(item, Show))
    different_show = next(item for item in different_result.entry.instructions
                          if isinstance(item, Show))
    assert isinstance(same.value, Constant) and same.value.value == 5
    assert not isinstance(different_show.value, Constant)


def test_loop_backedge_keeps_mutable_condition_dynamic():
    original, optimized = _compiled(
        "START { INT x = 0; WHILE (x < 3) { x = x + 1; } SHOW(x); }"
    )
    graph = analyze_routine(original.entry)
    assert len(graph.blocks) >= 3 and graph.backedges
    assert any(isinstance(item, BranchBool) for item in optimized.entry.instructions)
    assert not isinstance(next(item for item in optimized.entry.instructions
                               if isinstance(item, Show)).value, Constant)


def test_constant_false_loop_pruning_keeps_reachable_traps():
    source = "START { WHILE (FALSE) { SHOW(1 / 0); } SHOW(2 / 0); }"
    _, optimized = _compiled(source)
    divides = [item for item in optimized.entry.instructions
               if isinstance(item, Binary) and item.operator is TokenType.SLASH]
    assert len(divides) == 1
    assert any(isinstance(item, Show) for item in optimized.entry.instructions)


def test_do_while_false_preserves_first_body_execution():
    _, optimized = _compiled("START { DO { SHOW(1); } WHILE (FALSE); }")
    shows = [item for item in optimized.entry.instructions if isinstance(item, Show)]
    assert len(shows) == 1 and shows[0].value.value == 1


def test_select_selector_call_remains_single_and_ordered():
    source = (
        "FUNC f() -> INT { RETURN 1; } "
        "START { SELECT (f()) { CASE 1: { SHOW(1); } DEFAULT: { SHOW(2); } } }"
    )
    _, optimized = _compiled(source)
    items = optimized.entry.instructions
    calls = [i for i, item in enumerate(items) if isinstance(item, Call)]
    assert len(calls) == 1
    assert calls[0] < next(i for i, item in enumerate(items) if isinstance(item, Show))


def test_array_allocation_and_initializer_trap_order_unchanged():
    _, optimized = _compiled("START { INT a[1] = {1 / 0}; }")
    items = optimized.entry.instructions
    allocation = next(i for i, item in enumerate(items) if isinstance(item, InitArray))
    division = next(i for i, item in enumerate(items) if isinstance(item, Binary))
    assert allocation < division


def test_short_circuit_bool_merge_and_array_guards_remain_verified():
    source = "START { BOOL a[1]; BOOL b; READ(b); SHOW(b AND a[0]); SHOW(b OR a[0]); }"
    original, optimized = _compiled(source)
    assert len([x for x in optimized.entry.instructions if isinstance(x, CheckBounds)]) == 2
    assert len([x for x in optimized.entry.instructions if isinstance(x, ReadScalar)]) == 1
    assert len([x for x in optimized.entry.instructions if isinstance(x, BranchBool)]) >= 2
    assert original is not optimized


def test_float_overflow_and_huge_int_conversion_are_retained():
    large_float = "1." + "0" * 300
    _, overflow = _compiled(f"START {{ SHOW({large_float} * {large_float}); }}")
    assert any(isinstance(item, Binary) and item.result.type is T.FLOAT
               for item in overflow.entry.instructions)
    huge = "9" * 5000
    _, conversion = _compiled(f"START {{ SHOW({huge} + 0.0); }}")
    assert any(isinstance(item, Convert) for item in conversion.entry.instructions)
    assert len(format_tac(conversion)) < 700


def test_float_signed_zero_identity_and_int_zero_multiplication_remain():
    _, signed = _compiled("START { SHOW(-0.0 + 0.0); }")
    assert any(isinstance(item, Binary) and item.result.type is T.FLOAT
               for item in signed.entry.instructions)
    _, trapping = _compiled("START { SHOW((1 / 0) * 0); }")
    assert [item.operator for item in trapping.entry.instructions if isinstance(item, Binary)] == [
        TokenType.SLASH, TokenType.STAR,
    ]


def test_bounds_check_precedes_call_and_argument_conversion():
    huge = "9" * 5000
    source = (
        "FUNC f(FLOAT x) -> FLOAT { RETURN x; } "
        f"START {{ FLOAT a[1]; SHOW(f(a[0])); a[0] = f({huge}) / 1.0; }}"
    )
    _, optimized = _compiled(source)
    items = optimized.entry.instructions
    checks = [i for i, item in enumerate(items) if isinstance(item, CheckBounds)]
    calls = [i for i, item in enumerate(items) if isinstance(item, Call)]
    assert len(checks) == len(calls) == 2
    assert checks[0] < calls[0] and checks[1] < calls[1]
    assert checks[1] < next(i for i, item in enumerate(items) if isinstance(item, Convert)) < calls[1]


def test_array_reinitialization_and_both_checks_are_preserved():
    source = "START { INT a[1]; SHOW(a[0]); { INT b[1]; SHOW(b[0]); } SHOW(a[0]); }"
    _, optimized = _compiled(source)
    assert sum(isinstance(item, InitArray) for item in optimized.entry.instructions) == 2
    assert sum(isinstance(item, CheckBounds) for item in optimized.entry.instructions) == 3


def test_function_return_conversion_and_shadowed_storage_identity():
    source = (
        "FUNC f() -> FLOAT { RETURN 1; } "
        "START { INT x = 1; { INT x = 2; SHOW(x); } SHOW(x); SHOW(f()); }"
    )
    original, optimized = _compiled(source)
    assert [reference.symbol for reference in optimized.entry.local_symbols] == [
        reference.symbol for reference in original.entry.local_symbols
    ]
    assert optimized.entry.local_symbols[0].symbol is not optimized.entry.local_symbols[1].symbol
    assert len([item for item in optimized.entry.instructions if isinstance(item, Show)]) == 3
    assert any(isinstance(item, Call) for item in optimized.entry.instructions)


def test_unused_manual_trapping_division_is_not_deleted():
    original, _ = _compiled("START {}")
    owner, span = original.entry.owner, original.source_program.main.span
    division = Binary(owner, span, TokenType.SLASH, Constant(T.INT, 1),
                      Constant(T.INT, 0), Temporary(owner, 1, T.INT))
    manual = replace(original, entry=replace(original.entry,
        instructions=(division, original.entry.instructions[-1])))
    assert verify_program(manual) is manual
    optimized = optimize_program(manual)
    assert isinstance(optimized.entry.instructions[0], Binary)


def test_unused_manual_float_operation_is_not_deleted():
    original, _ = _compiled("START {}")
    owner, span = original.entry.owner, original.source_program.main.span
    operation = Binary(owner, span, TokenType.STAR, Constant(T.FLOAT, 1e300),
                       Constant(T.FLOAT, 1e300), Temporary(owner, 1, T.FLOAT))
    manual = replace(original, entry=replace(original.entry,
        instructions=(operation, original.entry.instructions[-1])))
    optimized = optimize_program(manual)
    assert isinstance(optimized.entry.instructions[0], Binary)


def test_nested_calls_recursion_and_return_ownership_survive():
    source = (
        "FUNC f(INT n) -> INT { WHEN (n == 0) { RETURN 1; } "
        "OTHERWISE { RETURN f(n - 1) + 1; } } "
        "START { SHOW(f(2)); }"
    )
    original, optimized = _compiled(source)
    assert len(optimized.functions) == 1
    assert [call.function.symbol for call in _instructions(optimized)
            if isinstance(call, Call)] == [original.functions[0].function.symbol] * 2
    assert original.functions[0].body.owner is optimized.functions[0].body.owner


def test_determinism_input_immutability_and_exact_analysis():
    source = "START { INT x = 2 + 2; SHOW(x); }"
    program = Parser(Lexer(source).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    original = generate_tac(program, analysis)
    before = format_tac(original)
    first = optimize_program(original, analysis)
    second = optimize_program(original, analysis)
    assert format_tac(original) == before
    assert format_tac(first) == format_tac(second)
    assert first is not original and first.entry.owner is original.entry.owner
    foreign = SemanticAnalyzer(program).analyze()
    with pytest.raises(OptimizationError, match="exact owning"):
        optimize_program(original, foreign)
    with pytest.raises(OptimizationError, match="IRProgram"):
        optimize_program(object())


def test_pass_failure_does_not_publish_partial_program(monkeypatch):
    original, _ = _compiled("START { SHOW(1 + 2); }")
    before = format_tac(original)
    def fail(_):
        raise ValueError("injected pass failure")
    monkeypatch.setattr("sparq.optimization._propagate_fold", fail)
    monkeypatch.setattr("sparq.optimization._PASSES", (("injected", fail),))
    with pytest.raises(OptimizationError, match="verified optimized"):
        optimize_program(original)
    assert format_tac(original) == before


def test_cli_default_optimize_compare_and_invalid_source(tmp_path, capsys):
    path = tmp_path / "program.spq"
    path.write_text("START { SHOW(2 + 3); }", encoding="utf-8")
    assert main([str(path)]) == 0
    default = capsys.readouterr().out
    assert "BINARY" in default
    assert main([str(path), "--optimize"]) == 0
    optimized = capsys.readouterr().out
    assert "BINARY" not in optimized and "Constant(INT, 5)" in optimized
    assert main([str(path), "--compare"]) == 0
    comparison = capsys.readouterr().out
    assert "ORIGINAL TAC" in comparison and "OPTIMIZED TAC" in comparison
    path.write_text("START { SHOW(unknown); }", encoding="utf-8")
    assert main([str(path), "--optimize"]) != 0
    captured = capsys.readouterr()
    assert not captured.out and "SemanticError" in captured.err


def test_fixed_pass_order_and_all_existing_examples_compile():
    assert pass_names() == (
        "unreachable", "global_constant_propagation_and_folding",
        "constant_branch_and_loop_pruning", "local_expression_dag_cse",
        "dead_code_and_copy_cleanup", "final_unreachable_cleanup",
    )
    for path in (ROOT / "examples").glob("*.spq"):
        original, optimized = _compiled(path.read_text(encoding="utf-8"))
        assert isinstance(original, IRProgram) and isinstance(optimized, IRProgram)
