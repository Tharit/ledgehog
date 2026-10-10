"""Finding labelled figures and dates anywhere in the file (csv.md §5).

The whole file is searched, preamble and footer included. A label matches a cell whose whole
trimmed text it is; failing that, a cell that contains it; the first match in file order wins.
A value sits at an offset from the label cell: cells to its right, rows below in the same column.
Nothing here echoes cell content into an error: messages name labels and settings only.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import date, timedelta

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import BalanceReport
from app.plugins.importers.csv.amounts import parse_amount
from app.plugins.importers.csv.dates import parse_date
from app.plugins.importers.csv.profile import LocatedDate, Profile
from app.plugins.importers.csv.reader import ReadFile, Record, resolve_column
from app.plugins.importers.csv.report import Kept, ReportBuilder

Position = tuple[int, int]  # (record index, cell index)


def _clean(cell: str) -> str:
    return cell.replace("﻿", "").strip()


def find_label(records: Sequence[Record], label: str) -> Position | None:
    wanted = label.strip()
    for i, rec in enumerate(records):
        for j, cell in enumerate(rec.cells):
            if _clean(cell) == wanted:
                return i, j
    for i, rec in enumerate(records):
        for j, cell in enumerate(rec.cells):
            if wanted in cell:
                return i, j
    return None


def cell_at(
    records: Sequence[Record], anchor: Position, right: int, below: int
) -> tuple[Position, str] | None:
    """The cell `right` cells right and `below` rows below the anchor, if the file has one."""
    i, j = anchor[0] + below, anchor[1] + right
    if i >= len(records) or j >= len(records[i].cells):
        return None
    return (i, j), records[i].cells[j]


def locate(records: Sequence[Record], label: str, setting: str) -> Position:
    pos = find_label(records, label)
    if pos is None:
        raise ParseFailed(f"{setting}: label {label!r} not found in the file")
    return pos


def where(records: Sequence[Record], pos: Position) -> str:
    return f"row {records[pos[0]].line}, column {pos[1] + 1}"


def read_date(
    records: Sequence[Record],
    spec: LocatedDate,
    setting: str,
    *,
    default_anchor: Position | None = None,
    default_label: str = "",
) -> tuple[date, str]:
    """The date `spec` points at, and a description of where it was found."""
    if spec.label is not None:
        anchor = locate(records, spec.label, setting)
        name = spec.label
    else:
        assert default_anchor is not None
        anchor, name = default_anchor, default_label
    found = cell_at(records, anchor, spec.right, spec.below)
    if found is None:
        raise ParseFailed(f"{setting}: no cell {spec.right} right / {spec.below} below label {name!r}")
    pos, text = found
    if spec.pattern is not None:
        m = re.search(spec.pattern, text)
        if m is None:
            raise ParseFailed(f"{setting}: the pattern does not match at label {name!r}")
        text = m.group(1) if m.re.groups else m.group(0)
    parsed = parse_date(text, spec.format)
    if parsed is None:
        raise ParseFailed(f"{setting}: the date at label {name!r} does not parse as {spec.format}")
    return parsed, f"label {name!r}, {where(records, pos)}"


def reported_balance(
    prof: Profile,
    rf: ReadFile,
    kept: Sequence[Kept],
    export_date: date,
    coverage: date,
    rep: ReportBuilder,
    currency: str,
    minor_units: int,
) -> tuple[int, date] | None:
    """The balance record to write (amount, date), or None: spec §5.1 and csv.md §5."""
    spec = prof.balance
    if spec is None:
        return None
    closed = export_date - timedelta(days=1)

    def amount_of(text: str, what: str) -> int:
        try:
            value = parse_amount(
                text,
                currency=currency,
                minor_units=minor_units,
                decimal_sep=prof.decimal_sep,
                thousands_sep=prof.thousands_sep,
            )
        except ValueError:
            raise ParseFailed(f"balance: {what} does not parse as an amount") from None
        return -value if prof.invert_balance else value

    if spec.mode == "running_column":
        found = _running(spec.column, rf, kept, closed, rep, amount_of)
        if found is None:
            rep.warnings.append("no row dated on or before the last closed day: no balance reported")
            return None
        amount, on, source = found
        figure, rolled_by, rolled_rows = amount, 0, 0
        figure_on = on
    else:
        assert spec.label is not None
        anchor = locate(rf.records, spec.label, "balance")
        got = cell_at(rf.records, anchor, spec.right, spec.below)
        if got is None or not got[1].strip():
            raise ParseFailed(
                f"balance: no value {spec.right} right / {spec.below} below label {spec.label!r}"
            )
        figure = amount_of(got[1], f"the value at label {spec.label!r}")
        if spec.date is None:
            figure_on, date_src = export_date, "the export date (the file states no date for the figure)"
        else:
            figure_on, date_src = read_date(
                rf.records, spec.date, "balance.date", default_anchor=anchor, default_label=spec.label
            )
        source = (
            f"labelled figure: label {spec.label!r} at {where(rf.records, anchor)}, value at "
            f"{where(rf.records, got[0])}; dated by {date_src}"
        )
        rolled_by = rolled_rows = 0
        amount, on = figure, figure_on
        if figure_on > closed:
            after = [k.amount for k in kept if k.row is not None and k.booked_on > closed]
            rolled_by, rolled_rows = sum(after), len(after)
            amount, on = figure - rolled_by, closed
    if on > coverage:
        rep.warnings.append(
            f"the balance would be dated {on.isoformat()}, after the file's coverage "
            f"{coverage.isoformat()}: no balance reported"
        )
        return None
    rep.balance = BalanceReport(amount, on, source, figure, figure_on, rolled_by, rolled_rows)
    return amount, on


def _running(
    ref: str | int | None,
    rf: ReadFile,
    kept: Sequence[Kept],
    closed: date,
    rep: ReportBuilder,
    amount_of: Callable[[str, str], int],
) -> tuple[int, date, str] | None:
    """The running balance of the last row on or before the closed day, by booking date."""
    assert ref is not None
    idx = resolve_column(rf.header, ref, "balance")
    name = rf.header[idx]
    usable = [k for k in kept if k.booked_on <= closed and idx < len(k.cells) and k.cells[idx]]
    if not usable:
        return None
    descending = kept[0].booked_on > kept[-1].booked_on  # newest first: the day's first row is its last
    best = max(k.booked_on for k in usable)
    same_day = [k for k in usable if k.booked_on == best]
    pick = same_day[0] if descending else same_day[-1]
    value = amount_of(pick.cells[idx], f"the running balance in column {name!r}, row {pick.record.line}")
    return value, pick.booked_on, f"running balance column {name!r}, row {pick.record.line}"
