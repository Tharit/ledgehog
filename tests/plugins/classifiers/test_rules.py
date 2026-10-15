from __future__ import annotations

import dataclasses
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.plugins.classifier import ClassifierContext, Condition, Proposal, RuleInvalid, RuleSpec
from app.plugins.classifiers.rules import (
    RuleError,
    RulesClassifier,
    matches,
    precedence_order,
    validate_rule,
)
from tests.plugins.classifiers.fakes import entry

CTX = ClassifierContext()


def cond(field: str, op: str, value: str) -> Condition:
    return Condition(field, op, value)  # type: ignore[arg-type]


def rule(id: int = 1, sets: str = "payee", target_id: int = 10, *conds: Condition, **kw: object) -> RuleSpec:
    kw.setdefault("name", f"rule {id}")
    return RuleSpec(id=id, sets=sets, target_id=target_id, conditions=conds, **kw)  # type: ignore[arg-type]


def one(field: str, op: str, value: str) -> RuleSpec:
    return rule(1, "payee", 10, cond(field, op, value))


def pay(payee_id: int | str) -> Condition:
    return cond("payee", "is", str(payee_id))


def rx(pattern: str = "x") -> Condition:
    return cond("purpose", "regex", pattern)


# ---- every operator on every field class ----

IBAN = "DE89 3704 0044 0532 0130 00"


@pytest.mark.parametrize("field", ["counterparty_ref", "mandate_ref"])
@pytest.mark.parametrize(
    ("op", "value", "have", "expected"),
    [
        # identifiers compare as canonical text on both sides: spaces, case and punctuation vanish
        ("equals", IBAN, "de89370400440532013000", True),
        ("equals", "DE89", "DE89 3704", False),
        ("starts_with", "DE89 3704", "de89370400440532013000", True),
        ("starts_with", "de89-3704", "DE89 3704 0044", True),
        ("starts_with", "3704", "DE89 3704 0044", False),
        ("contains", "3704 0044", "DE89 3704 0044 0532", True),
        ("contains", "9999", "DE89 3704 0044 0532", False),
        ("regex", r"^DE89 3704", "DE89 3704 0044", True),
        ("regex", r"^DE893704", "DE89 3704 0044", False),  # regex runs on the RAW value
        ("regex", r"0044\s0532", "DE89 3704 0044 0532", True),
    ],
)
def test_identifier_fields(field: str, op: str, value: str, have: str, expected: bool) -> None:
    assert matches(one(field, op, value), entry(**{field: have}), None) is expected


@pytest.mark.parametrize("field", ["counterparty_name", "purpose", "booking_text"])
@pytest.mark.parametrize(
    ("op", "value", "have", "expected"),
    [
        # words compare by name normalisation: casefold, whitespace collapsed, punctuation KEPT
        ("equals", "  Rewe  Markt", "REWE markt", True),
        ("equals", "Rewe", "Rewe Markt", False),
        ("equals", "rewe-markt", "Rewe Markt", False),
        ("starts_with", "PAYPAL *", "PAYPAL *SEEEDDEVELO", True),
        ("starts_with", "PAYPAL *", "PayPal Europe S.a.r.l.", False),
        ("starts_with", "paypal", "  PayPal   Europe", True),
        ("starts_with", "Markt", "Rewe Markt", False),
        ("contains", "markt  koeln", "REWE Markt Koeln 12", True),
        ("contains", "markt-koeln", "REWE Markt Koeln 12", False),
        ("regex", "^miete", "Monat Miete", False),
        ("regex", "MIETE", "Monat Miete Juni", True),
        ("regex", r"S\.a\.r\.l", "PayPal Europe S.a.r.l.", True),
    ],
)
def test_word_fields(field: str, op: str, value: str, have: str, expected: bool) -> None:
    assert matches(one(field, op, value), entry(**{field: have}), None) is expected


def test_an_entry_value_without_alphanumerics_never_equals_an_identifier() -> None:
    assert not matches(one("counterparty_ref", "equals", "-"), entry(counterparty_ref="--"), None)
    assert not matches(one("counterparty_ref", "starts_with", "--"), entry(counterparty_ref="DE89"), None)


