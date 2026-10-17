"""`CsvImporter`: the file importer for statement exports (csv.md).

A pure parse: bytes and a profile in, `ParsedFile` out. It reads neither the database nor
the clock; `today` is the upload date and stands in for an export date the file does not state.
A currency mismatch is not raised here: the rows go out unchanged, ingest's `ContractViolation`
fails the run, and the report records the mismatch so the dry run shows it (csv.md §3, §7).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import IncomingRow, MappedColumn, ParsedFile, SampleRow
from app.plugins.importers.csv.amounts import parse_amount
from app.plugins.importers.csv.balance import read_date, reported_balance
from app.plugins.importers.csv.dates import parse_date
from app.plugins.importers.csv.filters import CompiledFilter, compile_filter, first_hit
from app.plugins.importers.csv.profile import ColRef, Profile
from app.plugins.importers.csv.reader import ReadFile, read_file, resolve_column
from app.plugins.importers.csv.report import Kept, ReportBuilder
from app.plugins.importers.csv.statement_payment import statement_payment

CELL_DISPLAY = 24


def _collapse(text: str) -> str:
    return " ".join(text.split())


class CsvImporter:
    @property
    def presets(self) -> dict[str, dict[str, Any]]:
        """The shipped presets by name, for the catalog (csv.md §8)."""
        from app.plugins.importers.csv.presets import load_presets  # the presets package imports this one

        return load_presets()

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        Profile.from_dict(settings).validate()

    def parse(
        self,
        data: bytes,
        profile: Mapping[str, Any],
        *,
        account_currency: str,
        minor_units_of: Callable[[str], int],
        today: date,
        name: str,
        dry_run_samples: int = 5,
    ) -> ParsedFile:
        prof = Profile.from_dict(profile)
        prof.validate()
        report = ReportBuilder(limit=dry_run_samples)
        try:
            return _parse(data, prof, report, account_currency, _known(minor_units_of), today, name)
        except ParseFailed as exc:
            if exc.report is not None:
                raise
            raise ParseFailed(str(exc), report=report.build(failure=str(exc))) from None


def _known(lookup: Callable[[str], int]) -> Callable[[str], int]:
    """The caller's exponent lookup, an unknown currency turned into a ParseFailed naming it."""

    def exponent(currency: str) -> int:
        try:
            return lookup(currency)
        except KeyError:
            raise ParseFailed(f"unknown currency {currency!r}: no minor-unit exponent known") from None

    return exponent


def _parse(
    data: bytes, prof: Profile, rep: ReportBuilder, currency: str, exponent: Callable[[str], int], today: date, name: str
) -> ParsedFile:
    minor_units = exponent(currency)
    rf = read_file(
        data, encoding=prof.encoding, delimiter=prof.delimiter, quote=prof.quote, markers=prof.header_marker
    )
    rep.encoding, rep.delimiter = rf.encoding, rf.delimiter
    rep.header_line = rf.records[rf.header_index].line
    kept = _read_rows(rf, prof, rep, currency, exponent, name)
    emitted = [k.row for k in kept if k.row is not None]
    if rep.rows_read and rep.skipped.count == rep.rows_read:
        rep.warnings.append(
            "every row was skipped as not a transaction: check the booking date column and format"
        )
    elif rep.rows_read == 0:
        rep.warnings.append("the file has no rows below the header")
    if rep.currency_mismatch.count:
        rep.warnings.append(
            f"{rep.currency_mismatch.count} row(s) have a currency other than the account's: "
            "the run would fail"
        )
    export_date = _export_date(prof, rf, today, rep)
    coverage = _coverage(prof, rf, emitted, rep)
    balance = reported_balance(prof, rf, kept, export_date, coverage, rep, currency, minor_units)
    synthetic = statement_payment(prof, emitted, coverage, currency, rep)
    skipped = prof.statement_payment is not None and synthetic is None
    return ParsedFile(
        rows=(*emitted, synthetic) if synthetic is not None else tuple(emitted),
        reported_balance=None if balance is None else balance[0],
        balance_on=None if balance is None else balance[1],
        covered_through=coverage,
        data_start=min((r.booked_on for r in emitted), default=None),
        importer_stats={"filtered": rep.zero_dropped.count, "synthetic_skipped": int(skipped)},
        report=rep.build(),
    )


def _export_date(prof: Profile, rf: ReadFile, today: date, rep: ReportBuilder) -> date:
    if prof.export_date is None:
        rep.export_date, rep.export_date_source = today, "upload date (the profile reads no export date)"
    else:
        rep.export_date, found = read_date(rf.records, prof.export_date, "export_date")
        rep.export_date_source = f"read from the file at {found}"
    return rep.export_date


def _coverage(prof: Profile, rf: ReadFile, emitted: Sequence[IncomingRow], rep: ReportBuilder) -> date:
    if prof.coverage_end is not None:
        rep.coverage, found = read_date(rf.records, prof.coverage_end, "coverage_end")
        rep.coverage_source = f"stated period end, {found}"
        return rep.coverage
    last = max((r.booked_on for r in emitted), default=None)
    if last is None:
        raise ParseFailed("no coverage: the file has no booking rows and no stated period end")
    rep.coverage, rep.coverage_source = last, "last booking date (the profile states no period end)"
    return last


