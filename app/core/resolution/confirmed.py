"""Which entries are confirmed (spec §6, I20, I22), derived from columns and keys, never from stored flags.

Until units exist (step 8 joins the two legs of a pair) a unit is the entries of one source
transaction, and it is confirmed when every entry of it is complete and carries only standing keys:

* a type; for a flow a category (spec §3.4); for a transfer its pair (`counterpart_entry_id`, I22,
  so before pairing exists a transfer is never confirmed);
* no derivation key whose pass is not standing (`history`, `llm`, `matcher_proposal`, or a key
  without a pass).

This is exactly "no `unconfirmed` and no `unclassified` flag and a type", plus the pair for a
transfer, plus the unit. It is computed here rather than read from `review_flags` so that it is
right in the middle of a settle, where the flags are not yet rewritten and a new entry's empty
default would otherwise read as clean. Derived entries (balance records) have no source
transaction and are never part of it.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.plugins.classifier import STANDING_PASSES

STANDING = sorted(STANDING_PASSES)

# One row per movement entry: its id, unit (source transaction), `unit_ok` (the unit is confirmed)
# and `first_id` (the lowest entry id of its source transaction: the original entry of a split).
# `{scope}` narrows to the units of given entries, or to all.
_UNITS = """
    SELECT m.id, m.src,
           bool_and(m.ok) OVER (PARTITION BY m.src) AS unit_ok,
           min(m.id) OVER (PARTITION BY m.src) AS first_id
      FROM (
            SELECT le.id, le.source_transaction_id AS src,
                   (le.type IS NOT NULL
                    AND (le.type <> 'flow' OR le.category_id IS NOT NULL)
                    AND (le.type <> 'transfer' OR le.counterpart_entry_id IS NOT NULL)
                    AND NOT EXISTS (
                        SELECT 1 FROM jsonb_each(le.derivation) AS k
                         WHERE COALESCE(k.value ->> 'pass', '') <> ALL (:standing))) AS ok
              FROM ledger_entry AS le
             WHERE le.source_transaction_id IS NOT NULL{scope}
           ) AS m
"""

_ALL = ""
_OF_ENTRIES = (
    " AND le.source_transaction_id IN"
    " (SELECT x.source_transaction_id FROM ledger_entry AS x WHERE x.id = ANY(:ids))"
)


def units_sql(*, of_entries: bool = False) -> str:
    """The `units` CTE body (see above); bind `standing` (and `ids` when `of_entries`)."""
    return _UNITS.format(scope=_OF_ENTRIES if of_entries else _ALL)


_CONFIRMED_IDS = text(f"SELECT u.id FROM ({units_sql()}) AS u WHERE u.unit_ok")


def load_confirmed_ids(conn: Connection) -> set[int]:
    """The ids of every confirmed movement entry."""
    return {int(i) for i in conn.execute(_CONFIRMED_IDS, {"standing": STANDING}).scalars()}
