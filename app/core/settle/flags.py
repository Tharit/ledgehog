"""Review flags (spec §6, I23): derived from current state, rewritten wholesale.

One set-based statement computes the flags of every entry and writes only the rows whose stored
value differs, so settling twice touches nothing (I37). Tokens are stored sorted. Derived entries
(opening, valuation, reconciliation: `balance_record_id` set) are complete by construction, are in
no unit and never carry flags.

Produced: `unclassified`, `unconfirmed`, `waiting` and `unmatched_transfer`.

`waiting` and `unmatched_transfer` are per unpaired transfer leg (spec §5.7), from the leg's counter-
account C (under any key), `v_account_synced`, `v_account_coverage` and the matching window (the
`ledger.matching_window_days` setting): the leg is waiting iff C is set, synced, and its `synced_through`
is NULL or before `booked_on` plus the window; otherwise (C unsynced or closed, synced through the
window, or no C) it is unmatched. A paired leg has neither. `core/matching/states.py` is the same
judgement in Python, pinned to this SQL by a test.

The flags are judged over the UNIT (spec §6; the CTE of `core/resolution/confirmed.py`: the entries of
one source transaction and of a transfer pair):

* `unclassified` is the entry's own: no type, or a flow without a category.
* `unconfirmed` marks EVERY entry of a unit in which some entry carries a key that awaits a human (a
  proposal of `history`, `llm`, or a key without a pass): the complete sibling of
  such an entry, and the partner of such a leg, are unconfirmed with it. A unit that is merely incomplete
  (an unclassified sibling, an unpaired transfer) puts no `unconfirmed` on its complete entries; it is
  still not confirmed and is in the review queue, which reads the unit CTE rather than these flags.

An entry is confirmed iff its unit is: every entry complete, every transfer paired (I22) and no key but
standing ones. `review_flags_step` reports the entries that became confirmed since the last round (what
history learns from, and what keeps the rounds going).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.resolution.confirmed import load_confirmed_ids, units_binds, units_sql
from app.core.settle.run import StepOutcome, current_run

_RECOMPUTE = text(
    f"""
    WITH units AS ({units_sql()})
    UPDATE ledger_entry AS e
       SET review_flags = f.flags
      FROM (
            SELECT x.id,
                   ARRAY(
                       SELECT t.token
                         FROM (VALUES
                                ('unclassified', x.type IS NULL
                                                 OR (x.type = 'flow' AND x.category_id IS NULL)),
                                ('unconfirmed', x.unit_has_nonstanding),
                                ('unmatched_transfer', x.unpaired AND NOT x.is_waiting),
                                ('waiting', x.is_waiting)
                              ) AS t(token, applies)
                        WHERE t.applies
                        ORDER BY t.token
                   ) AS flags
              FROM (
                    SELECT le.id, le.type, le.category_id, u.unit_has_nonstanding,
                           (le.type = 'transfer' AND le.counterpart_entry_id IS NULL) AS unpaired,
                           COALESCE(le.type = 'transfer' AND le.counterpart_entry_id IS NULL
                                    AND sy.synced
                                    AND (cv.synced_through IS NULL
                                         OR cv.synced_through < le.booked_on + w.days), false) AS is_waiting
                      FROM ledger_entry AS le
                      JOIN units AS u ON u.id = le.id
                      CROSS JOIN (SELECT current_setting('ledger.matching_window_days')::int AS days) AS w
                      LEFT JOIN v_account_synced AS sy ON sy.account_id = le.counter_account_id
                      LEFT JOIN v_account_coverage AS cv ON cv.account_id = le.counter_account_id
                   ) AS x
           UNION ALL
            SELECT le.id, '{{}}'::text[]
              FROM ledger_entry AS le
             WHERE le.source_transaction_id IS NULL
           ) AS f
     WHERE e.id = f.id
       AND e.review_flags IS DISTINCT FROM f.flags
    RETURNING e.id
    """
)


def recompute_review_flags(conn: Connection) -> list[int]:
    """Rewrite every entry's flags; returns the ids whose stored value changed, ascending."""
    result = conn.execute(_RECOMPUTE, units_binds(conn))
    return sorted(int(i) for i in result.scalars())


def review_flags_step(conn: Connection) -> StepOutcome:
    """Step 5: rewrite the flags and count the entries confirmed since the previous round."""
    touched = recompute_review_flags(conn)
    run = current_run()
    if run.confirmed is None:  # outside a settle there is no previous round to compare with
        return StepOutcome(touched=touched)
    now = load_confirmed_ids(conn)
    new = sorted(now - run.confirmed)
    run.confirmed = now
    run.to_teach.extend(new)
    return StepOutcome(touched=touched, newly_confirmed=len(new))
