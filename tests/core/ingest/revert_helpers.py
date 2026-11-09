"""Builders for the revert tests: committed runs with rows, entries and a reported balance.

Written with direct SQL so they do not depend on the ingest signature. Every run gets a later
`finished_at` than the one before (the order ingest wrote them), unless a test says otherwise.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.balance.derived import recompute_derived
from tests.invariants.helpers import make_balance_record, make_entry, make_source, pair

BASE = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
D = date(2026, 3, 10)


def day(n: int) -> date:
    """March 2026, day `n`."""
    return date(2026, 3, n)


@dataclass
class Run:
    id: int
    sources: list[int] = field(default_factory=list)
    entries: list[int] = field(default_factory=list)
    record: int | None = None


@dataclass
class World:
    """Checking (the revert target) and Savings, committed on a clone database."""

    engine: Engine
    checking: int
    savings: int
    _tick: int = 0

    def tx(self, fn: Callable[[Connection], Any]) -> Any:
        with self.engine.begin() as conn:
            return fn(conn)

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def one(self, sql: str, **params: Any) -> Any:
        return self.q(sql, **params)[0]

    def run(
        self,
        movements: list[tuple[int, date]] | None = None,
        *,
        account: int | None = None,
        through: date = date(2026, 3, 14),
        balance: tuple[date, int] | None = None,
        status: str = "ok",
        finished_at: datetime | None = None,
    ) -> Run:
        """A committed transaction run: one row and entry per `(amount, booked_on)`, then the
        run's reported record (`(balance_on, balance)`) with the derived entries recomputed."""
        acct = self.checking if account is None else account
        self._tick += 1
        finished = finished_at or BASE + timedelta(minutes=self._tick)

        def make(c: Connection) -> Run:
            cols = {"status": status, "a": acct, "f": None if status == "running" else finished}
            if status in ("ok", "reverted"):
                cols["t"] = through
            run_id = int(
                c.execute(
                    text(
                        "INSERT INTO import_run (importer, emits, account_id, status, finished_at,"
                        " covered_through, reverted_at) VALUES ('test', 'transactions', :a, :status, :f,"
                        " :t, CASE WHEN CAST(:status AS text) = 'reverted' THEN CAST(:f AS timestamptz) END)"
                        " RETURNING id"
                    ),
                    {"t": cols.get("t"), **cols},
                ).scalar_one()
            )
            out = Run(run_id)
            for amount, booked in movements or []:
                src = make_source(c, acct, run_id=run_id, amount=amount, booked_on=booked)
                out.sources.append(src)
                out.entries.append(make_entry(c, src))
            if balance is not None:
                out.record = make_balance_record(
                    c, acct, balance_on=balance[0], balance=balance[1], run_id=run_id
                )
            recompute_derived(c, acct)
            return out

        return self.tx(make)  # type: ignore[no-any-return]

    def derived(self, account: int | None = None) -> list[tuple[str, date, int]]:
        """(type, booked_on, amount) of the account's derived entries, oldest first."""
        acct = self.checking if account is None else account
        return [
            (r.type, r.booked_on, r.amount)
            for r in self.q(
                "SELECT type, booked_on, amount FROM ledger_entry WHERE account_id = :a"
                " AND source_transaction_id IS NULL AND balance_record_id IS NOT NULL ORDER BY booked_on, id",
                a=acct,
            )
        ]

    def count(self, table: str) -> int:
        return int(self.q(f"SELECT count(*) FROM {table}")[0][0])  # noqa: S608

    def status(self, run_id: int) -> str:
        return str(self.one("SELECT status FROM import_run WHERE id = :i", i=run_id).status)

    def state(self) -> dict[str, list[Any]]:
        """Everything a revert may touch, for 'nothing was written' and 'same as before' checks."""
        return {
            "runs": self.q("SELECT id, status, reverted_at, reverted_by FROM import_run ORDER BY id"),
            "sources": self.q("SELECT id, import_run_id, duplicate_of FROM source_transaction ORDER BY id"),
            "entries": self.q(
                "SELECT id, version, source_transaction_id, balance_record_id, amount, type, booked_on,"
                " counterpart_entry_id, counter_account_id FROM ledger_entry ORDER BY id"
            ),
            "records": self.q("SELECT id, balance_on, balance FROM balance_record ORDER BY id"),
        }

    def assert_checks_clean(self) -> None:
        views = [
            r[0]
            for r in self.q(
                "SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_check_%'"
            )
        ]
        assert views, "no integrity views found"
        for v in views:
            bad = self.q(f"SELECT * FROM {v}")  # noqa: S608
            assert not bad, f"{v} reports {bad}"


def pair_key(pass_: str = "matcher_decision") -> str:
    """A counter-account derivation as a pair sets it (spec §5.7)."""
    return json.dumps({"counter_account": {"pass": pass_, "basis": {"from": "counterpart"}}})


def add_duplicate(world: World, run: Run, of_source: int, *, amount: int, booked_on: date) -> int:
    """A row of `run` that duplicates `of_source` (marked by hand): no entry."""

    def make(c: Connection) -> int:
        account = c.execute(
            text("SELECT account_id FROM source_transaction WHERE id = :i"), {"i": of_source}
        ).scalar_one()
        src = make_source(
            c, account, run_id=run.id, amount=amount, booked_on=booked_on, duplicate_of=of_source
        )
        run.sources.append(src)
        return src

    return int(world.tx(make))


def transfer_to_savings(world: World, source: int, entry: int) -> int:
    """Pair imported `entry` (on checking) with a user-authored leg on savings; returns that leg's entry.
    Both counter-accounts were set by the pair, so unpairing clears them."""

    def make(c: Connection) -> int:
        amount = c.execute(text("SELECT amount FROM ledger_entry WHERE id = :e"), {"e": entry}).scalar_one()
        c.execute(
            text(
                "UPDATE ledger_entry SET type = 'transfer', counter_account_id = :s,"
                " derivation = CAST(:d AS jsonb), note = 'keep a' WHERE id = :e"
            ),
            {"s": world.savings, "d": pair_key(), "e": entry},
        )
        b_src = make_source(c, world.savings, importer=None, amount=-amount, booked_on=D)
        b = make_entry(
            c,
            b_src,
            type="transfer",
            counter_account_id=world.checking,
            derivation=pair_key("user"),
            description="in",
            note="keep b",
        )
        pair(c, entry, b)
        return b

    return int(world.tx(make))
