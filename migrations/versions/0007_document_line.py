"""An entry's line of its transaction's document (spec §5.8, D225; step 9).

`ledger_entry.document_line_id` references the entry's own line of the document its transaction carries: a
document of one line, the original entry's, written with the link; of several, each entry the split along
the lines makes. A changed document's lines are replaced, which clears the references (ON DELETE SET NULL).
A document is not carried by a transfer (`ck_document_not_on_transfer`), and a line is the line of at most
one entry (`ux_le_document_line`). A change of the line bumps the entry's `version` like `document_id` does
(it is resolution input): `trg_le_version` is recreated with it.

No data backfill: entries cut before this change carry no line, and there is no real data yet. The column is
the last of `ledger_entry`, as `spec/schema.sql` declares it (the equivalence test compares column order).

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_FLOWS = """
CREATE VIEW v_flows AS
SELECT e.*, c.kind AS category_kind,
       base_value(e.amount, e.currency, e.booked_on) AS base_amount
  FROM ledger_entry e
  LEFT JOIN category c ON c.id = e.category_id
 WHERE e.type = 'flow' OR e.type IS NULL
"""

_UP = (
    # v_flows is `e.*`: a view keeps the columns it was created with, so it is recreated around the change
    "DROP VIEW v_flows",
    "ALTER TABLE ledger_entry ADD COLUMN document_line_id bigint",
    """ALTER TABLE ledger_entry
    ADD CONSTRAINT fk_le_document_line
    FOREIGN KEY (document_line_id) REFERENCES external_document_line(id) ON DELETE SET NULL""",
    """ALTER TABLE ledger_entry
    ADD CONSTRAINT ck_document_not_on_transfer
    CHECK (document_id IS NULL OR type IS DISTINCT FROM 'transfer')""",
    """CREATE UNIQUE INDEX ux_le_document_line
    ON ledger_entry (document_line_id) WHERE document_line_id IS NOT NULL""",
    "DROP TRIGGER trg_le_version ON ledger_entry",
)

_TRIGGER = """
CREATE TRIGGER trg_le_version BEFORE UPDATE ON ledger_entry
    FOR EACH ROW WHEN (
            OLD.account_id            IS DISTINCT FROM NEW.account_id
         OR OLD.amount                IS DISTINCT FROM NEW.amount
         OR OLD.counterpart_entry_id  IS DISTINCT FROM NEW.counterpart_entry_id
         OR OLD.document_id           IS DISTINCT FROM NEW.document_id
         {line}
         OR (current_setting('ledger.settling', true) IS DISTINCT FROM 'on'
             AND (   OLD.type         IS DISTINCT FROM NEW.type
                  OR OLD.counter_account_id IS DISTINCT FROM NEW.counter_account_id
                  OR OLD.currency     IS DISTINCT FROM NEW.currency
                  OR OLD.booked_on    IS DISTINCT FROM NEW.booked_on
                  OR OLD.value_on     IS DISTINCT FROM NEW.value_on
                  OR OLD.category_id  IS DISTINCT FROM NEW.category_id
                  OR OLD.payee_id     IS DISTINCT FROM NEW.payee_id
                  OR OLD.description  IS DISTINCT FROM NEW.description
                  OR OLD.note         IS DISTINCT FROM NEW.note)))
    EXECUTE FUNCTION bump_version()
"""

_LINE = "OR OLD.document_line_id      IS DISTINCT FROM NEW.document_line_id"


def upgrade() -> None:
    for statement in _UP:
        op.execute(statement)
    op.execute(_TRIGGER.format(line=_LINE))
    op.execute(_FLOWS)


def downgrade() -> None:
    op.execute("DROP VIEW v_flows")
    op.execute("DROP TRIGGER trg_le_version ON ledger_entry")
    op.execute(_TRIGGER.format(line=""))
    op.execute("DROP INDEX ux_le_document_line")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT ck_document_not_on_transfer")
    op.execute("ALTER TABLE ledger_entry DROP CONSTRAINT fk_le_document_line")
    op.execute("ALTER TABLE ledger_entry DROP COLUMN document_line_id")
    op.execute(_FLOWS)
