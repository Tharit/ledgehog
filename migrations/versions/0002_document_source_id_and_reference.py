"""A document's key is its `source_id`; its own `reference` is a separate, nullable field.

`external_id` read as "the vendor's id", but an importer may synthesise the key where its
source names nothing usable, so it becomes `source_id` (as on `source_transaction`). The
`reference` is the order, invoice or booking number a person would quote: nullable, shown and
searched, never the key (spec §5.5). `reference` is appended after `version`, where schema.sql
declares it.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _rename_not_null(old: str, new: str) -> str:
    """Postgres 18 names a NOT NULL constraint after its column and keeps the name through a column
    rename; earlier versions have no such constraint, so the rename is made only where it exists."""
    return (
        "DO $$ BEGIN"
        " IF EXISTS (SELECT 1 FROM pg_constraint"
        f" WHERE conrelid = 'external_document'::regclass AND conname = '{old}') THEN"
        f" ALTER TABLE external_document RENAME CONSTRAINT {old} TO {new};"
        " END IF; END $$"
    )


def upgrade() -> None:
    op.execute("ALTER TABLE external_document RENAME COLUMN external_id TO source_id")
    # RENAME COLUMN leaves the auto-named unique constraint (and its index) under the old name.
    op.execute(
        "ALTER TABLE external_document RENAME CONSTRAINT"
        " external_document_provider_external_id_key TO external_document_provider_source_id_key"
    )
    op.execute(
        _rename_not_null("external_document_external_id_not_null", "external_document_source_id_not_null")
    )
    op.execute("ALTER TABLE external_document ADD COLUMN reference text")


def downgrade() -> None:
    op.execute("ALTER TABLE external_document DROP COLUMN reference")
    op.execute(
        "ALTER TABLE external_document RENAME CONSTRAINT"
        " external_document_provider_source_id_key TO external_document_provider_external_id_key"
    )
    op.execute(
        _rename_not_null("external_document_source_id_not_null", "external_document_external_id_not_null")
    )
    op.execute("ALTER TABLE external_document RENAME COLUMN source_id TO external_id")
