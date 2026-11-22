"""Complete source-to-TAC integration and whole-routine verifier checks."""

from dataclasses import replace

import pytest

from sparq.ir import (
    ArrayRef, BoolMergeTemp, BranchBool, Call, CheckBounds, CheckedElement,
    Constant, FunctionRef, HaltStart, IRProgram, InitArray, Jump, Label,
    LabelRef, LoadElement, Move, Return, Show, Temporary,
)
from sparq.ast_nodes import SourceSpan
from sparq.ir_verify import IRVerificationError, verify_program
from sparq.lexer import Lexer
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.symbols import ScalarType as T
from sparq.tac import TACGenerationError, TACGenerator, format_tac, generate_tac, main


def _compile(source):
    program = Parser(Lexer(source).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    return program, analysis, generate_tac(program, analysis)


def test_empty_start_and_deterministic_complete_listing():
    program, analysis, result = _compile("START {}")
    assert result.source_program is program and result.semantic_owner is analysis
    assert len(result.functions) == 0
    assert [type(item) for item in result.entry.instructions] == [HaltStart]
    assert format_tac(result) == "START\n  0000 HALTSTART"
    assert format_tac(result) == format_tac(generate_tac(program, analysis))
    assert format_tac(TACGenerator(program, analysis).generate()) == format_tac(result)
    session = TACGenerator(program, analysis)
    assert session.generate() is session.generate()


@pytest.mark.parametrize("declarations", [
    "INT i = 1; FLOAT f = 2.5; CHAR c = 'A'; STRING s = \"s\"; BOOL b = TRUE; SHOW(i); SHOW(f); SHOW(c); SHOW(s); SHOW(b);",
    "INT a[2] = {1, 2}; INT i = 0; a[i] = a[1] + 1; READ(a[0]); READ(i); SHOW(a[i]);",
    "WHEN (TRUE) { SHOW(1); } OTHERWISE { SHOW(2); } SELECT (1) { CASE 1: { SHOW(3); } DEFAULT: { SHOW(4); } }",
    "INT i = 0; WHILE (i < 2) { i = i + 1; } DO { i = i + 1; } WHILE (i < 4);",
    "BOOL a[1]; SHOW(FALSE AND a[99]); SHOW(TRUE OR a[99]);",
    "WHEN (FALSE) { SHOW(1); } SHOW(2);",
])
def test_complete_supported_start_constructs(declarations):
    _, _, result = _compile(f"START {{ {declarations} }}")
    assert verify_program(result) is result
    assert isinstance(result.entry.instructions[-1], HaltStart)


@pytest.mark.parametrize("header", [
    ";;", "INT i = 0;;", "; i < 2;", ";; i = i + 1",
    "INT i = 0; i < 2;", "INT i = 0;; i = i + 1",
    "; i < 2; i = i + 1", "INT i = 0; i < 2; i = i + 1",
])
def test_complete_repeat_header_combinations(header):
    _, _, result = _compile(f"START {{ INT i = 0; REPEAT ({header}) {{ SHOW(i); }} }}")
    assert verify_program(result) is result


def test_integrated_recursion_arrays_loops_conversions_and_io():
    source = (
        "FUNC fib(INT n) -> INT { WHEN (n < 2) { RETURN n; } "
        "OTHERWISE { RETURN fib(n - 1) + fib(n - 2); } } "
        "FUNC echo(FLOAT v) -> FLOAT { RETURN v; } "
        "START { INT a[2] = {1, 2}; INT i = 0; "
        "WHILE (i < 2) { WHEN (a[i] > 0 AND fib(i) >= 0) "
        "{ FLOAT x = echo(a[i]); SHOW(x); } OTHERWISE { SHOW(0); } i = i + 1; } "
        "READ(a[0]); SHOW(fib(a[0])); }"
    )
    _, semantic, result = _compile(source)
    assert len(result.functions) == 2
    assert any(isinstance(item, Call) and item.function.symbol is semantic.signatures[0]
               for function in result.functions for item in function.body.instructions)
    text = format_tac(result)
    assert "FUNC fib#" in text and "FUNC echo#" in text
    assert "CHECKBOUNDS" in text and "READELEMENT" in text
    assert "CONVERT" in text and "HALTSTART" in text
    assert text == format_tac(_compile(source)[2])


def test_forward_mutual_calls_and_all_seven_conversion_contexts():
    source = (
        "FUNC first(INT n) -> FLOAT { WHEN (n == 0) { RETURN 1; } "
        "OTHERWISE { RETURN second(n - 1); } } "
        "FUNC second(INT n) -> FLOAT { RETURN first(n); } "
        "FUNC takes(FLOAT x) -> FLOAT { RETURN x; } "
        "START { FLOAT s = 1; FLOAT a[1] = {1}; s = 2; a[0] = 3; "
        "SHOW(1 + 2.0); SHOW(takes(1)); SHOW(first(0)); }"
    )
    _, semantic, result = _compile(source)
    from sparq.ir import Convert
    conversions = [item for routine in (*[f.body for f in result.functions], result.entry)
                   for item in routine.instructions if isinstance(item, Convert)]
    assert len(conversions) >= 7
    assert [f.function.symbol for f in result.functions] == list(semantic.signatures)
    assert verify_program(result) is result


def test_nested_shadowed_symbols_and_implicit_void_return():
    _, analysis, result = _compile(
        "FUNC f() -> VOID { INT x = 1; { INT x = 2; SHOW(x); } SHOW(x); } "
        "START { f(); }"
    )
    body = result.functions[0].body
    symbols = [reference.symbol for reference in body.local_symbols]
    assert len(symbols) == 2 and symbols[0] is not symbols[1]
    assert symbols == [symbol for _, symbol in analysis.functions[0].body.declarations]
    assert isinstance(body.instructions[-1], Return) and body.instructions[-1].value is None
    assert verify_program(result) is result


def test_foreign_source_analysis_and_foreign_equal_call_rejected():
    source = "FUNC f() -> INT { RETURN 1; } START { SHOW(f()); }"
    program, analysis, result = _compile(source)
    other = Parser(Lexer(source).tokenize()).parse()
    with pytest.raises(TACGenerationError):
        TACGenerator(other, analysis)
    call = next(item for item in result.entry.instructions if isinstance(item, Call))
    foreign = replace(analysis.signatures[0])
    assert foreign == analysis.signatures[0] and foreign is not analysis.signatures[0]
    changed = replace(call, function=FunctionRef(foreign))
    tampered = replace(result, entry=replace(result.entry, instructions=tuple(
        changed if item is call else item for item in result.entry.instructions
    )))
    with pytest.raises(IRVerificationError, match="CALL target is foreign"):
        verify_program(tampered)


def test_foreign_equal_symbol_inventory_rejected():
    _, _, result = _compile("START { INT x; }")
    symbol = result.entry.local_symbols[0]
    cloned = replace(symbol, symbol=replace(symbol.symbol))
    tampered = replace(result, entry=replace(result.entry,
        local_symbols=(cloned,), instructions=(result.entry.instructions[-1],)))
    with pytest.raises(IRVerificationError, match="START symbol inventory"):
        verify_program(tampered)


def test_temporary_use_before_definition_and_partial_join_rejected():
    _, _, baseline = _compile("START {}")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    value = Temporary(owner, 1, T.INT)
    with pytest.raises(IRVerificationError, match="unavailable"):
        verify_program(replace(baseline, entry=replace(baseline.entry,
            instructions=(Show(owner, span, value), HaltStart(owner, span)))))
    # Use one owner's records throughout the direct routine.
    a, b, end = (LabelRef(owner, n) for n in (1, 2, 3))
    items = [BranchBool(owner, span, Constant(T.BOOL, True), a, b),
             Label(owner, span, a), Move(owner, span, value, Constant(T.INT, 1)),
             Jump(owner, span, end), Label(owner, span, b), Label(owner, span, end),
             Show(owner, span, value), HaltStart(owner, span)]
    tampered = replace(baseline, entry=replace(baseline.entry, instructions=tuple(items)))
    with pytest.raises(IRVerificationError, match="unavailable"):
        verify_program(tampered)


def test_bool_merge_requires_both_paths_and_accepts_disjoint_writes():
    _, _, baseline = _compile("START {}")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    yes, no, join = (LabelRef(owner, n) for n in (1, 2, 3))
    merge = BoolMergeTemp(owner, 1)
    prefix = [BranchBool(owner, span, Constant(T.BOOL, True), yes, no),
              Label(owner, span, yes), Move(owner, span, merge, Constant(T.BOOL, True)),
              Jump(owner, span, join), Label(owner, span, no)]
    suffix = [Label(owner, span, join), Show(owner, span, merge), HaltStart(owner, span)]
    missing = replace(baseline, entry=replace(baseline.entry, instructions=tuple(prefix + suffix)))
    with pytest.raises(IRVerificationError, match="unavailable"):
        verify_program(missing)
    complete = replace(baseline, entry=replace(baseline.entry, instructions=tuple(
        prefix + [Move(owner, span, merge, Constant(T.BOOL, False))] + suffix)))
    assert verify_program(complete) is complete


def test_bool_merge_sequential_writes_rejected():
    _, _, baseline = _compile("START {}")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    merge = BoolMergeTemp(owner, 1)
    tampered = replace(baseline, entry=replace(baseline.entry, instructions=(
        Move(owner, span, merge, Constant(T.BOOL, True)),
        Move(owner, span, merge, Constant(T.BOOL, False)),
        Show(owner, span, merge), HaltStart(owner, span),
    )))
    with pytest.raises(IRVerificationError, match="sequentially"):
        verify_program(tampered)


def test_guard_use_before_check_and_reinitialization_rejected():
    _, _, baseline = _compile("START { INT a[1]; }")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    array = baseline.entry.local_symbols[0]
    assert isinstance(array, ArrayRef)
    index = Constant(T.INT, 0)
    guard = CheckedElement(owner, 1, array, index)
    check = CheckBounds(owner, span, array, index, guard)
    load = LoadElement(owner, span, guard, Temporary(owner, 1, T.INT))
    init = InitArray(owner, span, array, 1, Constant(T.INT, 0))
    for items in ([init, load], [init, check, init, load]):
        tampered = replace(baseline, entry=replace(baseline.entry,
            instructions=tuple(items + [HaltStart(owner, span)])))
        with pytest.raises(IRVerificationError, match="unavailable"):
            verify_program(tampered)
    valid = replace(baseline, entry=replace(baseline.entry,
        instructions=(init, check, load, HaltStart(owner, span))))
    assert verify_program(valid) is valid


def test_guard_available_on_one_branch_only_is_rejected():
    _, _, baseline = _compile("START { INT a[1]; }")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    array = baseline.entry.local_symbols[0]
    index = Constant(T.INT, 0)
    guard = CheckedElement(owner, 1, array, index)
    yes, no, join = (LabelRef(owner, n) for n in (1, 2, 3))
    instructions = (InitArray(owner, span, array, 1, Constant(T.INT, 0)),
        BranchBool(owner, span, Constant(T.BOOL, True), yes, no),
        Label(owner, span, yes), CheckBounds(owner, span, array, index, guard),
        Jump(owner, span, join), Label(owner, span, no), Label(owner, span, join),
        LoadElement(owner, span, guard, Temporary(owner, 1, T.INT)),
        HaltStart(owner, span))
    tampered = replace(baseline, entry=replace(baseline.entry, instructions=instructions))
    with pytest.raises(IRVerificationError, match="unavailable"):
        verify_program(tampered)


def test_loop_fixed_point_preserves_and_kills_guard_facts():
    _, _, baseline = _compile("START { INT a[1]; }")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    array = baseline.entry.local_symbols[0]
    index = Constant(T.INT, 0)
    guard = CheckedElement(owner, 1, array, index)
    top, body, exit_ = (LabelRef(owner, n) for n in (1, 2, 3))
    prefix = (InitArray(owner, span, array, 1, Constant(T.INT, 0)),
              CheckBounds(owner, span, array, index, guard), Label(owner, span, top))
    suffix = (BranchBool(owner, span, Constant(T.BOOL, True), body, exit_),
              Label(owner, span, body), LoadElement(owner, span, guard,
              Temporary(owner, 1, T.INT)), Jump(owner, span, top),
              Label(owner, span, exit_), HaltStart(owner, span))
    valid = replace(baseline, entry=replace(baseline.entry, instructions=prefix + suffix))
    assert verify_program(valid) is valid
    stale = replace(baseline, entry=replace(baseline.entry, instructions=
        prefix + (InitArray(owner, span, array, 1, Constant(T.INT, 0)),) + suffix))
    with pytest.raises(IRVerificationError, match="unavailable"):
        verify_program(stale)


def test_reachable_fallthrough_rejected_but_infinite_loop_and_unreachable_use_allowed():
    _, _, baseline = _compile("START {}")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    with pytest.raises(IRVerificationError, match="falls through"):
        verify_program(replace(baseline, entry=replace(baseline.entry,
            instructions=(Show(owner, span, Constant(T.INT, 1)),))))
    label = LabelRef(owner, 1)
    loop = replace(baseline, entry=replace(baseline.entry, instructions=(
        Label(owner, span, label), Jump(owner, span, label),
        Show(owner, span, Temporary(owner, 1, T.INT)),
    )))
    assert verify_program(loop) is loop


def test_invalid_label_and_call_return_shapes_rejected_at_record_boundary():
    _, _, baseline = _compile("START {}")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    with pytest.raises(ValueError, match="undefined branch label"):
        replace(baseline.entry, instructions=(Jump(owner, span, LabelRef(owner, 7)),))
    with pytest.raises(ValueError, match="RETURN is only valid"):
        Return(owner, span)


def test_wrong_guard_binding_and_call_contract_rejected_at_record_boundary():
    _, _, baseline = _compile("START { INT a[1]; INT b[1]; }")
    owner, span = baseline.entry.owner, baseline.source_program.main.span
    first, second = baseline.entry.local_symbols
    index = Constant(T.INT, 0)
    mismatched = CheckedElement(owner, 1, second, index)
    with pytest.raises(ValueError, match="exact array and index"):
        CheckBounds(owner, span, first, index, mismatched)
    _, analysis, with_call = _compile(
        "FUNC f(INT x) -> INT { RETURN x; } START { SHOW(f(1)); }"
    )
    call = next(item for item in with_call.entry.instructions if isinstance(item, Call))
    with pytest.raises(ValueError, match="argument count"):
        replace(call, arguments=())
    with pytest.raises(ValueError, match="scalar operand type"):
        replace(call, arguments=(Constant(T.BOOL, True),))
    assert call.function.symbol is analysis.signatures[0]


def test_instruction_span_must_belong_to_owning_source_body():
    _, _, baseline = _compile("START {}")
    owner = baseline.entry.owner
    invalid = replace(baseline, entry=replace(baseline.entry, instructions=(
        HaltStart(owner, SourceSpan(40, 1, 40, 2)),
    )))
    with pytest.raises(IRVerificationError, match="span lies outside"):
        verify_program(invalid)


def test_large_integer_listing_is_bounded_without_losing_exact_ir_value():
    huge = "9" * 5000
    _, _, result = _compile(f"START {{ SHOW({huge}); }}")
    constant = result.entry.instructions[0].value
    assert constant.value == 10 ** 5000 - 1
    assert constant.lexeme == huge
    shown = format_tac(result)
    assert "bits=" in shown and len(shown) < 250


def test_generator_failure_invalidates_session_without_partial_publication(monkeypatch):
    program = Parser(Lexer("FUNC f() -> INT { RETURN 1; } START {}").tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    session = TACGenerator(program, analysis)
    def fail(_):
        raise ValueError("injected lowering failure")
    monkeypatch.setattr("sparq.tac.lower_function", fail)
    with pytest.raises(TACGenerationError):
        session.generate()
    with pytest.raises(TACGenerationError, match="discarded"):
        session.generate()


def test_cli_success_and_controlled_failure(tmp_path, capsys):
    good = tmp_path / "good.spq"
    good.write_text("START { SHOW(1); }", encoding="utf-8")
    assert main([str(good)]) == 0
    assert "HALTSTART" in capsys.readouterr().out
    bad = tmp_path / "bad.spq"
    bad.write_text("START { SHOW(missing); }", encoding="utf-8")
    assert main([str(bad)]) != 0
    captured = capsys.readouterr()
    assert not captured.out and "TAC compilation failed" in captured.err
