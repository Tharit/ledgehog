"""The `BankSession` over the patched client, against a minimal scripted bank: the plain values it
hands the importer (the account list, the challenges, the codes) and how a library failure is told."""

from __future__ import annotations

from datetime import date

import pytest
from fints.client import FinTSOperations
from fints.exceptions import FinTSConnectionError
from fints.formals import SegmentHeader
from fints.segments.base import FinTS3Segment

from app.core.plugins.errors import AccountUnsupported, BankSetupRequired, SourceUnavailable
from app.core.plugins.fetch import SecretText
from app.plugins.importers.fints.bank import BankLogin, Challenge, DialogFailed, UpdAccount
from app.plugins.importers.fints.library import LibrarySession
from tests.plugins.importers.fints.wire import (
    CARD,
    END_OK,
    Item,
    ScriptedConnection,
    card_entry,
    card_page,
    codes,
    page,
    prime,
    tan_challenge,
    tan_media,
    upd_row,
    upd_rows,
)

OK = ("0020", "Auftrag ausgefuehrt")
LOGIN: list[Item] = [codes(None, ("0010", "ok")), codes("HKIDN", OK), *upd_rows(upd_row())]


class Handler:
    """A TAN handler that records what it was shown and answers a fixed TAN."""

    def __init__(self, typed: str = "654321") -> None:
        self.seen: list[Challenge] = []
        self.typed = typed
        self.polls = 0

    def __call__(self, challenge: Challenge, poll):  # type: ignore[no-untyped-def]
        self.seen.append(challenge)
        if poll is not None:
            while not poll():
                self.polls += 1
            self.polls += 1
            return None
        return self.typed


