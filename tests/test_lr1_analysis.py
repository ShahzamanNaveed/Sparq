"""Hand checkpoints and invariants for the CLR(1)/LALR(1) demonstrations."""

import pytest

from tools.lr_analysis import (
    DOCUMENT, END, EPSILON, Action, G0, G1, G2, Grammar, Item, LR1Item,
    Production, analyze, analyze_lr1, closure_lr1, conflict_kind,
    document_with_computed, document_with_lr1_computed, first_sequence_lr1,
    first_sets_lr1, goto_lr1, lr0_core, merge_lr1_cores, render_computed,
    render_lr1_computed, trace,
)


@pytest.fixture(scope="module")
def examples():
    return analyze_lr1(G1), analyze_lr1(G2)


def test_first_beta_lookahead_and_nullable_suffix_closure():
    grammar = Grammar("nullable", (
        Production("P0", "S'", ("S",)),
        Production("P1", "S", ("A", "B")),
        Production("P2", "A", ("a",)),
        Production("P3", "B", ("b",)),
        Production("P4", "B", ()),
    ))
    first = first_sets_lr1(grammar)
    assert first["B"] == {"b", EPSILON}
    assert first_sequence_lr1(("B", END), first, set(grammar.nonterminals)) == {"b", END}
    initial = closure_lr1(grammar, frozenset({LR1Item(0, 0, END)}), first)
    assert LR1Item(2, 0, "b") in initial
    assert LR1Item(2, 0, END) in initial
    assert LR1Item(2, 0, EPSILON) not in initial
    after_a = goto_lr1(grammar, initial, "A", first)
    assert {LR1Item(1, 1, END), LR1Item(3, 0, END), LR1Item(4, 0, END)} <= after_a


def test_epsilon_reduction_on_empty_input_preserves_state_and_uses_goto():
    grammar = Grammar("empty", (
        Production("P0", "S'", ("S",)),
        Production("P1", "S", ()),
    ))
    for automaton in (analyze_lr1(grammar).canonical, analyze_lr1(grammar).lalr):
        result = trace(automaton, automaton.table, (END,))
        assert result.accepted
        reduction, acceptance = result.steps
        assert reduction.action == "r1" and reduction.production == "P1"
        assert reduction.states == (0,) and reduction.symbols == ()
        assert reduction.goto == str(automaton.table.gotos[0, "S"])
        assert acceptance.states == (0, int(reduction.goto))
        assert acceptance.symbols == ("S",) and acceptance.action == "accept"
        assert not trace(automaton, automaton.table, ("x", END)).accepted


def test_epsilon_reduction_inside_nonempty_parse_pops_no_states():
    grammar = Grammar("nullable", (
        Production("P0", "S'", ("S",)),
        Production("P1", "S", ("A", "B")),
        Production("P2", "A", ("a",)),
        Production("P3", "B", ("b",)),
        Production("P4", "B", ()),
    ))
    automaton = analyze_lr1(grammar).canonical
    result = trace(automaton, automaton.table, ("a", END))
    assert result.accepted
    epsilon_index = next(index for index, step in enumerate(result.steps)
                         if step.production == "P4")
    before = result.steps[epsilon_index]
    after = result.steps[epsilon_index + 1]
    assert before.symbols == ("A",) and after.states[:-1] == before.states
    assert after.states == before.states + (int(before.goto),)
    assert after.symbols == ("A", "B")
    assert any(step.production == "P1" for step in result.steps)
    assert not trace(automaton, automaton.table, ("a", "a", END)).accepted


def test_g1_initial_closure_and_critical_goto_have_hand_derived_lookaheads(examples):
    g1, _ = examples
    i0 = g1.canonical.states[0]
    assert i0 == frozenset({
        LR1Item(0, 0, END), LR1Item(1, 0, END), LR1Item(2, 0, END),
        LR1Item(3, 0, "="), LR1Item(4, 0, "="),
        LR1Item(3, 0, END), LR1Item(4, 0, END), LR1Item(5, 0, END),
    })
    assert goto_lr1(G1, i0, "L") == g1.canonical.states[4] == frozenset({
        LR1Item(1, 1, END), LR1Item(5, 1, END),
    })
    assert LR1Item(5, 1, "=") not in g1.canonical.states[4]
    assert g1.canonical.states[8] >= {
        LR1Item(1, 2, END), LR1Item(5, 0, END),
        LR1Item(3, 0, END), LR1Item(4, 0, END),
    }


