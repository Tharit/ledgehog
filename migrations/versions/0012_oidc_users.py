"""A user may be the OIDC provider's: `source`, and a password that may be absent (architecture §5.6).

`pw_hash` becomes nullable (a provider's user has none; a configured one has none while OIDC is
enforced), `source` records whose user it is, and a provider's user can never hold a password.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app_user ALTER COLUMN pw_hash DROP NOT NULL")
    op.execute(
        "ALTER TABLE app_user ADD COLUMN source text NOT NULL DEFAULT 'config' "
        "CHECK (source IN ('config','oidc'))"
    )
    op.execute(
        "ALTER TABLE app_user ADD CONSTRAINT ck_app_user_oidc_no_password "
        "CHECK (source = 'config' OR pw_hash IS NULL)"
    )


def downgrade() -> None:
    # fails, on purpose, while a user without a password exists: there is nothing honest to put there
    op.execute("ALTER TABLE app_user DROP CONSTRAINT ck_app_user_oidc_no_password")
    op.execute("ALTER TABLE app_user DROP COLUMN source")
    op.execute("ALTER TABLE app_user ALTER COLUMN pw_hash SET NOT NULL")