def test_payee_condition_equals_resolved_payee() -> None:
    r = rule(1, "category", 10, pay(7))
    assert matches(r, entry(), 7)
    assert not matches(r, entry(), 8)
    assert not matches(r, entry(), None)


@pytest.mark.parametrize(
    "field", ["counterparty_name", "counterparty_ref", "purpose", "booking_text", "mandate_ref"]
)
@pytest.mark.parametrize("op", ["equals", "starts_with", "contains", "regex"])
def test_missing_field_fails(field: str, op: str) -> None:
    assert not matches(one(field, op, "x"), entry(), None)
    assert not matches(one(field, op, "x"), entry(**{field: "  "}), None)


def test_payee_condition_with_conditions_needs_both() -> None:
    r = rule(1, "category", 10, cond("purpose", "contains", "miete"), pay(7))
    e = entry(purpose="Miete Juni")
    assert matches(r, e, 7)
    assert not matches(r, e, 8)
    assert not matches(r, entry(purpose="other"), 7)


def test_payee_condition_alone() -> None:
    r = rule(1, "category", 10, pay(7))
    assert matches(r, entry(), 7) and not matches(r, entry(), None)


def test_several_payee_conditions_are_anded() -> None:
    r = rule(1, "category", 10, pay(7), pay(8))
    assert not matches(r, entry(), 7) and not matches(r, entry(), 8)  # one payee cannot be both
    twice = rule(1, "category", 10, pay(7), pay("007"), cond("purpose", "contains", "x"))
    assert matches(twice, entry(purpose="x"), 7) and not matches(twice, entry(purpose="y"), 7)


def test_a_payee_condition_never_reads_the_entry_and_a_dangling_id_never_matches() -> None:
    r = rule(1, "category", 10, pay(999))
    assert not matches(r, entry(purpose="999", counterparty_name="999"), 7)
    assert not matches(r, entry(), None)


def test_conditions_are_anded() -> None:
    r = rule(
        1,
        "payee",
        10,
        cond("counterparty_name", "starts_with", "paypal"),
        cond("purpose", "regex", "seeed"),
        cond("booking_text", "equals", "kartenzahlung"),
    )
    e = entry(counterparty_name="PayPal *X", purpose="Seeed order", booking_text="Kartenzahlung")
    assert matches(r, e, None)
    assert not matches(r, dataclasses.replace(e, booking_text="Lastschrift"), None)
    assert not matches(r, dataclasses.replace(e, purpose="other"), None)


def test_the_same_field_may_appear_several_times() -> None:
    r = rule(
        1,
        "payee",
        10,
        cond("purpose", "contains", "miete"),
        cond("purpose", "contains", "juni"),
        cond("purpose", "regex", "^(?!.*nachzahlung)"),
    )
    assert matches(r, entry(purpose="Miete Juni"), None)
    assert not matches(r, entry(purpose="Miete Mai"), None)
    assert not matches(r, entry(purpose="Miete Juni Nachzahlung"), None)


def test_regex_ignorecase_search() -> None:
    assert matches(one("purpose", "regex", "AbC"), entry(purpose="zzz abc zzz"), None)


# ---- order and proposals ----


def test_order_groups_priority_id() -> None:
    rs = [
        rule(1, "category", 10, rx(), priority=1),
        rule(2, "payee", 10, rx(), priority=5),
        rule(3, "payee", 10, rx(), priority=5),
        rule(4, "payee", 10, rx(), priority=1),
        rule(5, "counter_account", 10, rx(), priority=99),
    ]
    assert [r.id for r in precedence_order(rs)] == [5, 4, 2, 3, 1]


def test_first_match_wins_priority_then_id() -> None:
    c = RulesClassifier(
        [
            rule(3, "payee", 30, rx(), priority=1),
            rule(2, "payee", 20, rx(), priority=1),
            rule(1, "payee", 10, rx(), priority=2),
        ]
    )
    p = c.propose("payee", entry(purpose="x"), CTX)
    assert p == Proposal("payee", 20, {"rule_id": 2})


def test_no_match_none() -> None:
    assert RulesClassifier([rule(1, "payee", 10, rx())]).propose("payee", entry(purpose="y"), CTX) is None


