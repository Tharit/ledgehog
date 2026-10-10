"""Fixtures for the duplicate and removal tests: committed ledgers on a clone DB."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, Engine, text

from tests.invariants.helpers import make_entry, make_source, pair

DAY = date(2026, 3, 10)


def pair_key(pass_: str = "matcher_decision") -> str:
    """A counter-account key as a pair sets it (spec §5.7)."""
    return json.dumps({"counter_account": {"pass": pass_, "basis": {"from": "counterpart"}}})


@dataclass
class Ledger:
    """One committed ledger: a checking account with a run, a savings account, helpers to query."""

    engine: Engine
    checking: int
    savings: int
    run: int

    def tx(self, fn: Callable[[Connection], Any]) -> Any:
        with self.engine.begin() as conn:
            return fn(conn)

    def movement(self, **kw: Any) -> tuple[int, int]:
        """A committed source row with its one entry (a row without one cannot be committed)."""
        kw.setdefault("run_id", self.run)
        kw.setdefault("amount", -1000)
        kw.setdefault("booked_on", DAY)
        account = kw.pop("account", self.checking)

        def make(c: Connection) -> tuple[int, int]:
            src = make_source(c, account, **kw)
            return src, make_entry(c, src)

        return self.tx(make)  # type: ignore[no-any-return]

    def split(self, *amounts: int) -> tuple[int, list[int]]:
        """A committed source row whose entries are `amounts`."""

        def make(c: Connection) -> tuple[int, list[int]]:
            src = make_source(c, self.checking, run_id=self.run, amount=sum(amounts), booked_on=DAY)
            return src, [make_entry(c, src, amount=x) for x in amounts]

        return self.tx(make)  # type: ignore[no-any-return]

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def one(self, sql: str, **params: Any) -> Any:
        return self.q(sql, **params)[0]

    def mark_dup(self, conn: Connection, source_id: int, of: int | None = None) -> int:
        """What a legal caller does after `remove_entries`: the row now duplicates `of` (a fresh
        original on the same account when not given), in the same transaction."""
        if of is None:
            acct = conn.execute(
                text("SELECT account_id FROM source_transaction WHERE id = :i"), {"i": source_id}
            ).scalar_one()
            of = make_source(conn, acct, run_id=self.run, amount=-1, booked_on=DAY)
            make_entry(conn, of)
        conn.execute(
            text("UPDATE source_transaction SET duplicate_of = :o WHERE id = :s"),
            {"o": of, "s": source_id},
        )
        return int(of)

    def entries_of(self, source_id: int) -> list[int]:
        return [
            r.id
            for r in self.q(
                "SELECT id FROM ledger_entry WHERE source_transaction_id = :s ORDER BY id", s=source_id
            )
        ]

    def dup_of(self, source_id: int) -> int | None:
        return self.one("SELECT duplicate_of FROM source_transaction WHERE id = :i", i=source_id).duplicate_of

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

    def transfer_pair(self) -> tuple[int, int, int, int]:
        """A transfer pair: `a` (imported, checking) and the counter-leg `b` (user-authored,
        savings) a commit created. Both counter-accounts were set by the pair. Returns
        (a_source, a_entry, b_source, b_entry)."""

        def make(c: Connection) -> tuple[int, int, int, int]:
            a_src = make_source(c, self.checking, run_id=self.run, amount=-500, booked_on=DAY)
            a = make_entry(
                c,
                a_src,
                type="transfer",
                counter_account_id=self.savings,
                derivation=pair_key(),
                description="out",
                note="keep a",
            )
            b_src = make_source(c, self.savings, importer=None, amount=500, booked_on=DAY)
            b = make_entry(
                c,
                b_src,
                type="transfer",
                counter_account_id=self.checking,
                derivation=pair_key("user"),
                description="in",
                note="keep b",
            )
            pair(c, a, b)
            return a_src, a, b_src, b

        return self.tx(make)  # type: ignore[no-any-return]
