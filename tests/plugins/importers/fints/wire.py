"""A minimal scripted bank for the patch tests (architecture §8, fints.md §10).

The patches live in the library's message flow, so the few that cannot be seen in the bytes of one
request (P2, P3, P5, P6) are tested against answers built from the library's own segment classes.
Nothing here is recorded data: the structure is what the spike's log showed, the values are invented.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fints.formals import (
    AccountInformation,
    AllowedTransaction,
    BankIdentifier,
    ParameterTwostepTAN6,
    Response,
    SegmentHeader,
    TANMedia4,
    TANMediaClass3,
    TANMediumStatus,
    TANUsageOption,
    TwoStepParameters6,
    UPDUsage,
)
from fints.message import FinTSInstituteMessage
from fints.parser import FinTS3Parser
from fints.segments.auth import HITAB4, HITAN6, HITANS6
from fints.segments.bank import HIUPA4, HIUPD6
from fints.segments.base import FinTS3Segment
from fints.segments.dialog import HIRMG2, HIRMS2
from fints.segments.message import HNHBK3, HNHBS1
from fints.segments.statement import HIKAZ7
from fints.types import SegmentSequence

from app.plugins.importers.fints.hkku import ENTRY_FIELDS
from app.plugins.importers.fints.patches import LedgerClient

DIALOG_ID = "DLG1"


@dataclass
class Request:
    """One message the client sent: its inner segments, as the bank would read them."""

    message: Any
    segments: list[Any]

    def types(self) -> list[str]:
        return [s.header.type for s in self.segments]

    def first(self, kind: str) -> Any:
        return next(s for s in self.segments if s.header.type == kind)

    def number_of(self, kind: str) -> int:
        return int(self.first(kind).header.number)

    @property
    def message_number(self) -> int:
        return int(self.message.segments[0].message_number)


Item = tuple[str | None, FinTS3Segment]  # the request segment type it answers (None: the message)


def codes(answers: str | None, *entries: tuple[str, ...]) -> Item:
    """Return codes about one request segment (or about the message when `answers` is None). An entry
    is `(code, text, *parameters)`."""
    responses = [
        Response(code=code, reference_element="", text=text, parameters=list(parameters))
        for code, text, *parameters in entries
    ]
    seg: FinTS3Segment = HIRMG2(responses=responses) if answers is None else HIRMS2(responses=responses)
    return answers, seg


def tan_challenge(challenge: str, *, process: str = "4", hhduc: bytes | None = None) -> Item:
    return "HKTAN", HITAN6(tan_process=process, challenge=challenge, challenge_hhduc=hhduc)


def upd_rows(*rows: FinTS3Segment) -> list[Item]:
    """The user parameter data a login brings: the header and one row per account."""
    header = HIUPA4(user_identifier="user", upd_version=1, upd_usage=UPDUsage.UPD_CONCLUSIVE)
    return [(None, header), *((None, row) for row in rows)]


def upd_row(
    *,
    iban: str | None = "DE02120300000000202051",
    number: str | None = "0000202051",
    sub: str = "01",
    kind: int = 1,
    name: str = "Girokonto",
    currency: str = "EUR",
    transactions: Sequence[str] = ("HKKAZ",),
) -> FinTS3Segment:
    return HIUPD6(
        account_information=AccountInformation(
            account_number=number, subaccount_number=sub, bank_identifier=BankIdentifier("280", "12030000")
        ),
        iban=iban,
        customer_id="user",
        account_type=kind,
        account_currency=currency,
        name_account_owner_1="OWNER",
        account_product_name=name,
        allowed_transactions=[AllowedTransaction(transaction=t, required_signatures=1) for t in transactions],
    )


def page(text: str, answers: str = "HKKAZ") -> Item:
    return answers, HIKAZ7(statement_booked=text.encode("iso-8859-1"))


CARD = "1111222233334444"  # an invented card number


def card_entry(**fields: str) -> str:
    """One HIKKU booking group of 29 components, by the names of `hkku.ENTRY_FIELDS` (plus
    `description_1` to `description_8`). The card number is always there, as the bank sends it."""
    positions = {name: i for i, name in ENTRY_FIELDS.items()}
    positions.update({f"description_{n}": 11 + n for n in range(1, 9)})
    components = [""] * 29
    components[0] = CARD
    for name, value in fields.items():
        components[positions[name]] = value
    return ":".join(components)


def card_page(
    *entries: str,
    balance: str | None = "D:1234,56:EUR:20261016:101500",
    answers: str = "HKKKU",
) -> Item:
    """A HIKKU answer: card number, account id, the current balance, the two statement dates, one group
    per entry and the empty last group. Parsed by the library's own parser, as a bank's answer is."""
    groups = [CARD, "ACC1", balance or "", "20260901", "20261001", *entries, ":".join([""] * 29)]
    raw = ("HIKKU:5:1:4+" + "+".join(groups) + "'").encode("iso-8859-1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        segment = FinTS3Parser().parse_message(raw).segments[0]
    return answers, segment


def tan_media(*names: str, answers: str = "HKTAB") -> Item:
    media = [
        TANMedia4(tan_medium_class=TANMediaClass3.MOBILE, status=TANMediumStatus.ACTIVE, tan_medium_name=n)
        for n in names
    ]
    return answers, HITAB4(tan_usage_option=TANUsageOption.ALL_ACTIVE, tan_media_list=media)


Answer = Callable[[Request], Sequence[Item]]


class ScriptedConnection:
    """Replaces the client's connection: answers each message from the next scripted answer."""

    def __init__(self, *answers: Answer | Sequence[Item]) -> None:
        self.answers = list(answers)
        self.requests: list[Request] = []
        self.url = "https://bank.invalid/fints"

    def send(self, msg: Any) -> FinTSInstituteMessage:
        inner = msg.segments[2].data.segments if msg.segments[2].header.type == "HNVSD" else msg.segments
        request = Request(msg, list(inner))
        self.requests.append(request)
        answer = self.answers.pop(0)
        items = answer(request) if callable(answer) else answer
        reply = FinTSInstituteMessage()
        reply += HNHBK3(0, 300, DIALOG_ID, request.message_number)
        for answers, seg in items:
            if answers is not None:
                seg.header.reference = request.number_of(answers)
            reply += seg
        reply += HNHBS1(request.message_number)
        return reply


