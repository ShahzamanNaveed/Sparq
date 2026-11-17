"""Independent checkpoints for the illustrative operator-precedence recognizer."""

from itertools import product

import pytest

from tools.operator_precedence import (
    DOCUMENT, END, RULES, document_with_demonstrations, parse,
    precedence_sets, precedence_table,
)


def recognize(source: str):
    return parse(tuple(source.split()) + (END,))


def test_grammar_and_complete_relation_table_have_hand_derived_values():
    assert RULES == (
        ("O1", "E", ("E", "+", "T")),
        ("O2", "E", ("T",)),
        ("O3", "T", ("T", "*", "F")),
        ("O4", "T", ("F",)),
        ("O5", "F", ("(", "E", ")")),
        ("O6", "F", ("id",)),
    )
    first, last = precedence_sets()
    assert first == {
        "F": {"(", "id"},
        "T": {"(", "*", "id"},
        "E": {"(", "*", "+", "id"},
    }
    assert last == {
        "F": {")", "id"},
        "T": {")", "*", "id"},
        "E": {")", "*", "+", "id"},
    }
    table = precedence_table()
    terminals = ("id", "+", "*", "(", ")", END)
    rows = ("->>->>", "<><<>>", "<>><>>", "<<<<=-", "->>->>", "<<<<-=")
    assert len(table) == 30
    assert sum((a, b) not in table for a in terminals for b in terminals) == 6
    for left, row in zip(terminals, rows):
        assert "".join(table.get((left, right), "-") for right in terminals) == row


def test_required_traces_use_exhaustive_unit_closure_and_valid_handles():
    first = recognize("id + id * id")
    second = recognize("( id + id ) * id")
    third = recognize("id * id + id")
    assert first.accepted and second.accepted and third.accepted
    assert [step.productions for step in first.steps if step.action == "reduce"] == [
        ("O6", "O4", "O2"), ("O6", "O4", "O2"),
        ("O6", "O4", "O2"), ("O3", "O2"), ("O1",),
    ]
    for result in (first, second, third):
        assert all(step.handle and step.productions
                   for step in result.steps if step.action == "reduce")
        assert result.steps[-1].action == "accept"
    first_rules = [step.productions[0] for step in first.steps if step.action == "reduce"]
    third_rules = [step.productions[0] for step in third.steps if step.action == "reduce"]
    assert first_rules.index("O3") < first_rules.index("O1")
    assert third_rules.index("O3") < third_rules.index("O1")
    assert any(step.handle[0] == "(" and step.productions[0] == "O5"
               for step in second.steps if step.action == "reduce")


@pytest.mark.parametrize("source", [
    "id", "( id )", "id + id + id", "id * id * id",
    "id + id * id + id", "id * id + id * id",
    "( id + id ) * ( id + id )", "id * ( id + id * id )",
    "( ( id ) )", "( id + id * ( id + id ) ) * id",
])
def test_nested_and_repeated_valid_expressions(source):
    assert recognize(source).accepted


@pytest.mark.parametrize(("source", "reason"), [
    ("id + * id", "invalid handle"),
    ("id id", "undefined relation"),
    ("+ id", "invalid handle"),
    ("id +", "invalid handle"),
    ("( id + id", "undefined relation"),
    ("id + ( )", "invalid handle"),
    ("", "incomplete expression"),
])
def test_invalid_expressions_are_rejected(source, reason):
    result = recognize(source)
    assert not result.accepted
    assert reason in result.steps[-1].action


def test_bounded_independent_grammar_derivations_are_accepted():
    """Enumerate short strings from the grammar without using the recognizer."""
    grammar = {
        "E": (("E", "+", "T"), ("T",)),
        "T": (("T", "*", "F"), ("F",)),
        "F": (("(", "E", ")"), ("id",)),
    }
    generated = {name: set() for name in grammar}
    while True:
        previous = {name: values.copy() for name, values in generated.items()}
        for name, alternatives in grammar.items():
            for rhs in alternatives:
                pools = [generated[x] if x in grammar else {(x,)} for x in rhs]
                for pieces in product(*pools):
                    tokens = sum(pieces, ())
                    if len(tokens) <= 7:
                        generated[name].add(tokens)
        if generated == previous:
            break
    assert len(generated["E"]) == 60
    assert all(parse(tokens + (END,)).accepted for tokens in generated["E"])
    alphabet = ("id", "+", "*", "(", ")")
    for length in range(6):
        for tokens in product(alphabet, repeat=length):
            assert parse(tokens + (END,)).accepted == (tokens in generated["E"])


def test_all_four_documented_traces_match_executable_decisions():
    document = DOCUMENT.read_text(encoding="utf-8")
    assert document_with_demonstrations(document) == document

