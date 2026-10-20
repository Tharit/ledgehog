"""The card request on the wire (fints.md §6a): the HKKKU bytes, the HIKKU answer read as plain values, the
touchdown loop, the TAN request attached by `tan_for`, a challenge resumed. Invented data throughout;
the layout is the one the live spike found (spikes/fints/FINDINGS.md 20, 21)."""

from __future__ import annotations

import datetime

import pytest
from fints.formals import DescriptionRequired
from fints.models import SEPAAccount
from fints.types import SegmentSequence

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.fints.bank import CardAnswer, CardBalance
from app.plugins.importers.fints.hkku import HKKKU1, read_answer
from app.plugins.importers.fints.patches import LedgerClient
from tests.plugins.importers.fints.wire import (
    CARD,
    END_OK,
    LOGIN_OK,
    ScriptedConnection,
    banked_client,
    card_entry,
    card_page,
    codes,
    tan_challenge,
)

ACCOUNT = SEPAAccount(iban=None, bic=None, accountnumber=CARD, subaccount="01", blz="12030000")
FIRST, LAST = datetime.date(2026, 9, 20), datetime.date(2026, 10, 20)
OK = ("0020", "Auftrag ausgefuehrt")
SHOP = card_entry(
    booking_date="20261012",
    value_date="20261014",
    amount="12,50",
    currency="EUR",
    direction="D",
    description_1="Zeile 1",
    description_2="Zeile 2",
    merchant_name="SHOP",
    billed="J",
)
REFUND = card_entry(
    booking_date="20261014",
    original_amount="10,00",
    original_currency="USD",
    original_direction="D",
    exchange_rate="0,92",
    amount="9,20",
    currency="EUR",
    direction="C",
    description_1="Erstattung",
    merchant_name="Store",
    billed="J",
)


def render(segment: HKKKU1) -> str:
    segment.header.number = 3
    return SegmentSequence([segment]).render_bytes().decode("latin-1")


def card_dialog(client: LedgerClient, *, tan_for: set[str] | None = None) -> CardAnswer:
    client.tan_for = tan_for or set()
    with client:
        answer = client.card_transactions(ACCOUNT, FIRST, LAST)
    assert isinstance(answer, CardAnswer)
    return answer


def requests_of(client: LedgerClient):  # type: ignore[no-untyped-def]
    assert isinstance(client.connection, ScriptedConnection)
    return client.connection.requests


# ---- the request ---------------------------------------------------------------------------------------


def test_the_request_bytes_carry_the_full_account_connection_the_card_number_and_the_range() -> None:
    client = banked_client()
    segment = HKKKU1(
        account=client.account_field(HKKKU1, ACCOUNT),
        card_number=CARD,
        subaccount="01",
        date_start=FIRST,
        date_end=LAST,
    )
    # account connection (no IBAN, no BIC; card number, sub-account, country, bank code), card number,
    # sub-account, from, to
    assert render(segment) == f"HKKKU:3:1+::{CARD}:01:280:12030000+{CARD}+01+20260920+20261020'"


def test_a_touchdown_point_closes_the_request_after_an_empty_maximum() -> None:
    client = banked_client()
    segment = HKKKU1(
        account=client.account_field(HKKKU1, ACCOUNT),
        card_number=CARD,
        subaccount="01",
        date_start=FIRST,
        date_end=LAST,
        touchdown_point="TD1",
    )
    assert render(segment).endswith("+20261020++TD1'")


def test_the_sub_account_is_sent_empty_where_the_card_has_none() -> None:
    client = banked_client()
    bare = SEPAAccount(iban=None, bic=None, accountnumber=CARD, subaccount=None, blz="12030000")
    segment = HKKKU1(
        account=client.account_field(HKKKU1, bare),
        card_number=CARD,
        subaccount="",
        date_start=FIRST,
        date_end=LAST,
    )
    assert render(segment).startswith(f"HKKKU:3:1+::{CARD}::280:12030000+{CARD}++20260920")


# ---- the answer ---------------------------------------------------------------------------------------


def test_the_answer_is_the_balance_and_one_mapping_per_booking_without_the_card_number() -> None:
    client = banked_client(
        LOGIN_OK,
        [codes(None, ("0010", "ok")), codes("HKKKU", OK), card_page(SHOP, REFUND)],
        END_OK,
    )
    answer = card_dialog(client)
    assert answer.balance == CardBalance("D", "1234,56", "EUR", "20261016")
    assert answer.entries == (
        {
            "booking_date": "20261012",
            "value_date": "20261014",
            "amount": "12,50",
            "currency": "EUR",
            "direction": "D",
            "description_1": "Zeile 1",
            "description_2": "Zeile 2",
            "merchant_name": "SHOP",
            "billed": "J",
        },
        {
            "booking_date": "20261014",
            "original_amount": "10,00",
            "original_currency": "USD",
            "original_direction": "D",
            "exchange_rate": "0,92",
            "amount": "9,20",
            "currency": "EUR",
            "direction": "C",
            "description_1": "Erstattung",
            "merchant_name": "Store",
            "billed": "J",
        },
    )
    assert all(CARD not in value for entry in answer.entries for value in entry.values())


