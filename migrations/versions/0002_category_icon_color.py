"""A category's icon and colour, presentation only (spec §3.5).

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE category ADD COLUMN icon text, ADD COLUMN color text")


def downgrade() -> None:
    op.execute("ALTER TABLE category DROP COLUMN color, DROP COLUMN icon")
