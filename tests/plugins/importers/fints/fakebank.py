"""A fake `BankSession` for the importer's logic (fints.md §2): the bank's answers are a script of
dialogs, and everything the importer asked of it is recorded."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.plugins.fetch import (
    ChoicePrompt,
    Prompt,
    SecretPrompt,
    SecretText,
    TanPrompt,
    TextPrompt,
)
from app.plugins.importers.fints.bank import (
    Challenge,
    DialogFailed,
    Procedure,
    ReturnCode,
    TanHandler,
    UpdAccount,
)

OK = ReturnCode("0020", "Auftrag ausgefuehrt")


def rc(code: str, text: str = "Bankmeldung") -> ReturnCode:
    return ReturnCode(code, text)


def upd(
    *,
    iban: str | None = "DE02120300000000202051",
    number: str | None = "0000202051",
    sub: str | None = None,
    kind: int | None = 1,
    name: str | None = "Girokonto",
    currency: str | None = "EUR",
    statements: bool = True,
) -> UpdAccount:
    return UpdAccount(iban, number, sub, "12030000", kind, name, currency, statements)


@dataclass
class Dialog:
    """What the bank does in one dialog."""

    accounts: Sequence[UpdAccount] = field(default_factory=lambda: [upd()])
    login_codes: Sequence[ReturnCode] = (OK,)
    challenge: Challenge | None = None  # a TAN at login
    text: str = ""  # the statements' answer
    request_codes: Sequence[ReturnCode] = ()  # codes of the data request, no exception
    fail: Sequence[ReturnCode] | None = None  # the library fails in the data request, with these codes
    fail_login: Sequence[ReturnCode] | None = None  # the library fails at login, with these codes
    system_id: str | None = None  # assigned by this dialog


class _Open:
    def __init__(self, bank: FakeBank, script: Dialog, tan: TanHandler) -> None:
        self._bank, self._script, self._tan = bank, script, tan
        self._codes: list[ReturnCode] = []

    def __enter__(self) -> _Open:
        script = self._script
        self._codes.extend(script.login_codes)
        if script.system_id:
            self._bank.system_id = script.system_id
        if script.fail_login is not None:
            raise DialogFailed([*self._codes, *script.fail_login], "FinTSClientPINError")
        if script.challenge is not None:
            self._bank.challenges.append(script.challenge)
            answer = self._tan(script.challenge, self._bank.poll_for(script.challenge))
            self._bank.answers.append(answer)
        return self

    def __exit__(self, *exc: object) -> None:
        self._bank.ended += 1

    @property
    def accounts(self) -> Sequence[UpdAccount]:
        return self._script.accounts

    @property
    def codes(self) -> Sequence[ReturnCode]:
        return tuple(self._codes)

    def statements(self, account: UpdAccount, since: date, until: date, *, with_tan: bool) -> str:
        self._bank.requests.append((account, since, until, with_tan))
        if self._script.fail is not None:
            self._codes.extend(self._script.fail)
            raise DialogFailed(self._codes, "FinTSSCARequiredError")
        self._codes.extend(self._script.request_codes)
        return self._script.text


class FakeBank:
    """Satisfies `BankSession`."""

    def __init__(
        self,
        *dialogs: Dialog,
        procedures: Sequence[Procedure] = (),
        media: Sequence[str] | None = None,
        media_codes: Sequence[ReturnCode] | None = None,  # the listing fails with these
        medium_required: bool = False,
        procedures_codes: Sequence[ReturnCode] | None = None,
    ) -> None:
        self._dialogs = list(dialogs)
        self._procedures = tuple(procedures)
        self._media = media
        self._media_codes = media_codes
        self._medium_required = medium_required
        self._procedures_codes = procedures_codes
        self.system_id: str | None = None
        self.requests: list[tuple[UpdAccount, date, date, bool]] = []
        self.challenges: list[Challenge] = []
        self.answers: list[str | None] = []
        self.opened = 0
        self.ended = 0
        self.used_procedure: str | None = None
        self.used_media: list[str] = []
        self.setup_finished = False
        self.closed = False
        self.listed_media = 0
        self.polls_left = 0

    def poll_for(self, challenge: Challenge) -> Callable[[], bool] | None:
        if challenge.kind != "decoupled":
            return None

        def poll() -> bool:
            if self.polls_left > 0:
                self.polls_left -= 1
                return False
            return True

        return poll

    def procedures(self) -> Sequence[Procedure]:
        if self._procedures_codes is not None:
            raise DialogFailed(self._procedures_codes, "FinTSClientPINError")
        return self._procedures

    def use_procedure(self, code: str) -> None:
        self.used_procedure = code

    def procedure_name(self) -> str | None:
        return next((p.name for p in self._procedures if p.code == self.used_procedure), None)

    def medium_required(self) -> bool:
        return self._medium_required

    def media(self) -> Sequence[str] | None:
        self.listed_media += 1
        if self._media_codes is not None:
            raise DialogFailed(self._media_codes, "FinTSDialogInitError")
        return self._media

    def use_medium(self, name: str) -> None:
        self.used_media.append(name)

    def finish_setup(self) -> None:
        self.setup_finished = True

    def dialog(self, tan: TanHandler) -> _Open:
        self.opened += 1
        script = self._dialogs.pop(0) if len(self._dialogs) > 1 else self._dialogs[0]
        return _Open(self, script, tan)

    def close(self) -> None:
        self.closed = True


class Asker:
    """A prompter answering from a list; records every prompt and each decoupled poll."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.asked: list[Prompt] = []

    def ask(
        self, prompt: Prompt, *, poll: Callable[[], bool] | None = None, timeout_s: float | None = None
    ) -> Any:
        self.asked.append(prompt)
        if isinstance(prompt, TanPrompt) and prompt.medium == "decoupled":
            assert poll is not None
            while not poll():
                pass
            return None
        answer = self.answers.pop(0)
        return SecretText(answer) if isinstance(prompt, SecretPrompt | TanPrompt) else answer

    def kinds(self) -> list[str]:
        out = []
        for p in self.asked:
            if isinstance(p, SecretPrompt | ChoicePrompt | TextPrompt):
                out.append(p.subject)
            elif isinstance(p, TanPrompt):
                out.append(f"tan:{p.medium}")
        return out