def test_counter_account_rule_skipped_when_account_not_ok() -> None:
    c = RulesClassifier(
        [
            rule(1, "counter_account", 100, rx(), priority=1),  # wrong currency
            rule(2, "counter_account", 200, rx(), priority=2),
        ]
    )
    ctx = ClassifierContext(account_ok=lambda a: a != 100)
    p = c.propose("counter_account", entry(purpose="x"), ctx)
    assert p == Proposal("counter_account", 200, {"rule_id": 2})
    t = c.propose("type", entry(purpose="x"), ctx)
    assert t == Proposal("type", "transfer", {"rule_id": 2})
    none_ok = ClassifierContext(account_ok=lambda a: False)
    assert c.propose("counter_account", entry(purpose="x"), none_ok) is None
    assert c.propose("type", entry(purpose="x"), none_ok) is None


def test_category_rule_with_payee_condition() -> None:
    c = RulesClassifier([rule(1, "category", 50, pay(7))])
    e = entry()
    with_payee = ClassifierContext(resolved={"payee": Proposal("payee", 7, {})})
    other = ClassifierContext(resolved={"payee": Proposal("payee", 8, {})})
    assert c.propose("category", e, with_payee) == Proposal("category", 50, {"rule_id": 1})
    assert c.propose("category", e, other) is None
    assert c.propose("category", e, CTX) is None
    # never decides the type, even with the payee in ctx
    assert c.propose("type", e, with_payee) is None


def test_type_proposals() -> None:
    e = entry(purpose="x")
    payee_rule = rule(1, "payee", 10, rx())
    cat_rule = rule(2, "category", 5, rx())
    ca_rule = rule(3, "counter_account", 9, rx())
    assert RulesClassifier([payee_rule]).propose("type", e, CTX) == Proposal("type", "flow", {"rule_id": 1})
    assert RulesClassifier([cat_rule]).propose("type", e, CTX) == Proposal("type", "flow", {"rule_id": 2})
    assert RulesClassifier([payee_rule, cat_rule, ca_rule]).propose("type", e, CTX) == Proposal(
        "type", "transfer", {"rule_id": 3}
    )
    assert RulesClassifier([payee_rule, cat_rule]).propose("type", e, CTX) == Proposal(
        "type", "flow", {"rule_id": 1}
    )
    assert RulesClassifier([]).propose("type", e, CTX) is None


def test_matching_rules_in_order_filtering_account() -> None:
    rs = [
        rule(1, "payee", 10, rx()),
        rule(2, "counter_account", 100, rx()),
        rule(3, "counter_account", 200, rx()),
        rule(4, "payee", 10, rx("nomatch")),
    ]
    c = RulesClassifier([])
    ctx = ClassifierContext(account_ok=lambda a: a != 100)
    assert [r.id for r in c.matching_rules(entry(purpose="x"), rs, ctx)] == [3, 1]


# ---- validation ----


@pytest.mark.parametrize(
    "r",
    [
        rule(1, "payee", 10, rx(), name="  "),
        rule(),  # no condition
        rule(1, "payee", 10, cond("purpose", "contains", "  ")),  # blank value
        rule(1, "payee", 10, cond("purpose", "contains", "")),
        rule(1, "payee", 10, cond("purpose", "regex", "(")),
        rule(1, "payee", 10, cond("purpose", "regex", "a" * 201)),
        rule(1, "payee", 10, cond("counterparty_ref", "regex", "(")),  # a regex on any field is checked
        rule(1, "payee", 10, cond("amount", "equals", "5")),  # unknown field
        rule(1, "payee", 10, cond("purpose", "ends_with", "5")),  # unknown operator
        rule(1, "payee", 10, rx(), pay(3)),  # a payee condition on a rule that does not set a category
        rule(1, "counter_account", 10, rx(), pay(3)),
        rule(1, "category", 10, cond("payee", "equals", "3")),  # only `is`
        rule(1, "category", 10, cond("payee", "regex", "3")),
        rule(1, "category", 10, cond("purpose", "is", "3")),  # `is` is for payee only
        rule(1, "category", 10, pay("x")),
        rule(1, "category", 10, pay("0")),
        rule(1, "category", 10, pay("-3")),
        rule(1, "category", 10, pay("3.0")),
        rule(1, "category", 10, pay(" ")),
    ],
)
def test_validate_rule_refuses(r: RuleSpec) -> None:
    with pytest.raises(RuleError):
        validate_rule(r)


