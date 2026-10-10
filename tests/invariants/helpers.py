"""Row builders and assertions shared by the invariant and integrity-view tests.

The builders insert the minimum a constraint needs and return ids. They never
commit. Deferred constraint triggers fire at COMMIT, which a rollback-isolated
`db_conn` never reaches, so tests call `fire_deferred` (SET CONSTRAINTS ALL
IMMEDIATE) at the point where the commit would be.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

BOOKED = date(2026, 2, 10)
FINISHED = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)

# SQLSTATEs the schema raises
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
FK_VIOLATION = "23503"
RESTRICT_VIOLATION = "23001"  # ON DELETE RESTRICT (NO ACTION reports 23503)
NOT_NULL_VIOLATION = "23502"
RAISE_EXCEPTION = "P0001"  # RAISE EXCEPTION in a trigger function


@contextmanager
def rejects(
    conn: Connection,
    *,
    sqlstate: str,
    constraint: str | None = None,
    message: str | None = None,
) -> Iterator[None]:
    """The block must fail with this SQLSTATE (and constraint name / message part).

    Runs in a savepoint, so the outer transaction stays usable. Put `fire_deferred`
    inside the block for deferred triggers.
    """
    savepoint = conn.begin_nested()
    try:
        yield
    except DBAPIError as exc:
        savepoint.rollback()
        orig: Any = exc.orig
        assert orig.sqlstate == sqlstate, f"expected SQLSTATE {sqlstate}, got {orig.sqlstate}: {orig}"
        if constraint is not None:
            assert orig.diag.constraint_name == constraint, (
                f"expected constraint {constraint}, got {orig.diag.constraint_name}: {orig}"
            )
        if message is not None:
            assert message in str(orig.diag.message_primary), (
                f"expected {message!r} in {orig.diag.message_primary!r}"
            )
    else:
        savepoint.rollback()
        pytest.fail(f"expected a rejection (SQLSTATE {sqlstate}, {constraint or message}), got none")


def fire_deferred(conn: Connection) -> None:
    """Run every queued deferred constraint trigger now, as COMMIT would."""
    conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def scalar(conn: Connection, sql: str, **params: Any) -> Any:
    return conn.execute(text(sql), params).scalar_one()


def rows(conn: Connection, sql: str, **params: Any) -> list[Any]:
    return list(conn.execute(text(sql), params).all())


def _insert(conn: Connection, table: str, cols: dict[str, Any]) -> int:
    names = ", ".join(cols)
    marks = ", ".join(f":{c}" for c in cols)
    return int(
        conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({marks}) RETURNING id"), cols).scalar_one()  # noqa: S608
    )


def make_instance(conn: Connection, *, importer: str = "test", external_id: str | None = None) -> int:
    return _insert(
        conn,
        "importer_instance",
        {
            "importer": importer,
            "label": f"{importer} instance",
            "access": "shared",
            "external_id": external_id,
        },
    )


def link_account(
    conn: Connection, account_id: int, instance_id: int, external_ref: str | None = None
) -> None:
    conn.execute(
        text(
            "INSERT INTO account_source (account_id, importer_instance_id, external_ref) VALUES (:a, :i, :r)"
        ),
        {"a": account_id, "i": instance_id, "r": external_ref or uuid.uuid4().hex},
    )


def make_run(
    conn: Connection,
    account_id: int,
    *,
    status: str = "ok",
    covered_through: date | None = date(2026, 3, 1),
    instance_id: int | None = None,
) -> int:
    cols: dict[str, Any] = {
        "importer": "test",
        "importer_instance_id": instance_id,
        "emits": "transactions",
        "account_id": account_id,
        "status": status,
    }
    if status in ("ok", "reverted"):
        cols["covered_through"] = covered_through
    if status != "running":
        cols["finished_at"] = FINISHED
    if status == "reverted":
        cols["reverted_at"] = FINISHED
    run_id = _insert(conn, "import_run", cols)
    return run_id


def make_source(
    conn: Connection,
    account_id: int,
    *,
    amount: int = -1000,
    currency: str = "EUR",
    booked_on: date = BOOKED,
    value_on: date | None = None,
    importer: str | None = "test",
    run_id: int | None = None,
    instance_id: int | None = None,
    source_id: str | None = None,
    content_hash: str | None = None,
    duplicate_of: int | None = None,
    purpose: str | None = None,
) -> int:
    """A source_transaction. `importer=None` makes a user-authored row."""
    if importer is not None and run_id is None:
        run_id = make_run(conn, account_id, instance_id=instance_id)
    if content_hash is None and source_id is None:
        source_id = uuid.uuid4().hex
    return _insert(
        conn,
        "source_transaction",
        {
            "importer": importer,
            "importer_instance_id": instance_id,
            "import_run_id": run_id if importer is not None else None,
            "account_id": account_id,
            "source_id": source_id,
            "content_hash": content_hash,
            "source_format": "camt053" if importer is not None else None,
            "amount": amount,
            "currency": currency,
            "booked_on": booked_on,
            "value_on": value_on,
            "purpose": purpose,
            "raw": "{}",
            "duplicate_of": duplicate_of,
        },
    )


def make_entry(conn: Connection, source_id: int, *, amount: int | None = None, **cols: Any) -> int:
    """A movement entry of `source_id`, copying its account, currency and dates."""
    st = conn.execute(
        text(
            "SELECT account_id, currency, booked_on, value_on, amount FROM source_transaction WHERE id = :i"
        ),
        {"i": source_id},
    ).one()
    values: dict[str, Any] = {
        "source_transaction_id": source_id,
        "account_id": st.account_id,
        "currency": st.currency,
        "booked_on": st.booked_on,
        "value_on": st.value_on,
        "amount": st.amount if amount is None else amount,
        "type": "flow",
    }
    values.update(cols)
    return _insert(conn, "ledger_entry", values)


def make_movement(conn: Connection, account_id: int, **source_kw: Any) -> tuple[int, int]:
    """A source transaction with its single entry; returns (source_id, entry_id)."""
    source_id = make_source(conn, account_id, **source_kw)
    return source_id, make_entry(conn, source_id)


def make_category(conn: Connection, name: str, kind: str = "expense", parent_id: int | None = None) -> int:
    return _insert(conn, "category", {"name": name, "kind": kind, "parent_id": parent_id})


def make_balance_record(
    conn: Connection,
    account_id: int,
    *,
    balance_on: date,
    balance: int = 0,
    kind: str = "manual",
    run_id: int | None = None,
    currency: str = "EUR",
) -> int:
    return _insert(
        conn,
        "balance_record",
        {
            "account_id": account_id,
            "kind": kind,
            "import_run_id": run_id,
            "balance": balance,
            "currency": currency,
            "balance_on": balance_on,
        },
    )


def make_derived_entry(
    conn: Connection,
    account_id: int,
    record_id: int,
    *,
    type: str,
    booked_on: date,
    amount: int = 5000,
    currency: str = "EUR",
) -> int:
    return _insert(
        conn,
        "ledger_entry",
        {
            "account_id": account_id,
            "balance_record_id": record_id,
            "type": type,
            "amount": amount,
            "currency": currency,
            "booked_on": booked_on,
        },
    )


def pair(conn: Connection, a: int, b: int) -> None:
    """Make two transfer entries each other's counterpart, in one statement."""
    conn.execute(
        text(
            "UPDATE ledger_entry SET counterpart_entry_id = CASE id WHEN :a THEN :b ELSE :a END "
            "WHERE id IN (:a, :b)"
        ),
        {"a": a, "b": b},
    )


