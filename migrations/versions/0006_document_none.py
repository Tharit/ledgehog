"""Every confirmed unit records "no document" on its original entries (spec §6, I20; step 9).

From step 9 a unit is not confirmed while a document is awaited or suggested, but only for a transaction
with no `document` key; settling records "none", keyed `matcher_decision`, when it confirms a unit. A unit
confirmed before then has no such key, and with a document source set up it would flip back to waiting,
against I20. This writes the key on the original entry (the lowest entry id of its source transaction, I31)
of every transaction of every currently confirmed unit that has none. Data only, no schema change.

A unit is confirmed here as `core/resolution/confirmed.py` judges it, without the document test (no document
exists yet): every entry complete (a type; a flow has a category; a transfer is paired) and carrying only
standing keys (`own_account`, `rule`, `matcher_decision`, `user`); the unit is a source transaction plus the
source of the partner of its transfer leg. Idempotent: an entry that has the key is left alone. The key is
not told apart afterwards from one settling recorded, so downgrading leaves it.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_BACKFILL = """
WITH base AS (
    SELECT le.id, le.source_transaction_id AS src,
           LEAST(le.source_transaction_id,
                 COALESCE(p.source_transaction_id, le.source_transaction_id)) AS direct_key,
           (le.type IS NOT NULL
            AND (le.type <> 'flow' OR le.category_id IS NOT NULL)
            AND (le.type <> 'transfer' OR le.counterpart_entry_id IS NOT NULL)) AS complete,
           NOT EXISTS (
               SELECT 1 FROM jsonb_each(le.derivation) AS d
                WHERE COALESCE(d.value ->> 'pass', '')
                      NOT IN ('own_account', 'rule', 'matcher_decision', 'user')) AS standing
      FROM ledger_entry AS le
      LEFT JOIN ledger_entry AS p ON p.id = le.counterpart_entry_id
     WHERE le.source_transaction_id IS NOT NULL
),
keyed AS (
    SELECT b.*, min(b.direct_key) OVER (PARTITION BY b.src) AS unit_key FROM base AS b
),
confirmed AS (
    SELECT k.unit_key FROM keyed AS k GROUP BY k.unit_key HAVING bool_and(k.complete AND k.standing)
)
UPDATE ledger_entry AS e
   SET derivation = e.derivation || '{"document": {"pass": "matcher_decision"}}'::jsonb
 WHERE e.id IN (SELECT min(k.id)
                  FROM keyed AS k
                  JOIN confirmed AS c ON c.unit_key = k.unit_key
                 GROUP BY k.src)
   AND NOT jsonb_exists(e.derivation, 'document')
"""


def upgrade() -> None:
    op.execute(_BACKFILL)


def downgrade() -> None:
    # the key cannot be told apart from one settling recorded; leaving it is harmless
    pass
