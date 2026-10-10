"""The entry a source row gets (I3), shared by ingest and 'not a duplicate' (spec §5.6)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Connection, text


def insert_entries(conn: Connection, source_ids: Sequence[int]) -> list[int]:
    """One entry per source row, in one set-based statement (I3): amount, account, currency and
    dates copied; type, category and derivation left to settling. Returns the new entries' ids,
    in ascending source-row order."""
    if not source_ids:
        return []
    return [
        int(i)
        for i in conn.execute(
            text(
                "INSERT INTO ledger_entry (source_transaction_id, account_id, amount, currency,"
                " booked_on, value_on) SELECT id, account_id, amount, currency, booked_on, value_on"
                " FROM source_transaction WHERE id = ANY(:ids) ORDER BY id RETURNING id"
            ),
            {"ids": list(source_ids)},
        ).scalars()
    ]


def insert_entry(conn: Connection, source_id: int) -> int:
    """The one entry of a source row (I3). Returns the new entry's id."""
    (entry_id,) = insert_entries(conn, [source_id])
    return entry_id
