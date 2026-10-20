"""The CSV export of the ledger list's filter (architecture §4.1, spec §8).

Every matching row in the list's order, dimensions joined by name, streamed in batches. It is an
escape hatch and a debugging tool: amounts stay in their own currency (no base-currency value:
only reporting converts), and nothing here writes.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Mapping
from typing import Any

from sqlalchemy import Connection, text

from app.core.ledger.entries import EntryRow, stream_entries
from app.core.ledger.filters import LedgerFilter
from app.core.ledger.lookups import list_categories

COLUMNS = (
    "id",
    "booked_on",
    "value_on",
    "account",
    "type",
    "amount",
    "currency",
    "category",
    "payee",
    "tags",
    "description",
    "note",
    "counter_account",
    "partner_id",
    "review_flags",
    "counterparty",
    "purpose",
    "instructed_amount",
    "instructed_currency",
    "importer",
)

_JOIN = "; "
_CATEGORY_SEP = " > "
# a spreadsheet executes a text cell that starts with one of these; an apostrophe makes it text
_FORMULA_STARTS = ("=", "+", "-", "@")


def decimal(minor: int, exponent: int) -> str:
    """Minor units as a point-decimal with the currency's own exponent, signed as stored."""
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 10**exponent)
    return f"{sign}{whole}.{frac:0{exponent}d}" if exponent else f"{sign}{whole}"


def guard(cell: str | None) -> str:
    """A text cell as written: empty for none, apostrophe-prefixed where a spreadsheet would run it."""
    if not cell:
        return ""
    return "'" + cell if cell.startswith(_FORMULA_STARTS) else cell


class _Names:
    """The names an entry's ids stand for, read once for the whole export."""

    def __init__(self, conn: Connection) -> None:
        self.accounts = _names(conn, "account")
        self.payees = _names(conn, "payee")
        self.tags = _names(conn, "tag")
        self.exponents = {
            str(r.code): int(r.minor_units)
            for r in conn.execute(text("SELECT code, minor_units FROM currency"))
        }
        by_id = {c.id: c for c in list_categories(conn)}
        self.categories: dict[int, str] = {}
        for cid in by_id:
            path: list[str] = []
            node = by_id.get(cid)
            while node is not None:
                path.append(node.name)
                node = by_id.get(node.parent_id) if node.parent_id is not None else None
            self.categories[cid] = _CATEGORY_SEP.join(reversed(path))


def _names(conn: Connection, table: str) -> dict[int, str]:
    rows: Any = conn.execute(text(f"SELECT id, name FROM {table}"))  # noqa: S608  (a fixed table name)
    return {int(r.id): str(r.name) for r in rows}


def _opt(names: Mapping[int, str], key: int | None) -> str:
    return "" if key is None else guard(names.get(key))


def _row(e: EntryRow, n: _Names) -> list[str]:
    src = e.source
    instructed = src is not None and src.instructed_amount is not None and src.instructed_currency is not None
    return [
        str(e.id),
        e.booked_on.isoformat(),
        e.value_on.isoformat() if e.value_on else "",
        guard(n.accounts.get(e.account_id)),
        guard(e.type),
        decimal(e.amount, n.exponents[e.currency]),
        e.currency,
        _opt(n.categories, e.category_id),
        _opt(n.payees, e.payee_id),
        guard(_JOIN.join(sorted(n.tags[t] for t in e.tag_ids))),
        guard(e.description),
        guard(e.note),
        _opt(n.accounts, e.counter_account_id),
        "" if e.counterpart_entry_id is None else str(e.counterpart_entry_id),
        guard(_JOIN.join(e.review_flags)),
        guard(src.counterparty_name) if src else "",
        guard(src.purpose) if src else "",
        decimal(src.instructed_amount, n.exponents[src.instructed_currency])  # type: ignore[arg-type, index]
        if instructed and src
        else "",
        (src.instructed_currency or "") if instructed and src else "",
        guard(e.importer),
    ]


def _format(rows: list[list[str]]) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def export_csv(conn: Connection, flt: LedgerFilter, *, batch: int = 500) -> Iterator[str]:
    """The header, then every entry matching `flt` in the list's order, as chunks of CSV text.

    RFC 4180 quoting, `\\n` line ends, no BOM.
    """
    names = _Names(conn)
    yield _format([list(COLUMNS)])
    for entries in stream_entries(conn, flt, batch=batch):
        yield _format([_row(e, names) for e in entries])
