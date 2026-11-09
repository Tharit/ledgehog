"""D250: account kind `loan` becomes `debt`; `receivable` is added.

The kind is fixed at creation (trigger trg_account_kind_fixed), so the rename disables that trigger
for the one statement. Same execution route as the baseline: through the driver connection, since
the SQL is plain DDL.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_UPGRADE = """
ALTER TABLE account DROP CONSTRAINT account_kind_check;
ALTER TABLE account DISABLE TRIGGER trg_account_kind_fixed;
UPDATE account SET kind = 'debt' WHERE kind = 'loan';
ALTER TABLE account ENABLE TRIGGER trg_account_kind_fixed;
ALTER TABLE account ADD CONSTRAINT account_kind_check CHECK (kind IN (
    'checking','savings','card','cash',
    'digital_wallet','depot','debt','receivable','asset','clearance'));
"""

# back: receivable accounts have no earlier kind, so they fail the restored check and the
# downgrade refuses while any exist.
_DOWNGRADE = """
ALTER TABLE account DROP CONSTRAINT account_kind_check;
ALTER TABLE account DISABLE TRIGGER trg_account_kind_fixed;
UPDATE account SET kind = 'loan' WHERE kind = 'debt';
ALTER TABLE account ENABLE TRIGGER trg_account_kind_fixed;
ALTER TABLE account ADD CONSTRAINT account_kind_check CHECK (kind IN (
    'checking','savings','card','cash',
    'digital_wallet','depot','loan','asset','clearance'));
"""


def upgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_UPGRADE)


def downgrade() -> None:
    raw = op.get_bind().connection.driver_connection
    assert raw is not None
    raw.execute(_DOWNGRADE)
