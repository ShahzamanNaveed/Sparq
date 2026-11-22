"""Observable execution tests for the three-register Sparq VM."""

from dataclasses import replace
import io

import pytest

from sparq.lexer import Lexer
from sparq.optimization import optimize_program
from sparq.parser import Parser
from sparq.program_semantic import SemanticAnalyzer
from sparq.tac import generate_tac
from sparq.ir import Constant, LabelRef
from sparq.symbols import ScalarType
from sparq.target import Op, Register, TargetInstruction
from sparq.target_codegen import generate_target
from sparq.token import TokenType
from sparq.vm import (
    VMErrorCode, VMRuntimeError, VirtualMachine, main, run_target,
    validate_target,
)


def target_for(source: str, *, optimized: bool = False):
    program = Parser(Lexer(source).tokenize()).parse()
    analysis = SemanticAnalyzer(program).analyze()
    ir = generate_tac(program, analysis)
    if optimized:
        ir = optimize_program(ir, analysis)
    return generate_target(ir)


def execute(source: str, *, optimized: bool = False, input_text: str = "", **options):
    return run_target(target_for(source, optimized=optimized), input_stream=input_text, **options)


@pytest.mark.parametrize("optimized", [False, True])
def test_scalar_defaults_and_show_formats(optimized):
    source = (
        'START { INT i; FLOAT f; CHAR c; STRING s; BOOL b; '
        'SHOW(i); SHOW(f); SHOW(c); SHOW(s); SHOW(b); '
        'f = -0.0; SHOW(f); SHOW(2.0); }'
    )
    assert execute(source, optimized=optimized).output == "0\n0.0\n\0\n\nFALSE\n-0.0\n2.0\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_signed_integer_arithmetic_and_assignments(optimized):
    source = (
        "START { INT x = -7; SHOW(x / 3); SHOW(x % 3); "
        "SHOW(7 / -3); SHOW(7 % -3); SHOW(-7 / -3); SHOW(-7 % -3); "
        "x = x * 2 + 1; SHOW(x); }"
    )
    assert execute(source, optimized=optimized).output == "-2\n-1\n-2\n1\n2\n-1\n-13\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_float_arithmetic_conversion_and_comparison(optimized):
    source = (
        "START { INT i = 2; FLOAT f = i + 0.5; SHOW(f); "
        "SHOW(0.1 + 0.2); SHOW(f / 2.0); SHOW(f > 2.0); "
        "SHOW('a' == 'a'); SHOW(\"hi\" != \"bye\"); }"
    )
    assert execute(source, optimized=optimized).output == (
        "2.5\n0.30000000000000004\n1.25\nTRUE\nTRUE\nTRUE\n"
    )


@pytest.mark.parametrize("optimized", [False, True])
def test_array_defaults_initializers_guards_and_nested_indexes(optimized):
    source = (
        "START { INT a[3] = {2, 1, 0}; INT b[3]; INT i = 0; "
        "b[a[i]] = 7; SHOW(a[2]); SHOW(b[2]); SHOW(b[a[1]]); "
        "a[1] = 4; SHOW(a[1]); }"
    )
    assert execute(source, optimized=optimized).output == "0\n7\n0\n4\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_all_five_array_element_types(optimized):
    source = (
        "START { INT i[1]; FLOAT f[1]; CHAR c[1]; STRING s[1]; BOOL b[1]; "
        "SHOW(i[0]); SHOW(f[0]); SHOW(c[0]); SHOW(s[0]); SHOW(b[0]); "
        "f[0] = 2; c[0] = 'z'; s[0] = \"hi\"; b[0] = TRUE; "
        "SHOW(f[0]); SHOW(c[0]); SHOW(s[0]); SHOW(b[0]); }"
    )
    assert execute(source, optimized=optimized).output == (
        "0\n0.0\n\0\n\nFALSE\n2.0\nz\nhi\nTRUE\n"
    )