def test_an_answer_without_entries_or_balance_is_empty() -> None:
    page = card_page(balance=None)[1]
    assert read_answer([page]) == CardAnswer(None, ())


def test_a_segment_that_is_not_a_parsed_answer_is_parse_failed_without_data() -> None:
    with pytest.raises(ParseFailed) as err:
        read_answer([object()])
    assert CARD not in str(err.value)


def test_the_pages_of_a_touchdown_are_joined_and_the_first_balance_is_kept() -> None:
    client = banked_client(
        LOGIN_OK,
        [
            codes(None, ("0010", "ok")),
            codes("HKKKU", OK, ("3040", "Es liegen weitere Informationen vor", "TD1")),
            card_page(SHOP),
        ],
        [
            codes(None, ("0010", "ok")),
            codes("HKKKU", OK),
            card_page(REFUND, balance="D:99,00:EUR:20261017"),
        ],
        END_OK,
    )
    answer = card_dialog(client)
    assert [e["merchant_name"] for e in answer.entries] == ["SHOP", "Store"]
    assert answer.balance == CardBalance("D", "1234,56", "EUR", "20261016")
    first, second = requests_of(client)[1], requests_of(client)[2]
    assert first.first("HKKKU").touchdown_point is None
    assert second.first("HKKKU").touchdown_point == "TD1"


def test_a_range_without_bookings_is_an_empty_answer() -> None:
    client = banked_client(
        LOGIN_OK,
        [codes(None, ("0010", "ok")), codes("HKKKU", ("3010", "Es liegen keine Eintraege vor"))],
        END_OK,
    )
    assert card_dialog(client) == CardAnswer(None, ())


# ---- the TAN request ---------------------------------------------------------------------------------


def test_the_request_is_plain_unless_tan_for_names_it() -> None:
    client = banked_client(
        LOGIN_OK, [codes(None, ("0010", "ok")), codes("HKKKU", OK), card_page(SHOP)], END_OK
    )
    card_dialog(client)
    assert requests_of(client)[1].types() == ["HNSHK", "HKKKU", "HNSHA"]


def test_the_tan_request_is_attached_when_tan_for_names_the_card_request() -> None:
    client = banked_client(
        LOGIN_OK,
        [
            codes(None, ("0010", "ok")),
            codes("HKTAN", ("3076", "Keine starke Authentifizierung erforderlich")),
            codes("HKKKU", OK),
            card_page(SHOP),
        ],
        END_OK,
    )
    card_dialog(client, tan_for={"HKKKU"})
    sent = requests_of(client)[1]
    assert sent.types() == ["HNSHK", "HKKKU", "HKTAN", "HNSHA"]
    assert sent.first("HKTAN").tan_process == "4" and sent.first("HKTAN").segment_type == "HKKKU"


def test_the_chosen_device_name_goes_with_the_tan_request() -> None:
    client = banked_client(
        LOGIN_OK,
        [
            codes(None, ("0010", "ok")),
            codes("HKTAN", ("3076", "Keine starke Authentifizierung erforderlich")),
            codes("HKKKU", OK),
            card_page(SHOP),
        ],
        END_OK,
    )
    mechanism = client.get_tan_mechanisms()["900"]
    mechanism.supported_media_number = 2
    mechanism.description_required = DescriptionRequired.MUST
    client.selected_tan_medium = "My Phone"
    card_dialog(client, tan_for={"HKKKU"})
    assert requests_of(client)[1].first("HKTAN").tan_medium_name == "My Phone"


def test_a_challenge_on_the_card_request_resumes_into_the_answer() -> None:
    def resumed(request):  # type: ignore[no-untyped-def]
        _, segment = card_page(SHOP)
        segment.header.reference = requests_of(client)[1].number_of("HKKKU")
        return [codes(None, ("0010", "ok")), codes("HKTAN", OK), (None, segment)]

    client = banked_client(
        LOGIN_OK,
        [codes(None, ("0010", "ok")), codes("HKTAN", ("0030", "Bitte freigeben")), tan_challenge("Bitte")],
        resumed,
        END_OK,
    )
    client.tan_for = {"HKKKU"}
    with client:
        pending = client.card_transactions(ACCOUNT, FIRST, LAST)
        assert not isinstance(pending, CardAnswer) and pending.challenge == "Bitte"
        answer = client.send_tan(pending, "123456")
    assert isinstance(answer, CardAnswer) and [e["merchant_name"] for e in answer.entries] == ["SHOP"]
