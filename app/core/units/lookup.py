"""Finding a unit in the database (the reads `closure.py` cannot do): keys of sources, entries of a unit.

The SQL twin of `closure.py` for single lookups (indexed: `ix_le_source`, `ux_le_counterpart`). The
set-based judgement of every unit at once is the CTE in `core/resolution/confirmed.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, text

# one transfer entry per source (I31) and one partner per leg: at most one row per source
_PAIRED_SOURCES = text(
    "SELECT t.source_transaction_id AS src, q.source_transaction_id AS partner_src"
    "  FROM ledger_entry AS t"
    "  JOIN ledger_entry AS q ON q.id = t.counterpart_entry_id"
    " WHERE t.source_transaction_id = ANY(:srcs)"
)

_UNIT_OF_ENTRY = text(
    """
    WITH me AS (SELECT source_transaction_id AS src FROM ledger_entry WHERE id = :id),
         srcs AS (
              SELECT src FROM me WHERE src IS NOT NULL
              UNION
              SELECT q.source_transaction_id
                FROM ledger_entry AS t
                JOIN ledger_entry AS q ON q.id = t.counterpart_entry_id
               WHERE t.source_transaction_id = (SELECT src FROM me))
    SELECT (SELECT count(*) FROM me) AS found,
           (SELECT src FROM me) AS src,
           COALESCE((SELECT array_agg(e.id ORDER BY e.id)
                       FROM ledger_entry AS e
                      WHERE e.source_transaction_id IN (SELECT src FROM srcs)), '{}') AS ids,
           (SELECT min(src) FROM srcs) AS unit_key
    """
)


def unit_keys_of(conn: Connection, sources: Iterable[int]) -> dict[int, int]:
    """The unit key of each given source transaction: itself, or the lower id of its pair's two."""
    wanted = sorted(set(sources))
    if not wanted:
        return {}
    keys = {s: s for s in wanted}
    for r in conn.execute(_PAIRED_SOURCES, {"srcs": wanted}):
        keys[int(r.src)] = min(int(r.src), int(r.partner_src))
    return keys


@dataclass(frozen=True, slots=True)
class UnitIds:
    unit_key: int
    entry_ids: tuple[int, ...]  # ascending: the first is the anchor


def unit_ids_of(conn: Connection, entry_id: int) -> UnitIds | None:
    """The entries of the unit holding `entry_id`; None when there is no such entry or it is derived."""
    row = conn.execute(_UNIT_OF_ENTRY, {"id": entry_id}).one()
    if not row.found or row.src is None:
        return None
    return UnitIds(unit_key=int(row.unit_key), entry_ids=tuple(int(i) for i in row.ids))
