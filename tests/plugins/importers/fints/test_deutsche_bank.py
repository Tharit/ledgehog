"""The whole importer over the library on a scripted wire, for a bank like the Deutsche Bank of the spike
(FINDINGS 17 to 21): it lists no TAN procedure until a device is activated, it wants the device name in every
TAN request and refuses its device list in a login that carries one, and its cards come by HKKKU. Invented
data; the layout is what the spike's log showed."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import pytest
from fints.formals import DescriptionRequired, SegmentHeader
from fints.segments.base import FinTS3Segment

from app.core.plugins.errors import BankSetupRequired
from app.plugins.importers.fints import FintsImporter
from app.plugins.importers.fints.bank import BankLogin
from app.plugins.importers.fints.library import LibrarySession
from tests.plugins.importers.fints.fakebank import Asker
from tests.plugins.importers.fints.wire import (
    CARD,
    END_OK,
    Item,
    ScriptedConnection,
    card_entry,
    card_page,
    codes,
    prime,
    tan_media,
    upd_row,
    upd_rows,
)

SETTINGS = {"url": "https://bank.invalid/fints", "bank_code": "12030000", "user_id": "alice"}
TODAY = date(2026, 11, 1)
OK = ("0020", "Auftrag ausgefuehrt")
CARD_ROW = upd_row(iban=None, number=CARD, kind=50, name="Credit Card", transactions=("HKKKU", "HKTAB"))
Answer = Sequence[Item] | Callable[[Any], Sequence[Item]]


def importer_over(*answers: Answer) -> tuple[FintsImporter, list[LibrarySession]]:
    """The importer on the real `LibrarySession`, whose connection is the script."""
    sessions: list[LibrarySession] = []

    def connect(login: BankLogin) -> LibrarySession:
        session = LibrarySession(login)
        prime(session.client, *answers, mechanism=None)
        session.client.bpd.segments.append(FinTS3Segment(header=SegmentHeader("HITABS", 8, 4)))
        mechanism = session.client.get_tan_mechanisms()["900"]  # the bank wants a device named
        mechanism.supported_media_number = 2
        mechanism.description_required = DescriptionRequired.MUST
        session.client.allowed_security_functions = []  # until the bank says so (3920)
        sessions.append(session)
        return session

    return FintsImporter("PID", "0.1.0", connect=connect), sessions


def login(*procedures: str) -> list[Item]:
    """What a login answers; the allowed procedures (3920) only where the bank has any."""
    items: list[Item] = [codes(None, ("0010", "ok")), codes("HKIDN", OK)]
    if procedures:
        items.append(codes(None, ("3920", "Zugelassene Verfahren", *procedures)))
    return items


def test_a_bank_that_sends_no_list_of_procedures_ends_the_open_in_bank_setup_required() -> None:
    importer, sessions = importer_over(login(), END_OK)
    with pytest.raises(BankSetupRequired) as err:
        importer.open(SETTINGS, {"system_id": "SYS"}, Asker("123456"), today=TODAY)
    assert "activate" in str(err.value)
    connection = sessions[0].client.connection
    assert isinstance(connection, ScriptedConnection)
    assert len(connection.requests) == 2  # the one dialog that asked, and its end: nothing guessed after


def test_the_device_list_is_asked_without_a_tan_request_and_its_name_goes_with_every_one_after() -> None:
    entry = card_entry(booking_date="20261012", amount="12,50", currency="EUR", direction="D", billed="J")

    importer, sessions = importer_over(
        login("900"),  # the procedures
        END_OK,
        [*login(), tan_media("iPhone", "iPad")],  # the device list, in a login of its own
        END_OK,
        [  # the data dialog's login carries a TAN request, and with it the name
            codes(None, ("0010", "ok")),
            codes("HKTAN", ("3076", "Keine starke Authentifizierung erforderlich")),
            *upd_rows(CARD_ROW),
        ],
        [codes(None, ("0010", "ok")), codes("HKKKU", OK), card_page(entry)],
        END_OK,
    )
    asker = Asker("123456", "iPad")
    state: dict[str, Any] = {"system_id": "SYS"}  # known, so no synchronisation dialog comes first
    session = importer.open(SETTINGS, state, asker, today=TODAY)
    assert asker.kinds() == ["pin", "tan_medium"] and state["tan_medium"] == "iPad"

    result = session.fetch_account(
        f"{CARD}/01",
        since=date(2026, 10, 1),
        today=TODAY,
        currency="EUR",
        minor_units_of=lambda c: 2,
        progress=lambda d, t: None,
    )
    assert [r.amount_minor for r in result.rows] == [-1250]

    connection = sessions[0].client.connection
    assert isinstance(connection, ScriptedConnection)
    assert connection.requests[2].types() == ["HNSHK", "HKIDN", "HKVVB", "HKTAB", "HNSHA"]  # no HKTAN
    data_login = connection.requests[4]
    assert "HKTAN" in data_login.types() and data_login.first("HKTAN").tan_medium_name == "iPad"
