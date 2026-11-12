"""D251: a clearance account's data age is how long its balance has been open.

Only the view changes (spec §3.11). Same execution route as the baseline: through the driver
connection, since the SQL is plain DDL. Nothing depends on v_account_data_age.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_UPGRADE = """
DROP VIEW v_account_data_age;
CREATE VIEW v_account_data_age AS
WITH clearance_day AS (
  SELECT e.account_id, e.booked_on AS day,
         sum(sum(e.amount)) OVER (PARTITION BY e.account_id
                                  ORDER BY e.booked_on) AS balance
    FROM ledger_entry e
    JOIN account k ON k.id = e.account_id AND k.kind = 'clearance'
   GROUP BY e.account_id, e.booked_on
)
SELECT a.account_id,
       CASE WHEN k.kind = 'clearance' THEN GREATEST(
              (SELECT min(b.balance_on) FROM v_balance_record b
                WHERE b.account_id = a.account_id),
              (SELECT max(d.day) FROM clearance_day d
                WHERE d.account_id = a.account_id
                  AND (n.balance = 0 OR sign(d.balance) <> sign(n.balance))))
            WHEN a.synced THEN c.synced_through
            ELSE (SELECT max(b.balance_on) FROM v_balance_record b
                   WHERE b.account_id = a.account_id)
       END AS last_data_on
  FROM v_account_synced a
  JOIN account k ON k.id = a.account_id
  JOIN v_account_coverage c ON c.account_id = a.account_id
  CROSS JOIN LATERAL (SELECT COALESCE(sum(e.amount), 0) AS balance
                        FROM ledger_entry e
                       WHERE e.account_id = a.account_id) n;
"""

_DOWNGRADE = """
DROP VIEW v_account_data_age;
CREATE VIEW v_account_data_age AS
SELECT a.account_id,
       CASE WHEN a.synced THEN c.synced_through
            ELSE (SELECT max(b.balance_on) FROM v_balance_record b
                   WHERE b.account_id = a.account_id)
       END AS last_data_on
  FROM v_account_synced a
  JOIN v_account_coverage c ON c.account_id = a.account_id;
"""


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_UPGRADE)


def downgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_DOWNGRADE)
