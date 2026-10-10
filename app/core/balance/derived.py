"""Derived entries and balance records: `core/balance` is their only writer (architecture §5.1)."""

from __future__ import annotations

from sqlalchemy import Connection


def recompute_derived(conn: Connection, account_id: int) -> None:
    """Step 4 hook: derived entries and balance records of the account are recomputed here."""
