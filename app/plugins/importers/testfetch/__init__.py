"""A scripted fake fetch importer for development and tests (architecture §5.5, §8).

Everything it does is determined by its instance settings, so a database, a test and the sync UI can
exercise every path — each prompt kind, a wrong PIN, an expired TAN, every failure class, discovery with a
pocket in a second currency — without a bank. It reads nothing but its settings and `state`, and no
clock: `today` is passed in.

Settings (`importer_instance.settings`):

    accounts        list of {ref, name?, currency="EUR", kind_hint="checking",
                    capabilities=["transactions", "balance"], history_start="2026-01-01",
                    rows_per_day=1, opening_minor=0, fetch=[step, ...]}
                    `fetch` steps run before that account's fetch
    open            steps run in `open`
    discover        steps run in `accounts()`
    documents       list of documents, `start_date` and `covered_through`: as `testdocs`
    documents_fetch steps run before the documents are fetched
    documents_position  object: the delivery's `position` (applied to `state` once ingested)
    documents_stats object of integers: the delivery's `importer_stats`
    documents_exponents list of currency codes: each adds `exponent_<code>` to the delivery's
                    `importer_stats`, the exponent `minor_units_of` answered (what the caller passed)
    default_start   ISO date: `default_fetch_start` (else thirty days before today)

A step is one of:

    {"ask": "secret", "subject": "pin", "expect": "<value>"}      a wrong value raises AuthRejected
    {"ask": "tan", "medium": "text" | "image" | "decoupled", "expect": "<value>", "polls": N}
    {"ask": "choice", "subject": "tan_medium", "options": [{"id": .., "label": ..}], "remember": "medium"}
    {"ask": "text", "subject": "tan_medium_name", "remember": "medium_name"}
    {"raise": "auth_rejected" | "challenge_expired" | "challenge_abandoned" | "source_unavailable"
              | "parse_failed" | "not_registered" | "bank_setup_required" | "account_unsupported"
              | "unexpected"}
    {"sleep_ms": N}

Every `ask` takes `timeout_s` (to test expiry in milliseconds) and `unless_state` (skip the step when
`state` already has that key); a choice or text `ask` takes `remember`, which writes the answer into
`state` so a second run does not ask again (a secret is never remembered). A decoupled step polls and
confirms after `polls` calls.

Rows are a pure function of the date, never of `since`: for each day from `history_start` to the day
before `today`, `rows_per_day` rows whose amount, purpose, `source_id` and `raw` derive from
`(ref, day, i)`. A fetch returns the rows dated `since` or later; the coverage is `today - 1`; the
reported balance is `opening_minor` plus every generated row up to that day, dated `today - 1`, whatever
`since` is. Two overlapping fetches therefore deliver the same identities and the second reconciles to
zero (the two-run rule, architecture §8).
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

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
    DiscoveredAccount,
    FetchedTransactions,
    FetchSession,
    FetchSessionBase,
    Option,
    Prompter,
    SecretPrompt,
    TanPrompt,
    TextPrompt,
)
from app.core.plugins.importer import DocumentDelivery, IncomingRow
from app.plugins.importers.testdocs import PROVIDERS, TestDocumentImporter
from app.utils import clock

# a one-pixel PNG: the photoTAN of every image step
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

_RAISES: dict[str, Callable[[], Exception]] = {
    "auth_rejected": lambda: AuthRejected("simulated: the PIN was rejected"),
    "challenge_expired": lambda: ChallengeExpired("simulated: the TAN timed out"),
    "challenge_abandoned": lambda: ChallengeAbandoned("simulated: the challenge was abandoned"),
    "source_unavailable": lambda: SourceUnavailable("simulated: the bank is unreachable"),
    "parse_failed": lambda: ParseFailed("simulated: the response does not fit"),
    "not_registered": lambda: NotRegistered("simulated: the product is not registered"),
    "bank_setup_required": lambda: BankSetupRequired(
        "simulated 9940: no active TAN device; finish setup with the bank, then run again"
    ),
    "account_unsupported": lambda: AccountUnsupported("simulated: no booking retrieval for this account"),
    "unexpected": lambda: RuntimeError("simulated unexpected failure"),
}
_CAPABILITIES = frozenset({"transactions", "balance"})
_DEFAULT_HISTORY_START = date(2026, 1, 1)


# ---- settings ------------------------------------------------------------------------------


def _bad(path: str, why: str) -> InvalidProfile:
    return InvalidProfile(f"{path}: {why}")


def _iso(path: str, value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise _bad(path, "must be an ISO date") from None


def _check_steps(path: str, steps: Any) -> None:
    if not isinstance(steps, list | tuple):
        raise _bad(path, "must be a list of steps")
    for n, step in enumerate(steps):
        here = f"{path}[{n}]"
        if not isinstance(step, Mapping):
            raise _bad(here, "a step is an object")
        kinds = [k for k in ("ask", "raise", "sleep_ms") if k in step]
        if len(kinds) != 1:
            raise _bad(here, "a step is exactly one of ask, raise, sleep_ms")
        if "raise" in step and step["raise"] not in _RAISES:
            raise _bad(here, f"raise is one of {sorted(_RAISES)}")
        if "sleep_ms" in step and not (isinstance(step["sleep_ms"], int) and step["sleep_ms"] >= 0):
            raise _bad(here, "sleep_ms must be a non-negative integer")
        if "ask" in step:
            _check_ask(here, step)


def _check_ask(here: str, step: Mapping[str, Any]) -> None:
    kind = step["ask"]
    if kind not in ("secret", "tan", "choice", "text"):
        raise _bad(here, "ask is one of secret, tan, choice, text")
    if kind == "tan" and step.get("medium", "text") not in ("text", "image", "decoupled"):
        raise _bad(here, "medium is one of text, image, decoupled")
    if kind == "choice":
        options = step.get("options")
        if not (
            isinstance(options, list)
            and options
            and all(isinstance(o, Mapping) and "id" in o for o in options)
        ):
            raise _bad(here, "a choice needs options, each with an id")
    if "remember" in step and kind not in ("choice", "text"):
        raise _bad(here, "only a choice or a text answer is remembered: a secret never goes into state")
    if "polls" in step and not (isinstance(step["polls"], int) and step["polls"] >= 0):
        raise _bad(here, "polls must be a non-negative integer")
    if "timeout_s" in step and not (isinstance(step["timeout_s"], int | float) and step["timeout_s"] > 0):
        raise _bad(here, "timeout_s must be a positive number")


def _check_account(path: str, raw: Any) -> str:
    if not isinstance(raw, Mapping):
        raise _bad(path, "an account is an object")
    ref = raw.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        raise _bad(f"{path}.ref", "must be a non-empty string")
    currency = raw.get("currency", "EUR")
    if not (isinstance(currency, str) and len(currency) == 3):
        raise _bad(f"{path}.currency", "must be a three-letter code")
    capabilities = raw.get("capabilities", ["transactions", "balance"])
    if not (isinstance(capabilities, list) and set(capabilities) <= _CAPABILITIES):
        raise _bad(f"{path}.capabilities", f"must be a list drawn from {sorted(_CAPABILITIES)}")
    _iso(f"{path}.history_start", raw.get("history_start", _DEFAULT_HISTORY_START.isoformat()))
    for key in ("rows_per_day", "opening_minor"):
        if not isinstance(raw.get(key, 0), int):
            raise _bad(f"{path}.{key}", "must be an integer")
    if raw.get("rows_per_day", 1) < 0:
        raise _bad(f"{path}.rows_per_day", "must not be negative")
    _check_steps(f"{path}.fetch", raw.get("fetch", []))
    return ref


# ---- rows ----------------------------------------------------------------------------------


def _digest(ref: str, day: date, i: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{ref}|{day.isoformat()}|{i}".encode()).digest()[:8], "big")


def _row(ref: str, currency: str, day: date, i: int) -> IncomingRow:
    h = _digest(ref, day, i)
    amount = 100 + h % 9000
    if h % 5:  # four in five are debits
        amount = -amount
    return IncomingRow(
        amount_minor=amount,
        currency=currency,
        booked_on=day,
        source_format="testfetch",
        raw={"ref": ref, "day": day.isoformat(), "i": i},
        counterparty_name=f"Shop {h % 7}",
        purpose=f"Test booking {ref} {day.isoformat()} #{i}",
        booking_text="TESTBOOKING",
        source_id=f"{ref}-{day:%Y%m%d}-{i}",
    )


def _days(start: date, end: date) -> Sequence[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


# ---- the importer --------------------------------------------------------------------------


class _Session(FetchSessionBase):
    def __init__(
        self, settings: Mapping[str, Any], state: MutableMapping[str, Any], prompter: Prompter, today: date
    ) -> None:
        self._settings = settings
        self._state = state
        self._prompter = prompter
        self._today = today

    def accounts(self) -> Sequence[DiscoveredAccount]:
        self.run_steps(self._settings.get("discover", ()))
        return [
            DiscoveredAccount(
                external_ref=a["ref"],
                name=a.get("name", a["ref"]),
                currency=a.get("currency", "EUR"),
                kind_hint=a.get("kind_hint", "checking"),
                capabilities=frozenset(a.get("capabilities", _CAPABILITIES)),
            )
            for a in self._settings.get("accounts", ())
        ]

    def fetch_account(
        self,
        external_ref: str,
        *,
        since: date,
        today: date,
        currency: str,
        minor_units_of: Callable[[str], int],
    ) -> FetchedTransactions:
        account = next((a for a in self._settings.get("accounts", ()) if a["ref"] == external_ref), None)
        capabilities = set(account.get("capabilities", _CAPABILITIES)) if account else set()
        if account is None or "transactions" not in capabilities:
            raise AccountUnsupported("the bank offers no booking retrieval for this account")
        self.run_steps(account.get("fetch", ()))
        ref, own_currency = account["ref"], account.get("currency", "EUR")
        start = date.fromisoformat(account.get("history_start", _DEFAULT_HISTORY_START.isoformat()))
        through = today - timedelta(days=1)
        per_day = account.get("rows_per_day", 1)
        generated = [_row(ref, own_currency, d, i) for d in _days(start, through) for i in range(per_day)]
        balance = account.get("opening_minor", 0) + sum(r.amount_minor for r in generated)
        wants_balance = "balance" in capabilities
        return FetchedTransactions(
            rows=tuple(r for r in generated if r.booked_on >= since),
            covered_through=through,
            covered_from=since,
            reported_balance=balance if wants_balance else None,
            balance_on=through if wants_balance else None,
        )

    def fetch_documents(
        self, *, since: date, today: date, minor_units_of: Callable[[str], int]
    ) -> DocumentDelivery:
        self.run_steps(self._settings.get("documents_fetch", ()))
        settings = {
            "start_date": self._settings.get("start_date", since.isoformat()),
            "covered_through": self._settings.get("covered_through", (today - timedelta(days=1)).isoformat()),
            "documents": self._settings.get("documents", []),
        }
        delivery = TestDocumentImporter().fetch(settings, since=since, today=today)
        stats = dict(self._settings.get("documents_stats", {}))
        for code in self._settings.get("documents_exponents", ()):
            stats[f"exponent_{code}"] = minor_units_of(code)
        position = self._settings.get("documents_position")
        return replace(delivery, importer_stats=stats, position=dict(position) if position else None)

    # ---- steps ----

    def run_steps(self, steps: Sequence[Mapping[str, Any]]) -> None:
        for step in steps:
            if step.get("unless_state") in self._state:
                continue
            if "raise" in step:
                raise _RAISES[step["raise"]]()
            if "sleep_ms" in step:
                clock.sleep(step["sleep_ms"] / 1000)
            else:
                self._ask(step)

    def _ask(self, step: Mapping[str, Any]) -> None:
        kind = step["ask"]
        timeout = step.get("timeout_s")
        expect = step.get("expect")
        if kind == "secret":
            answer = self._prompter.ask(SecretPrompt(step.get("subject", "pin")), timeout_s=timeout)
            self._check_expected(answer, expect, "the PIN was rejected")
        elif kind == "tan":
            medium = step.get("medium", "text")
            if medium == "decoupled":
                calls = 0
                wanted: int = step.get("polls", 1)

                def poll() -> bool:
                    nonlocal calls
                    calls += 1
                    return calls >= wanted

                self._prompter.ask(
                    TanPrompt("decoupled", "Confirm in your banking app", "testApp"),
                    poll=poll,
                    timeout_s=timeout,
                )
                return
            prompt = (
                TanPrompt("image", "Scan the code", "testPhotoTAN", PIXEL_PNG, "image/png")
                if medium == "image"
                else TanPrompt("text", "Enter the TAN", "testTAN")
            )
            self._check_expected(
                self._prompter.ask(prompt, timeout_s=timeout), expect, "the TAN was rejected"
            )
        elif kind == "choice":
            options = tuple(Option(str(o["id"]), str(o.get("label", o["id"]))) for o in step["options"])
            chosen = self._prompter.ask(
                ChoicePrompt(step.get("subject", "tan_medium"), options), timeout_s=timeout
            )
            self._remember(step, chosen)
        else:
            typed = self._prompter.ask(TextPrompt(step.get("subject", "tan_medium_name")), timeout_s=timeout)
            self._remember(step, typed)

    @staticmethod
    def _check_expected(answer: Any, expect: str | None, message: str) -> None:
        if expect is not None and (answer is None or answer.reveal() != expect):
            raise AuthRejected(message)  # never quotes the answer

    def _remember(self, step: Mapping[str, Any], answer: Any) -> None:
        if "remember" in step:
            self._state[step["remember"]] = answer


class TestFetchImporter:
    """Satisfies `FetchImporter`; scripted entirely by its settings."""

    __test__ = False  # not a pytest class, whatever its name

    emits: frozenset[str] = frozenset({"transactions", "documents"})
    providers: frozenset[str] = PROVIDERS

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        accounts = settings.get("accounts", [])
        if not isinstance(accounts, list):
            raise _bad("accounts", "must be a list")
        refs = [_check_account(f"accounts[{n}]", a) for n, a in enumerate(accounts)]
        if len(set(refs)) != len(refs):
            raise _bad("accounts", "references must be unique")
        _check_steps("open", settings.get("open", []))
        _check_steps("discover", settings.get("discover", []))
        _check_steps("documents_fetch", settings.get("documents_fetch", []))
        if "default_start" in settings:
            _iso("default_start", settings["default_start"])
        if "start_date" in settings:
            _iso("start_date", settings["start_date"])
        if "covered_through" in settings:
            _iso("covered_through", settings["covered_through"])
        documents = settings.get("documents", [])
        if not isinstance(documents, list):
            raise _bad("documents", "must be a list")
        if documents:  # reuse the document importer's own check
            TestDocumentImporter().validate_settings(
                {
                    "start_date": settings.get("start_date", "2026-01-01"),
                    "covered_through": settings.get("covered_through", "2026-01-01"),
                    "documents": documents,
                }
            )

    def default_fetch_start(self, settings: Mapping[str, Any], *, today: date) -> date:
        if "default_start" in settings:
            return _iso("default_start", settings["default_start"])
        return today - timedelta(days=30)

    def open(
        self,
        settings: Mapping[str, Any],
        state: MutableMapping[str, Any],
        prompter: Prompter,
        *,
        today: date,
    ) -> FetchSession:
        session = _Session(settings, state, prompter, today)
        session.run_steps(settings.get("open", ()))
        return session
