"""An index to find the carriers of a document: a unit joins them (spec I21, I35).

`ux_le_document` went with 0013, and with it the lookup of an entry by its document. The unit's closure
reads every transaction carrying a document, so the column gets a plain partial index.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_le_document ON ledger_entry (document_id) WHERE document_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX ix_le_document")