def _read_rows(
    rf: ReadFile,
    prof: Profile,
    rep: ReportBuilder,
    currency: str,
    exponent: Callable[[str], int],
    name: str,
) -> list[Kept]:
    header = rf.header

    def col(ref: ColRef | None, field_name: str) -> int | None:
        if ref is None:
            return None
        idx = resolve_column(header, ref, field_name)
        rep.columns.append(MappedColumn(field_name, header[idx], idx))
        return idx

    booked_i = col(prof.booked_on, "booked_on")
    value_i = col(prof.value_on, "value_on")
    assert booked_i is not None
    amount_i, credit_i, debit_i = (
        col(prof.amount.column, "amount"),
        col(prof.amount.credit, "amount.credit"),
        col(prof.amount.debit, "amount.debit"),
    )
    optional = {
        name: col(getattr(prof, name), name)
        for name in (
            "counterparty_name",
            "counterparty_ref",
            "counterparty_bic",
            "end_to_end_id",
            "mandate_ref",
            "booking_text",
        )
    }
    purpose_is = [col(p, "purpose") for p in prof.purpose]
    cur_i = col(prof.currency, "currency")
    instr_amount_i = instr_cur_i = None
    if prof.instructed is not None:
        instr_amount_i = col(prof.instructed.amount, "instructed.amount")
        instr_cur_i = col(prof.instructed.currency, "instructed.currency")
    filters: list[CompiledFilter] = []
    for f in prof.filters:
        idx = resolve_column(header, f.column, "filters")
        filters.append(compile_filter(f, idx, header[idx]))

    placeholders = set(prof.placeholders)
    lim = rep.limit
    source_format = f"csv:{name}"  # the instance's label at the time of the run
    kept: list[Kept] = []

    def cell(cells: Sequence[str], i: int | None) -> str:
        return cells[i] if i is not None and i < len(cells) else ""

    def amount_of(text: str, row_no: int, setting: str, in_currency: str = currency) -> int:
        try:
            return parse_amount(
                text,
                currency=in_currency,
                minor_units=exponent(in_currency),
                decimal_sep=prof.decimal_sep,
                thousands_sep=prof.thousands_sep,
            )
        except ValueError:
            raise ParseFailed(f"row {row_no}: {setting} does not parse as an amount") from None

    for rec in rf.records[rf.header_index + 1 :]:
        if all(not c.strip() for c in rec.cells):
            continue  # a blank line is not a row
        rep.rows_read += 1
        cells = ["" if c.strip() in placeholders else c.strip() for c in rec.cells]
        hit = first_hit(filters, cells)
        if hit is not None:
            rep.filtered.add(rec.line, f"row filter: {hit.description}", lim)
            continue
        booked_on = parse_date(cell(cells, booked_i), prof.date_format)
        if booked_on is None:
            rep.skipped.add(rec.line, "booking date does not parse: not a transaction", lim)
            continue
        row_currency = currency
        if cur_i is not None and cell(cells, cur_i):
            row_currency = cell(cells, cur_i)
        value_on = None
        if value_i is not None and cell(cells, value_i):
            value_on = parse_date(cell(cells, value_i), prof.date_format)
            if value_on is None:
                raise ParseFailed(f"row {rec.line}: value_on does not parse as a date")
        if amount_i is not None:
            if not cell(cells, amount_i):
                raise ParseFailed(f"row {rec.line}: amount is empty")
            amount = amount_of(cell(cells, amount_i), rec.line, "amount")
        else:
            credit = (
                amount_of(cell(cells, credit_i), rec.line, "amount.credit") if cell(cells, credit_i) else 0
            )
            debit = amount_of(cell(cells, debit_i), rec.line, "amount.debit") if cell(cells, debit_i) else 0
            amount = credit - debit
        if prof.invert_amounts:
            amount = -amount
        if amount == 0:
            rep.zero_dropped.add(rec.line, "amount is zero", lim)
            kept.append(Kept(rec, cells, booked_on, 0, None))
            continue
        if row_currency != currency:  # only a row that goes on to ingest can break the contract
            rep.currency_mismatch.add(rec.line, "currency differs from the account's", lim)
        instr_amount = instr_currency = None
        if instr_amount_i is not None:
            ic, ia = cell(cells, instr_cur_i), cell(cells, instr_amount_i)
            if ia and ic and ic != currency:
                instr_amount = amount_of(ia, rec.line, "instructed.amount", ic)
                instr_currency = ic
                if prof.invert_amounts:
                    instr_amount = -instr_amount
        purpose = _collapse(" ".join(cell(cells, i) for i in purpose_is)) or None
        extras = {k: (_collapse(cell(cells, i)) or None) for k, i in optional.items()}
        row = IncomingRow(
            amount_minor=amount,
            currency=row_currency,
            booked_on=booked_on,
            source_format=source_format,
            raw={"header": list(header), "cells": list(rec.cells), "text": rec.text},
            value_on=value_on,
            instructed_amount_minor=instr_amount,
            instructed_currency=instr_currency,
            counterparty_ref=extras["counterparty_ref"],
            counterparty_bic=extras["counterparty_bic"],
            counterparty_name=extras["counterparty_name"],
            purpose=purpose,
            end_to_end_id=extras["end_to_end_id"],
            mandate_ref=extras["mandate_ref"],
            booking_text=extras["booking_text"],
        )
        kept.append(Kept(rec, cells, booked_on, amount, row))
        rep.emitted += 1
        if len(rep.sample) < lim:
            rep.sample.append(
                SampleRow(rec.line, booked_on, amount, tuple(c.strip()[:CELL_DISPLAY] for c in rec.cells))
            )
    return kept
