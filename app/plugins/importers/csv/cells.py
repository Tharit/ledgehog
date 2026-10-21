"""Cells a spreadsheet stores as a date or a number (csv.md §2, Spreadsheets).

A typed cell is a `str` (its plain rendering, which every text reader of the importer can use:
labels, filters, placeholders, `raw`) that also carries the value the sheet stored. The date and
amount parsers take that value directly; the profile's formats apply to text cells only.
`strip` returns the cell itself, so trimming a row's cells keeps their type.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Self


class DateCell(str):
    value: date

    def __new__(cls, value: date) -> Self:
        obj = super().__new__(cls, value.isoformat())
        obj.value = value
        return obj

    def strip(self, chars: str | None = None, /) -> Self:
        return self


class NumberCell(str):
    value: Decimal

    def __new__(cls, value: Decimal) -> Self:
        obj = super().__new__(cls, format(value, "f"))
        obj.value = value
        return obj

    def strip(self, chars: str | None = None, /) -> Self:
        return self
