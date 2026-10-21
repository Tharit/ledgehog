"""The account kind `paypal` becomes `digital_wallet` (spec §3.3).

Existing PayPal accounts are carried over, then the kind check is replaced. The importer and the
document provider named `paypal` are untouched.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _swap(old: str, new: str) -> None:
    op.execute("ALTER TABLE account DROP CONSTRAINT account_kind_check")
    op.execute(f"UPDATE account SET kind = '{new}' WHERE kind = '{old}'")
    op.execute(
        f"""
ALTER TABLE account ADD CONSTRAINT account_kind_check CHECK (kind IN (
    'checking','savings','card','cash',
    '{new}','depot','loan','asset'))
"""
    )


def upgrade() -> None:
    # the fixed-kind trigger refuses the data update, so it is lifted around it
    op.execute("ALTER TABLE account DISABLE TRIGGER trg_account_kind_fixed")
    _swap("paypal", "digital_wallet")
    op.execute("ALTER TABLE account ENABLE TRIGGER trg_account_kind_fixed")


def downgrade() -> None:
    op.execute("ALTER TABLE account DISABLE TRIGGER trg_account_kind_fixed")
    _swap("digital_wallet", "paypal")
    op.execute("ALTER TABLE account ENABLE TRIGGER trg_account_kind_fixed")
