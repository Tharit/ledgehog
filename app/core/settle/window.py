"""The matching window (spec §5.7): a ledger-wide number of days, and the document window (§5.8): two.

Core never reads configuration (architecture §5.1): the engine sets `ledger.matching_window_days` on
every pooled connection, the way it sets `ledger.max_rate_age`, and core reads it back here.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.matching.documents import DocWindow


def matching_window_days(conn: Connection) -> int:
    """The configured matching window in days. An unset setting is an error, never a default."""
    value = conn.execute(text("SELECT current_setting('ledger.matching_window_days')")).scalar_one()
    return int(value)


def document_window(conn: Connection) -> DocWindow:
    """The configured document window (spec §5.8) as (back, ahead) days: a transaction matches a document
    dated within [booked_on - back, booked_on + ahead], and waits for one until booked_on + ahead. Set
    like the matching window; an unset setting is an error, never a default."""
    back, ahead = conn.execute(
        text(
            "SELECT current_setting('ledger.document_window_back_days'),"
            " current_setting('ledger.document_window_ahead_days')"
        )
    ).one()
    return DocWindow(int(back), int(ahead))