@pytest.mark.parametrize("optimized", [False, True])
def test_when_select_and_all_loop_forms(optimized):
    source = (
        "START { INT x = 0; WHEN (FALSE) { SHOW(99); } "
        "OTHERWISE { SHOW(1); } WHEN (TRUE) { SHOW(2); } "
        "SELECT (-1) { CASE -1: { SHOW(3); } DEFAULT: { SHOW(99); } } "
        "SELECT ('a') { CASE 'a': { SHOW(4); } } "
        'SELECT ("x") { CASE "y": { SHOW(99); } DEFAULT: { SHOW(5); } } '
        "WHILE (x < 2) { SHOW(x); x = x + 1; } "
        "DO { SHOW(x); x = x + 1; } WHILE (x < 3); "
        "REPEAT (INT i = 0; i < 2; i = i + 1) { SHOW(i); } }"
    )
    assert execute(source, optimized=optimized).output == "1\n2\n3\n4\n5\n0\n1\n2\n0\n1\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_repeat_all_header_combinations(optimized):
    sources = [
        "REPEAT (INT i = 0; i < 1; i = i + 1) { SHOW(i); }",
        "INT i = 0; REPEAT (; i < 1; i = i + 1) { SHOW(i); }",
        "REPEAT (INT i = 0; i < 1; ) { SHOW(i); i = i + 1; }",
        "INT i = 0; REPEAT (; i < 1; ) { SHOW(i); i = i + 1; }",
        "REPEAT (INT i = 0; ; i = i + 1) { SHOW(i); WHEN (i == 0) { RETURN; } }",
        "INT i = 0; REPEAT (; ; i = i + 1) { SHOW(i); RETURN; }",
        "REPEAT (INT i = 0; ; ) { SHOW(i); RETURN; }",
        "REPEAT (; ; ) { SHOW(0); RETURN; }",
    ]
    for statement in sources[:4]:
        assert execute("START { " + statement + " }", optimized=optimized).output == "0\n"
    for statement in sources[4:]:
        source = "FUNC f() -> VOID { " + statement + " } START { f(); }"
        assert execute(source, optimized=optimized).output == "0\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_calls_recursion_mutation_shadowing_and_void(optimized):
    source = (
        "FUNC fib(INT n) -> INT { WHEN (n < 2) { RETURN n; } "
        "OTHERWISE { RETURN fib(n - 1) + fib(n - 2); } } "
        "FUNC change(INT n) -> INT { n = n + 4; "
        "WHEN (TRUE) { INT n = 9; SHOW(n); } RETURN n; } "
        "FUNC quiet() -> VOID { SHOW(8); } "
        "START { INT a = 1; SHOW(fib(6)); SHOW(change(a)); "
        "SHOW(a); quiet(); change(2); }"
    )
    assert execute(source, optimized=optimized).output == "8\n9\n5\n1\n8\n9\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_nested_calls_forward_calls_argument_order_and_return_conversion(optimized):
    source = (
        "FUNC first(INT x) -> INT { SHOW(x); RETURN x; } "
        "FUNC pair(INT a, INT b) -> INT { RETURN a * 10 + b; } "
        "FUNC forward() -> FLOAT { RETURN later(); } "
        "FUNC later() -> INT { RETURN 3; } "
        "START { SHOW(pair(first(1), first(2))); SHOW(forward()); }"
    )
    assert execute(source, optimized=optimized).output == "1\n2\n12\n3.0\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_mutual_recursion_and_independent_frames(optimized):
    source = (
        "FUNC even(INT n) -> BOOL { WHEN (n == 0) { RETURN TRUE; } "
        "OTHERWISE { RETURN odd(n - 1); } } "
        "FUNC odd(INT n) -> BOOL { WHEN (n == 0) { RETURN FALSE; } "
        "OTHERWISE { RETURN even(n - 1); } } "
        "START { SHOW(even(8)); SHOW(odd(8)); SHOW(odd(9)); }"
    )
    assert execute(source, optimized=optimized).output == "TRUE\nFALSE\nTRUE\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_short_circuit_skips_calls_and_traps(optimized):
    source = (
        "FUNC side() -> BOOL { SHOW(99); RETURN TRUE; } "
        "START { BOOL a = FALSE AND side(); BOOL b = TRUE OR side(); "
        "SHOW(a); SHOW(b); SHOW(FALSE AND 1 / 0 == 1); }"
    )
    assert execute(source, optimized=optimized).output == "FALSE\nTRUE\nFALSE\n"


