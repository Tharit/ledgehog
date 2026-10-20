"""One test per python-fints fix the plugin carries (fints.md §10). Each asserts behaviour, on the wire
or in a decision, not that the code exists: **a fix is deleted when its test passes without it**, so
when upstream carries one, remove the fix and see whether its test still passes."""

from __future__ import annotations

import datetime
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import requests
from fints.client import HKKAZ7
from fints.exceptions import FinTSConnectionError, FinTSSCARequiredError
from fints.formals import SegmentHeader, SystemIDStatus
from fints.models import SEPAAccount
from fints.segments.auth import HKIDN2
from fints.segments.base import FinTS3Segment
from fints.types import SegmentSequence

from app.core.plugins.errors import SourceUnavailable
from app.core.plugins.fetch import SecretText
from app.plugins.importers.fints import patches
from app.plugins.importers.fints.bank import BankLogin
from app.plugins.importers.fints.library import LibrarySession
from app.plugins.importers.fints.patches import LedgerClient, LedgerConnection
from tests.plugins.importers.fints.wire import (
    END_OK,
    LOGIN_OK,
    ScriptedConnection,
    banked_client,
    codes,
    page,
    tan_challenge,
    tan_media,
)

ACCOUNT = SEPAAccount(
    iban="DE02120300000000202051", bic=None, accountnumber="0000202051", subaccount="01", blz="12030000"
)
FIRST, LAST = datetime.date(2026, 7, 1), datetime.date(2026, 7, 31)
OK = ("0020", "Auftrag ausgefuehrt")


def raw_login_message(mechanism: str) -> str:
    client = banked_client(mechanism=mechanism)
    dialog = client._new_dialog()
    message = dialog.new_customer_message()
    message += HKIDN2(client.bank_identifier, "user", "0", SystemIDStatus.ID_NECESSARY)
    dialog.finish_message(message)
    return message.render_bytes().decode("latin-1")


# ---- P1: the signature carries the profile of the envelope --------------------------------------


def test_p1_a_two_step_message_is_signed_with_the_same_pin_profile_as_its_envelope() -> None:
    raw = raw_login_message("900")
    assert "HNVSK:998:3+PIN:2+" in raw
    assert "HNSHK:2:4+PIN:2+900+" in raw


def test_p1_a_one_step_message_stays_on_profile_one_in_both() -> None:
    raw = raw_login_message("999")
    assert "HNVSK:998:3+PIN:1+" in raw
    assert "HNSHK:2:4+PIN:1+999+" in raw


# ---- P2: a login TAN challenge is found wherever the bank attached its code ------------------------


def login_client(*items):  # type: ignore[no-untyped-def]
    return banked_client([codes(None, ("0010", "ok")), *items, END_OK[0]])


def test_p2_a_challenge_attached_to_the_identification_segment_is_detected() -> None:
    client = login_client(
        codes("HKIDN", ("0030", "Sicherheitsfreigabe erforderlich")), tan_challenge("Bitte freigeben")
    )
    client._new_dialog().init()
    pending = client.init_tan_response
    assert pending is not None and pending.challenge == "Bitte freigeben" and not pending.decoupled


def test_p2_a_decoupled_login_challenge_is_marked_decoupled() -> None:
    client = login_client(
        codes("HKIDN", ("3955", "Freigabe in der App")), tan_challenge("In der App bestaetigen")
    )
    client._new_dialog().init()
    assert client.init_tan_response is not None and client.init_tan_response.decoupled


def test_p2_a_login_without_a_challenge_reports_none() -> None:
    client = login_client(codes("HKIDN", ("3076", "Keine starke Authentifizierung erforderlich")))
    client._new_dialog().init()
    assert client.init_tan_response is None


# ---- P3: after setup a 9075 raises, it never returns an empty result --------------------------------


def test_p3_a_9075_after_setup_raises_instead_of_returning_nothing() -> None:
    client = banked_client(
        LOGIN_OK,
        [codes(None, ("0010", "ok")), codes("HKKAZ", ("9075", "Starke Authentifizierung erforderlich"))],
    )
    client.finish_setup()
    with pytest.raises(FinTSSCARequiredError), client:
        client.booked_statements(ACCOUNT, FIRST, LAST)


# ---- P4: the account connection of the statement request is complete -------------------------------


def test_p4_the_request_names_iban_number_subaccount_and_bank() -> None:
    client = banked_client()
    segment = HKKAZ7(
        account=client.account_field(HKKAZ7, ACCOUNT), all_accounts=False, date_start=FIRST, date_end=LAST
    )
    segment.header.number = 3
    raw = SegmentSequence([segment]).render_bytes().decode("latin-1")
    assert "DE02120300000000202051::0000202051:01:280:12030000" in raw


# ---- P5: a TAN request is attached to the statement request when tan_for says so -------------------


def statements_dialog(client: LedgerClient, *, tan_for: set[str]) -> str:
    client.tan_for = tan_for
    with client:
        text = client.booked_statements(ACCOUNT, FIRST, LAST)
    assert isinstance(text, str)
    return text


def test_p5_a_statement_request_is_plain_unless_tan_for_names_it() -> None:
    client = banked_client(
        LOGIN_OK, [codes(None, ("0010", "ok")), codes("HKKAZ", OK), page("PLAIN")], END_OK, mechanism="900"
    )
    assert statements_dialog(client, tan_for=set()) == "PLAIN"
    assert isinstance(client.connection, ScriptedConnection)
    assert client.connection.requests[1].types() == ["HNSHK", "HKKAZ", "HNSHA"]


