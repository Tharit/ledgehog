"""The payee condition of a rule becomes a normal condition (spec §5.9, D215).

`condition_payee_id` and its CHECKs go; a payee condition is `{"field":"payee","op":"is","value":"<id>"}`
in `conditions`. No rule exists in any real database before this revision, and the equivalence test
compares column order too, so the table is dropped and recreated exactly as `spec/schema.sql` has it.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_NEW = """
CREATE TABLE rule (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sets               text NOT NULL CHECK (sets IN ('counter_account','payee','category')),
    counter_account_id bigint REFERENCES account(id)  ON DELETE RESTRICT,
    payee_id           bigint REFERENCES payee(id)    ON DELETE CASCADE,
    category_id        bigint REFERENCES category(id) ON DELETE RESTRICT,
    conditions         jsonb NOT NULL DEFAULT '[]',
    priority           integer NOT NULL DEFAULT 100,
    name               text NOT NULL CONSTRAINT ck_rule_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_rule_sets CHECK (
            (sets = 'counter_account') = (counter_account_id IS NOT NULL)
        AND (sets = 'payee')           = (payee_id IS NOT NULL)
        AND (sets = 'category')        = (category_id IS NOT NULL)),
    CONSTRAINT ck_rule_condition
        CHECK (jsonb_array_length(conditions) > 0),
    CONSTRAINT ck_rule_cond_array
        CHECK (jsonb_typeof(conditions) = 'array')
)
"""

_OLD = """
CREATE TABLE rule (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sets               text NOT NULL CHECK (sets IN ('counter_account','payee','category')),
    counter_account_id bigint REFERENCES account(id)  ON DELETE RESTRICT,
    payee_id           bigint REFERENCES payee(id)    ON DELETE CASCADE,
    category_id        bigint REFERENCES category(id) ON DELETE RESTRICT,
    condition_payee_id bigint REFERENCES payee(id)    ON DELETE CASCADE,
    conditions         jsonb NOT NULL DEFAULT '[]',
    priority           integer NOT NULL DEFAULT 100,
    name               text NOT NULL CONSTRAINT ck_rule_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_rule_sets CHECK (
            (sets = 'counter_account') = (counter_account_id IS NOT NULL)
        AND (sets = 'payee')           = (payee_id IS NOT NULL)
        AND (sets = 'category')        = (category_id IS NOT NULL)),
    CONSTRAINT ck_rule_payee_condition
        CHECK (condition_payee_id IS NULL OR sets = 'category'),
    CONSTRAINT ck_rule_condition
        CHECK (jsonb_array_length(conditions) > 0 OR condition_payee_id IS NOT NULL),
    CONSTRAINT ck_rule_cond_array
        CHECK (jsonb_typeof(conditions) = 'array')
)
"""


def upgrade() -> None:
    op.execute("DROP TABLE rule")
    op.execute(_NEW)
    op.execute("CREATE UNIQUE INDEX ux_rule_name ON rule (lower(name))")


def downgrade() -> None:
    op.execute("DROP TABLE rule")
    op.execute(_OLD)
    op.execute("CREATE UNIQUE INDEX ux_rule_name ON rule (lower(name))")
