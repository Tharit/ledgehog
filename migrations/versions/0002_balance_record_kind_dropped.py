"""D248: `balance_record.kind` goes; whether a record is reported is read from `import_run_id`.

The views that read `kind` are recreated without it, and so are those built on `v_balance_record`
(`b.*` there expands to the column list, so the column cannot be dropped beneath it). Same
execution route as the baseline: through the driver connection, since the SQL is plain DDL.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# the views over balance_record / v_balance_record, in drop order (dependents first)
_DROP_VIEWS = """
DROP VIEW v_account_data_age;
DROP VIEW v_unexplained_difference;
DROP VIEW v_check_anchor_not_opening;
DROP VIEW v_check_opening_not_anchor;
DROP VIEW v_check_derived_on_uncounted;
DROP VIEW v_balance_record;
DROP VIEW v_check_reported_after_coverage;
"""

# the views as the baseline defines them, with `kind` replaced by `import_run_id` where it was read
_CREATE_VIEWS = """
CREATE VIEW v_check_reported_after_coverage AS
SELECT b.id AS balance_record_id, b.balance_on, r.id AS import_run_id,
       r.covered_through
  FROM balance_record b
  JOIN import_run r ON r.id = b.import_run_id
 WHERE (r.covered_through IS NULL OR b.balance_on > r.covered_through);

CREATE VIEW v_balance_record AS
SELECT b.*
  FROM balance_record b
  LEFT JOIN import_run r ON r.id = b.import_run_id
 WHERE r.id IS NULL OR r.status <> 'reverted';

CREATE VIEW v_check_derived_on_uncounted AS
SELECT e.id AS entry_id, e.balance_record_id
  FROM ledger_entry e
 WHERE e.balance_record_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM v_balance_record b
                    WHERE b.id = e.balance_record_id);

CREATE VIEW v_check_opening_not_anchor AS
SELECT e.id AS opening_entry_id, e.account_id, e.balance_record_id
  FROM ledger_entry e
 WHERE e.type = 'opening'
   AND e.balance_record_id IS DISTINCT FROM (
         SELECT b.id FROM v_balance_record b
          WHERE b.account_id = e.account_id
          ORDER BY b.balance_on, b.id LIMIT 1);

CREATE VIEW v_check_anchor_not_opening AS
SELECT e.id AS entry_id, e.account_id, e.type
  FROM ledger_entry e
 WHERE e.balance_record_id IS NOT NULL AND e.type <> 'opening'
   AND e.balance_record_id = (
         SELECT b.id FROM v_balance_record b
          WHERE b.account_id = e.account_id
          ORDER BY b.balance_on, b.id LIMIT 1);

CREATE VIEW v_unexplained_difference AS
WITH reported AS (
    SELECT account_id, balance_on, id FROM v_balance_record WHERE import_run_id IS NOT NULL
), first_reported AS (
    SELECT DISTINCT ON (account_id) account_id, balance_on, id
      FROM reported ORDER BY account_id, balance_on, id
), last_reported AS (
    SELECT DISTINCT ON (account_id) account_id, balance_on, id
      FROM reported ORDER BY account_id, balance_on DESC, id DESC
)
SELECT b.account_id, sum(e.amount)::bigint AS difference
  FROM v_balance_record b
  JOIN first_reported f ON f.account_id = b.account_id
  JOIN last_reported  l ON l.account_id = b.account_id
  JOIN ledger_entry e ON e.balance_record_id = b.id
 WHERE e.type = 'reconciliation'
   AND (b.balance_on, b.id) >= (f.balance_on, f.id)
   AND (b.balance_on, b.id) <= (l.balance_on, l.id)
 GROUP BY b.account_id
HAVING sum(e.amount) <> 0;

CREATE VIEW v_account_data_age AS
SELECT a.account_id,
       CASE WHEN a.synced THEN c.synced_through
            ELSE (SELECT max(b.balance_on) FROM v_balance_record b
                   WHERE b.account_id = a.account_id)
       END AS last_data_on
  FROM v_account_synced a
  JOIN v_account_coverage c ON c.account_id = a.account_id;
"""

_UPGRADE = (
    _DROP_VIEWS
    + """
ALTER TABLE balance_record DROP CONSTRAINT ck_balance_record_run;
DROP INDEX ux_balance_record_reported;
DROP INDEX ux_balance_record_manual_date;
ALTER TABLE balance_record DROP COLUMN kind;
CREATE UNIQUE INDEX ux_balance_record_reported
    ON balance_record (import_run_id) WHERE import_run_id IS NOT NULL;
CREATE UNIQUE INDEX ux_balance_record_manual_date
    ON balance_record (account_id, balance_on) WHERE import_run_id IS NULL;
"""
    + _CREATE_VIEWS
)

# back: the column returns derived from the run, so the baseline's check holds again. The column
# is appended last (a table's column order is not part of its meaning).
_DOWNGRADE = (
    _DROP_VIEWS
    + """
DROP INDEX ux_balance_record_reported;
DROP INDEX ux_balance_record_manual_date;
ALTER TABLE balance_record ADD COLUMN kind text;
UPDATE balance_record SET kind = CASE WHEN import_run_id IS NULL THEN 'manual' ELSE 'reported' END;
ALTER TABLE balance_record ALTER COLUMN kind SET NOT NULL;
ALTER TABLE balance_record ADD CONSTRAINT balance_record_kind_check CHECK (kind IN ('reported','manual'));
ALTER TABLE balance_record ADD CONSTRAINT ck_balance_record_run
    CHECK ((kind = 'manual') = (import_run_id IS NULL));
CREATE UNIQUE INDEX ux_balance_record_reported
    ON balance_record (import_run_id) WHERE kind = 'reported';
CREATE UNIQUE INDEX ux_balance_record_manual_date
    ON balance_record (account_id, balance_on) WHERE kind = 'manual';
"""
    + _CREATE_VIEWS.replace("WHERE import_run_id IS NOT NULL", "WHERE kind = 'reported'").replace(
        " WHERE (r.covered_through IS NULL", " WHERE b.kind = 'reported'\n   AND (r.covered_through IS NULL"
    )
)


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_UPGRADE)


def downgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_DOWNGRADE)