def test_p5_the_tan_request_is_attached_when_tan_for_names_the_statement_request() -> None:
    client = banked_client(
        LOGIN_OK,
        [
            codes(None, ("0010", "ok")),
            codes("HKTAN", ("3076", "Keine starke Authentifizierung erforderlich")),
            codes("HKKAZ", OK),
            page("WITH TAN"),
        ],
        END_OK,
    )
    assert statements_dialog(client, tan_for={"HKKAZ"}) == "WITH TAN"
    assert isinstance(client.connection, ScriptedConnection)
    assert client.connection.requests[1].types() == ["HNSHK", "HKKAZ", "HKTAN", "HNSHA"]
    assert client.connection.requests[1].first("HKTAN").tan_process == "4"


def test_p5_a_one_step_login_never_gets_a_tan_request() -> None:
    client = banked_client(
        LOGIN_OK, [codes(None, ("0010", "ok")), codes("HKKAZ", OK), page("X")], END_OK, mechanism="999"
    )
    statements_dialog(client, tan_for={"HKKAZ"})
    assert isinstance(client.connection, ScriptedConnection)
    assert "HKTAN" not in client.connection.requests[1].types()


# ---- P6: the raw booked text of every page comes back ----------------------------------------------


def test_p6_the_pages_of_a_touchdown_are_joined_and_only_booked_text_is_returned() -> None:
    client = banked_client(
        LOGIN_OK,
        [
            codes(None, ("0010", "ok")),
            codes("HKKAZ", OK, ("3040", "Es liegen weitere Informationen vor", "TD1")),
            page(":20:A\n"),
        ],
        [codes(None, ("0010", "ok")), codes("HKKAZ", OK), page(":20:B\n")],
        END_OK,
    )
    assert statements_dialog(client, tan_for=set()) == ":20:A\n:20:B\n"
    assert isinstance(client.connection, ScriptedConnection)
    first, second = client.connection.requests[1], client.connection.requests[2]
    assert first.first("HKKAZ").touchdown_point is None
    assert second.first("HKKAZ").touchdown_point == "TD1"


def test_p6_a_range_without_bookings_is_an_empty_text() -> None:
    client = banked_client(
        LOGIN_OK,
        [codes(None, ("0010", "ok")), codes("HKKAZ", ("3010", "Es liegen keine Eintraege vor"))],
        END_OK,
    )
    assert statements_dialog(client, tan_for=set()) == ""


# ---- P8: the device list is asked for in a login without a TAN request ----------------------------------


def media_client(*answers):  # type: ignore[no-untyped-def]
    client = banked_client(*answers)
    client.bpd.segments.append(FinTS3Segment(header=SegmentHeader("HITABS", 8, 4)))
    return client


def test_p8_the_media_list_rides_on_a_login_that_carries_no_tan_request() -> None:
    client = media_client(
        [
            codes(None, ("0010", "ok")),
            codes("HKIDN", ("3076", "Keine starke Authentifizierung erforderlich")),
            tan_media("iPhone", "iPad"),
        ],
        END_OK,
    )
    media = client.tan_media_without_tan_request()
    assert [m.tan_medium_name for m in media] == ["iPhone", "iPad"]
    assert isinstance(client.connection, ScriptedConnection)
    login = client.connection.requests[0]
    assert login.types() == ["HNSHK", "HKIDN", "HKVVB", "HKTAB", "HNSHA"]  # no HKTAN
    assert client.allowed_security_functions == ["900"]  # the procedures are known again afterwards


def test_p8_a_login_without_the_hiding_carries_the_tan_request() -> None:
    """The control: it is the library's own login that appends the TAN request P8 leaves out."""
    client = media_client([codes(None, ("0010", "ok")), codes("HKIDN", OK)], END_OK)
    client._new_dialog().init()
    assert isinstance(client.connection, ScriptedConnection)
    assert "HKTAN" in client.connection.requests[0].types()


def test_p8_a_bank_that_answers_with_no_list_gives_none() -> None:
    client = media_client(
        [codes(None, ("0010", "ok")), codes("HKIDN", OK), codes("HKTAB", ("3010", "keine Eintraege"))],
        END_OK,
    )
    assert client.tan_media_without_tan_request() == []


# ---- P7: a bank that never answers cannot hold the thread --------------------------------------------


@contextmanager
def silent_bank() -> Iterator[str]:
    """A loopback server that takes the connection and never answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.1)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.getsockname()[1]}/fints"
    finally:
        stop.set()
        thread.join(2)
        for conn in held:
            conn.close()
        server.close()


def test_p7_every_request_carries_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_request(self: requests.Session, method: str, url: str, **kwargs: object) -> requests.Response:
        seen.update(kwargs)
        return requests.Response()

    monkeypatch.setattr(requests.Session, "request", fake_request)
    LedgerConnection("https://bank.invalid/fints").session.post("https://bank.invalid/fints", data=b"x")
    assert seen["timeout"] == patches.HTTP_TIMEOUT_S


def test_p7_a_stuck_bank_ends_as_a_connection_error_and_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(patches, "HTTP_TIMEOUT_S", 0.3)
    with silent_bank() as url:
        client = banked_client(mechanism="999")
        client.connection = LedgerConnection(url)
        with pytest.raises(FinTSConnectionError), client:
            pass  # the login's first message is never answered

        login = BankLogin(
            url=url,
            bank_code="12345678",
            user_id="user",
            customer_id=None,
            pin=SecretText("123456"),
            product_id="test",
            product_version="0.1.0",
            system_id="SYS",
            tan_medium=None,
        )
        session = LibrarySession(login)
        with pytest.raises(SourceUnavailable) as err, session.dialog(lambda c, p: None):
            pass
        assert "could not be reached" in str(err.value)
