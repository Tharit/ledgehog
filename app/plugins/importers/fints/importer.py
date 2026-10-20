"""The FinTS fetch importer (spec/plugins/importers/fints.md).

Its logic (the PIN and TAN prompts, the code table, the learned `tan_for`, discovery, statements to
records, card answers to records) is written against `BankSession` (bank.py) and holds no open dialog
between calls: every data call runs in its own dialog (fints.md §2). Tested against a fake session.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from datetime import date, timedelta
from typing import Any, TypeVar
from urllib.parse import urlsplit

from app.core.plugins.errors import (
    AccountUnsupported,
    ChallengeAbandoned,
    InvalidProfile,
    NotRegistered,
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
    SecretText,
    TanPrompt,
    TextPrompt,
)
from app.plugins.importers.fints.bank import (
    BankConnect,
    BankLogin,
    BankSession,
    CardAnswer,
    Challenge,
    Dialog,
    DialogFailed,
    ReturnCode,
)
from app.plugins.importers.fints.cards import read_card
from app.plugins.importers.fints.codes import MEDIUM_REFUSED, STRONG_AUTH_REQUIRED, error_for, errors_in, has
from app.plugins.importers.fints.discovery import discover, fetch_kind, find
from app.plugins.importers.fints.hkku import CARD_REQUEST
from app.plugins.importers.fints.library import connect_bank
from app.plugins.importers.fints.statements import read_statements

log = logging.getLogger("ledgehog.fints")

T = TypeVar("T")

SETTINGS = ("url", "bank_code", "user_id", "customer_id")
DEFAULT_START_DAYS = 90  # the bank's history that needs no strong authentication (PSD2)
STATEMENT_REQUEST = "HKKAZ"
ONE_STEP = "999"


def _bad(key: str, why: str) -> InvalidProfile:
    return InvalidProfile(f"{key}: {why}")


class _Refused(Exception):
    """A dialog the bank refused: its codes decide what that is."""

    def __init__(self, codes: Sequence[ReturnCode], detail: str) -> None:
        super().__init__(detail)
        self.codes = tuple(codes)
        self.detail = detail


class _Plan:
    """The TAN request of one attempt (§4): the dialog's body names the request it sends, and whether a
    TAN request goes with it is decided here, from what is learned and from a retry after a 9075."""

    def __init__(self, learned: set[str], retry: bool) -> None:
        self._learned, self._retry = learned, retry
        self.request: str | None = None  # the request the body sent, once it has
        self.attached = False

    def attach(self, request: str) -> bool:
        self.request = request
        self.attached = request in self._learned or self._retry
        return self.attached


class FintsImporter:
    """Satisfies `FetchImporter`. Reads neither the database nor the clock."""

    emits: frozenset[str] = frozenset({"transactions"})
    providers: frozenset[str] = frozenset()

    def __init__(
        self, product_id: str | None, product_version: str, *, connect: BankConnect = connect_bank
    ) -> None:
        self._product_id = product_id
        self._product_version = product_version[:5]  # the field's length in the protocol
        self._connect = connect

    # ---- settings ----

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        for key in settings:
            if key not in SETTINGS:
                raise _bad(str(key), "unknown setting")
        url = settings.get("url")
        if not isinstance(url, str) or not url.strip():
            raise _bad("url", "is required")
        parts = urlsplit(url.strip())
        if parts.scheme == "http":
            raise _bad("url", "must be https: the PIN would cross the wire in the clear")
        if parts.scheme != "https" or not parts.hostname:
            raise _bad("url", "must be an https address with a host")
        if parts.username is not None or parts.password is not None:
            raise _bad("url", "must not carry credentials")
        code = settings.get("bank_code")
        if not isinstance(code, str) or not re.fullmatch(r"\d{8}", code.strip()):
            raise _bad("bank_code", "must be the bank's eight-digit code")
        user = settings.get("user_id")
        if not isinstance(user, str) or not user.strip():
            raise _bad("user_id", "is required")
        customer = settings.get("customer_id")
        if customer is not None and not isinstance(customer, str):
            raise _bad("customer_id", "must be text")

    def default_fetch_start(self, settings: Mapping[str, Any], *, today: date) -> date:
        return today - timedelta(days=DEFAULT_START_DAYS)

    # ---- the session ----

    def open(
        self,
        settings: Mapping[str, Any],
        state: MutableMapping[str, Any],
        prompter: Prompter,
        *,
        today: date,
    ) -> FetchSession:
        if not self._product_id:
            raise NotRegistered("FINTS_PRODUCT_ID is not set (spec §7.1)")
        pin = prompter.ask(SecretPrompt("pin"))
        if not isinstance(pin, SecretText) or not pin:
            raise ChallengeAbandoned("no PIN was given")
        customer = settings.get("customer_id")
        medium = state.get("tan_medium")
        bank = self._connect(
            BankLogin(
                url=str(settings["url"]).strip(),
                bank_code=str(settings["bank_code"]).strip(),
                user_id=str(settings["user_id"]).strip(),
                customer_id=customer.strip() if isinstance(customer, str) and customer.strip() else None,
                pin=pin,
                product_id=self._product_id,
                product_version=self._product_version,
                system_id=str(state["system_id"]) if state.get("system_id") else None,
                tan_medium=str(medium) if medium else None,
            )
        )
        session = _Session(bank, state, prompter)
        try:
            session.set_up()
        except BaseException:
            bank.close()
            raise
        return session


class _Session(FetchSessionBase):
    def __init__(self, bank: BankSession, state: MutableMapping[str, Any], prompter: Prompter) -> None:
        self._bank = bank
        self._state = state
        self._prompter = prompter
        self._asked_medium_name = False

    # ---- setup: the TAN procedure and, where wanted, the medium ----

    def set_up(self) -> None:
        procedures = self._call(self._bank.procedures)
        self._learn_system_id()
        by_code = {p.code: p for p in procedures}
        remembered = self._state.get("tan_mechanism")
        if remembered is not None and str(remembered) not in by_code:
            # the bank no longer lists it: asked afresh, and its medium with it
            self._state.pop("tan_mechanism", None)
            self._state.pop("tan_medium", None)
            remembered = None
        if remembered is not None:
            code = str(remembered)
        else:
            code = self._choose_procedure([p for p in procedures if p.code != ONE_STEP], by_code)
        self._bank.use_procedure(code)
        if self._bank.medium_required():
            medium = self._state.get("tan_medium") or self._choose_medium()
            self._bank.use_medium(str(medium))
        self._bank.finish_setup()

    def _choose_procedure(self, candidates: list[Any], by_code: Mapping[str, Any]) -> str:
        if not candidates:  # one-step, or a bank that lists none: let the bank decide
            return ONE_STEP
        if len(candidates) == 1:
            code = str(candidates[0].code)
        else:
            options = tuple(Option(p.code, p.name) for p in candidates)
            answer = self._prompter.ask(ChoicePrompt("tan_mechanism", options))
            code = str(answer) if answer is not None else ""
            if code not in by_code:
                raise ChallengeAbandoned("no TAN procedure was chosen")
        self._state["tan_mechanism"] = code
        return code

    def _choose_medium(self) -> str:
        try:
            media = self._bank.media()
        except DialogFailed as failed:
            if not has(failed.codes, MEDIUM_REFUSED):
                raise error_for(failed.codes, failed.detail) from None
            media = None  # the bank refuses the list: the user names the device
        self._learn_system_id()
        if media and len(media) == 1:
            name = media[0]
        elif media:
            answer = self._prompter.ask(ChoicePrompt("tan_medium", tuple(Option(m, m) for m in media)))
            name = str(answer) if answer is not None else ""
            if name not in media:
                raise ChallengeAbandoned("no TAN medium was chosen")
        else:
            name = self._ask_medium_name()
        self._state["tan_medium"] = name
        return name

    def _ask_medium_name(self) -> str:
        self._asked_medium_name = True
        answer = self._prompter.ask(TextPrompt("tan_medium_name"))
        name = str(answer).strip() if answer is not None else ""
        if not name:
            raise ChallengeAbandoned("no TAN medium name was given")
        return name

    # ---- the FetchSession ----

    def accounts(self) -> Sequence[DiscoveredAccount]:
        return self._run(lambda dialog, plan: discover(dialog.accounts))

    def fetch_account(
        self,
        external_ref: str,
        *,
        since: date,
        today: date,
        currency: str,
        minor_units_of: Callable[[str], int],
    ) -> FetchedTransactions:
        until = today - timedelta(days=1)
        start = min(since, until)  # a request is never empty-ranged

        def request(dialog: Dialog, plan: _Plan) -> str | CardAnswer:
            account = find(dialog.accounts, external_ref)
            kind = None if account is None else fetch_kind(account)
            if account is None or kind is None:
                raise AccountUnsupported("the bank offers no statement or card request for this account")
            if kind == "card":
                return dialog.card(account, start, until, with_tan=plan.attach(CARD_REQUEST))
            return dialog.statements(account, start, until, with_tan=plan.attach(STATEMENT_REQUEST))

        answer = self._run(request)
        if isinstance(answer, CardAnswer):
            card = read_card(answer, until=until, minor_units_of=minor_units_of)
            return FetchedTransactions(
                rows=card.rows,
                covered_through=card.covered_through,
                covered_from=min(start, card.covered_through),
                reported_balance=card.balance_minor,
                balance_on=card.balance_on,
                importer_stats={"filtered": card.filtered},
            )
        read = read_statements(answer, until=until, minor_units_of=minor_units_of)
        return FetchedTransactions(
            rows=read.rows,
            covered_through=until,
            covered_from=start,
            reported_balance=read.balance_minor,
            balance_on=read.balance_on,
            importer_stats={"filtered": read.filtered},
        )

    def close(self) -> None:
        self._bank.close()

    # ---- one dialog per data call ----

    def _run(self, body: Callable[[Dialog, _Plan], T]) -> T:
        """Run `body` in a fresh dialog. The request it sends (named through `plan`, which decides whether
        a TAN request goes with it) answered 9075 plain is repeated once with a TAN request attached,
        and the type is learned; a medium name refused (9210) is asked once."""
        sca_retry = False
        while True:
            plan = _Plan(self._tan_for(), sca_retry)
            try:
                result = self._attempt(body, plan)
            except _Refused as refused:
                if (
                    has(refused.codes, MEDIUM_REFUSED)
                    and not self._asked_medium_name
                    and self._medium_wanted()
                ):
                    self._state["tan_medium"] = self._ask_medium_name()
                    self._bank.use_medium(str(self._state["tan_medium"]))
                    continue
                plain = plan.request is not None and not plan.attached
                if has(refused.codes, STRONG_AUTH_REQUIRED) and plain:
                    sca_retry = True
                    continue
                raise error_for(refused.codes, refused.detail) from None
            if sca_retry and plan.request is not None:
                self._state["tan_for"] = sorted({*self._tan_for(), plan.request})
            return result

    def _attempt(self, body: Callable[[Dialog, _Plan], T], plan: _Plan) -> T:
        try:
            with self._bank.dialog(self._tan) as dialog:
                self._check(dialog.codes)  # a refused login: nothing is sent
                result = body(dialog, plan)
                self._check(dialog.codes)  # never an empty result without the codes
                self._log(dialog.codes)
                return result
        except DialogFailed as failed:
            self._log(failed.codes)
            raise _Refused(failed.codes, failed.detail) from None
        finally:
            self._learn_system_id()

    def _check(self, codes: Sequence[ReturnCode]) -> None:
        if errors_in(codes):
            self._log(codes)
            raise _Refused(codes, "the bank refused the request")

    @staticmethod
    def _log(codes: Sequence[ReturnCode]) -> None:
        for code in codes:  # return codes and texts only: never a segment, an account or an answer
            log.info("bank answered %s %s", code.code, code.text)

    def _medium_wanted(self) -> bool:
        return bool(self._bank.medium_required())

    def _tan_for(self) -> set[str]:
        learned = self._state.get("tan_for")
        return {str(x) for x in learned} if isinstance(learned, list) else set()

    def _learn_system_id(self) -> None:
        system_id = self._bank.system_id
        if system_id and self._state.get("system_id") != system_id:
            self._state["system_id"] = system_id

    # ---- TAN challenges ----

    def _tan(self, challenge: Challenge, poll: Callable[[], bool] | None) -> str | None:
        prompt = TanPrompt(
            challenge.kind, challenge.text, challenge.method, challenge.image, challenge.image_mime
        )
        try:
            answer = self._prompter.ask(prompt, poll=poll if challenge.kind == "decoupled" else None)
        except DialogFailed as failed:  # the bank's answer to a poll
            raise error_for(failed.codes, failed.detail) from None
        if isinstance(answer, SecretText):
            return answer.reveal()
        return None if answer is None else str(answer)

    def _call(self, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except DialogFailed as failed:
            self._log(failed.codes)
            raise error_for(failed.codes, failed.detail) from None
