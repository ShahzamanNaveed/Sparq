import pytest

from tools.ll1_analysis import (
    DOCUMENT, END_MARKER, EPSILON, Production, analyze,
    document_with_computed, extract_frozen_grammar, first_sequence,
    grammar_from_productions, predictive_trace, render_computed,
)


@pytest.fixture(scope="module")
def sparq_analysis():
    return analyze(extract_frozen_grammar())


def test_frozen_bnf_inventory_and_integrity(sparq_analysis):
    analysis = sparq_analysis
    grammar = analysis.grammar
    assert grammar.start == "<program>"
    assert (len(grammar.nonterminals), len(grammar.productions)) == (55, 117)
    assert len(grammar.terminals) == 52
    assert len(analysis.nullable) == 23
    assert not (analysis.undefined or analysis.unreachable or analysis.unproductive or analysis.duplicates)
    assert grammar.productions[0] == Production(
        "P001", "<program>", ("<function-list>", "START", "<block>", "EOF"), 56
    )
    assert len([p for p in grammar.productions if p.lhs == "<type>"]) == 5
    function = next(p for p in grammar.productions if p.lhs == "<function>")
    assert function.rhs == (
        "FUNC", "IDENTIFIER", "(", "<params-opt>", ")", "->", "<return-type>", "<block>"
    )
    switch = next(p for p in grammar.productions if p.lhs == "<switch-statement>")
    assert switch.rhs == (
        "SELECT", "(", "<expression>", ")", "{", "<case-list>", "<default-opt>", "}"
    )
    assert len([p for p in grammar.productions if not p.rhs]) == 23


def test_nullable_first_and_follow_anchor_sets(sparq_analysis):
    a = sparq_analysis
    assert a.nullable_rounds[0] == a.nullable
    assert a.first["<program>"] == {"FUNC", "START"}
    assert a.follow["<program>"] == {END_MARKER}
    assert a.first["<function-list>"] == {"FUNC", EPSILON}
    assert a.follow["<function-list>"] == {"START"}
    assert a.first["<declaration-tail>"] == {"=", "[", EPSILON}
    assert a.follow["<declaration-tail>"] == {";"}
    assert a.follow["<statement-list>"] == {"}"}
    assert a.follow["<params-opt>"] == {")"}
    assert a.follow["<return-value-opt>"] == {";"}
    assert a.first["<or-tail>"] == {"OR", EPSILON}
    assert a.follow["<or-tail>"] == {")", ",", ";", "]", "}"}
    assert a.first["<expression>"] == {
        "(", "-", "CHAR_LITERAL", "FALSE", "FLOAT_LITERAL", "IDENTIFIER",
        "INT_LITERAL", "NOT", "STRING_LITERAL", "TRUE",
    }
    assert "OTHERWISE" not in a.follow["<else-opt>"]
    assert all(EPSILON not in values for values in a.follow.values())


def test_select_sets_predictive_cells_and_separate_end_marker(sparq_analysis):
    a = sparq_analysis
    assert a.table["<function-list>", "FUNC"] == ("P002",)
    assert a.table["<function-list>", "START"] == ("P003",)
    assert a.table["<statement-list>", "}"] == ("P020",)
    assert ("<expression>", ")") not in a.table
    assert a.select["P003"] == {"START"}
    assert a.select["P020"] == {"}"}
    assert "EOF" in a.grammar.terminals
    assert END_MARKER not in a.grammar.terminals
    assert ("<program>", "EOF") not in a.table
    assert len(a.table) == 350
    assert not a.conflicts and not a.conflicting_pairs
    assert sum(len(a.select[p.identifier]) for p in a.grammar.productions) == sum(
        len(ids) for ids in a.table.values()
    )


def test_predictive_traces_accept_empty_start_and_reject_missing_show_value(sparq_analysis):
    valid = predictive_trace(sparq_analysis, ("START", "{", "}", "EOF", END_MARKER))
    assert valid.accepted
    assert valid.steps[-2].action == "match EOF"
    assert valid.steps[-1].action == "accept"
    invalid = predictive_trace(
        sparq_analysis, ("START", "{", "SHOW", "(", ")", ";", "}", "EOF", END_MARKER)
    )
    assert not invalid.accepted
    assert invalid.steps[-1].action == "error: M[<expression>, )] is empty"


def test_nullable_prefixes_and_follow_through_nullable_suffix():
    grammar = grammar_from_productions((
        Production("P001", "<S>", ("<A>", "<B>")),
        Production("P002", "<A>", ("a",)),
        Production("P003", "<A>", ()),
        Production("P004", "<B>", ("b",)),
        Production("P005", "<B>", ()),
    ))
    a = analyze(grammar)
    assert a.nullable == {"<S>", "<A>", "<B>"}
    assert a.nullable_rounds[0] == {"<A>", "<B>"}
    assert a.first["<S>"] == {"a", "b", EPSILON}
    assert first_sequence(("<A>", "<B>", "x"), a.first, a.nullable) == {"a", "b", "x"}
    assert a.follow["<A>"] == {"b", END_MARKER}
    assert a.follow["<B>"] == {END_MARKER}
    assert a.select["P001"] == {"a", "b", END_MARKER}
    assert a.select["P003"] == {"b", END_MARKER}


def test_conflicting_illustrative_grammar_retains_both_candidates():
    grammar = grammar_from_productions((
        Production("P001", "<S>", ("a", "<A>")),
        Production("P002", "<S>", ("a", "<B>")),
        Production("P003", "<A>", ("b",)),
        Production("P004", "<B>", ("c",)),
    ))
    a = analyze(grammar)
    assert a.table["<S>", "a"] == ("P001", "P002")
    assert a.conflicts == {("<S>", "a"): ("P001", "P002")}
    assert a.conflicting_pairs == {("P001", "P002")}
    trace = predictive_trace(a, ("a", "b", END_MARKER))
    assert not trace.accepted and "conflict" in trace.steps[0].action


def test_integrity_checks_report_duplicate_unreachable_and_unproductive_rules():
    grammar = grammar_from_productions((
        Production("P001", "<S>", ("a",)),
        Production("P002", "<S>", ("a",)),
        Production("P003", "<U>", ("<U>",)),
    ))
    a = analyze(grammar)
    assert a.duplicates == (("P001", "P002"),)
    assert a.unreachable == ("<U>",)
    assert a.unproductive == ("<U>",)
    with pytest.raises(ValueError, match="Undefined nonterminals"):
        analyze(grammar_from_productions((
            Production("P001", "<S>", ("<Missing>",)),
        )))


def test_documented_calculation_is_current_and_deterministic(sparq_analysis):
    document = DOCUMENT.read_text(encoding="utf-8")
    computed = render_computed(sparq_analysis)
    assert document_with_computed(document, computed) == document
    assert analyze(extract_frozen_grammar()) == sparq_analysis
    assert render_computed(analyze(extract_frozen_grammar())) == computed
