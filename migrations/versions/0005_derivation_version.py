"""D255: the derivation of derived entries last applied is stored (architecture §5.7).

A start whose code carries another version recomputes every account's derived entries. Existing
ledgers start at 0, so the first start after this release recomputes once.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ledger_setting ADD COLUMN derivation_version integer NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE ledger_setting DROP COLUMN derivation_version")