def session_with(*answers, mechanism: str | None = "900") -> LibrarySession:  # type: ignore[no-untyped-def]
    login = BankLogin(
        url="https://bank.invalid/fints",
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
    prime(session.client, *answers, mechanism=mechanism)
    session.finish_setup()
    return session


def sent(session: LibrarySession) -> ScriptedConnection:
    connection = session.client.connection
    assert isinstance(connection, ScriptedConnection)
    return connection


def test_the_login_returns_the_account_list_as_plain_values() -> None:
    session = session_with(LOGIN, END_OK)
    with session.dialog(Handler()) as dialog:
        assert list(dialog.accounts) == [
            UpdAccount(
                iban="DE02120300000000202051",
                account_number="0000202051",
                subaccount="01",
                bank_code="12030000",
                account_type=1,
                product_name="Girokonto",
                currency="EUR",
                statements=True,
            )
        ]
        assert [c.code for c in dialog.codes] == ["0010", "0020"]


def test_a_row_without_the_statement_request_says_so() -> None:
    rows = upd_rows(upd_row(transactions=("HKSAL",)), upd_row(iban=None, number="9", kind=3))
    session = session_with([codes(None, ("0010", "ok")), codes("HKIDN", OK), *rows], END_OK)
    with session.dialog(Handler()) as dialog:
        assert [a.statements for a in dialog.accounts] == [False, True]


def test_the_card_request_is_read_from_the_raw_upd_list_not_the_librarys_operation_table() -> None:
    card_row = upd_row(iban=None, number=CARD, kind=50, name="Credit Card", transactions=("HKKKU", "HKSPA"))
    session = session_with(
        [codes(None, ("0010", "ok")), codes("HKIDN", OK), *upd_rows(card_row, upd_row())], END_OK
    )
    with session.dialog(Handler()) as dialog:
        card, girokonto = dialog.accounts
    assert (card.cards, card.statements, card.account_type, card.iban) == (True, False, 50, None)
    assert (girokonto.cards, girokonto.statements) == (False, True)
    # the library's own table has nothing for it, which is why the raw list is read
    info = session.client.get_information()["accounts"][0]
    operations = info["supported_operations"]
    assert not operations[FinTSOperations.GET_CREDIT_CARD_TRANSACTIONS]  # it knows DKKKU, not HKKKU


def test_the_card_comes_back_as_plain_values_with_its_account_connection_in_the_request() -> None:
    card_row = upd_row(iban=None, number=CARD, kind=50, transactions=("HKKKU",))
    session = session_with(
        [codes(None, ("0010", "ok")), codes("HKIDN", OK), *upd_rows(card_row)],
        [codes(None, ("0010", "ok")), codes("HKKKU", OK), card_page(card_entry(booking_date="20261012"))],
        END_OK,
    )
    with session.dialog(Handler()) as dialog:
        answer = dialog.card(dialog.accounts[0], date(2026, 9, 20), date(2026, 10, 20), with_tan=False)
        assert [c.code for c in dialog.codes][-1] == "0020"
    assert answer.balance is not None and answer.balance.on == "20261016"
    assert [dict(e) for e in answer.entries] == [{"booking_date": "20261012"}]
    request = sent(session).requests[1].first("HKKKU")
    assert (request.card_number, request.subaccount) == (CARD, "01")
    connection = request.account
    assert (connection.account_number, connection.bank_identifier.country_identifier) == (CARD, "280")


def test_a_9075_on_the_card_request_is_a_failed_dialog_that_carries_its_codes() -> None:
    card_row = upd_row(iban=None, number=CARD, kind=50, transactions=("HKKKU",))
    session = session_with(
        [codes(None, ("0010", "ok")), codes("HKIDN", OK), *upd_rows(card_row)],
        [codes(None, ("0010", "ok")), codes("HKKKU", ("9075", "SCA erforderlich"))],
    )
    with pytest.raises(DialogFailed) as err, session.dialog(Handler()) as dialog:
        dialog.card(dialog.accounts[0], date(2026, 9, 20), date(2026, 10, 20), with_tan=False)
    assert [c.code for c in err.value.codes][-1] == "9075"
    assert len(sent(session).requests) == 2


def test_the_media_list_comes_back_as_names_from_a_login_without_a_tan_request() -> None:
    session = session_with(
        [codes(None, ("0010", "ok")), codes("HKIDN", OK), tan_media("iPhone", "iPad")], END_OK
    )
    session.client.bpd.segments.append(FinTS3Segment(header=SegmentHeader("HITABS", 8, 4)))
    assert session.media() == ["iPhone", "iPad"]
    assert "HKTAN" not in sent(session).requests[0].types()


def test_a_bank_that_refuses_the_media_list_fails_with_its_codes() -> None:
    session = session_with(
        [codes(None, ("0010", "ok")), codes("HKIDN", ("9210", "Name des TAN-Mediums erforderlich"))]
    )
    session.client.bpd.segments.append(FinTS3Segment(header=SegmentHeader("HITABS", 8, 4)))
    with pytest.raises(DialogFailed) as err:
        session.media()
    assert "9210" in [c.code for c in err.value.codes]


def test_a_login_challenge_is_answered_through_the_handler_and_the_dialog_goes_on() -> None:
    session = session_with(
        [
            codes(None, ("0010", "ok")),
            codes("HKIDN", ("0030", "Sicherheitsfreigabe erforderlich")),
            tan_challenge("Bitte die TAN eingeben"),
            *upd_rows(upd_row()),
        ],
        [codes(None, ("0010", "ok")), codes("HKTAN", OK), tan_challenge("", process="2")],
        END_OK,
    )
    handler = Handler("654321")
    with session.dialog(handler) as dialog:
        assert len(dialog.accounts) == 1
    assert [(c.kind, c.text) for c in handler.seen] == [("text", "Bitte die TAN eingeben")]
    answer = sent(session).requests[1]
    assert answer.first("HKTAN").tan_process == "2"
    assert "654321" in answer.message.render_bytes().decode("latin-1")


def test_a_decoupled_challenge_is_polled_until_the_bank_says_confirmed() -> None:
    session = session_with(
        [
            codes(None, ("0010", "ok")),
            codes("HKIDN", ("3955", "Freigabe in der App")),
            tan_challenge("In der App bestaetigen"),
            *upd_rows(upd_row()),
        ],
        [
            codes(None, ("0010", "ok")),
            codes("HKTAN", ("3956", "noch nicht freigegeben")),
            tan_challenge("", process="S"),
        ],
        [codes(None, ("0010", "ok")), codes("HKTAN", OK), tan_challenge("", process="S")],
        END_OK,
    )
    handler = Handler()
    with session.dialog(handler):
        pass
    assert [c.kind for c in handler.seen] == ["decoupled"] and handler.polls == 2


def test_a_photo_challenge_arrives_with_its_image() -> None:
    mime, png = b"image/png", b"\x89PNG" + b"x" * 300
    hhduc = len(mime).to_bytes(2, "big") + mime + len(png).to_bytes(2, "big") + png
    session = session_with(
        [
            codes(None, ("0010", "ok")),
            codes("HKIDN", ("0030", "TAN")),
            tan_challenge("Scan", hhduc=hhduc),
            *upd_rows(upd_row()),
        ],
        [codes(None, ("0010", "ok")), codes("HKTAN", OK), tan_challenge("", process="2")],
        END_OK,
    )
    handler = Handler()
    with session.dialog(handler):
        pass
    (seen,) = handler.seen
    assert (seen.kind, seen.image_mime, seen.image) == ("image", "image/png", png)


def test_a_flicker_code_without_text_ends_in_bank_setup_required() -> None:
    session = session_with(
        [
            codes(None, ("0010", "ok")),
            codes("HKIDN", ("0030", "TAN")),
            tan_challenge("", hhduc=b"0123456789"),
            *upd_rows(upd_row()),
        ],
        END_OK,
    )
    with pytest.raises(BankSetupRequired) as err, session.dialog(Handler()):
        pass
    assert "flicker" in str(err.value)


def test_the_statements_come_back_as_text_and_the_codes_are_kept() -> None:
    session = session_with(
        LOGIN,
        [codes(None, ("0010", "ok")), codes("HKKAZ", OK, ("3010", "keine Eintraege")), page("T")],
        END_OK,
    )
    with session.dialog(Handler()) as dialog:
        account = dialog.accounts[0]
        assert dialog.statements(account, date(2026, 7, 1), date(2026, 7, 31), with_tan=False) == "T"
        assert "3010" in [c.code for c in dialog.codes]
    request = sent(session).requests[1].first("HKKAZ")
    assert str(request.date_start) == "2026-07-01" and request.account.account_number == "0000202051"


def test_a_9075_is_a_failed_dialog_that_carries_its_codes_and_ends_quietly() -> None:
    session = session_with(
        LOGIN, [codes(None, ("0010", "ok")), codes("HKKAZ", ("9075", "SCA erforderlich"))], mechanism="900"
    )
    with pytest.raises(DialogFailed) as err, session.dialog(Handler()) as dialog:
        dialog.statements(dialog.accounts[0], date(2026, 7, 1), date(2026, 7, 2), with_tan=False)
    assert [c.code for c in err.value.codes][-1] == "9075"
    assert len(sent(session).requests) == 2  # no end-of-dialog message to a dialog the bank closed


def test_a_bank_without_the_statement_request_is_account_unsupported() -> None:
    session = session_with(LOGIN, END_OK)
    session.client.bpd.segments = [s for s in session.client.bpd.segments if s.header.type != "HIKAZS"]
    with pytest.raises(AccountUnsupported), session.dialog(Handler()) as dialog:
        dialog.statements(dialog.accounts[0], date(2026, 7, 1), date(2026, 7, 2), with_tan=False)


def test_a_failed_login_leaves_the_session_usable_for_the_next_dialog() -> None:
    session = session_with(
        [codes(None, ("0010", "ok")), codes("HKIDN", ("9931", "Anmeldename oder PIN falsch"))], LOGIN, END_OK
    )
    with pytest.raises(DialogFailed) as err, session.dialog(Handler()):
        pass
    assert "9931" in [c.code for c in err.value.codes]
    assert session.client._standing_dialog is None


def test_the_system_id_is_read_once_the_bank_has_assigned_one() -> None:
    session = session_with(END_OK)
    assert session.system_id == "SYS"
    session.client.system_id = "0"
    assert session.system_id is None


def test_a_connection_error_is_source_unavailable_without_the_library_text() -> None:
    class Broken:
        url = "https://bank.invalid/fints"

        def send(self, msg: object) -> None:
            raise FinTSConnectionError("Could not connect to FinTS endpoint: secret-ish detail")

    session = session_with(END_OK)
    session.client.connection = Broken()  # type: ignore[assignment]
    with pytest.raises(SourceUnavailable) as err, session.dialog(Handler()):
        pass
    assert "secret-ish" not in str(err.value)