@pytest.mark.parametrize("optimized", [False, True])
def test_read_all_types_and_consumption(optimized):
    source = (
        "START { INT i; FLOAT f; CHAR c; STRING s; BOOL b; "
        "INT a[1]; READ(i); READ(f); READ(c); READ(s); READ(b); READ(a[0]); "
        "SHOW(i); SHOW(f); SHOW(c); SHOW(s); SHOW(b); SHOW(a[0]); }"
    )
    result = execute(source, optimized=optimized,
                     input_text="-12 +2.5 Ω hello TRUE 7")
    assert result.output == "-12\n2.5\nΩ\nhello\nTRUE\n7\n"
    assert result.consumed_fields == 6


@pytest.mark.parametrize("optimized", [False, True])
def test_indexed_read_evaluates_index_once_before_input(optimized):
    source = (
        "FUNC index() -> INT { SHOW(5); RETURN 0; } "
        "START { INT a[1]; READ(a[index()]); SHOW(a[0]); }"
    )
    result = execute(source, optimized=optimized, input_text="7")
    assert result.output == "5\n7\n"
    assert result.consumed_fields == 1


@pytest.mark.parametrize("optimized", [False, True])
def test_select_default_still_evaluates_trapping_selector(optimized):
    source = "START { SELECT (1 / 0) { DEFAULT: { SHOW(1); } } }"
    vm = VirtualMachine(target_for(source, optimized=optimized))
    with pytest.raises(VMRuntimeError) as info:
        vm.run()
    assert info.value.code is VMErrorCode.DIVISION_BY_ZERO
    assert vm.output == ""


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("source,code,output,consumed", [
    ("START { SHOW(1 / 0); }", VMErrorCode.DIVISION_BY_ZERO, "", 0),
    ("START { SHOW(1 % 0); }", VMErrorCode.REMAINDER_BY_ZERO, "", 0),
    ("START { FLOAT f = 1.0 / 0.0; }", VMErrorCode.DIVISION_BY_ZERO, "", 0),
    ("START { INT a[1]; SHOW(a[1]); }", VMErrorCode.BOUNDS, "", 0),
    ("START { INT a[1]; READ(a[2]); }", VMErrorCode.BOUNDS, "", 0),
    ("START { INT x; READ(x); }", VMErrorCode.INPUT_EXHAUSTED, "", 0),
    ("START { INT x; READ(x); }", VMErrorCode.INVALID_READ, "", 1),
])
def test_controlled_runtime_errors(optimized, source, code, output, consumed):
    input_text = ("oops" if code is VMErrorCode.INVALID_READ else ""
                  if code is VMErrorCode.INPUT_EXHAUSTED else "7")
    vm = VirtualMachine(target_for(source, optimized=optimized), input_stream=input_text)
    with pytest.raises(VMRuntimeError) as info:
        vm.run()
    assert info.value.code is code
    assert info.value.span is not None
    assert vm.output == output
    assert vm.consumed_fields == consumed


@pytest.mark.parametrize("optimized", [False, True])
def test_bounds_precede_rhs_and_read_input(optimized):
    source = (
        "FUNC side() -> INT { SHOW(99); RETURN 1 / 0; } "
        "START { INT a[1]; a[2] = side(); }"
    )
    vm = VirtualMachine(target_for(source, optimized=optimized))
    with pytest.raises(VMRuntimeError) as info:
        vm.run()
    assert info.value.code is VMErrorCode.BOUNDS
    assert vm.output == ""


@pytest.mark.parametrize("optimized", [False, True])
def test_read_after_prior_output_and_invalid_field_consumption(optimized):
    source = "START { INT x = 7; SHOW(x); READ(x); SHOW(x); }"
    vm = VirtualMachine(target_for(source, optimized=optimized), input_stream="bad 12")
    with pytest.raises(VMRuntimeError) as info:
        vm.run()
    assert info.value.code is VMErrorCode.INVALID_READ
    assert vm.output == "7\n"
    assert vm.consumed_fields == 1
    source = "START { FLOAT f; READ(f); SHOW(f); }"
    with pytest.raises(VMRuntimeError) as info:
        execute(source, optimized=optimized, input_text="1e3")
    assert info.value.code is VMErrorCode.INVALID_READ


