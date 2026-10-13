"""The rule table's declarative checks on `conditions` (spec §5.9, D207): shape only.

Which fields and operators are valid is the rules plugin's to say; the database holds the two
facts that keep a rule from being vacuous or malformed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text

from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import CHECK_VIOLATION, rejects

ONE = '[{"field": "purpose", "op": "contains", "value": "x"}]'


def _insert(conn: Connection, conditions: str, *, payee: int | None = None, name: str = "r") -> int:
    category = seed.category(conn, f"C {name}")
    return int(
        conn.execute(
            text(
                "INSERT INTO rule (name, sets, category_id, condition_payee_id, conditions)"
                " VALUES (:n, 'category', :c, :p, CAST(:j AS jsonb)) RETURNING id"
            ),
            {"n": name, "c": category, "p": payee, "j": conditions},
        ).scalar_one()
    )


@pytest.mark.parametrize("not_an_array", ['{"field": "purpose"}', '"x"', "5", "null", "true"])
def test_conditions_must_be_an_array(db_conn: Connection, not_an_array: str) -> None:
    payee = seed.payee(db_conn, "P")
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_rule_cond_array"):
        _insert(db_conn, not_an_array, payee=payee)


def test_an_empty_list_needs_a_payee_condition(db_conn: Connection) -> None:
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_rule_condition"):
        _insert(db_conn, "[]")


def test_an_empty_list_with_a_payee_condition_is_accepted(db_conn: Connection) -> None:
    payee = seed.payee(db_conn, "P")
    rid = _insert(db_conn, "[]", payee=payee)
    assert db_conn.execute(text("SELECT conditions FROM rule WHERE id = :i"), {"i": rid}).scalar_one() == []


def test_a_list_alone_is_accepted_and_the_default_is_empty(db_conn: Connection) -> None:
    rid = _insert(db_conn, ONE)
    got = db_conn.execute(text("SELECT conditions FROM rule WHERE id = :i"), {"i": rid}).scalar_one()
    assert got == [{"field": "purpose", "op": "contains", "value": "x"}]
    category = seed.category(db_conn, "Other")
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_rule_condition"):
        # no list given: the default `[]` and no payee condition
        db_conn.execute(
            text("INSERT INTO rule (name, sets, category_id) VALUES ('d', 'category', :c)"), {"c": category}
        )


def test_the_flat_condition_columns_are_gone(db_conn: Connection) -> None:
    cols = set(
        db_conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'rule'")
        ).scalars()
    )
    assert {"conditions", "condition_payee_id"} <= cols
    assert not cols & {
        "counterparty_ref",
        "mandate_ref",
        "name_exact",
        "name_prefix",
        "purpose_regex",
        "booking_text",
    }
