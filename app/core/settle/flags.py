"""Review flags (spec §6, I23): derived from current state, rewritten wholesale.

One set-based statement computes the flags of every entry and writes only the rows whose stored
value differs, so settling twice touches nothing (I37). Tokens are stored sorted. Derived entries
(opening, valuation, reconciliation: `balance_record_id` set) are complete by construction, are in
no unit and never carry flags.

Produced: `unclassified`, `unconfirmed`, `waiting`, `unmatched_transfer` and `document_suggested`.

`waiting` is also a transaction's wait for its document (spec §5.8, documents.md §7), on its original
entry: it is set when the unit CTE says `doc_awaited` (`core/resolution/confirmed.py`), even while
documents are suggested (a unit waiting for a document has `waiting` in addition to `document_suggested`).
`waiting` is also set, on the original entry that carries a matcher's link, while the document's order is not
all charged (`doc_rest`, documents.md §7); that wait holds no confirmation.
`document_suggested` is `doc_suggested`: candidates exist and no automatic link is possible. Both are
judged for the original entry of a transaction whose payee has a provider and which has no `document` key.

`waiting` and `unmatched_transfer` are per unpaired transfer leg (spec §5.7), from the leg's counter-
account C (under any key), `v_account_synced`, `v_account_coverage` and the matching window (the
`ledger.matching_window_days` setting): the leg is waiting iff C is set, synced, and its `synced_through`
is NULL or before `booked_on` plus the window; otherwise (C unsynced or closed, synced through the
window, or no C) it is unmatched. A paired leg has neither. `core/matching/states.py` is the same
judgement in Python, pinned to this SQL by a test.

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
                                ('document_suggested', x.doc_suggested),
                                ('waiting', x.is_waiting OR x.doc_awaited OR x.doc_rest)
                              ) AS t(token, applies)
                        WHERE t.applies
                        ORDER BY t.token
                   ) AS flags
              FROM (
                    SELECT le.id, le.type, le.category_id, u.unit_has_nonstanding,
                           u.doc_awaited, u.doc_suggested, u.doc_rest,
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


# The "none" settling records when it confirms a unit (spec §6): a standing decision without a link, on the
# original entry (I31) of each transaction of the unit that has no `document` key. Only `derivation` changes,
# so `version` does not move; a second run finds the key and writes nothing.
NONE_KEY = '{"document": {"pass": "matcher_decision"}}'

_RECORD_NONE = text(
    """
    UPDATE ledger_entry AS e
       SET derivation = e.derivation || CAST(:none AS jsonb)
     WHERE e.id = ANY(:ids)
       AND NOT jsonb_exists(e.derivation, 'document')
       AND NOT EXISTS (SELECT 1 FROM ledger_entry AS o
                        WHERE o.source_transaction_id = e.source_transaction_id AND o.id < e.id)
    RETURNING e.id
    """
)


def record_none_documents(conn: Connection, confirmed_ids: list[int]) -> list[int]:
    """Record "none" on every given entry that is the original entry of its source transaction and has no
    document key; returns the ids written. The entries are those of confirmed units, whole (a unit is
    confirmed together), so each transaction of such a unit has its original among them."""
    if not confirmed_ids:
        return []
    result = conn.execute(_RECORD_NONE, {"none": NONE_KEY, "ids": confirmed_ids})
    return sorted(int(i) for i in result.scalars())


def review_flags_step(conn: Connection) -> StepOutcome:
    """Step 5: rewrite the flags, count the entries confirmed since the previous round, and record "none"
    for the document of each transaction of a newly confirmed unit that has no document key (spec §6)."""
    touched = recompute_review_flags(conn)
    run = current_run()
    if run.confirmed is None:  # outside a settle there is no previous round to compare with
        return StepOutcome(touched=touched, affects_documents=False)
    now = load_confirmed_ids(conn)
    new = sorted(now - run.confirmed)
    run.confirmed = now
    run.to_teach.extend(new)
    recorded = record_none_documents(conn, new)
    # the "none" goes to units that are confirmed, so without a candidate: it leaves the matching as it was
    return StepOutcome(
        touched=sorted({*touched, *recorded}), newly_confirmed=len(new), affects_documents=False
    )