def test_validate_rule_accepts() -> None:
    validate_rule(rule(1, "payee", 10, rx("a" * 200)))
    validate_rule(rule(1, "category", 10, pay(3)))  # a payee condition alone is a condition
    validate_rule(rule(1, "category", 10, cond("purpose", "contains", "x"), pay(3), pay(4)))
    validate_rule(rule(1, "payee", 10, cond("counterparty_name", "starts_with", "PAYPAL *")))
    validate_rule(rule(1, "payee", 10, rx(), rx("y"), cond("purpose", "equals", "z")))
    # a long value is only bounded for a regex
    validate_rule(rule(1, "payee", 10, cond("purpose", "contains", "a" * 500)))


def test_constructor_refuses_invalid_rule() -> None:
    with pytest.raises(RuleError):
        RulesClassifier([rule(1, "payee", 10, rx("("))])


# ---- properties ----


@given(
    st.lists(
        st.tuples(st.integers(0, 3), st.sampled_from(["payee", "category", "counter_account"])),
        min_size=1,
        max_size=8,
        unique=True,
    ),
    st.randoms(use_true_random=False),
)
def test_rule_order_does_not_change_result(specs: list[tuple[int, str]], rnd: random.Random) -> None:
    rules = [rule(i + 1, s, 100 + i, rx(), priority=p) for i, (p, s) in enumerate(specs)]
    shuffled = rules[:]
    rnd.shuffle(shuffled)
    e = entry(purpose="x")
    for f in ("type", "payee", "category", "counter_account"):
        assert RulesClassifier(rules).propose(f, e, CTX) == RulesClassifier(shuffled).propose(f, e, CTX)


# ---- what core's rule writes read of the plugin ----


@pytest.mark.parametrize(
    ("r", "field"),
    [
        (rule(1, "payee", 10, rx(), name=" "), "name"),
        (rule(1, "payee", 10, rx(), rx("(SECRET")), "conditions[1].value"),
        (rule(1, "payee", 10, rx("SECRET" + "a" * 200)), "conditions[0].value"),
        (
            rule(1, "payee", 10, cond("purpose", "contains", "ok"), cond("mandate_ref", "equals", "  ")),
            "conditions[1].value",
        ),
        (rule(1, "payee", 10, cond("SECRETFIELD", "equals", "x")), "conditions[0].field"),
        (rule(1, "payee", 10, cond("purpose", "SECRETOP", "x")), "conditions[0].op"),
        (rule(1, "payee", 10, rx(), pay(3)), "conditions[1].field"),
        (rule(1, "category", 10, cond("payee", "equals", "3")), "conditions[0].op"),
        (rule(1, "category", 10, cond("purpose", "is", "SECRET")), "conditions[0].op"),
        (rule(1, "category", 10, rx(), pay("SECRET")), "conditions[1].value"),
        (rule(1, "category", 10, pay("0")), "conditions[0].value"),
        (rule(), "conditions"),
    ],
)
def test_validation_errors_name_the_field_and_never_quote_the_pattern(r: RuleSpec, field: str) -> None:
    with pytest.raises(RuleInvalid) as info:
        validate_rule(r)
    assert info.value.field == field
    assert "SECRET" not in str(info.value)


def test_a_regex_that_re_quotes_in_its_message_is_not_echoed() -> None:
    with pytest.raises(RuleError) as info:
        validate_rule(rule(1, "payee", 10, rx(r"\qSECRET")))  # re: "bad escape \q at position 0"
    assert "SECRET" not in str(info.value) and "\\q" not in str(info.value)


def test_default_rule_tools_are_the_functions_settling_uses() -> None:
    from app.plugins.classifiers import default_rule_tools

    tools = default_rule_tools()
    assert tools.validate is validate_rule and tools.matches is matches
    assert tools.precedence_order is precedence_order
