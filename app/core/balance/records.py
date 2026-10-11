"""Writing balance records (spec §3.10, §5.10).

Reported records are written inside the ingest transaction (`insert_reported_record`, which does
not recompute; the caller does, after). Manual records are set, edited and deleted here, one
transaction each: settle lock shared, then the account's lock, then the write and
`recompute_derived`; it commits, and only then settles (a settling failure is reported on the
result, never raised into the committed write). Reported records are never edited, but any
record may be deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, Engine, text

from app.core.accounts import AccountMissing
from app.core.balance.derived import recompute_derived
from app.core.settle.settle import SettleResult, settle
from app.utils.db.locks import lock_accounts, lock_settle_shared, retry_on_deadlock


class RecordError(Exception):
    """A balance record operation was refused; the message states the rule. Nothing was written."""


AccountNotFound = AccountMissing  # the one account-missing error lives in core.accounts


class RecordNotFound(RecordError):
    def __init__(self, record_id: int) -> None:
        self.record_id = record_id
        super().__init__(f"balance record {record_id} does not exist")


class ReportedRecordNotEditable(RecordError):
    def __init__(self, record_id: int) -> None:
        self.record_id = record_id
        super().__init__(f"balance record {record_id} was reported by an importer; it can only be deleted")


class RecordDateTaken(RecordError):
    def __init__(self, account_id: int, balance_on: date) -> None:
        self.account_id = account_id
        self.balance_on = balance_on
        super().__init__(f"account {account_id} already has a manual balance record on {balance_on}")


@dataclass(frozen=True)
class RecordResult:
    record_id: int
    settle: SettleResult
    created: bool = False  # set_manual_record: True when the upsert inserted, False when it edited


def insert_reported_record(
    conn: Connection, *, account_id: int, import_run_id: int, balance_on: date, balance: int
) -> int:
    """Write the run's reported record (at most one per run, enforced by the schema).

    Runs in the caller's (ingest) transaction under the account lock; the caller recomputes after.
    The record's date is checked against the run's coverage by the caller (I36).
    """
    return int(
        conn.execute(
            text(
                "INSERT INTO balance_record (account_id, kind, import_run_id, balance, currency, balance_on) "
                "SELECT id, 'reported', :run, :bal, currency, :on FROM account WHERE id = :a RETURNING id"
            ),
            {"a": account_id, "run": import_run_id, "bal": balance, "on": balance_on},
        ).scalar_one()
    )


def set_manual_record(
    engine: Engine, account_id: int, balance_on: date, balance: int, *, user_id: int | None = None
) -> RecordResult:
    """Set the balance at the end of `balance_on`; a date that already has a manual record edits it.

    `user_id` is accepted for the caller's audit trail; records carry no author (spec §3.2).
    """
    record_id, created = retry_on_deadlock(lambda: _set(engine, account_id, balance_on, balance))
    return RecordResult(record_id, settle(engine), created)


def update_manual_record(
    engine: Engine, record_id: int, *, balance: int, balance_on: date | None = None
) -> RecordResult:
    """Edit a manual record's balance and, optionally, its date."""
    retry_on_deadlock(lambda: _update(engine, record_id, balance, balance_on))
    return RecordResult(record_id, settle(engine))


def delete_record(engine: Engine, record_id: int) -> RecordResult:
    """Delete any record, reported or manual; its derived entry goes with it (a reported record's
    run keeps its coverage)."""
    retry_on_deadlock(lambda: _delete(engine, record_id))
    return RecordResult(record_id, settle(engine))


def _locked_record_account(conn: Connection, record_id: int) -> int:
    """Settle shared, then the account's lock; the record is read again under it."""
    lock_settle_shared(conn)
    account = conn.execute(
        text("SELECT account_id FROM balance_record WHERE id = :i"), {"i": record_id}
    ).scalar_one_or_none()
    if account is None:
        raise RecordNotFound(record_id)
    lock_accounts(conn, [int(account)])
    return int(account)


def _set(engine: Engine, account_id: int, balance_on: date, balance: int) -> tuple[int, bool]:
    with engine.begin() as conn:
        lock_settle_shared(conn)
        lock_accounts(conn, [account_id])
        if conn.execute(text("SELECT 1 FROM account WHERE id = :a"), {"a": account_id}).first() is None:
            raise AccountMissing(account_id)
        # xmax is 0 on a row this statement inserted, not on one it updated
        row = conn.execute(
            text(
                "INSERT INTO balance_record (account_id, kind, balance, currency, balance_on) "
                "SELECT id, 'manual', :bal, currency, :on FROM account WHERE id = :a "
                "ON CONFLICT (account_id, balance_on) WHERE kind = 'manual' "
                "DO UPDATE SET balance = EXCLUDED.balance RETURNING id, (xmax = 0) AS created"
            ),
            {"a": account_id, "bal": balance, "on": balance_on},
        ).one()
        recompute_derived(conn, account_id)
        return int(row.id), bool(row.created)


def _update(engine: Engine, record_id: int, balance: int, balance_on: date | None) -> None:
    with engine.begin() as conn:
        account = _locked_record_account(conn, record_id)
        row = conn.execute(
            text("SELECT kind, balance_on FROM balance_record WHERE id = :i"), {"i": record_id}
        ).one_or_none()
        if row is None:
            raise RecordNotFound(record_id)
        if row.kind != "manual":
            raise ReportedRecordNotEditable(record_id)
        new_date = row.balance_on if balance_on is None else balance_on
        clash = conn.execute(
            text(
                "SELECT 1 FROM balance_record WHERE account_id = :a AND kind = 'manual' "
                "AND balance_on = :on AND id <> :i"
            ),
            {"a": account, "on": new_date, "i": record_id},
        ).first()
        if clash is not None:
            raise RecordDateTaken(account, new_date)
        conn.execute(
            text("UPDATE balance_record SET balance = :b, balance_on = :on WHERE id = :i"),
            {"b": balance, "on": new_date, "i": record_id},
        )
        recompute_derived(conn, account)


def _delete(engine: Engine, record_id: int) -> None:
    with engine.begin() as conn:
        account = _locked_record_account(conn, record_id)
        deleted = conn.execute(text("DELETE FROM balance_record WHERE id = :i"), {"i": record_id}).rowcount
        if deleted == 0:
            raise RecordNotFound(record_id)
        recompute_derived(conn, account)
