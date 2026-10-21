"""Spreadsheets as another reader of the CSV importer (csv.md §2). Synthetic data only.

The `.xlsx` tests need python-calamine and skip without it. An `.xls` cannot be built here
without a writer library: it is covered by its magic bytes and, in the user's dry run, by a real
export.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.csv.amounts import parse_amount
from app.plugins.importers.csv.cells import DateCell, NumberCell
from app.plugins.importers.csv.dates import parse_date
from app.plugins.importers.csv.reader import _typed, is_spreadsheet
from tests.plugins.importers.csv.helpers import TODAY, run
from tests.plugins.importers.csv.sheets import Cell, xlsx_bytes

needs_calamine = pytest.mark.skipif(
    importlib.util.find_spec("python_calamine") is None, reason="python-calamine is not installed"
)

ROWS: list[list[Cell]] = [
    ["Account statement"],  # 1: preamble
    ["Balance", None, 1234.56],  # 2: a figure by label, typed number two cells right
    [],  # 3: blank
    ["Booking", "Value", "Amount", "Purpose"],  # 4: header
    [date(2026, 8, 17), "17.08.2026", -12.34, "Shop"],  # 5: typed date, text date, typed number
    ["18.08.2026", date(2026, 8, 18), "1.500,00", "Rent"],  # 6: text date, typed date, text number
    [],  # 7: blank
    ["Total", None, 1487.66],  # 8: footer: its booking cell is no date
]


def profile(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "header_marker": ["Booking", "Amount"],
        "booked_on": "Booking",
        "value_on": "Value",
        "date_format": "dd.MM.yyyy",
        "amount": {"column": "Amount"},
        "purpose": ["Purpose"],
        "balance": {"mode": "labelled", "label": "Balance", "right": 2},
    }
    p.update(over)
    return p


MINI: dict[str, Any] = {
    "header_marker": ["Booking", "Amount"],
    "booked_on": "Booking",
    "date_format": "dd.MM.yyyy",
    "amount": {"column": "Amount"},
}


def parse(data: bytes, **over: Any) -> Any:
    return run(data, profile=profile(**over))


# -- detection and the typed cells (no library needed) ---------------------------------------


def test_spreadsheets_are_recognised_by_their_first_bytes() -> None:
    assert is_spreadsheet(b"PK\x03\x04rest")  # xlsx, ods
    assert is_spreadsheet(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")  # xls
    assert not is_spreadsheet(b"Datum;Betrag\n")
    assert not is_spreadsheet("﻿Datum;Betrag".encode())
    assert not is_spreadsheet(b"")


@pytest.mark.parametrize("head", [b"PK\x03\x04", b"\xd0\xcf\x11\xe0"])
def test_a_damaged_spreadsheet_fails_the_run_with_a_clear_message(head: bytes) -> None:
    with pytest.raises(ParseFailed, match="cannot be read as a spreadsheet"):
        parse(head + b"this is not a workbook")


def test_a_typed_date_ignores_the_profile_format_and_text_obeys_it() -> None:
    typed = DateCell(date(2026, 8, 17))
    assert parse_date(typed, "dd.MM.yyyy") == date(2026, 8, 17)
    assert parse_date(typed.strip(), "yyyyMMdd") == date(2026, 8, 17)
    assert parse_date("17.08.2026", "dd.MM.yyyy") == date(2026, 8, 17)
    assert parse_date("2026-08-17", "dd.MM.yyyy") is None  # the plain rendering is not read as text


def test_a_typed_number_ignores_the_separators_and_text_obeys_them() -> None:
    kw: dict[str, Any] = {"currency": "EUR", "minor_units": 2, "decimal_sep": ",", "thousands_sep": "."}
    assert parse_amount(NumberCell(Decimal("-12.34")), **kw) == -1234
    assert parse_amount(NumberCell(Decimal("1500.0")), **kw) == 150000
    assert parse_amount("1.500,00", **kw) == 150000
    with pytest.raises(ValueError):
        parse_amount(NumberCell(Decimal("0.001")), **kw)  # excess precision is an error, as for text


def test_a_typed_cell_survives_trimming_and_reads_as_its_rendering() -> None:
    cell = NumberCell(Decimal("1234.5"))
    assert cell.strip() is cell
    assert cell == "1234.5"
    assert DateCell(date(2026, 8, 17)) == "2026-08-17"


# -- reading a workbook -----------------------------------------------------------------------


@needs_calamine
def test_typed_and_text_cells_in_one_sheet() -> None:
    out = parse(xlsx_bytes(ROWS))
    assert [(r.booked_on, r.value_on, r.amount_minor, r.purpose) for r in out.rows] == [
        (date(2026, 8, 17), date(2026, 8, 17), -1234, "Shop"),
        (date(2026, 8, 18), date(2026, 8, 18), 150000, "Rent"),
    ]
    assert out.covered_through == date(2026, 8, 18)


@needs_calamine
def test_row_numbers_are_sheet_rows_and_blank_rows_are_ignored() -> None:
    rep = parse(xlsx_bytes(ROWS)).report
    assert rep.header_line == 4
    assert rep.encoding == "spreadsheet"
    assert rep.delimiter is None
    assert rep.rows_read == 3  # the two bookings and the footer; the blank rows 3 and 7 are not rows
    assert rep.skipped.count == 1
    assert [e.row for e in rep.skipped.examples] == [8]
    assert [s.row for s in rep.sample] == [5, 6]


@needs_calamine
def test_the_header_is_found_by_marker_below_a_preamble() -> None:
    data = xlsx_bytes([["x"], ["y"], ["z"], *ROWS])
    assert parse(data).report.header_line == 7
    with pytest.raises(ParseFailed, match="no header row"):
        parse(xlsx_bytes(ROWS), header_marker=["Booking", "Nonexistent"])


@needs_calamine
def test_the_balance_is_located_by_label_on_a_sheet() -> None:
    out = parse(xlsx_bytes(ROWS))
    assert out.reported_balance == 123456
    assert out.balance_on == date(2026, 8, 18)  # the earliest of export-1 day, and the coverage
    assert parse(xlsx_bytes(ROWS), invert_balance=True).reported_balance == -123456


@needs_calamine
def test_a_located_date_on_a_sheet_may_be_a_typed_cell() -> None:
    rows: list[list[Cell]] = [["Period end", date(2026, 8, 17)], *ROWS[1:]]
    out = parse(xlsx_bytes(rows), coverage_end={"format": "yyyyMMdd", "label": "Period end", "right": 1})
    assert out.covered_through == date(2026, 8, 17)


@needs_calamine
def test_signs_and_inversion() -> None:
    assert [r.amount_minor for r in parse(xlsx_bytes(ROWS), invert_amounts=True).rows] == [1234, -150000]
    split: list[list[Cell]] = [
        ["Booking", "Credit", "Debit"],
        [date(2026, 8, 17), None, 12.5],
        [date(2026, 8, 18), 20, None],
    ]
    out = run(
        xlsx_bytes(split),
        profile={
            "header_marker": ["Booking", "Credit"],
            "booked_on": "Booking",
            "date_format": "dd.MM.yyyy",
            "amount": {"credit": "Credit", "debit": "Debit"},
        },
    )
    assert [r.amount_minor for r in out.rows] == [-1250, 2000]


@needs_calamine
def test_money_is_exact_and_follows_the_currency_exponent() -> None:
    rows: list[list[Cell]] = [
        ["Booking", "Amount"],
        [date(2026, 8, 17), 0.1 + 0.2],  # stored as 0.30000000000000004: float noise, shown as 0.3
    ]
    assert run(xlsx_bytes(rows), profile=MINI).rows[0].amount_minor == 30
    rows[1][1] = 12.345  # genuine excess precision for EUR still fails
    with pytest.raises(ParseFailed, match="amount"):
        run(xlsx_bytes(rows), profile=MINI)
    big: list[list[Cell]] = [["Booking", "Amount"], [date(2026, 8, 17), 1e20], [date(2026, 8, 18), 1e-5]]
    assert [str(c) for c in (_typed(1e20), _typed(1e-5))] == ["100000000000000000000", "0.00001"]
    assert run(xlsx_bytes(big[:2]), profile=MINI, currency="JPY").rows[0].amount_minor == 10**20
    with pytest.raises(ParseFailed, match="amount"):
        run(xlsx_bytes(big), profile=MINI)  # 1e-5 is excess precision
    yen: list[list[Cell]] = [["Booking", "Amount"], [date(2026, 8, 17), -1500]]
    out = run(xlsx_bytes(yen), profile=MINI, currency="JPY")
    assert out.rows[0].amount_minor == -1500
    kwd: list[list[Cell]] = [["Booking", "Amount"], [date(2026, 8, 17), 1.234]]
    out = run(xlsx_bytes(kwd), profile=MINI, currency="KWD")
    assert out.rows[0].amount_minor == 1234


@needs_calamine
def test_only_the_first_sheet_is_read() -> None:
    other: list[list[Cell]] = [["Booking", "Amount"], [date(2026, 8, 19), 99.0]]
    out = parse(xlsx_bytes(ROWS, other))
    assert len(out.rows) == 2


@needs_calamine
def test_raw_keeps_the_header_the_cells_and_a_tab_joined_text() -> None:
    row = parse(xlsx_bytes(ROWS)).rows[0]
    assert row.raw["header"] == ["Booking", "Value", "Amount", "Purpose"]
    assert row.raw["cells"] == ["2026-08-17", "17.08.2026", "-12.34", "Shop"]
    assert row.raw["text"] == "2026-08-17\t17.08.2026\t-12.34\tShop"
    assert all(type(c) is str for c in row.raw["cells"])


@needs_calamine
def test_the_export_date_is_the_upload_date_without_a_profile_reading() -> None:
    assert parse(xlsx_bytes(ROWS)).report.export_date == TODAY