LOGIN_OK = (
    codes(None, ("0010", "Nachricht entgegengenommen")),
    codes("HKIDN", ("0020", "Auftrag ausgefuehrt")),
)
END_OK = (codes(None, ("0010", "Nachricht entgegengenommen")),)


def banked_client(*answers: Answer | Sequence[Item], mechanism: str | None = "900") -> LedgerClient:
    """A patched client holding the bank parameters a real login would have brought, and a scripted
    connection. `system_id` is set, so no synchronisation dialog comes first."""
    client = LedgerClient(
        "12345678", "user", "123456", "https://bank.invalid/fints", product_id="test", system_id="SYS"
    )
    return prime(client, *answers, mechanism=mechanism)


def prime(
    client: LedgerClient, *answers: Answer | Sequence[Item], mechanism: str | None = "900"
) -> LedgerClient:
    hikazs = FinTS3Segment(header=SegmentHeader("HIKAZS", 5, 7))
    mech = TwoStepParameters6(
        security_function="900", tan_process="2", tech_id="x", name="photoTAN", challenge_structured=False
    )
    hitans = HITANS6(
        header=SegmentHeader("HITANS", 6, 6), parameter=ParameterTwostepTAN6(twostep_parameters=[mech])
    )
    # a one-step bank publishes no TAN procedures
    client.bpd = SegmentSequence([hikazs] if mechanism == "999" else [hikazs, hitans])
    client.allowed_security_functions = ["900"]
    if mechanism is not None:
        client.set_tan_mechanism(mechanism)
    client.connection = ScriptedConnection(*answers)  # type: ignore[assignment]
    return client
