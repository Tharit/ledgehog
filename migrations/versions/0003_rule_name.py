"""A name on every rule: how evidence explains it (spec §5.9, D198).

No rule is written before this revision, so the column is added as NOT NULL.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE rule ADD COLUMN name text NOT NULL CONSTRAINT ck_rule_name CHECK (btrim(name) <> '')"
    )
    op.execute("CREATE UNIQUE INDEX ux_rule_name ON rule (lower(name))")


def downgrade() -> None:
    op.execute("DROP INDEX ux_rule_name")
    op.execute("ALTER TABLE rule DROP COLUMN name")
