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
        text("SELECT id, account_id, kind, balance_on, balance, currency FROM balance_record WHERE id = :i"),
        {"i": record_id},
    ).one_or_none()
    if row is None:
        raise RecordNotFound(record_id)
    return RecordView(row.id, row.account_id, row.kind, row.balance_on, int(row.balance), row.currency)


def manual_record_id_on(conn: Connection, account_id: int, balance_on: date) -> int | None:
    value = conn.execute(
        text("SELECT id FROM balance_record WHERE account_id = :a AND kind = 'manual' AND balance_on = :d"),
        {"a": account_id, "d": balance_on},
    ).scalar_one_or_none()
    return None if value is None else int(value)
