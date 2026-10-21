"""Run the CSV importer on a file and print ONLY its privacy-safe report.

    uv run --no-sync python scripts/csv_dry_run.py --preset consorsbank_giro \\
        --file export.csv --currency EUR [--today YYYY-MM-DD] [--set key=value ...]

Nothing is written anywhere and no database is needed. The report holds counts, the mapped
columns, the detected encoding and delimiter, the coverage and export date with where they came
from, the balance record, the synthetic payment and a few parsed rows whose cells are cut to 24
characters. It never prints the file's preamble, so it is safe to paste.

Amounts are read with the minor-unit exponent of their currency: a small built-in table (JPY 0,
KWD 3, BHD 3, every other currency 2), changed per run with `--exponent CUR=N`.

`--set` overrides one setting of the preset; the key may be dotted (`balance.label=Saldo`), the
value is JSON where it parses (`statement_payment.date_offset_days=6`) and text otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from app.core.domain.money import Money
from app.core.plugins.errors import InvalidProfile, ParseFailed
from app.core.plugins.importer import Category, DryRunReport
from app.plugins.importers.csv import CsvImporter, load_presets

DEFAULT_EXPONENTS = {"JPY": 0, "KWD": 3, "BHD": 3}


def _exponents(assignments: Sequence[str]) -> dict[str, int]:
    table = dict(DEFAULT_EXPONENTS)
    for a in assignments:
        cur, sep, n = a.partition("=")
        if not sep or not cur or not n.isdigit():
            raise SystemExit(f"--exponent expects CUR=N, got {a!r}")
        table[cur.strip()] = int(n)
    return table


def _apply(settings: dict[str, Any], assignment: str) -> None:
    key, sep, raw = assignment.partition("=")
    if not sep or not key:
        raise SystemExit(f"--set expects key=value, got {assignment!r}")
    try:
        value: Any = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    *path, last = key.split(".")
    target = settings
    for part in path:
        nxt = target.get(part)
        if not isinstance(nxt, dict):
            nxt = target[part] = {}
        target = nxt
    target[last] = value


def _money(minor: int, minor_units: int, currency: str) -> str:
    return f"{Money(minor, currency).format(minor_units=minor_units)} {currency}"


def _category(title: str, cat: Category) -> list[str]:
    lines = [f"{title}: {cat.count}"]
    lines += [f"    row {e.row}: {e.reason}" for e in cat.examples]
    return lines


def format_report(report: DryRunReport, *, minor_units: int = 2, currency: str = "EUR") -> str:
    def m(v: int) -> str:
        return _money(v, minor_units, currency)

    out: list[str] = []
    if report.failure is not None:
        out.append(f"FAILED: {report.failure}")
    out.append(
        f"encoding: {report.encoding}   delimiter: {report.delimiter!r}   header at line {report.header_line}"
    )
    out.append("columns:")
    out += [f"    {c.field} <- {c.name!r} (column {c.index + 1})" for c in report.columns]
    out.append(f"rows read: {report.rows_read}   emitted: {report.emitted}")
    out += _category("skipped as not transactions", report.skipped)
    out += _category("filtered by a row filter (pending rows among them)", report.filtered)
    out += _category("dropped as zero bookings", report.zero_dropped)
    out += _category("currency differs from the account's", report.currency_mismatch)
    out.append(f"export date: {report.export_date} ({report.export_date_source})")
    out.append(f"coverage: {report.coverage} ({report.coverage_source})")
    b = report.balance
    if b is None:
        out.append("balance: none written")
    else:
        out.append(f"balance: {m(b.amount_minor)} dated {b.dated_on}; {b.source}")
        out.append(f"    figure {m(b.figure_minor)} dated {b.figure_on}")
        if b.rolled_back_rows:
            out.append(
                f"    rolled back by {m(b.rolled_back_by_minor)} over {b.rolled_back_rows} booked row(s)"
            )
    s = report.synthetic
    if s is None:
        out.append("synthetic payment: none")
    else:
        out.append(
            f"synthetic payment: {m(s.amount_minor)} booked {s.booked_on}, made of {s.row_count} row(s) "
            f"summing {m(s.sum_minor)}"
        )
    out.append(f"first rows as parsed (cells after the header, cut to 24 characters): {len(report.sample)}")
    for r in report.sample:
        out.append(f"    row {r.row}: {r.booked_on} {m(r.amount_minor)} | " + " | ".join(r.cells))
    out += [f"WARNING: {w}" for w in report.warnings]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--preset", required=True)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--currency", required=True)
    parser.add_argument(
        "--exponent", action="append", default=[], metavar="CUR=N", help="minor-unit exponent of a currency"
    )
    parser.add_argument("--today", type=date.fromisoformat, default=None, help="upload date, default: today")
    parser.add_argument("--set", action="append", default=[], dest="overrides", metavar="key=value")
    args = parser.parse_args(argv)

    presets = load_presets()
    if args.preset not in presets:
        parser.error(f"unknown preset {args.preset!r}; available: {', '.join(sorted(presets))}")
    settings = presets[args.preset]
    for assignment in args.overrides:
        _apply(settings, assignment)
    table = _exponents(args.exponent)

    def exponent_of(currency: str) -> int:
        return table.get(currency, 2)

    minor_units = exponent_of(args.currency)
    today = args.today or date.today()  # noqa: DTZ011 - a local helper script, the user's own day
    try:
        parsed = CsvImporter().parse(
            args.file.read_bytes(),
            settings,
            account_currency=args.currency,
            minor_units_of=exponent_of,
            today=today,
            name=args.preset,
        )
    except InvalidProfile as exc:
        print(f"FAILED: invalid profile: {exc}")
        return 1
    except ParseFailed as exc:
        report = exc.report if exc.report is not None else DryRunReport(failure=str(exc))
        print(format_report(report, minor_units=minor_units, currency=args.currency))
        return 1
    print(format_report(parsed.report, minor_units=minor_units, currency=args.currency))
    return 0


if __name__ == "__main__":
    sys.exit(main())
