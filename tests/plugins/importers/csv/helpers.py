"""Shared builders for the CSV importer tests. All data here is synthetic."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.plugins.importer import ParsedFile
from app.plugins.importers.csv import CsvImporter

TODAY = date(2026, 8, 20)


def base_profile(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "label": "t",
        "delimiter": ";",
        "header_marker": ["Datum", "Betrag"],
        "booked_on": "Datum",
        "date_format": "dd.MM.yyyy",
        "amount": {"column": "Betrag"},
        "purpose": ["Zweck"],
    }
    p.update(over)
    return p


def run(
    text: str | bytes,
    *,
    profile: dict[str, Any] | None = None,
    today: date = TODAY,
    currency: str = "EUR",
    minor_units: int = 2,
    samples: int = 5,
    **over: Any,
) -> ParsedFile:
    data = text if isinstance(text, bytes) else text.encode()
    prof = profile if profile is not None else base_profile(**over)
    return CsvImporter().parse(
        data, prof, account_currency=currency, minor_units=minor_units, today=today, dry_run_samples=samples
    )


HEADER = "Datum;Betrag;Zweck\n"


CARD = (
    "Titel\n"
    "Abrechnungsdatum: 3.8.2026\n"
    "\n"
    "Belegdatum;Eingangstag;Zweck;Betrag\n"
    "1.8.2026;2.8.2026;Shop;-12,00\n"
    "2.8.2026;3.8.2026;Shop;-30,01\n"
    "Saldo:;;;-42,01;EUR\n"
)


def card_profile(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "label": "card",
        "delimiter": ";",
        "header_marker": ["Belegdatum", "Eingangstag"],
        "booked_on": "Eingangstag",
        "value_on": "Belegdatum",
        "date_format": "d.M.yyyy",
        "amount": {"column": "Betrag"},
        "purpose": ["Zweck"],
        "balance": {
            "mode": "labelled",
            "label": "Saldo:",
            "right": 3,
            "date": {
                "format": "d.M.yyyy",
                "label": "Abrechnungsdatum",
                "pattern": r"(\d{1,2}\.\d{1,2}\.\d{4})",
            },
        },
        "coverage_end": {
            "format": "d.M.yyyy",
            "label": "Abrechnungsdatum",
            "pattern": r"(\d{1,2}\.\d{1,2}\.\d{4})",
        },
    }
    p.update(over)
    return p
