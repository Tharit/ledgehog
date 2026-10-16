"""The matching window (spec §5.7): a ledger-wide number of days.

Core never reads configuration (architecture §5.1): the engine sets `ledger.matching_window_days` on
every pooled connection, the way it sets `ledger.max_rate_age`, and core reads it back here.
"""

from __future__ import annotations

from sqlalchemy import Connection, text


def matching_window_days(conn: Connection) -> int:
    """The configured matching window in days. An unset setting is an error, never a default."""
    value = conn.execute(text("SELECT current_setting('ledger.matching_window_days')")).scalar_one()
    return int(value)


def document_window(conn: Connection) -> int:
    """The configured document window in days (spec §5.8), set like the matching window. An unset
    setting is an error, never a default."""
    value = conn.execute(text("SELECT current_setting('ledger.document_window_days')")).scalar_one()
    return int(value)
