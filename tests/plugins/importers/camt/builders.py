"""Hand-built OLB XML with invented data, mirroring the export's structure (camt.md §7)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.plugins.importer import ParsedFile
from app.plugins.importers.camt import CamtImporter

TODAY = date(2026, 8, 20)
EXPONENTS = {"EUR": 2, "USD": 2, "JPY": 0}
PFX = "de.datadesign.fb.jfbl.transport.AccountMovementCamt_-BankToCustomerAccountReport"
BACK = '<outer-class reference="../../.."/>'


def exponent_of(currency: str) -> int:
    return EXPONENTS[currency]


def utc(day: str, hour: int = 0) -> str:
    """The instant the export writes for a day's midnight (or an hour of it) in Europe/Berlin."""
    local = datetime.fromisoformat(day).replace(hour=hour, tzinfo=ZoneInfo("Europe/Berlin"))
    return local.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.0 UTC")


def balance(code: str, amount: str, cred: str, day: str, currency: str = "EUR") -> str:
    return (
        f"<{PFX}_-Report_-Balance><code>{code}</code><amount><value>{amount}</value>"
        f"<currencyCode>{currency}</currencyCode></amount><credDebtIndex>{cred}</credDebtIndex>"
        f"<date>{utc(day)}</date>{BACK}</{PFX}_-Report_-Balance>"
    )


def detail(
    *,
    name: str | None = "ACME GMBH",
    account: str | None = "DE89370400440532013000",
    agent: str | None = "COBADEFFXXX",
    e2e: str | None = "NOTPROVIDED",
    mandate: str | None = None,
    lines: tuple[str, ...] = (),
) -> str:
    parts = ["<bankTransactionCode>PMNT-IDDT-ESDD</bankTransactionCode>"]
    for tag, value in (("endToEndId", e2e), ("foreignAccount", account), ("foreignAgent", agent)):
        if value is not None:
            parts.append(f"<{tag}>{value}</{tag}>")
    if name is not None:
        parts.append(f"<foreignName>{name}</foreignName>")
    parts.append("<gbiBankTransactionCode>NDDT+171+0000000+000</gbiBankTransactionCode>")
    if mandate:
        parts.append(f"<mandateId>{mandate}</mandateId>")
    if lines:
        parts.append(
            "<remittanceInformation>"
            + "".join(f"<string>{x}</string>" for x in lines)
            + "</remittanceInformation>"
        )
    else:
        parts.append("<remittanceInformation/>")
    tag = f"{PFX}_-Report_-Entry_-EntryDetails_-TransactionDetails"
    return f"<{tag}>{''.join(parts)}{BACK}</{tag}>"


def entry(
    amount: str,
    cred: str,
    booked: str,
    *,
    value: str | None = None,
    status: str | None = "BOOK",
    details: tuple[str, ...] | None = None,
    currency: str = "EUR",
) -> str:
    details = (detail(),) if details is None else details
    status_xml = "" if status is None else f"<statusCode>{status}</statusCode>"
    value_xml = "" if value is None else f"<validityDate>{utc(value)}</validityDate>"
    return (
        f"<{PFX}_-Report_-Entry><amount><value>{amount}</value><currencyCode>{currency}</currencyCode></amount>"
        f"<credDebtIndex>{cred}</credDebtIndex>{status_xml}<bookingDate>{utc(booked)}</bookingDate>{value_xml}"
        f"<entryDetails><{PFX}_-Report_-Entry_-EntryDetails><transactionDetails>{''.join(details)}</transactionDetails>"
        f"{BACK}</{PFX}_-Report_-Entry_-EntryDetails></entryDetails>{BACK}</{PFX}_-Report_-Entry>"
    )


def report(
    message_id: str,
    balances: tuple[str, ...],
    entries: tuple[str, ...] = (),
    *,
    created: str | None = "2026-08-20",
) -> str:
    header = f"<messageId>{message_id}</messageId>"
    if created:
        header += f"<creationDate>{utc(created)}</creationDate>"
    return (
        f"<{PFX}><groupHeader>{header}{BACK}</groupHeader><report><balances>{''.join(balances)}</balances>"
        f"<entries>{''.join(entries)}</entries>{BACK}</report>{BACK}</{PFX}>"
    )


def document(
    reports: tuple[str, ...],
    *,
    descriptor: str = "camt.052.001.08",
    pending: tuple[str, ...] = (),
    doctype: str = "",
) -> str:
    entries = "".join(pending)
    return (
        f"{doctype}<AccountMovementCamt><camtDescriptor>urn:iso:std:iso:20022:tech:xsd:{descriptor}</camtDescriptor>"
        f"<bookedCamtTransationsList>{''.join(reports)}</bookedCamtTransationsList>"
        f"<nonbookedCamtTransations><groupHeader>{BACK}</groupHeader><report><balances/><entries>{entries}</entries>"
        f"{BACK}</report>{BACK}</nonbookedCamtTransations></AccountMovementCamt>"
    )


def simple(entries: tuple[str, ...] = (), opening: str = "100.00", closing: str = "100.00", **kw: Any) -> str:
    """One report, a credit opening and closing balance dated 2026-08-10, the given entries."""
    return document(
        (
            report(
                "MSG1",
                (
                    balance("OPBD", opening, "CREDIT", "2026-08-10"),
                    balance("CLBD", closing, "CREDIT", "2026-08-10"),
                ),
                entries,
            ),
        ),
        **kw,
    )


def run(
    xml: str | bytes,
    *,
    today: date = TODAY,
    currency: str = "EUR",
    minor_units_of: Callable[[str], int] = exponent_of,
    samples: int = 5,
) -> ParsedFile:
    data = xml if isinstance(xml, bytes) else xml.encode()
    return CamtImporter().parse(
        data,
        {},
        account_currency=currency,
        minor_units_of=minor_units_of,
        today=today,
        name="t",
        dry_run_samples=samples,
    )