def test_g2_a_and_b_closures_keep_complementary_lookaheads(examples):
    _, g2 = examples
    after_a = g2.canonical.states[1]
    after_b = g2.canonical.states[2]
    assert after_a == frozenset({
        LR1Item(1, 1, END), LR1Item(3, 1, END),
        LR1Item(5, 0, "c"), LR1Item(6, 0, "d"),
    })
    assert after_b == frozenset({
        LR1Item(2, 1, END), LR1Item(4, 1, END),
        LR1Item(5, 0, "d"), LR1Item(6, 0, "c"),
    })
    assert goto_lr1(G2, after_a, "e") == g2.canonical.states[4] == frozenset({
        LR1Item(5, 1, "c"), LR1Item(6, 1, "d"),
    })
    assert goto_lr1(G2, after_b, "e") == g2.canonical.states[7] == frozenset({
        LR1Item(5, 1, "d"), LR1Item(6, 1, "c"),
    })


def test_canonical_collection_is_deterministic_and_every_edge_recomputes(examples):
    for grammar, result in ((G1, examples[0]), (G2, examples[1])):
        assert analyze_lr1(grammar) == result
        assert len(result.canonical.states) == 14
        assert len(set(result.canonical.states)) == len(result.canonical.states)
        assert {0} | set(result.canonical.transitions.values()) == set(range(14))
        first = first_sets_lr1(grammar)
        for (source, symbol), target in result.canonical.transitions.items():
            assert goto_lr1(grammar, result.canonical.states[source], symbol, first) == (
                result.canonical.states[target]
            )


def test_g1_clr_and_lalr_remove_slr_shift_reduce_conflict(examples):
    g1, _ = examples
    prior = analyze(G1)
    assert prior.lr0.conflicts[4, "="] == (
        Action("shift", 8), Action("reduce", 5),
    )
    assert prior.slr.conflicts[4, "="] == prior.lr0.conflicts[4, "="]
    assert not g1.canonical.table.conflicts
    assert not g1.lalr.table.conflicts
    assert len(g1.lalr.states) == 10
    assert g1.canonical.table.actions[4, "="] == (Action("shift", 8),)
    assert g1.lalr.table.actions[4, "="] == (Action("shift", 8),)
    assert g1.canonical.table.actions[4, END] == (Action("reduce", 5),)
    assert g1.lalr.table.actions[4, END] == (Action("reduce", 5),)


def test_g1_valid_and_invalid_traces_for_both_methods(examples):
    g1, _ = examples
    for automaton in (g1.canonical, g1.lalr):
        for tokens in (("id", "=", "id", END), ("*", "id", "=", "id", END)):
            accepted = trace(automaton, automaton.table, tokens)
            assert accepted.accepted and accepted.steps[-1].action == "accept"
            assert accepted.steps[-1].symbols == ("S",)
            assert any(step.production == "P1" and step.goto for step in accepted.steps)
        invalid = trace(automaton, automaton.table, ("id", "=", END))
        assert not invalid.accepted
        assert invalid.steps[-1].action == "error: empty ACTION cell"


def test_g2_canonical_table_is_conflict_free_and_accepts_all_four_examples(examples):
    _, g2 = examples
    assert not g2.canonical.table.conflicts
    assert g2.canonical.table.actions[4, "c"] == (Action("reduce", 5),)
    assert g2.canonical.table.actions[4, "d"] == (Action("reduce", 6),)
    assert g2.canonical.table.actions[7, "c"] == (Action("reduce", 6),)
    assert g2.canonical.table.actions[7, "d"] == (Action("reduce", 5),)
    for tokens in (("a", "e", "c", END), ("a", "e", "d", END),
                   ("b", "e", "c", END), ("b", "e", "d", END)):
        accepted = trace(g2.canonical, g2.canonical.table, tokens)
        assert accepted.accepted and accepted.steps[-1].symbols == ("S",)
    invalid = trace(g2.canonical, g2.canonical.table, ("a", "e", END))
    assert not invalid.accepted
    assert invalid.steps[-1].action == "error: empty ACTION cell"


