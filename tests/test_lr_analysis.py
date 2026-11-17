"""Check the teaching LR tables against selected hand-derived checkpoints."""

import pytest

from tools.lr_analysis import (
    DOCUMENT, END, Action, G0, G1, Grammar, Item, Production,
    analyze, closure, conflict_kind, document_with_computed, goto,
    render_computed, trace,
)


@pytest.fixture(scope="module")
def examples():
    return analyze(G0), analyze(G1)


def test_g0_closure_and_goto_match_hand_items(examples):
    g0, _ = examples
    assert g0.states[0] == frozenset({Item(0, 0), Item(1, 0)})
    assert closure(G0, frozenset({Item(1, 2)})) == frozenset({
        Item(1, 2), Item(2, 0), Item(3, 0),
    })
    assert goto(G0, g0.states[0], "id") == frozenset({Item(1, 1)}) == g0.states[1]
    assert goto(G0, g0.states[3], "V") == frozenset({Item(1, 3)}) == g0.states[6]


def test_g1_critical_closure_and_goto_match_hand_items(examples):
    _, g1 = examples
    assert g1.states[0] == frozenset({Item(i, 0) for i in range(6)})
    assert goto(G1, g1.states[0], "L") == frozenset({Item(1, 1), Item(5, 1)})
    assert g1.states[4] == frozenset({Item(1, 1), Item(5, 1)})
    assert goto(G1, g1.states[1], "*") == g1.states[1]


def test_state_numbering_is_deterministic_and_every_edge_is_a_goto(examples):
    for grammar, result, count in ((G0, examples[0], 8), (G1, examples[1], 10)):
        assert len(result.states) == count
        assert analyze(grammar) == result
        assert set(range(count)) == {0} | {target for target in result.transitions.values()}
        for (source, symbol), target in result.transitions.items():
            assert goto(grammar, result.states[source], symbol) == result.states[target]
        for source, state in enumerate(result.states):
            for symbol in grammar.symbols:
                target = goto(grammar, state, symbol)
                if target:
                    assert (source, symbol) in result.transitions
                else:
                    assert (source, symbol) not in result.transitions


def test_g0_lr0_and_slr_reductions_match_follow_restrictions(examples):
    g0, _ = examples
    assert G0.terminals == ("id", "=", ";", "int")
    assert g0.follow["S"] == {END}
    assert g0.follow["V"] == {";"}
    assert not g0.lr0.conflicts and not g0.slr.conflicts
    for terminal in G0.terminals + (END,):
        assert g0.lr0.actions[4, terminal] == (Action("reduce", 2),)
        assert g0.lr0.actions[5, terminal] == (Action("reduce", 3),)
        assert g0.lr0.actions[7, terminal] == (Action("reduce", 1),)
    assert g0.slr.actions[4, ";"] == (Action("reduce", 2),)
    assert g0.slr.actions[5, ";"] == (Action("reduce", 3),)
    assert g0.slr.actions[7, END] == (Action("reduce", 1),)
    assert (4, "id") not in g0.slr.actions
    assert (7, ";") not in g0.slr.actions


def test_shifts_and_gotos_use_the_same_dfa_in_lr0_and_slr(examples):
    for result in examples:
        assert result.lr0.gotos == result.slr.gotos
        for (source, symbol), target in result.transitions.items():
            if symbol in result.grammar.terminals:
                expected = Action("shift", target)
                assert expected in result.lr0.actions[source, symbol]
                assert expected in result.slr.actions[source, symbol]
            else:
                assert result.lr0.gotos[source, symbol] == target
                assert result.slr.gotos[source, symbol] == target


