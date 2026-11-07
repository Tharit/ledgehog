"""The scripted fetch importer: rows are a pure function of the date, the balance follows the capabilities,
and its steps drive every prompt kind and failure class. No database, no task."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from app.core.plugins.errors import (
    AccountUnsupported,
    AuthRejected,
    BankSetupRequired,
    ChallengeAbandoned,
    ChallengeExpired,
    InvalidProfile,
    NotRegistered,
    ParseFailed,
    SourceUnavailable,
)
from app.core.plugins.fetch import (
    ChoicePrompt,
    FetchImporter,
    Option,
    Prompt,
    SecretPrompt,
    SecretText,
    TanPrompt,
    TextPrompt,
)
from app.plugins.importers.testdocs import PROVIDERS
from app.plugins.importers.testfetch import PIXEL_PNG, TestFetchImporter
from app.utils import clock

TODAY = date(2026, 6, 15)
IMP = TestFetchImporter()


class Scripted:
    """A prompter that answers from a list and records what it was asked."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[Prompt, float | None]] = []
        self.polls = 0

    def ask(
        self, prompt: Prompt, *, poll: Callable[[], bool] | None = None, timeout_s: float | None = None
    ) -> Any:
        self.asked.append((prompt, timeout_s))
        if isinstance(prompt, TanPrompt) and prompt.medium == "decoupled":
            assert poll is not None
            while not poll():
                self.polls += 1
            self.polls += 1
            return None
        answer = self.answers.pop(0)
        return SecretText(answer) if isinstance(prompt, SecretPrompt | TanPrompt) else answer


def session(
    settings: dict[str, Any], prompter: Scripted | None = None, state: dict[str, Any] | None = None
) -> Any:
    return IMP.open(settings, {} if state is None else state, prompter or Scripted(), today=TODAY)


def fetch(sess: Any, ref: str = "A", *, since: date = date(2026, 6, 1), today: date = TODAY) -> Any:
    return sess.fetch_account(
        ref, since=since, today=today, currency="EUR", minor_units_of=lambda c: 2, progress=lambda d, t: None
    )


def acct(**kw: Any) -> dict[str, Any]:
    return {"ref": "A", "history_start": "2026-06-01", **kw}


# ---- shape -----------------------------------------------------------------------------------------


def test_it_is_a_fetch_importer_emitting_both_kinds() -> None:
    assert isinstance(IMP, FetchImporter)
    assert IMP.emits == {"transactions", "documents"} and IMP.providers == PROVIDERS


def test_default_start_is_the_setting_else_thirty_days_back() -> None:
    assert IMP.default_fetch_start({"default_start": "2026-02-01"}, today=TODAY) == date(2026, 2, 1)
    assert IMP.default_fetch_start({}, today=TODAY) == date(2026, 5, 16)


# ---- rows ------------------------------------------------------------------------------------------


def test_rows_are_a_pure_function_of_the_date_not_of_since() -> None:
    sess = session({"accounts": [acct(rows_per_day=2)]})
    wide, narrow = fetch(sess, since=date(2026, 6, 1)), fetch(sess, since=date(2026, 6, 10))
    assert len(wide.rows) == 28 and len(narrow.rows) == 10  # 14 days, two a day; 5 days, two a day
    assert narrow.rows == wide.rows[-10:]  # the very same rows, identities included
    assert fetch(sess, since=date(2026, 6, 1)).rows == wide.rows  # and again
    ids = [r.source_id for r in wide.rows]
    assert len(set(ids)) == 28 and ids[0] == "A-20260601-0"
    assert all(r.amount_minor != 0 and r.currency == "EUR" and r.raw["ref"] == "A" for r in wide.rows)
    assert {r.booked_on for r in wide.rows} == {date(2026, 6, d) for d in range(1, 15)}
    other = fetch(session({"accounts": [acct(ref="B")]}), "B")
    # the amounts are keyed by the reference too
    assert [r.amount_minor for r in other.rows] != [r.amount_minor for r in wide.rows[::2]]


def test_coverage_is_the_day_before_today_even_when_nothing_is_delivered() -> None:
    sess = session({"accounts": [acct()]})
    got = fetch(sess, since=TODAY)  # nothing dated today or later is delivered
    assert got.rows == () and got.covered_through == date(2026, 6, 14)
    assert got.covered_from == TODAY