@pytest.mark.parametrize("optimized", [False, True])
def test_allocation_precedes_initializer_and_reinitialization(optimized):
    source = "START { INT a[2] = {1 / 0, 2}; }"
    with pytest.raises(VMRuntimeError) as info:
        execute(source, optimized=optimized, max_array_elements=1)
    assert info.value.code is VMErrorCode.ALLOCATION
    source = (
        "START { INT i = 0; WHILE (i < 2) { "
        "INT a[2] = {i + 1, 0}; SHOW(a[0]); SHOW(a[1]); i = i + 1; } }"
    )
    assert execute(source, optimized=optimized).output == "1\n0\n2\n0\n"


def test_huge_declared_array_fails_before_host_allocation():
    vm = VirtualMachine(target_for("START { INT a[1000000000000]; SHOW(1); }"))
    with pytest.raises(VMRuntimeError) as info:
        vm.run()
    assert info.value.code is VMErrorCode.ALLOCATION
    assert vm.output == ""


@pytest.mark.parametrize("optimized", [False, True])
def test_large_integer_show_and_input(optimized):
    digits = "9" * 5000
    source = "START { INT i; READ(i); SHOW(i); SHOW(" + digits + "); }"
    result = execute(source, optimized=optimized, input_text=digits)
    assert result.output == digits + "\n" + digits + "\n"
    assert result.consumed_fields == 1


@pytest.mark.parametrize("optimized", [False, True])
def test_conversion_float_overflow_and_call_depth(optimized):
    huge = "9" * 400
    source = "START { FLOAT f = " + huge + "; }"
    with pytest.raises(VMRuntimeError) as info:
        execute(source, optimized=optimized)
    assert info.value.code is VMErrorCode.INT_TO_FLOAT
    source = "START { FLOAT x = 1.0; REPEAT (INT i = 0; i < 1024; i = i + 1) { x = x * 2.0; } }"
    with pytest.raises(VMRuntimeError) as info:
        execute(source, optimized=optimized)
    assert info.value.code is VMErrorCode.NONFINITE_FLOAT
    source = "FUNC f() -> VOID { f(); } START { f(); }"
    with pytest.raises(VMRuntimeError) as info:
        execute(source, optimized=optimized, max_call_depth=8)
    assert info.value.code is VMErrorCode.CALL_DEPTH


def test_default_depth_limit_uses_vm_frames_not_python_recursion():
    source = (
        "FUNC depth(INT n) -> INT { WHEN (n == 0) { RETURN 0; } "
        "OTHERWISE { RETURN depth(n - 1); } } "
        "START { SHOW(depth(1000)); }"
    )
    with pytest.raises(VMRuntimeError) as info:
        execute(source)
    assert info.value.code is VMErrorCode.CALL_DEPTH


def test_explicit_step_safeguard_and_one_shot_session():
    vm = VirtualMachine(target_for("START { WHILE (TRUE) { } }"), max_steps=20)
    with pytest.raises(VMRuntimeError) as info:
        vm.run()
    assert info.value.code is VMErrorCode.STEP_LIMIT
    with pytest.raises(VMRuntimeError) as info:
        vm.run()
    assert info.value.code is VMErrorCode.INVALID_STATE


def test_invalid_target_reachable_fallthrough_and_operator():
    target = target_for("START { SHOW(1 + 2); }")
    entry = replace(target.entry, instructions=target.entry.instructions[:-1])
    malformed = replace(target, entry=entry)
    with pytest.raises(VMRuntimeError) as info:
        VirtualMachine(malformed)
    assert info.value.code is VMErrorCode.INVALID_TARGET
    instructions = list(target.entry.instructions)
    position = next(i for i, item in enumerate(instructions) if item.opcode is Op.BINARY)
    instructions[position] = replace(instructions[position], operands=(
        Register.R2, TokenType.AND, Register.R0, Register.R1, instructions[position].operands[4],
    ))
    malformed = replace(target, entry=replace(target.entry, instructions=tuple(instructions)))
    with pytest.raises(VMRuntimeError) as info:
        VirtualMachine(malformed)
    assert info.value.code is VMErrorCode.INVALID_TARGET


