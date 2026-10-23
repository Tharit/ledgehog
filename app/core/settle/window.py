"""The matching window (spec §5.7): a ledger-wide number of days, and the document window (§5.8): two
(`document_window`, read in `core/resolution/doc_load.py`, the unit CTE's home).

Core never reads configuration (architecture §5.1): the engine sets `ledger.matching_window_days` on
every pooled connection, the way it sets `ledger.max_rate_age`, and core reads it back here.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.resolution.doc_load import document_window


def matching_window_days(conn: Connection) -> int:
    """The configured matching window in days. An unset setting is an error, never a default."""
    value = conn.execute(text("SELECT current_setting('ledger.matching_window_days')")).scalar_one()
    return int(value)


__all__ = ["document_window", "matching_window_days"]
