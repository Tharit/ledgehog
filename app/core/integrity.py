"""The integrity check (architecture §4.1, schema §9): every `v_check_*` view, read as rows.

The views are discovered from the catalog, so a view added to the schema is reported without
touching this module. Each should be empty; a row names an offender. Rows are returned as
JSON-ready dicts (dates ISO, numerics as integers, anything else as text), capped per view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class ViewCheck:
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class IntegrityReport:
    checks: dict[str, ViewCheck]

    @property
    def ok(self) -> bool:
        return all(not c.rows for c in self.checks.values())


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return str(value)


def check_integrity(conn: Connection, *, limit: int = 50) -> IntegrityReport:
    """Read every `v_check_*` view, at most `limit` rows each (`truncated` when there were more)."""
    names = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT viewname FROM pg_views WHERE schemaname = current_schema() "
                "AND viewname LIKE 'v\\_check\\_%' ORDER BY viewname"
            )
        )
    ]
    checks: dict[str, ViewCheck] = {}
    for name in names:
        fetched = conn.execute(text(f'SELECT * FROM "{name}" LIMIT :n'), {"n": limit + 1}).mappings().all()  # noqa: S608
        rows = [{k: _plain(v) for k, v in r.items()} for r in fetched[:limit]]
        checks[name] = ViewCheck(rows, truncated=len(fetched) > limit)
    return IntegrityReport(checks)
