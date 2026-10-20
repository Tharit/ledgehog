"""The card answer to records, the coverage and the closing balance (fints.md §6a; spec §5.1).

An entry the bank marks as not yet billed is the card's pending item: it can change or disappear and has
no reference, so it is not imported. It still counts twice: coverage stops before the earliest of its
booking dates (an item billed later keeps its booking date, and the next fetch must reach it), and the
bank's current balance includes it, so it is taken off to get the booked balance. That figure is then
dated and rolled back by the same rule as a statement's. Nothing here names a value in a message: no
card number, no amount.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import IncomingRow
from app.plugins.importers.fints.bank import CardAnswer
from app.plugins.importers.fints.hkku import DESCRIPTION_LINES
from app.plugins.importers.fints.statements import roll_back

_DEBIT = "D"
_CREDIT = "C"


@dataclass(frozen=True, slots=True)
class CardRead:
    """What a card answer holds, as one fetch delivers it."""

    rows: tuple[IncomingRow, ...]
    filtered: int  # zero bookings dropped
    covered_through: date
    balance_minor: int | None
    balance_on: date | None


@dataclass(frozen=True, slots=True)
class _Unbilled:
    booked_on: date
    amount_minor: int
    currency: str


def read_card(answer: CardAnswer, *, until: date, minor_units_of: Callable[[str], int]) -> CardRead:
    """Rows, coverage and balance of `answer`. `until` is the last closed day, the day before today."""
    rows: list[IncomingRow] = []
    unbilled: list[_Unbilled] = []
    filtered = 0
    for entry in answer.entries:
        booked_on = _day(_need(entry, "booking_date"))
        currency = _need(entry, "currency")
        exponent = _exponent(currency, minor_units_of)
        amount = _minor(_need(entry, "amount"), _need(entry, "direction"), exponent)
        if entry.get("billed", "").upper() == "N":
            unbilled.append(_Unbilled(booked_on, amount, currency))
            continue
        if amount == 0:
            filtered += 1
            continue
        rows.append(_row(entry, booked_on, amount, currency, minor_units_of))
    covered = until
    if unbilled:
        covered = min(until, min(u.booked_on for u in unbilled) - timedelta(days=1))
    balance, balance_on = _balance(answer, rows, unbilled, covered, minor_units_of)
    return CardRead(tuple(rows), filtered, covered, balance, balance_on)


def _balance(
    answer: CardAnswer,
    rows: list[IncomingRow],
    unbilled: list[_Unbilled],
    covered: date,
    minor_units_of: Callable[[str], int],
) -> tuple[int | None, date | None]:
    current = answer.balance
    if current is None:
        return None, None
    if any(u.currency != current.currency for u in unbilled):
        raise ParseFailed("the card answer mixes currencies in its balance and its pending entries")
    # the current balance includes the unbilled entries: without them it is the booked balance
    booked = _minor(current.amount, current.mark, _exponent(current.currency, minor_units_of))
    booked -= sum(u.amount_minor for u in unbilled)
    return roll_back(booked, _day(current.on), rows, covered)


def _row(
    entry: Mapping[str, str],
    booked_on: date,
    amount: int,
    currency: str,
    minor_units_of: Callable[[str], int],
) -> IncomingRow:
    instructed: int | None = None
    instructed_currency: str | None = None
    original = entry.get("original_currency")
    if original and original != currency and entry.get("original_amount"):
        instructed_currency = original
        instructed = _minor(
            entry["original_amount"],
            entry.get("original_direction") or entry["direction"],
            _exponent(original, minor_units_of),
        )
    lines = (entry.get(f"description_{n}") for n in range(1, len(DESCRIPTION_LINES) + 1))
    purpose = re.sub(r"\s+", " ", " ".join(line for line in lines if line)).strip()
    return IncomingRow(
        amount_minor=amount,
        currency=currency,
        booked_on=booked_on,
        value_on=_day(entry["value_date"]) if entry.get("value_date") else None,
        instructed_amount_minor=instructed,
        instructed_currency=instructed_currency,
        counterparty_name=entry.get("merchant_name") or None,
        purpose=purpose or None,
        source_format="hkkku",
        raw=dict(entry),
        source_id=None,  # an entry has no stable id (fints.md §6a)
    )


def _need(entry: Mapping[str, str], key: str) -> str:
    value = entry.get(key)
    if not value:
        raise ParseFailed(f"a card entry has no {key.replace('_', ' ')}")
    return value


def _exponent(currency: str, minor_units_of: Callable[[str], int]) -> int:
    try:
        return minor_units_of(currency)
    except KeyError:
        raise ParseFailed("the card answer names a currency that is not known") from None


def _minor(text: str, mark: str, exponent: int) -> int:
    """`12,50` and `D` is -1250 at exponent 2: the decimal comma, the debit mark negative (ledger sign)."""
    if mark not in (_DEBIT, _CREDIT):
        raise ParseFailed("a card amount has neither a credit nor a debit mark")
    try:
        value = Decimal(text.replace(",", "."))
    except InvalidOperation:
        raise ParseFailed("a card amount cannot be read") from None
    scaled = value.scaleb(exponent) if value.is_finite() else None
    if scaled is None or scaled < 0 or scaled != scaled.to_integral_value():
        raise ParseFailed("a card amount is not a whole number of minor units")
    return -int(scaled) if mark == _DEBIT else int(scaled)


def _day(text: str) -> date:
    """`YYYYMMDD`."""
    if not re.fullmatch(r"\d{8}", text):
        raise ParseFailed("a card date cannot be read")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        raise ParseFailed("a card date cannot be read") from None
