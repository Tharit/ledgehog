"""Building units in the database for the units tests (rolled-back `db_conn`; triggers stay deferred)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from tests.invariants.helpers import make_category, make_entry, make_source, pair

D = date(2026, 3, 10)


def keys(**passes: str) -> str:
    return json.dumps({k: {"pass": v} for k, v in passes.items()})


class Bench:
    """Two accounts and a category; every method adds rows and returns ids."""

    def __init__(self, conn: Connection, make_account: Any) -> None:
        self.conn = conn
        self.a = make_account(conn, name="A")
        self.b = make_account(conn, name="B")
        self.cat = make_category(conn, "Food")
        self._each: dict[int, int] = {}

    def source(
        self,
        account: int | None = None,
        *,
        on: date = D,
        amount: int = -100,
        parts: int = 1,
        authored: bool = False,
    ) -> int:
        """An imported (or `authored`) source of `parts` entries of `amount` each (a split sums to it)."""
        src = make_source(
            self.conn,
            account or self.a,
            booked_on=on,
            amount=amount * parts,
            importer=None if authored else "test",
        )
        self._each[src] = amount
        return src

    def flow(self, src: int, *, amount: int | None = None, done: bool = True, **cols: Any) -> int:
        """A flow of `src`: categorised (complete) unless `done` is False."""
        if done:
            cols.setdefault("category_id", self.cat)
        return make_entry(self.conn, src, amount=self._each[src] if amount is None else amount, **cols)

    def transfer(self, src: int, **cols: Any) -> int:
        return make_entry(self.conn, src, amount=self._each[src], type="transfer", **cols)

    def pair(self, x: int, y: int) -> None:
        """Pair two transfer legs the way the commit does: counter-accounts are the partners' accounts."""
        self.conn.execute(
            text(
                "UPDATE ledger_entry AS e SET counter_account_id = o.account_id"
                "  FROM ledger_entry AS o"
                " WHERE (e.id, o.id) IN ((:x, :y), (:y, :x))"
            ),
            {"x": x, "y": y},
        )
        pair(self.conn, x, y)
