"""The entry a source row gets (I3), shared by ingest and 'not a duplicate' (spec §5.6)."""

from __future__ import annotations

from sqlalchemy import Connection, text


def insert_entry(conn: Connection, source_id: int) -> int:
    """The one entry of a source row (I3): amount, account, currency and dates copied; type,
    category and derivation left to settling. Returns the new entry's id."""
    return int(
        conn.execute(
            text(
                "INSERT INTO ledger_entry (source_transaction_id, account_id, amount, currency,"
                " booked_on, value_on) SELECT id, account_id, amount, currency, booked_on, value_on"
                " FROM source_transaction WHERE id = :id RETURNING id"
            ),
            {"id": source_id},
        ).scalar_one()
    )
