"""MT940 statements to records, and the closing balance (fints.md §6; spec §5.1).

The raw statement text is split at each `:20:` and read by the mt-940 library, which gives the
balances and the `:61:` lines; the free text of a booking (field 86) is read by `field86.py`. The
library is told to leave field 86 as it came and to sign reversal marks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import mt940

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import IncomingRow
from app.plugins.importers.fints.field86 import parse_field86

_OPENING = ("final_opening_balance", "intermediate_opening_balance", "opening_balance")
_CLOSING = ("final_closing_balance", "intermediate_closing_balance", "closing_balance")
_LINE61 = (
    "date",
    "entry_date",
    "status",
    "funds_code",
    "amount",
    "id",
    "customer_reference",
    "bank_reference",
    "extra_details",
)


@dataclass(frozen=True, slots=True)
class Read:
    """What the statements of one fetch hold."""

    rows: tuple[IncomingRow, ...]
    filtered: int  # zero bookings dropped
    balance_minor: int | None
    balance_on: date | None


@dataclass(frozen=True, slots=True)
class _Closing:
    minor: int
    on: date  # the figure's date: the balance date, or the latest line the balance includes


def read_statements(text: str, *, until: date, minor_units_of: Callable[[str], int]) -> Read:
    """Rows and the balance of the MT940 `text`: the last final statement's figure, whatever its date,
    rolled back to `until` (the coverage) where it is later. Raises `ParseFailed` where the text cannot
    be read or a statement does not add up."""
    statements = _parse(text)
    rows: list[IncomingRow] = []
    filtered = 0
    final: list[tuple[date, int, _Closing]] = []
    for position, statement in enumerate(statements):
        opening, closing = _balance(statement, _OPENING), _balance(statement, _CLOSING)
        reference = str(statement.data.get("transaction_reference") or "?")
        if opening is None or closing is None:
            raise ParseFailed(f"statement {reference}: it has no opening or no closing balance")
        lines = list(statement.transactions)
        total = opening.amount.amount + sum((_amount(t, reference) for t in lines), Decimal(0))
        if total != closing.amount.amount:
            raise ParseFailed(
                f"statement {reference} ({_day(opening.date)} to {_day(closing.date)}): "
                "the opening balance and the lines do not add up to the closing balance; "
                "a CSV export of the period is the fallback"
            )
        currency = str(closing.amount.currency)
        exponent = minor_units_of(currency)
        booked: list[date] = []
        for tx in lines:
            amount = _minor(_amount(tx, reference), exponent, reference)
            booked.append(_booked_on(tx))
            if amount == 0:
                filtered += 1
                continue
            rows.append(_row(tx, reference, amount, str(tx.data.get("currency") or currency)))
        if "final_closing_balance" in statement.data:
            balance_date = _day(closing.date)
            later = [d for d in booked if d > balance_date]
            figure_on = max([balance_date, *later])
            figure = _minor(closing.amount.amount, exponent, reference)
            final.append((balance_date, position, _Closing(figure, figure_on)))
    if not final:
        return Read(tuple(rows), filtered, None, None)
    chosen = max(final, key=lambda f: (f[0], f[1]))[2]
    amount, on = roll_back(chosen.minor, chosen.on, rows, until)
    return Read(tuple(rows), filtered, amount, on)


def roll_back(figure: int, figure_on: date, rows: Sequence[IncomingRow], coverage: date) -> tuple[int, date]:
    """The one dating rule (spec §5.1), for statements and cards alike: the figure is dated at the earliest
    of its own date and `coverage` (which is never after the last closed day); a figure moved back loses
    the rows booked in (record date, figure date]. Returns the amount and the date of the record."""
    on = min(figure_on, coverage)
    if on < figure_on:
        figure -= sum(r.amount_minor for r in rows if on < r.booked_on <= figure_on)
    return figure, on


def _parse(text: str) -> list[Any]:
    # The library's debug log carries every matched line, i.e. the bookings: keep it at warning (fints.md §8).
    logging.getLogger("mt940").setLevel(logging.WARNING)
    try:
        return list(
            mt940.parse_statements(
                text,
                processors={"post_transaction_details": []},  # keep field 86 as it came
                options=mt940.Options.all(),
            )
        )
    except (ValueError, KeyError, AttributeError, TypeError, RuntimeError, InvalidOperation) as exc:
        raise ParseFailed(f"the MT940 text could not be read ({type(exc).__name__})") from None


def _balance(statement: Any, keys: Sequence[str]) -> Any:
    for key in keys:
        found = statement.data.get(key)
        if found is not None and getattr(found.amount, "amount", None) is not None:
            return found
    return None


def _amount(tx: Any, reference: str) -> Decimal:
    amount = tx.data.get("amount")
    if amount is None or not isinstance(amount.amount, Decimal):
        raise ParseFailed(f"statement {reference}: a booking line has no readable amount")
    return amount.amount


def _minor(value: Decimal, exponent: int, reference: str) -> int:
    scaled = value.scaleb(exponent)
    if scaled != scaled.to_integral_value():
        raise ParseFailed(f"statement {reference}: an amount is not a whole number of minor units")
    return int(scaled)


def _day(value: Any) -> date:
    return date(value.year, value.month, value.day)


def _booked_on(tx: Any) -> date:
    entry = tx.data.get("entry_date")
    return _day(entry if entry is not None else tx.data["date"])


def _row(tx: Any, reference: str, amount_minor: int, currency: str) -> IncomingRow:
    data = tx.data
    raw86 = data.get("transaction_details")
    free = parse_field86(raw86) if raw86 else None
    return IncomingRow(
        amount_minor=amount_minor,
        currency=currency,
        booked_on=_booked_on(tx),
        value_on=_day(data["date"]),
        source_format="mt940",
        raw={
            "statement": reference,
            "field86": raw86,
            "line61": {k: str(data[k]) for k in _LINE61 if data.get(k) is not None},
        },
        counterparty_ref=free.counterparty_iban if free else None,
        counterparty_bic=free.counterparty_bic if free else None,
        counterparty_name=free.counterparty_name if free else None,
        purpose=free.purpose if free else None,
        end_to_end_id=free.end_to_end_id if free else None,
        mandate_ref=free.mandate_ref if free else None,
        booking_text=free.booking_text if free else None,
        source_id=None,  # the statement reference and the library's ids are not stable (spec §5.2)
    )
