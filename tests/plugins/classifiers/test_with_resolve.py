"""The real classifiers driven by `core/resolution`: the two halves agree on their contract."""

from __future__ import annotations

from datetime import date

from app.core.plugins.classifier import AccountFact, Condition, RuleSpec
from app.core.resolution import Decided, resolve
from app.plugins.classifiers.history import HistoryClassifier
from app.plugins.classifiers.llm import LlmClassifier
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_of
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


# ---- history gives way to the model's stored answer (spec §5.9, D241) ----

PATHS = {1: "Expense > Rent", 2: "Expense > Dining"}
FRIEND = [
    vote(counterparty_ref="DE99", purpose="Miete Juni", category_id=1, payee_id=4),
    vote(counterparty_ref="DE99", purpose="Miete Juli", category_id=1, payee_id=4),
    vote(counterparty_ref="DE99", purpose="Pizza Essen Freitag", category_id=2, payee_id=4),
]


def _with_model(e, votes=FRIEND, stored=None):  # type: ignore[no-untyped-def]
    return resolve(
        e,
        accounts=ACCOUNTS,
        classifiers=[RulesClassifier(()), HistoryClassifier(), LlmClassifier()],
        history=ListHistory(votes, PATHS),
        stored=stored,
    )


def _answer(e, value, seen):  # type: ignore[no-untyped-def]
    payload = payload_of(e)
    assert payload is not None
    return {
        "category": Decided(
            value, "llm", {"model": "m", "rationale": "r", "fingerprint": fingerprint_of(payload, seen)}
        )
    }


def test_a_mixed_counterparty_uses_historys_majority_until_the_model_answers() -> None:
    e = entry(counterparty_ref="DE99", counterparty_name="Max", purpose="Konzert Karten")
    out = _with_model(e)
    assert out["category"].value == 1 and out["category"].pass_name == "history"
    assert (out["category"].basis["agree"], out["category"].basis["of"]) == (2, 3)


def test_a_stored_answer_for_the_same_payload_and_categories_wins_over_historys_majority() -> None:
    e = entry(counterparty_ref="DE99", counterparty_name="Max", purpose="Konzert Karten")
    out = _with_model(e, stored=_answer(e, 2, (2, 1)))
    assert out["category"].value == 2 and out["category"].pass_name == "llm"
    # "no category fits" replaces it as well: an explained absence
    out = _with_model(e, stored=_answer(e, None, (1, 2)))
    assert out["category"].value is None and out["category"].pass_name == "llm"
    assert out["type"].value == "flow"


def test_an_answer_given_for_other_categories_no_longer_stands() -> None:
    e = entry(counterparty_ref="DE99", counterparty_name="Max", purpose="Konzert Karten")
    out = _with_model(e, stored=_answer(e, 2, (1,)))
    assert out["category"].pass_name == "history"


def test_a_unanimous_history_is_not_replaced_by_a_stored_answer() -> None:
    e = entry(counterparty_ref="DE99", counterparty_name="Max", purpose="Pizza Essen Samstag")
    out = _with_model(e, stored=_answer(e, 1, (1, 2)))
    assert out["category"].value == 2 and out["category"].pass_name == "history"
    assert out["category"].basis["matched_on"] == "counterparty_ref+purpose"


def test_when_history_has_votes_but_no_majority_the_model_is_asked_with_the_categories() -> None:
    votes = [
        vote(counterparty_ref="DE99", purpose="a", category_id=1),
        vote(counterparty_ref="DE99", purpose="b", category_id=2),
    ]
    e = entry(counterparty_ref="DE99", counterparty_name="Max", purpose="Konzert Karten")
    assert "category" not in _with_model(e, votes)
    out = _with_model(e, votes, stored=_answer(e, 2, (2, 1)))
    assert out["category"].value == 2 and out["category"].pass_name == "llm"


def test_shell_and_mediamarkt_share_nothing_but_the_banks_words() -> None:
    votes = [
        vote(counterparty_name="MediaMarkt", purpose="Kartenzahlung girocard", category_id=2, payee_id=9)
    ]
    shell = entry(counterparty_name="Shell", purpose="Kartenzahlung girocard")
    out = _with_model(shell, votes)
    assert dict(out) == {}