@dataclass(frozen=True)
class Clean:
    """Ids of the clean dataset built by `seed_clean`."""

    checking: int
    savings: int
    depot: int
    run: int
    m1: int  # source with one entry
    m1_entry: int
    dup: int  # duplicate of m1
    split: int  # source with two entries
    spare: int  # plain source with one entry, for violations
    transfer_a: int  # paired transfer entries
    transfer_b: int
    opening: int  # checking: derived entry of the anchor (manual record)
    reported_record: int  # checking: reported record of `run`
    reconciliation: int  # its derived entry
    valuation: int  # depot


def seed_clean(conn: Connection, make_account: Any) -> Clean:
    """A small ledger that satisfies every invariant and every v_check_* view.

    Built through the real triggers and validated by firing the deferred ones, so
    it doubles as proof that the good state is accepted.
    """
    checking = make_account(conn, name="Checking")
    savings = make_account(conn, name="Savings", kind="savings")
    depot = make_account(conn, name="Depot", kind="depot")

    run = make_run(conn, checking, covered_through=date(2026, 3, 1))
    m1 = make_source(conn, checking, run_id=run, amount=-1000, booked_on=date(2026, 2, 10))
    m1_entry = make_entry(conn, m1)
    dup = make_source(conn, checking, run_id=run, amount=-1000, booked_on=date(2026, 2, 10), duplicate_of=m1)
    split = make_source(conn, checking, run_id=run, amount=-3000, booked_on=date(2026, 2, 11))
    make_entry(conn, split, amount=-1000)
    make_entry(conn, split, amount=-2000)
    spare, _ = make_movement(conn, checking, run_id=run, amount=-700, booked_on=date(2026, 2, 13))

    ta_src = make_source(conn, checking, run_id=run, amount=-500, booked_on=date(2026, 2, 12))
    ta = make_entry(conn, ta_src, type="transfer", counter_account_id=savings)
    tb_src = make_source(conn, savings, amount=500, booked_on=date(2026, 2, 12))
    tb = make_entry(conn, tb_src, type="transfer", counter_account_id=checking)
    pair(conn, ta, tb)

    anchor = make_balance_record(conn, checking, balance_on=date(2026, 1, 1), balance=5000)
    opening = make_derived_entry(conn, checking, anchor, type="opening", booked_on=date(2026, 1, 1))
    reported = make_balance_record(
        conn, checking, balance_on=date(2026, 3, 1), balance=3000, kind="reported", run_id=run
    )
    reconciliation = make_derived_entry(
        conn, checking, reported, type="reconciliation", booked_on=date(2026, 3, 1), amount=1
    )

    d0 = make_balance_record(conn, depot, balance_on=date(2026, 1, 1), balance=10000)
    make_derived_entry(conn, depot, d0, type="opening", booked_on=date(2026, 1, 1), amount=10000)
    d1 = make_balance_record(conn, depot, balance_on=date(2026, 2, 1), balance=11000)
    valuation = make_derived_entry(conn, depot, d1, type="valuation", booked_on=date(2026, 2, 1), amount=1000)

    fire_deferred(conn)
    return Clean(
        checking=checking,
        savings=savings,
        depot=depot,
        run=run,
        m1=m1,
        m1_entry=m1_entry,
        dup=dup,
        split=split,
        spare=spare,
        transfer_a=ta,
        transfer_b=tb,
        opening=opening,
        reported_record=reported,
        reconciliation=reconciliation,
        valuation=valuation,
    )
