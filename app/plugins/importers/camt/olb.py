"""The OLB XML reader (camt.md §3.1).

The export is a Java object serialisation (XStream) of a camt report, with the library's field names
for elements, not ISO 20022. The reader transcribes into the statement model and decides nothing: no
sign convention, no balance dating, no coverage. Error messages name elements, never their content.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.camt.model import Balance, Detail, Entry, Report, Statement

ROOT: Final = "AccountMovementCamt"
NAME: Final = "olb"

_BANK_DAY = ZoneInfo("Europe/Berlin")
_INSTANT = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))? UTC")
_DESCRIPTOR = re.compile(r"camt\.(052|053)\.")


def _text(el: ET.Element | None, path: str) -> str | None:
    found = el.find(path) if el is not None else None
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _required(el: ET.Element | None, path: str, what: str) -> str:
    value = _text(el, path)
    if value is None:
        raise ParseFailed(f"{what}: element {path} is missing")
    return value


def bank_day(text: str, what: str) -> date:
    """An instant in UTC as the bank's calendar day: it must be a midnight in Europe/Berlin."""
    m = _INSTANT.fullmatch(text.strip())
    if m is None:
        raise ParseFailed(f"{what}: not an instant in UTC")
    try:
        utc = datetime.fromisoformat(f"{m[1]}T{m[2]}").replace(tzinfo=UTC)
    except ValueError:
        raise ParseFailed(f"{what}: not an instant in UTC") from None
    local = utc.astimezone(_BANK_DAY)
    if (local.hour, local.minute, local.second) != (0, 0, 0) or int(m[3] or 0) != 0:
        raise ParseFailed(f"{what}: not a midnight in the bank's time zone (Europe/Berlin)")
    return local.date()


def _amount(el: ET.Element, what: str) -> tuple[Decimal, str]:
    value = _required(el, "amount/value", what)
    currency = _required(el, "amount/currencyCode", what)
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ParseFailed(f"{what}: the amount does not parse") from None
    if not amount.is_finite():
        raise ParseFailed(f"{what}: the amount does not parse")
    return amount, currency


def _credit(el: ET.Element, what: str) -> bool:
    mark = _required(el, "credDebtIndex", what)
    if mark not in ("CREDIT", "DEBIT"):
        raise ParseFailed(f"{what}: credDebtIndex is neither CREDIT nor DEBIT")
    return mark == "CREDIT"


def _balance(el: ET.Element, what: str) -> Balance:
    amount, currency = _amount(el, what)
    return Balance(amount, currency, _credit(el, what), bank_day(_required(el, "date", what), f"{what} date"))


def _detail(el: ET.Element) -> Detail:
    lines = tuple(
        s.text.strip() for s in el.findall("remittanceInformation/string") if s.text and s.text.strip()
    )
    codes = tuple(c for c in (_text(el, "bankTransactionCode"), _text(el, "gbiBankTransactionCode")) if c)
    return Detail(
        name=_text(el, "foreignName"),
        account=_text(el, "foreignAccount"),
        agent=_text(el, "foreignAgent"),
        end_to_end_id=_text(el, "endToEndId"),
        mandate_id=_text(el, "mandateId"),
        remittance=lines,
        codes=codes,
    )


def _entry(el: ET.Element, what: str) -> Entry:
    status = _text(el, "statusCode")
    if status != "BOOK":
        raise ParseFailed(f"{what}: a booked report holds an entry whose status is not BOOK")
    amount, currency = _amount(el, what)
    value_text = _text(el, "validityDate")
    details = tuple(_detail(d) for d in el.findall("entryDetails/*/transactionDetails/*"))
    return Entry(
        amount=amount,
        currency=currency,
        credit=_credit(el, what),
        booked_on=bank_day(_required(el, "bookingDate", what), f"{what} booking date"),
        value_on=None if value_text is None else bank_day(value_text, f"{what} value date"),
        details=details,
        xml=ET.tostring(el, encoding="unicode").strip(),
    )


def _report(el: ET.Element, index: int) -> Report:
    where = f"report {index}"
    message_id = _required(el, "groupHeader/messageId", where)
    where = f"report {message_id}"
    body = el.find("report")
    if body is None:
        raise ParseFailed(f"{where}: element report is missing")
    opening = closing = None
    for b in body.findall("balances/*"):
        code = _text(b, "code")
        if code == "OPBD":
            opening = _balance(b, f"{where} opening balance")
        elif code == "CLBD":
            closing = _balance(b, f"{where} closing balance")
    entries = tuple(_entry(e, f"{where} entry {n}") for n, e in enumerate(body.findall("entries/*"), start=1))
    return Report(message_id, opening, closing, entries)


def read(root: ET.Element) -> Statement:
    """The statement of an OLB document whose root element is `AccountMovementCamt`."""
    descriptor = _required(root, "camtDescriptor", "the file")
    m = _DESCRIPTOR.search(descriptor)
    if m is None:
        raise ParseFailed("the file's camtDescriptor names neither camt.052 nor camt.053")
    created = [
        bank_day(t, "the creation date") for e in root.iter("groupHeader") if (t := _text(e, "creationDate"))
    ]
    booked = root.find("bookedCamtTransationsList")
    reports = () if booked is None else tuple(_report(r, i) for i, r in enumerate(booked, start=1))
    pending = len(root.findall("nonbookedCamtTransations/report/entries/*"))
    return Statement(
        reader=NAME,
        message_type=f"camt.{m[1]}",
        export_date=max(created, default=None),
        reports=reports,
        pending=pending,
    )
