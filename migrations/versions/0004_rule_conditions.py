"""Uniform rule conditions: one `conditions` list instead of six flat columns (spec §5.9, D207).

No rule exists in any real database before this revision, and the equivalence test compares column
order too, so the table is dropped and recreated exactly as `spec/schema.sql` has it.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_NEW = """
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

_OLD = """
CREATE TABLE rule (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sets               text NOT NULL CHECK (sets IN ('counter_account','payee','category')),
    counter_account_id bigint REFERENCES account(id)  ON DELETE RESTRICT,
    payee_id           bigint REFERENCES payee(id)    ON DELETE CASCADE,
    category_id        bigint REFERENCES category(id) ON DELETE RESTRICT,
    condition_payee_id bigint REFERENCES payee(id)    ON DELETE CASCADE,
    counterparty_ref   text,
    mandate_ref        text,
    name_exact         text,
    name_prefix        text,
    purpose_regex      text,
    booking_text       text,
    priority           integer NOT NULL DEFAULT 100,
    name               text NOT NULL CONSTRAINT ck_rule_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_rule_sets CHECK (
            (sets = 'counter_account') = (counter_account_id IS NOT NULL)
        AND (sets = 'payee')           = (payee_id IS NOT NULL)
        AND (sets = 'category')        = (category_id IS NOT NULL)),
    CONSTRAINT ck_rule_payee_condition
        CHECK (condition_payee_id IS NULL OR sets = 'category'),
    CONSTRAINT ck_rule_condition
        CHECK (num_nonnulls(condition_payee_id, counterparty_ref, mandate_ref,
                            name_exact, name_prefix, purpose_regex,
                            booking_text) > 0)
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