def test_the_balance_is_the_opening_plus_every_row_whatever_since_is() -> None:
    sess = session({"accounts": [acct(opening_minor=5000)]})
    wide, narrow = fetch(sess, since=date(2026, 6, 1)), fetch(sess, since=date(2026, 6, 12))
    total = sum(r.amount_minor for r in wide.rows)
    assert wide.reported_balance == narrow.reported_balance == 5000 + total
    assert wide.balance_on == narrow.balance_on == date(2026, 6, 14)


def test_a_day_later_adds_rows_and_moves_the_balance_by_exactly_them() -> None:
    sess = session({"accounts": [acct()]})
    today1, today2 = fetch(sess), fetch(sess, today=date(2026, 6, 16))
    extra = [r for r in today2.rows if r.booked_on == date(2026, 6, 15)]
    assert len(extra) == 1
    assert today2.reported_balance == today1.reported_balance + extra[0].amount_minor


def test_capabilities_decide_the_balance_and_the_fetch() -> None:
    sess = session(
        {
            "accounts": [
                acct(ref="NB", capabilities=["transactions"]),
                acct(ref="NT", capabilities=["balance"]),
                acct(ref="NONE", capabilities=[]),
            ]
        }
    )
    no_balance = fetch(sess, "NB")
    assert no_balance.reported_balance is None and no_balance.balance_on is None and no_balance.rows
    for ref in ("NT", "NONE", "UNKNOWN"):
        with pytest.raises(AccountUnsupported):
            fetch(sess, ref)


def test_discovery_lists_accounts_with_what_each_can_deliver() -> None:
    sess = session(
        {
            "accounts": [
                acct(ref="EUR1", name="Main"),
                acct(ref="USD1", name="Main USD", currency="USD"),
                acct(ref="DEPOT", kind_hint="depot", capabilities=[]),
            ]
        }
    )
    found = sess.accounts()
    assert [(a.external_ref, a.name, a.currency, a.kind_hint) for a in found] == [
        ("EUR1", "Main", "EUR", "checking"),
        ("USD1", "Main USD", "USD", "checking"),
        ("DEPOT", "DEPOT", "EUR", "depot"),
    ]
    assert found[0].capabilities == {"transactions", "balance"} and found[2].capabilities == frozenset()


def test_documents_are_testdocs_behaviour() -> None:
    doc = {
        "provider": "paypal",
        "source_id": "D1",
        "occurred_on": "2026-06-02",
        "total_minor": -100,
        "currency": "EUR",
    }
    old = {**doc, "source_id": "D0", "occurred_on": "2026-05-01"}
    sess = session({"start_date": "2026-05-01", "documents": [doc, old]})
    got = sess.fetch_documents(
        since=date(2026, 6, 1), today=TODAY, minor_units_of=lambda c: 2, progress=lambda d, t: None
    )
    assert [d.source_id for d in got.documents] == ["D1"]
    assert got.covered_through == date(2026, 6, 14) and got.covered_from == date(2026, 5, 1)


# ---- steps -------------------------------------------------------------------------------------------


def test_a_wrong_pin_raises_auth_rejected_without_quoting_it() -> None:
    steps = {"open": [{"ask": "secret", "subject": "pin", "expect": "1234"}]}
    session(steps, Scripted("1234"))  # right: signed in
    with pytest.raises(AuthRejected) as err:
        session(steps, Scripted("0000-secret"))
    assert "0000" not in str(err.value) and "1234" not in str(err.value)


def test_every_tan_medium() -> None:
    prompter = Scripted("111", "222")
    session(
        {
            "open": [
                {"ask": "tan", "medium": "text", "expect": "111"},
                {"ask": "tan", "medium": "image", "expect": "222"},
                {"ask": "tan", "medium": "decoupled", "polls": 3},
            ]
        },
        prompter,
    )
    text_tan, image_tan, decoupled = (p for p, _ in prompter.asked)
    assert isinstance(text_tan, TanPrompt) and text_tan.medium == "text"
    assert isinstance(image_tan, TanPrompt) and image_tan.image == PIXEL_PNG
    assert image_tan.image_mime == "image/png"
    assert isinstance(decoupled, TanPrompt) and decoupled.medium == "decoupled"
    assert prompter.polls == 3  # confirmed on the third poll
    with pytest.raises(AuthRejected):
        session({"open": [{"ask": "tan", "medium": "text", "expect": "111"}]}, Scripted("999"))


