"""Review flags (spec §6, I23): derived from current state, rewritten wholesale.

One set-based statement computes the flags of every entry and writes only the rows whose stored
value differs, so settling twice touches nothing (I37). Tokens are stored sorted. Derived entries
(opening, valuation, reconciliation: `balance_record_id` set) are complete by construction, are in
no unit and never carry flags.

Produced so far: `unclassified` and `unconfirmed`. `document_suggested`, `waiting` and
`unmatched_transfer` belong to the closed set but need the matcher and pairing steps (8 and 9), which
do not exist yet; an unpaired transfer leg therefore carries no flag, though its unit is not confirmed.

The flags are judged over the UNIT (spec §6; the CTE of `core/resolution/confirmed.py`: the entries of
one source transaction and of a transfer pair, transitively):

* `unclassified` is the entry's own: no type, or a flow without a category.
* `unconfirmed` marks EVERY entry of a unit in which some entry carries a key that awaits a human (a
  proposal of `history`, `llm`, `matcher_proposal`, or a key without a pass): the complete sibling of
  such an entry, and the partner of such a leg, are unconfirmed with it. A unit that is merely incomplete
  (an unclassified sibling, an unpaired transfer) puts no `unconfirmed` on its complete entries; it is
  still not confirmed and is in the review queue, which reads the unit CTE rather than these flags.

An entry is confirmed iff its unit is: every entry complete, every transfer paired (I22) and no key but
standing ones. `review_flags_step` reports the entries that became confirmed since the last round (what
history learns from, and what keeps the rounds going).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.core.resolution.confirmed import STANDING, load_confirmed_ids, units_sql
from app.core.settle.run import StepOutcome, current_run

_RECOMPUTE = text(
    f"""
    WITH units AS ({units_sql()})
    UPDATE ledger_entry AS e
       SET review_flags = f.flags
      FROM (
            SELECT le.id,
                   ARRAY(
                       SELECT t.token
                         FROM (VALUES
                                ('unclassified', le.type IS NULL
                                                 OR (le.type = 'flow' AND le.category_id IS NULL)),
                                ('unconfirmed', u.unit_has_nonstanding)
                              ) AS t(token, applies)
                        WHERE t.applies
                        ORDER BY t.token
                   ) AS flags
              FROM ledger_entry AS le
              JOIN units AS u ON u.id = le.id
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
    result = conn.execute(_RECOMPUTE, {"standing": STANDING})
    return sorted(int(i) for i in result.scalars())


def review_flags_step(conn: Connection) -> StepOutcome:
    """Step 5: rewrite the flags, and count the entries confirmed since the previous round."""
    touched = recompute_review_flags(conn)
    run = current_run()
    if run.confirmed is None:  # outside a settle there is no previous round to compare with
        return StepOutcome(touched=touched)
    now = load_confirmed_ids(conn)
    new = sorted(now - run.confirmed)
    run.confirmed = now
    run.to_teach.extend(new)
    return StepOutcome(touched=touched, newly_confirmed=len(new))
