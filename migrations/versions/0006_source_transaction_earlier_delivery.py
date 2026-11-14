"""D256: a source transaction delivered again by a run whose coverage ends before the coverage of
the run that inserted it is recorded in source_transaction_earlier_delivery.

Skips made before this release left no trace; running the import again records them.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE source_transaction_earlier_delivery (
            source_transaction_id bigint NOT NULL REFERENCES source_transaction(id) ON DELETE CASCADE,
            import_run_id         bigint NOT NULL REFERENCES import_run(id) ON DELETE CASCADE,
            PRIMARY KEY (source_transaction_id, import_run_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE source_transaction_earlier_delivery")
