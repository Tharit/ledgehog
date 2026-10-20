"""An account's kind is fixed at creation (trigger 8.5, I38).

The investment-class-only trigger is replaced by one refusing any change of `account.kind`.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER trg_account_investment_fixed ON account")
    op.execute("DROP FUNCTION assert_account_investment_fixed()")
    op.execute(
        """
CREATE OR REPLACE FUNCTION assert_account_kind_fixed() RETURNS trigger AS $$
BEGIN
    IF NEW.kind IS DISTINCT FROM OLD.kind THEN
        RAISE EXCEPTION 'account %: kind is fixed at creation', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
    )
    op.execute(
        """
CREATE TRIGGER trg_account_kind_fixed BEFORE UPDATE OF kind ON account
    FOR EACH ROW EXECUTE FUNCTION assert_account_kind_fixed()
"""
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_account_kind_fixed ON account")
    op.execute("DROP FUNCTION assert_account_kind_fixed()")
    op.execute(
        """
CREATE OR REPLACE FUNCTION assert_account_investment_fixed() RETURNS trigger AS $$
BEGIN
    IF (OLD.kind IN ('depot','asset')) IS DISTINCT FROM (NEW.kind IN ('depot','asset')) THEN
        RAISE EXCEPTION 'account %: whether it is an investment account is fixed at creation', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
    )
    op.execute(
        """
CREATE TRIGGER trg_account_investment_fixed BEFORE UPDATE OF kind ON account
    FOR EACH ROW EXECUTE FUNCTION assert_account_investment_fixed()
"""
    )
