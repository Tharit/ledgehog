"""Review flags (spec §6, I23): derived from current state, rewritten wholesale.

One set-based statement computes the flags of every entry from its columns and
writes only the rows whose stored value differs, so settling twice touches
nothing (I37). Tokens are stored sorted. Derived entries (opening, valuation,
reconciliation: `balance_record_id` set) are complete by construction and never
carry flags.

Produced so far: `unclassified` and `unconfirmed`. `document_suggested`,
`waiting` and `unmatched_transfer` belong to the closed set but need the
matcher and pairing steps, which do not exist yet.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

# Derivation keys of these passes are standing (schema comment on ledger_entry.derivation);
# any other key - including a malformed one without a pass - awaits a human.
STANDING_PASSES = ("own_account", "rule", "matcher_decision", "user")

_RECOMPUTE = text(
    """
    UPDATE ledger_entry AS e
       SET review_flags = f.flags
      FROM (
            SELECT le.id,
                   ARRAY(
                       SELECT t.token
                         FROM (VALUES
                                ('unclassified', le.type IS NULL
                                                 OR (le.type = 'flow' AND le.category_id IS NULL)),
                                ('unconfirmed', EXISTS (
                                    SELECT 1 FROM jsonb_each(le.derivation) AS k
                                     WHERE COALESCE(k.value ->> 'pass', '') <> ALL (:standing)))
                              ) AS t(token, applies)
                        WHERE t.applies
                        ORDER BY t.token
                   ) AS flags
              FROM ledger_entry AS le
             WHERE le.balance_record_id IS NULL
           UNION ALL
            SELECT le.id, '{}'::text[]
              FROM ledger_entry AS le
             WHERE le.balance_record_id IS NOT NULL
           ) AS f
     WHERE e.id = f.id
       AND e.review_flags IS DISTINCT FROM f.flags
    RETURNING e.id
    """
)


def recompute_review_flags(conn: Connection) -> list[int]:
    """Rewrite every entry's flags; returns the ids whose stored value changed, ascending."""
    result = conn.execute(_RECOMPUTE, {"standing": list(STANDING_PASSES)})
    return sorted(int(i) for i in result.scalars())
