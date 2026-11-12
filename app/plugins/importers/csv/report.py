"""The rows a CSV parse kept; the dry-run report builder they feed is `core/plugins/report.py`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.plugins.importer import IncomingRow
from app.plugins.importers.csv.reader import Record


@dataclass(slots=True)
class Kept:
    """A transaction row that passed the row filters (a zero booking included, `row` None)."""

    record: Record
    cells: list[str]
    booked_on: date
    amount: int
    row: IncomingRow | None
