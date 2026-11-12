"""The synthetic statement payment (csv.md §6, spec §5.1).

A card that lists purchases and never the payment that settles them gets one derived movement
per file: the negated net sum of the file's rows, dated after the coverage so the balance record
(dated at the coverage) does not include it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import IncomingRow, SyntheticReport
from app.core.plugins.report import ReportBuilder
from app.plugins.importers.csv.profile import Profile

SYNTHETIC_FORMAT = "csv:synthetic"


def statement_payment(
    prof: Profile, rows: Sequence[IncomingRow], coverage: date, currency: str, rep: ReportBuilder
) -> IncomingRow | None:
    """The payment row, or None when the profile has none or the net sum is not negative."""
    spec = prof.statement_payment
    if spec is None:
        return None
    net = sum(r.amount_minor for r in rows)
    if net >= 0:
        return None
    try:
        booked_on = coverage + timedelta(days=spec.date_offset_days)
    except OverflowError:
        raise ParseFailed("statement_payment: the payment date is beyond the calendar") from None
    statement_date = coverage.isoformat()
    rep.synthetic = SyntheticReport(-net, booked_on, len(rows), net)
    return IncomingRow(
        amount_minor=-net,
        currency=currency,
        booked_on=booked_on,
        source_format=SYNTHETIC_FORMAT,
        raw={
            "settings": prof.to_dict(),
            "row_count": len(rows),
            "sum_minor": net,
            "statement_date": statement_date,
        },
        counterparty_ref=spec.counter_account_ref,
        purpose=spec.purpose.replace("{statement_date}", statement_date),
    )
