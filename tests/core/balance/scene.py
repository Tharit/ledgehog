"""A small ledger on one account, for the derived-entry tests (rolled-back `db_conn`)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.core.balance.derived import recompute_derived
from tests.invariants.helpers import (
    fire_deferred,
    make_balance_record,
    make_entry,
    make_run,
    make_source,
    rows,
)

FAR = date(2030, 1, 1)


def day(month: int, d: int, year: int = 2026) -> date:
    return date(year, month, d)


def assert_checks_clean(conn: Connection) -> None:
    """Every v_check_* view is empty and the deferred triggers pass."""
    fire_deferred(conn)
    views = [
        r[0]
        for r in conn.execute(
            text("SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_check_%'")
        )
    ]
    assert views, "no integrity views found"
    for v in views:
        bad = list(conn.execute(text(f"SELECT * FROM {v}")).all())  # noqa: S608
        assert not bad, f"{v} reports {bad}"


class Scene:
    def __init__(
        self, conn: Connection, make_account: Callable[..., int], *, kind: str = "checking", name: str = "A"
    ) -> None:
        self.conn = conn
        self.account = make_account(conn, name=name, kind=kind)

    def move(self, on: date, amount: int) -> int:
        """A movement entry (a source transaction with its one entry)."""
        src = make_source(self.conn, self.account, amount=amount, booked_on=on)
        return make_entry(self.conn, src)

    def manual(self, on: date, balance: int) -> int:
        return make_balance_record(self.conn, self.account, balance_on=on, balance=balance)

    def reported(self, on: date, balance: int, *, run_id: int | None = None) -> int:
        run = run_id or make_run(self.conn, self.account, covered_through=max(on, FAR))
        return make_balance_record(
            self.conn, self.account, balance_on=on, balance=balance, run_id=run
        )

    def recompute(self) -> None:
        recompute_derived(self.conn, self.account)

    def derived(self) -> list[tuple[str, date, int]]:
        """(type, booked_on, amount) of the account's derived entries, by date then id."""
        return [
            (r.type, r.booked_on, r.amount)
            for r in self.conn.execute(
                text(
                    "SELECT type, booked_on, amount FROM ledger_entry "
                    "WHERE account_id = :a AND balance_record_id IS NOT NULL ORDER BY booked_on, id"
                ),
                {"a": self.account},
            )
        ]

    def derived_of(self, record_id: int) -> tuple[str, date, int] | None:
        r = self.conn.execute(
            text("SELECT type, booked_on, amount FROM ledger_entry WHERE balance_record_id = :r"),
            {"r": record_id},
        ).first()
        return None if r is None else (r.type, r.booked_on, r.amount)

    def snapshot(self) -> list[Any]:
        """Every derived row with its id, version and physical row version (xmin)."""
        return rows(
            self.conn,
            "SELECT id, balance_record_id, type, booked_on, amount, version, xmin::text AS x "
            "FROM ledger_entry WHERE account_id = :a AND balance_record_id IS NOT NULL ORDER BY id",
            a=self.account,
        )

    def check(self) -> None:
        assert_checks_clean(self.conn)


def prev(d: date) -> date:
    return d - timedelta(days=1)
