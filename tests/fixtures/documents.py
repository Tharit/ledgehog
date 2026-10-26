"""A stored document, for the tests that read documents (documents carry no entry)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from tests.invariants.helpers import _insert


def make_document(
    conn: Connection,
    provider: str = "paypal",
    *,
    total: int = -1000,
    on: date = date(2026, 3, 10),
    currency: str = "EUR",
    external_id: str | None = None,
) -> int:
    cols: dict[str, Any] = {
        "provider": provider,
        "external_id": external_id
        or f"d{conn.execute(text('SELECT count(*) FROM external_document')).scalar_one()}",
        "occurred_on": on,
        "total": total,
        "currency": currency,
        "raw": "{}",
    }
    return _insert(conn, "external_document", cols)
