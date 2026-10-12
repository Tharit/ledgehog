from __future__ import annotations

import dataclasses
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.plugins.classifier import ClassifierContext, Proposal, RuleSpec
from app.plugins.classifiers.rules import (
    RuleError,
    RulesClassifier,
    matches,
    precedence_order,
    validate_rule,
)
from tests.plugins.classifiers.fakes import entry

CTX = ClassifierContext()


def rule(id: int = 1, sets: str = "payee", target_id: int = 10, **kw: object) -> RuleSpec:
    kw.setdefault("name", f"rule {id}")
    return RuleSpec(id=id, sets=sets, target_id=target_id, **kw)  # type: ignore[arg-type]


# ---- single conditions ----


@pytest.mark.parametrize(
    ("r", "e", "expected"),
    [
        (
            rule(counterparty_ref="DE89 3704 0044 0532 0130 00"),
            {"counterparty_ref": "de89370400440532013000"},
            True,
        ),
        (rule(counterparty_ref="DE89"), {"counterparty_ref": "DE90"}, False),
        (rule(mandate_ref="M-001"), {"mandate_ref": "m 001"}, True),
        (rule(mandate_ref="M-001"), {"mandate_ref": "M-002"}, False),
        (rule(booking_text="GA-Auszahlung"), {"booking_text": "ga auszahlung"}, True),
        (rule(booking_text="GA-Auszahlung"), {"booking_text": "Entgelt"}, False),
        (rule(name_exact="  Rewe  Markt"), {"counterparty_name": "REWE markt"}, True),
        (rule(name_exact="Rewe"), {"counterparty_name": "Rewe Markt"}, False),
        (rule(name_prefix="PAYPAL *"), {"counterparty_name": "PAYPAL *SEEEDDEVELO"}, True),
        (rule(name_prefix="PAYPAL *"), {"counterparty_name": "PayPal Europe S.a.r.l."}, False),
        (rule(purpose_regex="miete"), {"purpose": "Monat MIETE Juni"}, True),
        (rule(purpose_regex="^miete"), {"purpose": "Monat Miete"}, False),
    ],
)
def test_single_condition(r: RuleSpec, e: dict[str, object], expected: bool) -> None:
    assert matches(r, entry(**e), None) is expected


def test_payee_condition_equals_resolved_payee() -> None:
    r = rule(sets="category", condition_payee_id=7)
    assert matches(r, entry(), 7)
    assert not matches(r, entry(), 8)
    assert not matches(r, entry(), None)


def test_missing_field_fails() -> None:
    for r in (
        rule(counterparty_ref="X"),
        rule(mandate_ref="X"),
        rule(booking_text="X"),
        rule(name_exact="X"),
        rule(name_prefix="X"),
        rule(purpose_regex="x"),
    ):
        assert not matches(r, entry(), None)


def test_conditions_are_anded() -> None:
    r = rule(name_prefix="paypal", purpose_regex="seeed", booking_text="kartenzahlung")
    e = entry(counterparty_name="PayPal *X", purpose="Seeed order", booking_text="Kartenzahlung")
    assert matches(r, e, None)
    assert not matches(r, dataclasses.replace(e, booking_text="Lastschrift"), None)
    assert not matches(r, dataclasses.replace(e, purpose="other"), None)


def test_blank_condition_counts_as_absent() -> None:
    r = rule(name_exact="  ", purpose_regex="x")
    assert matches(r, entry(purpose="x"), None)


def test_regex_ignorecase_search() -> None:
    assert matches(rule(purpose_regex="AbC"), entry(purpose="zzz abc zzz"), None)


# ---- order and proposals ----


def test_order_groups_priority_id() -> None:
    rs = [
        rule(1, "category", priority=1, purpose_regex="x"),
        rule(2, "payee", priority=5, purpose_regex="x"),
        rule(3, "payee", priority=5, purpose_regex="x"),
        rule(4, "payee", priority=1, purpose_regex="x"),
        rule(5, "counter_account", priority=99, purpose_regex="x"),
    ]
    assert [r.id for r in precedence_order(rs)] == [5, 4, 2, 3, 1]


def test_first_match_wins_priority_then_id() -> None:
    c = RulesClassifier(
        [
            rule(3, target_id=30, priority=1, purpose_regex="x"),
            rule(2, target_id=20, priority=1, purpose_regex="x"),
            rule(1, target_id=10, priority=2, purpose_regex="x"),
        ]
    )
    p = c.propose("payee", entry(purpose="x"), CTX)
    assert p == Proposal("payee", 20, {"rule_id": 2})


def test_no_match_none() -> None:
    assert RulesClassifier([rule(purpose_regex="x")]).propose("payee", entry(purpose="y"), CTX) is None


def test_counter_account_rule_skipped_when_account_not_ok() -> None:
    c = RulesClassifier(
        [
            rule(1, "counter_account", 100, priority=1, purpose_regex="x"),  # wrong currency
            rule(2, "counter_account", 200, priority=2, purpose_regex="x"),
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
    c = RulesClassifier([rule(1, "category", 50, condition_payee_id=7)])
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
    payee_rule = rule(1, "payee", purpose_regex="x")
    cat_rule = rule(2, "category", 5, purpose_regex="x")
    ca_rule = rule(3, "counter_account", 9, purpose_regex="x")
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
        rule(1, "payee", purpose_regex="x"),
        rule(2, "counter_account", 100, purpose_regex="x"),
        rule(3, "counter_account", 200, purpose_regex="x"),
        rule(4, "payee", purpose_regex="nomatch"),
    ]
    c = RulesClassifier([])
    ctx = ClassifierContext(account_ok=lambda a: a != 100)
    assert [r.id for r in c.matching_rules(entry(purpose="x"), rs, ctx)] == [3, 1]


# ---- validation ----


@pytest.mark.parametrize(
    "r",
    [
        rule(name="  ", purpose_regex="x"),
        rule(),  # no condition
        rule(name_exact="  ", purpose_regex=""),  # blanks only
        rule(purpose_regex="("),
        rule(purpose_regex="a" * 201),
        rule(sets="payee", condition_payee_id=3),
        rule(sets="counter_account", condition_payee_id=3),
    ],
)
def test_validate_rule_refuses(r: RuleSpec) -> None:
    with pytest.raises(RuleError):
        validate_rule(r)


def test_validate_rule_accepts() -> None:
    validate_rule(rule(purpose_regex="a" * 200))
    validate_rule(rule(sets="category", condition_payee_id=3))
    validate_rule(rule(name_prefix="PAYPAL *"))


def test_constructor_refuses_invalid_rule() -> None:
    with pytest.raises(RuleError):
        RulesClassifier([rule(purpose_regex="(")])


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
    rules = [rule(i + 1, s, 100 + i, priority=p, purpose_regex="x") for i, (p, s) in enumerate(specs)]
    shuffled = rules[:]
    rnd.shuffle(shuffled)
    e = entry(purpose="x")
    for f in ("type", "payee", "category", "counter_account"):
        assert RulesClassifier(rules).propose(f, e, CTX) == RulesClassifier(shuffled).propose(f, e, CTX)