def test_reallocation_invalidates_exact_array_guard():
    target = target_for("START { INT a[1]; a[0] = 5; }")
    instructions = list(target.entry.instructions)
    check = next(i for i, item in enumerate(instructions) if item.opcode is Op.CHECK_BOUNDS)
    allocation = next(item for item in instructions if item.opcode is Op.ALLOC_ARRAY)
    instructions.insert(check + 1, allocation)
    altered = replace(target, entry=replace(target.entry, instructions=tuple(instructions)))
    with pytest.raises(VMRuntimeError) as info:
        run_target(altered)
    assert info.value.code is VMErrorCode.INVALID_TARGET


def _wrong_const_before(source, marker, replacement, *, function=False):
    target = target_for(source)
    routine = target.functions[0] if function else target.entry
    instructions = list(routine.instructions)
    position = next(i for i, item in enumerate(instructions) if item.opcode is marker)
    assert instructions[position - 1].opcode is Op.CONST
    constant = instructions[position - 1]
    instructions[position - 1] = replace(
        constant, operands=(constant.operands[0], replacement)
    )
    changed = replace(routine, instructions=tuple(instructions))
    return replace(target, functions=(changed,)) if function else replace(target, entry=changed)


@pytest.mark.parametrize("source,marker,wrong,function", [
    ("FUNC f() -> INT { RETURN 1; } START { SHOW(9); SHOW(f()); }",
     Op.RETURN, Constant(ScalarType.BOOL, True), True),
    ("START { SHOW(9); INT x = 1; SHOW(x); }",
     Op.INIT_SCALAR, Constant(ScalarType.BOOL, True), False),
    ("FUNC f(INT x) -> INT { RETURN x; } START { SHOW(9); SHOW(f(1)); }",
     Op.PUSH_ARG, Constant(ScalarType.BOOL, True), False),
    ("START { SHOW(9); INT a[1]; a[0] = 1; }",
     Op.STORE_ELEMENT, Constant(ScalarType.BOOL, True), False),
    ("START { SHOW(9); WHEN (TRUE) { SHOW(1); } }",
     Op.BRANCH_BOOL, Constant(ScalarType.INT, 1), False),
    ("START { SHOW(9); SHOW(1 + 2); }",
     Op.BINARY, Constant(ScalarType.BOOL, True), False),
    ("START { SHOW(9); FLOAT f = 1; SHOW(f); }",
     Op.TO_FLOAT, Constant(ScalarType.BOOL, True), False),
])
def test_wrong_register_type_rejected_before_execution(source, marker, wrong, function):
    malformed = _wrong_const_before(source, marker, wrong, function=function)
    output = io.StringIO()
    input_stream = io.StringIO("17")
    with pytest.raises(VMRuntimeError) as info:
        validate_target(malformed)
    assert info.value.code is VMErrorCode.INVALID_TARGET
    with pytest.raises(VMRuntimeError) as info:
        VirtualMachine(malformed, input_stream=input_stream, output_stream=output)
    assert info.value.code is VMErrorCode.INVALID_TARGET
    assert output.getvalue() == ""
    assert input_stream.tell() == 0


def _manual_start(builder):
    base = target_for("START { }")
    owner = base.entry.owner
    span = base.entry.instructions[0].span

    def instruction(opcode, *operands):
        return TargetInstruction(owner, opcode, operands, span)

    items = builder(owner, instruction)
    return replace(base, entry=replace(base.entry, instructions=tuple(items)))


def test_register_use_before_definition_rejected():
    malformed = _manual_start(lambda owner, emit: (
        emit(Op.SHOW, Register.R0), emit(Op.HALT),
    ))
    with pytest.raises(VMRuntimeError) as info:
        validate_target(malformed)
    assert info.value.code is VMErrorCode.INVALID_TARGET


