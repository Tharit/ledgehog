"""Drop `v_document_link`: nothing reads it, the document list counts carriers directly (spec §5.8).

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP VIEW v_document_link")


def downgrade() -> None:
    op.execute(
        """
CREATE VIEW v_document_link AS
SELECT d.id AS document_id, e.id AS ledger_entry_id,
       e.source_transaction_id
  FROM external_document d
  LEFT JOIN ledger_entry e ON e.document_id = d.id
"""
    )