def test_g2_only_equal_core_pair_merges_and_unions_lookaheads(examples):
    _, g2 = examples
    assert g2.merged_from[4] == (4, 7)
    assert sorted(group for group in g2.merged_from if len(group) > 1) == [(4, 7)]
    assert len(g2.lalr.states) == 13
    assert lr0_core(g2.canonical.states[4]) == lr0_core(g2.canonical.states[7]) == {
        Item(5, 1), Item(6, 1),
    }
    assert g2.lalr.states[4] == frozenset({
        LR1Item(5, 1, "c"), LR1Item(5, 1, "d"),
        LR1Item(6, 1, "c"), LR1Item(6, 1, "d"),
    })


def test_g2_lalr_conflicts_are_retained_and_classified(examples):
    _, g2 = examples
    expected = (Action("reduce", 5), Action("reduce", 6))
    assert g2.lalr.table.conflicts == {(4, "c"): expected, (4, "d"): expected}
    assert conflict_kind(expected) == "reduce/reduce"
    stopped = trace(g2.lalr, g2.lalr.table, ("a", "e", "c", END))
    assert not stopped.accepted
    assert stopped.steps[-1].states[-1] == 4
    assert stopped.steps[-1].action == "conflict: r5/r6"


def test_merged_edges_redirect_coherently_and_inconsistent_edge_is_rejected(examples):
    for result in examples:
        old_to_new = {old: new for new, group in enumerate(result.merged_from)
                      for old in group}
        assert len(old_to_new) == len(result.canonical.states)
        for new, group in enumerate(result.merged_from):
            assert all(lr0_core(result.canonical.states[old]) ==
                       lr0_core(result.lalr.states[new]) for old in group)
        for (source, symbol), target in result.canonical.transitions.items():
            assert result.lalr.transitions[old_to_new[source], symbol] == old_to_new[target]
    states = (
        frozenset({LR1Item(0, 0, END)}),
        frozenset({LR1Item(0, 0, "x")}),
        frozenset({LR1Item(1, 0, END)}),
        frozenset({LR1Item(2, 0, END)}),
    )
    with pytest.raises(ValueError, match="Inconsistent LALR transition"):
        merge_lr1_cores(states, {(0, "x"): 2, (1, "x"): 3})


def test_every_lr1_table_action_has_the_required_item_or_edge(examples):
    for result in examples:
        grammar = result.grammar
        for automaton in (result.canonical, result.lalr):
            table = automaton.table
            for state, items in enumerate(automaton.states):
                for index, production in enumerate(grammar.productions[1:], start=1):
                    for terminal in grammar.terminals + (END,):
                        expected = LR1Item(index, len(production.rhs), terminal) in items
                        actual = Action("reduce", index) in table.actions.get(
                            (state, terminal), ()
                        )
                        assert actual == expected
                for terminal in grammar.terminals:
                    edge = automaton.transitions.get((state, terminal))
                    shifts = [action for action in table.actions.get((state, terminal), ())
                              if action.kind == "shift"]
                    assert shifts == ([Action("shift", edge)] if edge is not None else [])
            accepts = [(cell, action) for cell, choices in table.actions.items()
                       for action in choices if action.kind == "accept"]
            assert len(accepts) == 1
            (state, terminal), _ = accepts[0]
            assert terminal == END and LR1Item(0, 1, END) in automaton.states[state]


def test_old_lr0_slr_results_and_generated_sections_remain_current(examples):
    assert (len(analyze(G0).states), len(analyze(G0).lr0.conflicts),
            len(analyze(G0).slr.conflicts)) == (8, 0, 0)
    old_g1 = analyze(G1)
    assert (len(old_g1.states), len(old_g1.lr0.conflicts),
            len(old_g1.slr.conflicts)) == (10, 1, 1)
    assert (len(analyze_lr1(G0).canonical.states),
            len(analyze_lr1(G0).lalr.states)) == (8, 8)
    old_g2 = analyze(G2)
    assert (len(old_g2.states), len(old_g2.lr0.conflicts),
            len(old_g2.slr.conflicts)) == (13, 6, 2)
    text = DOCUMENT.read_text(encoding="utf-8")
    assert document_with_computed(text, render_computed(analyze(G0), old_g1)) == text
    assert document_with_lr1_computed(text, render_lr1_computed(*examples)) == text