def test_scalar_slot_load_before_initialization_rejected():
    target = target_for("START { INT x; SHOW(x); }")
    slot = next(slot for slot in target.entry.slots if slot.symbol is not None)
    span = target.entry.instructions[0].span
    owner = target.entry.owner
    instructions = (
        TargetInstruction(owner, Op.LOAD, (Register.R0, slot), span),
        TargetInstruction(owner, Op.SHOW, (Register.R0,), span),
        TargetInstruction(owner, Op.HALT, (), span),
    )
    malformed = replace(target, entry=replace(target.entry, instructions=instructions))
    with pytest.raises(VMRuntimeError) as info:
        validate_target(malformed)
    assert info.value.code is VMErrorCode.INVALID_TARGET


def _branch_join(right_kind):
    def build(owner, emit):
        true_label = LabelRef(owner, 1)
        false_label = LabelRef(owner, 2)
        join_label = LabelRef(owner, 3)
        return (
            emit(Op.CONST, Register.R0, Constant(ScalarType.BOOL, True)),
            emit(Op.BRANCH_BOOL, Register.R0, true_label, false_label),
            emit(Op.LABEL, true_label),
            emit(Op.CONST, Register.R1, Constant(ScalarType.INT, 2)),
            emit(Op.JUMP, join_label),
            emit(Op.LABEL, false_label),
            emit(Op.CONST, Register.R1, Constant(right_kind, True if right_kind is ScalarType.BOOL else 3)),
            emit(Op.JUMP, join_label),
            emit(Op.LABEL, join_label),
            emit(Op.CONST, Register.R2, Constant(ScalarType.INT, 4)),
            emit(Op.BINARY, Register.R0, TokenType.PLUS, Register.R1, Register.R2, ScalarType.INT),
            emit(Op.SHOW, Register.R0),
            emit(Op.HALT),
        )
    return _manual_start(build)


def test_conflicting_register_types_across_branch_paths_rejected():
    with pytest.raises(VMRuntimeError) as info:
        validate_target(_branch_join(ScalarType.BOOL))
    assert info.value.code is VMErrorCode.INVALID_TARGET


def test_same_register_type_on_both_branch_paths_is_valid():
    valid = _branch_join(ScalarType.INT)
    assert validate_target(valid) is valid
    assert run_target(valid).output == "6\n"


def test_register_can_be_reassigned_a_new_type_before_use():
    valid = _manual_start(lambda owner, emit: (
        emit(Op.CONST, Register.R0, Constant(ScalarType.BOOL, True)),
        emit(Op.CONST, Register.R0, Constant(ScalarType.INT, 5)),
        emit(Op.SHOW, Register.R0), emit(Op.HALT),
    ))
    assert run_target(valid).output == "5\n"


def test_loop_backedge_type_fixed_point():
    def build(owner, emit):
        loop = LabelRef(owner, 1)
        done = LabelRef(owner, 2)
        return (
            emit(Op.CONST, Register.R0, Constant(ScalarType.INT, 0)),
            emit(Op.LABEL, loop),
            emit(Op.CONST, Register.R1, Constant(ScalarType.INT, 1)),
            emit(Op.BINARY, Register.R0, TokenType.PLUS, Register.R0, Register.R1, ScalarType.INT),
            emit(Op.CONST, Register.R2, Constant(ScalarType.BOOL, False)),
            emit(Op.BRANCH_BOOL, Register.R2, loop, done),
            emit(Op.LABEL, done), emit(Op.SHOW, Register.R0), emit(Op.HALT),
        )
    assert run_target(_manual_start(build)).output == "1\n"


def test_loop_backedge_conflicting_type_rejected():
    def build(owner, emit):
        loop = LabelRef(owner, 1)
        done = LabelRef(owner, 2)
        return (
            emit(Op.CONST, Register.R0, Constant(ScalarType.INT, 0)),
            emit(Op.LABEL, loop),
            emit(Op.CONST, Register.R1, Constant(ScalarType.INT, 1)),
            emit(Op.BINARY, Register.R2, TokenType.PLUS, Register.R0, Register.R1, ScalarType.INT),
            emit(Op.CONST, Register.R0, Constant(ScalarType.BOOL, False)),
            emit(Op.BRANCH_BOOL, Register.R0, loop, done),
            emit(Op.LABEL, done), emit(Op.HALT),
        )
    with pytest.raises(VMRuntimeError) as info:
        validate_target(_manual_start(build))
    assert info.value.code is VMErrorCode.INVALID_TARGET


