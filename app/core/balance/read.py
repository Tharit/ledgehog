"""Reading balance records (spec §3.10): one record, and the manual record of a date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

from app.core.balance.records import RecordNotFound


@dataclass(frozen=True)
class RecordView:
    id: int
    account_id: int
    kind: str  # 'reported' | 'manual'
    balance_on: date
    balance: int
    currency: str


def get_record(conn: Connection, record_id: int) -> RecordView:
    row = conn.execute(
        text("SELECT id, account_id, balance_on, balance, currency, import_run_id IS NOT NULL AS reported "
            "FROM balance_record WHERE id = :i"
        ),
        {"i": record_id},
    ).one_or_none()
    if row is None:
        raise RecordNotFound(record_id)
    kind = "reported" if row.reported else "manual"
    return RecordView(row.id, row.account_id, kind, row.balance_on, int(row.balance), row.currency)
