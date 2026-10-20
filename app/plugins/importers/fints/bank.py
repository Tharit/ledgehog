"""The one narrow seam between the FinTS importer's logic and the bank (fints.md §2).

Everything the importer knows about a bank dialog goes through `BankSession` and `Dialog`: the
patched python-fints client (`library.py`) implements them, and the importer's own logic (the code
table, prompts, `tan_for` learning, discovery, statements to records) is tested against a fake.
Plain values and protocols only: no python-fints type crosses this line.

A session owns no open dialog between calls. `dialog()` opens one (log in, and answer a login TAN),
the importer sends at most one request through it, and leaving the `with` ends it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from app.core.plugins.fetch import SecretText


@dataclass(frozen=True, slots=True)
class ReturnCode:
    """One answer of the bank: its code and its text (the only thing of an exchange that is logged)."""

    code: str
    text: str


@dataclass(frozen=True, slots=True)
class Procedure:
    """A TAN procedure the bank allows for this login. `999` is the one-step procedure."""

    code: str
    name: str


@dataclass(frozen=True, slots=True)
class UpdAccount:
    """One row of the bank's account list (the UPD): what discovery and a fetch read."""

    iban: str | None
    account_number: str | None
    subaccount: str | None
    bank_code: str | None
    account_type: int | None
    product_name: str | None
    currency: str | None
    statements: bool  # the UPD allows the MT940 statement request (HKKAZ)
    cards: bool = False  # the UPD's own list allows the card transaction request (HKKKU)


@dataclass(frozen=True, slots=True)
class CardBalance:
    """The card's current balance as the bank wrote it (fints.md §6a): the credit or debit mark
    (`C`/`D`), the amount with a decimal comma, the currency and the date as `YYYYMMDD`."""

    mark: str
    amount: str
    currency: str
    on: str


@dataclass(frozen=True, slots=True)
class CardAnswer:
    """The card request's answer, plain: the current balance and one mapping of the entry's fields
    as received (named, empty ones left out) per booking. Never carries the card number."""

    balance: CardBalance | None
    entries: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class Challenge:
    """A TAN challenge to present: typed text, an image (photoTAN), or a decoupled confirmation."""

    kind: Literal["text", "image", "decoupled"]
    text: str
    method: str | None
    image: bytes | None = None
    image_mime: str | None = None


# Answers a challenge: the typed TAN, or None for a decoupled one. For a decoupled challenge the
# second argument is the bank's "confirmed yet?", which the handler hands to the prompter.
TanHandler = Callable[[Challenge, Callable[[], bool] | None], str | None]


class DialogFailed(Exception):
    """The library failed in a dialog. Carries the return codes recorded so far, which decide what
    the failure is (codes.py); `detail` is the library exception's class, never its message."""

    def __init__(self, codes: Sequence[ReturnCode], detail: str) -> None:
        super().__init__(detail)
        self.codes = tuple(codes)
        self.detail = detail


class Dialog(Protocol):
    """An open dialog, logged in. Leave it with the `with` that opened it."""

    @property
    def accounts(self) -> Sequence[UpdAccount]:
        """The account list the login returned."""
        ...

    @property
    def codes(self) -> Sequence[ReturnCode]:
        """Every return code the bank gave in this dialog so far."""
        ...

    def statements(self, account: UpdAccount, since: date, until: date, *, with_tan: bool) -> str:
        """The booked MT940 text of `since` to `until` (all pages, joined); empty where there is none.
        `with_tan` attaches a TAN request to the request. A challenge goes to the TAN handler."""
        ...

    def card(self, account: UpdAccount, since: date, until: date, *, with_tan: bool) -> CardAnswer:
        """The card's transactions of `since` to `until` (all pages) with its current balance
        (fints.md §6a). `with_tan` as for `statements`."""
        ...


class DialogContext(Protocol):
    def __enter__(self) -> Dialog: ...

    def __exit__(self, *exc: object) -> None: ...


class BankSession(Protocol):
    """The credential at one bank, in memory. Every method blocks. A method that talks to the bank
    raises `DialogFailed` where the library fails, or a taxonomy error for a connection that fails."""

    @property
    def system_id(self) -> str | None:
        """The id the bank assigned this installation, once it has."""
        ...

    def procedures(self) -> Sequence[Procedure]:
        """One dialog: the TAN procedures the bank allows this login."""
        ...

    def use_procedure(self, code: str) -> None: ...

    def procedure_name(self) -> str | None: ...

    def medium_required(self) -> bool:
        """The chosen procedure needs a TAN medium (device) named."""
        ...

    def media(self) -> Sequence[str] | None:
        """One dialog, without a TAN request in its login (a bank refuses the list in one that carries
        one): the bank's list of media. None where the bank gives none."""
        ...

    def use_medium(self, name: str) -> None: ...

    def finish_setup(self) -> None:
        """Setup is done: from now on the bank's refusals raise instead of being absorbed."""
        ...

    def dialog(self, tan: TanHandler) -> DialogContext:
        """A fresh dialog. Entering it logs in; a login TAN goes to `tan`."""
        ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BankLogin:
    """What the library needs to talk to one bank. `pin` is revealed only to build the client."""

    url: str
    bank_code: str
    user_id: str
    customer_id: str | None
    pin: SecretText
    product_id: str
    product_version: str
    system_id: str | None
    tan_medium: str | None


BankConnect = Callable[[BankLogin], BankSession]