def test_valid_infinite_loop_and_unreachable_type_error():
    def build(owner, emit):
        loop = LabelRef(owner, 1)
        return (emit(Op.LABEL, loop), emit(Op.JUMP, loop),
                emit(Op.SHOW, Register.R0))
    infinite = _manual_start(build)
    assert validate_target(infinite) is infinite
    with pytest.raises(VMRuntimeError) as info:
        run_target(infinite, max_steps=9)
    assert info.value.code is VMErrorCode.STEP_LIMIT

    def dead(owner, emit):
        end = LabelRef(owner, 1)
        return (emit(Op.JUMP, end), emit(Op.SHOW, Register.R0),
                emit(Op.LABEL, end), emit(Op.HALT))
    unreachable = _manual_start(dead)
    assert run_target(unreachable).output == ""


def test_call_clobbers_caller_registers_for_validation():
    target = target_for("FUNC f() -> VOID { RETURN; } START { SHOW(9); f(); }")
    instructions = list(target.entry.instructions)
    call = next(i for i, item in enumerate(instructions) if item.opcode is Op.CALL)
    const = TargetInstruction(target.entry.owner, Op.CONST,
                              (Register.R1, Constant(ScalarType.INT, 4)),
                              instructions[call].span)
    show = TargetInstruction(target.entry.owner, Op.SHOW,
                             (Register.R1,), instructions[call].span)
    instructions.insert(call, const)
    instructions.insert(call + 2, show)
    malformed = replace(target, entry=replace(target.entry, instructions=tuple(instructions)))
    with pytest.raises(VMRuntimeError) as info:
        validate_target(malformed)
    assert info.value.code is VMErrorCode.INVALID_TARGET


def test_validation_finishes_before_any_show_or_read():
    source = "START { SHOW(9); INT x; READ(x); SHOW(1 + 2); }"
    malformed = _wrong_const_before(source, Op.BINARY, Constant(ScalarType.BOOL, True))
    output = io.StringIO()
    input_stream = io.StringIO("17")
    with pytest.raises(VMRuntimeError) as info:
        VirtualMachine(malformed, input_stream=input_stream, output_stream=output)
    assert info.value.code is VMErrorCode.INVALID_TARGET
    assert output.getvalue() == ""
    assert input_stream.tell() == 0


def test_valid_original_and_optimized_target_type_analysis():
    sources = [
        "START { INT a[2] = {1, 2}; SHOW(a[1]); }",
        "FUNC f(INT x) -> FLOAT { RETURN x; } START { SHOW(f(3)); }",
        "START { INT x = 0; WHILE (x < 2) { SHOW(x); x = x + 1; } }",
    ]
    for source in sources:
        for optimized in (False, True):
            target = target_for(source, optimized=optimized)
            assert validate_target(target) is target


def test_streaming_output_and_cli(tmp_path, capsys, monkeypatch):
    target = target_for('START { SHOW("hello"); }')
    output = io.StringIO()
    result = run_target(target, output_stream=output)
    assert result.output == output.getvalue() == "hello\n"
    path = tmp_path / "hello.spq"
    path.write_text('START { SHOW("hello"); }', encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main([str(path)]) == 0
    assert capsys.readouterr().out == "hello\n"
    assert main([str(path), "--optimize"]) == 0
    assert capsys.readouterr().out == "hello\n"
    path.write_text("START { SHOW(1 / 0); }", encoding="utf-8")
    assert main([str(path)]) == 3
    assert "DIVISION_BY_ZERO" in capsys.readouterr().err
    path.write_text("START { SHOW(; }", encoding="utf-8")
    assert main([str(path)]) == 2
    assert "compilation error" in capsys.readouterr().err
