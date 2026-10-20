"""The card transaction request (HKKKU) and its answer (HIKKU), on the wire (fints.md §6a).

python-fints has no card support, so the request is a segment of ours and the answer is read from the
library's generic segment (`_additional_data`). The layout is the one the spike found live at Deutsche
Bank (spikes/fints/FINDINGS.md 20, 21): HIKKU element 3 is the current balance (`D/C : amount :
currency : date [: time]`), 6 onwards one group of 29 components per booking, the last one empty. Decimal
comma, dates `YYYYMMDD`. Nothing here logs or raises with the card number: an unreadable answer is
`ParseFailed` naming the segment type only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from fints.fields import DataElementField, DataElementGroupField
from fints.formals import KTI1
from fints.segments.base import FinTS3Segment

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.fints.bank import CardAnswer, CardBalance

CARD_REQUEST = "HKKKU"

# HIKKU entry components by position (the entry's fields as the bank names them in the DK's layout).
ENTRY_FIELDS: Mapping[int, str] = {
    1: "receipt_date",
    2: "booking_date",
    3: "statement_date",
    4: "value_date",
    5: "original_amount",
    6: "original_currency",
    7: "original_direction",
    8: "exchange_rate",
    9: "amount",
    10: "currency",
    11: "direction",
    20: "country",
    21: "merchant_name",
    22: "terminal",
    23: "billed",
    24: "booking_reference",
    25: "fee_code",
    26: "statement_marker",
    27: "cash_fee",
    28: "foreign_use_fee",
}
DESCRIPTION_LINES = range(12, 20)  # components 12 to 19, the description lines
# component 0 is the card number: it is the card's reference already, so an entry does not carry it


class HKKKU1(FinTS3Segment):  # type: ignore[misc]
    """Kreditkartenumsaetze anfordern, version 1. The element order follows the open-source Rust crate
    floatingpixels/fints (verified live there and in the spike): the account connection, card number,
    sub-account, from, to, [max entries (left empty), touchdown point]. The account connection is
    required by the bank although its parameters may read otherwise (9210 without it)."""

    account = DataElementGroupField(type=KTI1, required=False, _d="Kontoverbindung international")
    card_number = DataElementField(type="an", max_length=30, _d="Kreditkartennummer")
    subaccount = DataElementField(type="an", required=False, _d="Unterkontomerkmal")
    date_start = DataElementField(type="dat", required=False, _d="Von Datum")
    date_end = DataElementField(type="dat", required=False, _d="Bis Datum")
    max_number_responses = DataElementField(
        type="num", max_length=4, required=False, _d="Maximale Anzahl Eintraege"
    )
    touchdown_point = DataElementField(type="an", max_length=35, required=False, _d="Aufsetzpunkt")


def read_answer(pages: Iterable[Any]) -> CardAnswer:
    """The HIKKU segments of one request (one per page) as plain values. The balance is the first
    page's; the entries are all pages', in order."""
    balance: CardBalance | None = None
    entries: list[Mapping[str, str]] = []
    for segment in pages:
        data = getattr(segment, "_additional_data", None)
        if not isinstance(data, list):
            raise ParseFailed("the card answer could not be read")
        if balance is None and len(data) > 2:
            balance = _balance(data[2])
        for element in data[5:]:
            entry = _entry(element)
            if entry:
                entries.append(entry)
    return CardAnswer(balance, tuple(entries))


def _balance(element: Any) -> CardBalance | None:
    if not isinstance(element, list) or len(element) < 4:
        return None
    mark, amount, currency, on = (_text(c) for c in element[:4])
    if not (mark and amount and currency and on):
        return None
    return CardBalance(mark, amount, currency, on)


def _entry(element: Any) -> dict[str, str]:
    if not isinstance(element, list):
        return {}
    entry: dict[str, str] = {}
    for i, name in ENTRY_FIELDS.items():
        if i < len(element) and (text := _text(element[i])):
            entry[name] = text
    for number, i in enumerate(DESCRIPTION_LINES, start=1):
        if i < len(element) and (text := _text(element[i])):
            entry[f"description_{number}"] = text
    return entry


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
