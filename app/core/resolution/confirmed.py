"""Which entries are confirmed (spec §6, I20, I22, I31), from columns and keys, never from stored flags.

A UNIT is the entries of one source transaction plus, when one of them is a transfer leg that is
paired, the entries of the partner's source transaction. A source holds at most one transfer entry (I31,
`ux_le_one_transfer_per_source`) and a pair has exactly two legs (`ux_le_counterpart`,
`trg_transfer_pair`), so a unit is a source or a pair of them and never a chain: one step finds it. The
unit key of an entry is the lowest source id among its own source and its partner's, taken over every
entry of its source (so the siblings of a transfer leg share its key).

A unit is confirmed when every entry of it is complete and carries only standing keys:

* a type; for a flow a category (spec §3.4); for a transfer its pair (`counterpart_entry_id`, I22,
  so an unpaired transfer is never confirmed);
* no derivation key whose pass is not standing (`history`, `llm`, or a key without a pass).

This is computed here rather than read from `review_flags` so that it is right in the middle of a
settle, where the flags are not yet rewritten and a new entry's empty default would otherwise read as
clean. Derived entries (balance records) have no source transaction and are in no unit.
`app/core/units/state.py` is the same judgement in pure Python, pinned to this SQL by a test.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.plugins.classifier import STANDING_PASSES
from app.core.resolution.entry_state import COMPLETE
from app.core.resolution.entry_state import STANDING as STANDING_SQL

STANDING = sorted(STANDING_PASSES)

# One row per movement entry: its id, source, `unit_key` (the unit), `unit_ok` (the unit is
# confirmed), `unit_has_nonstanding` (some entry of the unit carries a key that awaits a human: what
# `unconfirmed` means) and `first_id` (the lowest entry id of its SOURCE transaction: the original entry
# of a split, I31). `{scope}` narrows to the units of given entries, or to all.
_UNITS = """
    SELECT m.id, m.src, m.unit_key,
           bool_and(m.complete AND m.standing) OVER (PARTITION BY m.unit_key) AS unit_ok,
           bool_or(NOT m.standing) OVER (PARTITION BY m.unit_key) AS unit_has_nonstanding,
           min(m.id) OVER (PARTITION BY m.src) AS first_id
      FROM (
            SELECT k.id, k.src, k.complete, k.standing,
                   min(k.direct_key) OVER (PARTITION BY k.src) AS unit_key
              FROM (
                    SELECT le.id, le.source_transaction_id AS src,
                           LEAST(le.source_transaction_id,
                                 COALESCE(p.source_transaction_id, le.source_transaction_id)) AS direct_key,
                           {complete} AS complete,
                           {standing_sql} AS standing
                      FROM ledger_entry AS le
                      LEFT JOIN ledger_entry AS p ON p.id = le.counterpart_entry_id
                     WHERE le.source_transaction_id IS NOT NULL{scope}
                   ) AS k
           ) AS m
"""

_ALL = ""
# the sources of the given entries and of the partners of the transfer legs in those sources
_OF_ENTRIES = """
       AND le.source_transaction_id IN (
            SELECT x.source_transaction_id FROM ledger_entry AS x WHERE x.id = ANY(:ids)
            UNION
            SELECT q.source_transaction_id
              FROM ledger_entry AS x
              JOIN ledger_entry AS t ON t.source_transaction_id = x.source_transaction_id
              JOIN ledger_entry AS q ON q.id = t.counterpart_entry_id
             WHERE x.id = ANY(:ids))
"""


def units_sql(*, of_entries: bool = False) -> str:
    """The `units` CTE body (see above); bind `units_binds(conn)` (and `ids` when `of_entries`)."""
    return _UNITS.format(
        scope=_OF_ENTRIES if of_entries else _ALL,
        complete=COMPLETE,
        standing_sql=STANDING_SQL,
    )


def units_binds(conn: Connection) -> dict[str, object]:
    """The binds every execution of `units_sql` needs besides `ids`: the standing passes."""
    return {"standing": STANDING}


_CONFIRMED_IDS = text(f"SELECT u.id FROM ({units_sql()}) AS u WHERE u.unit_ok")


def load_confirmed_ids(conn: Connection) -> set[int]:
    """The ids of every confirmed movement entry."""
    return {int(i) for i in conn.execute(_CONFIRMED_IDS, units_binds(conn)).scalars()}
