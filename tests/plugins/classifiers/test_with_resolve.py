"""The real classifiers driven by `core/resolution`: the two halves agree on their contract."""

from __future__ import annotations

from datetime import date

from app.core.plugins.classifier import AccountFact, Condition, RuleSpec
from app.core.resolution import resolve
from app.plugins.classifiers.history import HistoryClassifier
from app.plugins.classifiers.rules import RulesClassifier

from .fakes import ListHistory, entry, vote

ACCOUNTS = [
    AccountFact(id=1, currency="EUR", external_ref=None),
    AccountFact(id=2, currency="EUR", external_ref="de89"),
]


def _resolve(e, rules=(), votes=(), accounts=ACCOUNTS):
    history = ListHistory(votes)
    return resolve(
        e,
        accounts=accounts,
        classifiers=[RulesClassifier(rules), HistoryClassifier()],
        history=history,
    )


def test_a_payee_rule_sets_flow_and_payee_as_standing_rule_keys() -> None:
    rule = RuleSpec(
        id=7,
        name="Rewe",
        sets="payee",
        target_id=11,
        conditions=(Condition("counterparty_name", "starts_with", "rewe"),),
    )
    e = entry(account_id=1, counterparty_name="REWE Markt 123")
    out = _resolve(e, rules=[rule])
    assert out["type"].value == "flow" and out["type"].pass_name == "rule"
    assert out["payee"].value == 11 and out["payee"].basis == {"rule_id": 7}


def test_history_proposes_when_no_rule_matches() -> None:
    e = entry(account_id=1, counterparty_name="Bakery Mueller")
    votes = [
        vote(
            entry_id=i,
            account_id=1,
            booked_on=date(2026, 1, i),
            type="flow",
            payee_id=5,
            category_id=9,
            counterparty_name="Bakery Mueller",
        )
        for i in (1, 2, 3)
    ]
    out = _resolve(e, votes=votes)
    assert out["type"].pass_name == "history"
    assert out["payee"].value == 5 and out["payee"].pass_name == "history"
    assert out["category"].value == 9
    assert out["payee"].basis["agree"] == 3 and out["payee"].basis["of"] == 3


def test_pass_zero_beats_rules_and_history() -> None:
    rule = RuleSpec(
        id=1,
        name="x",
        sets="payee",
        target_id=3,
        conditions=(Condition("counterparty_name", "starts_with", "own"),),
    )
    e = entry(account_id=1, counterparty_name="own transfer", counterparty_ref="DE89")
    out = _resolve(e, rules=[rule])
    assert out["type"].value == "transfer" and out["type"].pass_name == "own_account"
    assert out["counter_account"].value == 2
    assert "payee" not in out and "category" not in out


def test_nothing_known_resolves_nothing() -> None:
    assert dict(_resolve(entry(account_id=1, counterparty_name="Unknown Shop"))) == {}
