"""The core: a statement model in, what spec §5.1 asks of an importer out (camt.md §4).

Written once, whatever the reader: the per-report check, the records in ledger sign convention, the
balance record dated and rolled back by the §5.1 rule, and the coverage. Messages name a report by its
message id and never carry an amount.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import BalanceReport, IncomingRow, ParsedFile, SampleRow
from app.plugins.importers.camt.model import Balance, Detail, Entry, Report, Statement
from app.plugins.importers.csv.report import ReportBuilder  # the dry run's collector, not CSV logic

CELL_DISPLAY = 40


def _collapse(text: str) -> str:
    return " ".join(text.split())


def check(report: Report) -> tuple[Balance, Balance]:
    """The report's balances once the opening plus its entries is shown to equal the closing."""
    if report.opening is None or report.closing is None:
        raise ParseFailed(f"report {report.message_id}: it lacks an opening or a closing balance")
    currencies = {report.opening.currency, report.closing.currency, *(e.currency for e in report.entries)}
    if len(currencies) > 1:
        raise ParseFailed(f"report {report.message_id}: its balances and entries are not in one currency")
    if report.opening.signed + sum((e.signed for e in report.entries), Decimal(0)) != report.closing.signed:
        raise ParseFailed(
            f"report {report.message_id}: the opening balance plus its entries "
            "does not equal the closing balance"
        )
    return report.opening, report.closing


def _minor(amount: Decimal, exponent: int, what: str) -> int:
    scaled = amount.scaleb(exponent)
    if scaled != scaled.to_integral_value():
        raise ParseFailed(f"{what}: the amount is not a whole number of minor units")
    return int(scaled)


def _record(entry: Entry, message_id: str, source_format: str, amount_minor: int) -> IncomingRow:
    one: Detail | None = entry.details[0] if len(entry.details) == 1 else None
    e2e = (one.end_to_end_id or "") if one else ""
    purpose = _collapse(" ".join(line for d in entry.details for line in d.remittance))

    def own(value: str | None) -> str | None:
        return (_collapse(value) or None) if value else None

    return IncomingRow(
        amount_minor=amount_minor,
        currency=entry.currency,
        booked_on=entry.booked_on,
        value_on=entry.value_on,
        source_format=source_format,
        raw={"report": message_id, "entry": entry.xml},
        counterparty_name=own(one.name if one else None),
        counterparty_ref=own(one.account if one else None),
        counterparty_bic=own(one.agent if one else None),
        end_to_end_id=None if e2e.strip().upper() in ("", "NOTPROVIDED") else e2e.strip(),
        mandate_ref=own(one.mandate_id if one else None),
        purpose=purpose or None,
    )


def run(
    statement: Statement,
    rep: ReportBuilder,
    currency: str,
    exponent: Callable[[str], int],
    today: date,
) -> ParsedFile:
    rep.format = f"{statement.reader.upper()} XML, {statement.message_type}"
    if not statement.reports:
        raise ParseFailed("no coverage: the file has no booked report")
    checked = [(r, *check(r)) for r in statement.reports]
    source_format = f"{statement.message_type.replace('.', '')}:{statement.reader}"
    lim = rep.limit

    rows: list[IncomingRow] = []
    n = 0
    for report in statement.reports:
        for entry in report.entries:
            n += 1
            rep.rows_read += 1
            what = f"report {report.message_id} entry {n}"
            amount = _minor(entry.signed, exponent(entry.currency), what)
            if amount == 0:
                rep.zero_dropped.add(n, "amount is zero", lim)
                continue
            if entry.currency != currency:
                rep.currency_mismatch.add(n, "currency differs from the account's", lim)
            row = _record(entry, report.message_id, source_format, amount)
            rows.append(row)
            rep.emitted += 1
            if len(rep.sample) < lim:
                cells = (row.counterparty_name or "", row.purpose or "")
                rep.sample.append(SampleRow(n, row.booked_on, amount, tuple(c[:CELL_DISPLAY] for c in cells)))
    for k in range(1, statement.pending + 1):
        rep.rows_read += 1
        rep.filtered.add(n + k, "pending entry: never imported", lim)
    if rep.currency_mismatch.count:
        rep.warnings.append(
            f"{rep.currency_mismatch.count} row(s) have a currency other than the account's: "
            "the run would fail"
        )

    last, opening, closing = checked[-1][0], checked[0][1], checked[-1][2]
    if closing.currency != currency:
        raise ParseFailed(f"report {last.message_id}: the closing balance is not in the account's currency")

    if statement.export_date is None:
        export, rep.export_date_source = today, "upload date (the file states none)"
    else:
        export, rep.export_date_source = statement.export_date, "creation date of the file's report header"
    rep.export_date = export
    closed = export - timedelta(days=1)
    if closing.on < export:
        coverage, rep.coverage_source = closing.on, "closing balance date of the last report"
    else:
        coverage, rep.coverage_source = (
            closed,
            "the day before the export date (the closing balance is not before it)",
        )
    rep.coverage = coverage

    figure_on = max([closing.on, *(e.booked_on for e in last.entries)])
    figure = _minor(closing.signed, exponent(currency), f"report {last.message_id} closing balance")
    on = min(figure_on, closed, coverage)
    undone = [r.amount_minor for r in rows if on < r.booked_on <= figure_on] if on < figure_on else []
    amount = figure - sum(undone)
    rep.balance = BalanceReport(
        amount,
        on,
        "closing balance of the last report",
        figure,
        figure_on,
        sum(undone),
        len(undone),
    )
    return ParsedFile(
        rows=tuple(rows),
        reported_balance=amount,
        balance_on=on,
        covered_through=coverage,
        data_start=min((r.booked_on for r in rows), default=opening.on),
        importer_stats={"filtered": rep.zero_dropped.count},
        report=rep.build(),
    )