def test_choice_and_text_answers_are_remembered_and_skipped_next_time() -> None:
    steps = {
        "open": [
            {
                "ask": "choice",
                "subject": "tan_medium",
                "options": [{"id": "1", "label": "Phone"}, {"id": "2"}],
                "remember": "medium",
                "unless_state": "medium",
            },
            {"ask": "text", "subject": "tan_medium_name", "remember": "name", "unless_state": "name"},
        ]
    }
    state: dict[str, Any] = {}
    prompter = Scripted("2", "My card")
    session(steps, prompter, state)
    assert state == {"medium": "2", "name": "My card"}
    choice = prompter.asked[0][0]
    assert choice == ChoicePrompt("tan_medium", (Option("1", "Phone"), Option("2", "2")))
    assert prompter.asked[1][0] == TextPrompt("tan_medium_name")
    again = Scripted()
    session(steps, again, state)  # remembered: nothing is asked
    assert again.asked == []


def test_a_timeout_is_passed_to_the_prompter() -> None:
    prompter = Scripted("x")
    session({"open": [{"ask": "secret", "subject": "pin", "timeout_s": 0.25}]}, prompter)
    assert prompter.asked[0][1] == 0.25


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("auth_rejected", AuthRejected),
        ("challenge_expired", ChallengeExpired),
        ("challenge_abandoned", ChallengeAbandoned),
        ("source_unavailable", SourceUnavailable),
        ("parse_failed", ParseFailed),
        ("not_registered", NotRegistered),
        ("bank_setup_required", BankSetupRequired),
        ("account_unsupported", AccountUnsupported),
        ("unexpected", RuntimeError),
    ],
)
def test_every_failure_class_can_be_raised_at_open_and_at_a_data_call(
    code: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        session({"open": [{"raise": code}]})
    sess = session({"accounts": [acct(fetch=[{"raise": code}])]})
    with pytest.raises(error):
        fetch(sess)
    with pytest.raises(error):
        session({"discover": [{"raise": code}]}).accounts()
    with pytest.raises(error):
        session({"documents_fetch": [{"raise": code}]}).fetch_documents(
            since=TODAY, today=TODAY, minor_units_of=lambda c: 2, progress=lambda d, t: None
        )


def test_sleep_waits_through_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(clock, "sleep", slept.append)
    session({"open": [{"sleep_ms": 250}]})
    assert slept == [0.25]


# ---- validation --------------------------------------------------------------------------------------


def test_valid_settings_pass() -> None:
    IMP.validate_settings({})
    IMP.validate_settings(
        {
            "accounts": [acct(rows_per_day=2, opening_minor=-5, fetch=[{"sleep_ms": 1}])],
            "open": [{"ask": "secret", "subject": "pin"}, {"raise": "source_unavailable"}],
            "discover": [],
            "default_start": "2026-01-01",
            "start_date": "2026-01-01",
            "covered_through": "2026-06-01",
            "documents": [
                {
                    "provider": "paypal",
                    "source_id": "D",
                    "occurred_on": "2026-02-01",
                    "total_minor": -1,
                    "currency": "EUR",
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"accounts": "no"},
        {"accounts": [{"name": "no ref"}]},
        {"accounts": [acct(), acct()]},
        {"accounts": [acct(currency="EURO")]},
        {"accounts": [acct(capabilities=["magic"])]},
        {"accounts": [acct(history_start="long ago")]},
        {"accounts": [acct(rows_per_day=-1)]},
        {"accounts": [acct(fetch="nothing")]},
        {"open": [{"ask": "nothing"}]},
        {"open": [{"ask": "secret", "raise": "auth_rejected"}]},
        {"open": [{"raise": "teapot"}]},
        {"open": [{"sleep_ms": -1}]},
        {"open": [{"ask": "tan", "medium": "voice"}]},
        {"open": [{"ask": "choice", "options": []}]},
        {"open": [{"ask": "secret", "subject": "pin", "remember": "pin"}]},  # a secret never goes into state
        {"open": [{"ask": "tan", "medium": "decoupled", "polls": -2}]},
        {"open": [{"ask": "secret", "timeout_s": 0}]},
        {"open": "none"},
        {"default_start": "soon"},
        {"documents": "none"},
        {"documents": [{"provider": "ebay"}]},
    ],
)
def test_malformed_settings_are_refused_naming_the_setting(bad: dict[str, Any]) -> None:
    with pytest.raises(InvalidProfile):
        IMP.validate_settings(bad)


def test_the_message_names_the_setting() -> None:
    with pytest.raises(InvalidProfile, match=r"^accounts\[1\]\.ref: "):
        IMP.validate_settings({"accounts": [acct(), {"name": "x"}]})
