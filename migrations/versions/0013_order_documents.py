"""One document, several charges: a document may be carried by several transactions, and a line
carries the model's answer (spec I35 §5.5 §5.9).

`ux_le_document` goes (a document is no longer carried by at most one entry; a transaction still has at
most one carrier, and a line is still the line of at most one entry). The line gains the model's answer
for it, `category_id` (SET NULL) and `category_key`.

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX ux_le_document")
    op.execute(
        "ALTER TABLE external_document_line ADD COLUMN category_id bigint REFERENCES category(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE external_document_line ADD COLUMN category_key jsonb")


def downgrade() -> None:
    # recreating the index fails, on purpose, while a document has two carriers: there is nothing
    # honest to drop
    op.execute("ALTER TABLE external_document_line DROP COLUMN category_key")
    op.execute("ALTER TABLE external_document_line DROP COLUMN category_id")
    op.execute(
        "CREATE UNIQUE INDEX ux_le_document ON ledger_entry (document_id) WHERE document_id IS NOT NULL"
    )