def test_every_reduction_cell_matches_a_completed_item_and_lookahead_rule(examples):
    for result in examples:
        terminals = result.grammar.terminals + (END,)
        for slr, table in ((False, result.lr0), (True, result.slr)):
            for state, items in enumerate(result.states):
                for index, production in enumerate(result.grammar.productions[1:], start=1):
                    completed = Item(index, len(production.rhs)) in items
                    for terminal in terminals:
                        expected = completed and (
                            not slr or terminal in result.follow[production.lhs]
                        )
                        present = Action("reduce", index) in table.actions.get(
                            (state, terminal), ()
                        )
                        assert present == expected


def test_g0_valid_and_invalid_traces_show_exact_reductions(examples):
    g0, _ = examples
    valid = ("id", "=", "int", ";", END)
    invalid = ("id", "=", ";", END)
    for table in (g0.lr0, g0.slr):
        accepted = trace(g0, table, valid)
        assert accepted.accepted
        assert [step.action for step in accepted.steps] == [
            "s1", "s3", "s5", "r3", "s7", "r1", "accept",
        ]
        assert [(step.production, step.goto) for step in accepted.steps
                if step.production] == [("P3", "6"), ("P1", "2")]
        assert accepted.steps[-1].states == (0, 2)
        assert accepted.steps[-1].symbols == ("S",)
        rejected = trace(g0, table, invalid)
        assert not rejected.accepted
        assert rejected.steps[-1].states == (0, 1, 3)
        assert rejected.steps[-1].remaining == (";", END)
        assert rejected.steps[-1].action == "error: empty ACTION cell"


def test_g1_conflict_is_retained_in_both_tables(examples):
    _, g1 = examples
    assert g1.follow["S"] == {END}
    assert g1.follow["L"] == {"=", END}
    assert g1.follow["R"] == {"=", END}
    expected = {(4, "="): (Action("shift", 8), Action("reduce", 5))}
    assert g1.lr0.conflicts == expected
    assert g1.slr.conflicts == expected
    assert g1.lr0.actions[4, "="] == expected[4, "="]
    assert g1.slr.actions[4, "="] == expected[4, "="]
    assert conflict_kind(expected[4, "="]) == "shift/reduce"
    assert (4, "*") in g1.lr0.actions and (4, "*") not in g1.slr.actions
    stopped = trace(g1, g1.slr, ("id", "=", "id", END))
    assert not stopped.accepted
    assert stopped.steps[-1].action == "conflict: s8/r5"


def test_deliberate_reduce_reduce_conflict_is_not_overwritten():
    grammar = Grammar("RR", (
        Production("P0", "S'", ("S",)),
        Production("P1", "S", ("A",)),
        Production("P2", "S", ("B",)),
        Production("P3", "A", ("id",)),
        Production("P4", "B", ("id",)),
    ))
    result = analyze(grammar)
    completed = next(i for i, state in enumerate(result.states)
                     if {Item(3, 1), Item(4, 1)} <= state)
    expected = (Action("reduce", 3), Action("reduce", 4))
    assert result.lr0.conflicts[completed, END] == expected
    assert result.slr.conflicts[completed, END] == expected
    assert conflict_kind(expected) == "reduce/reduce"
    stopped = trace(result, result.slr, ("id", END))
    assert not stopped.accepted and stopped.steps[-1].action == "conflict: r3/r4"


def test_accept_is_only_from_completed_augmented_rule_on_end_marker(examples):
    for result in examples:
        for table in (result.lr0, result.slr):
            accepts = {(state, terminal) for (state, terminal), actions in table.actions.items()
                       if Action("accept") in actions}
            assert len(accepts) == 1
            state, terminal = next(iter(accepts))
            assert terminal == END
            assert Item(0, 1) in result.states[state]
            assert all(Action("reduce", 0) not in actions for actions in table.actions.values())


def test_documented_tables_and_traces_match_fresh_calculation(examples):
    document = DOCUMENT.read_text(encoding="utf-8")
    computed = render_computed(*examples)
    assert document_with_computed(document, computed) == document
    assert "ACTION[I4, =]" in computed
    assert "s8/r5" in computed
