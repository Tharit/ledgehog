"""Account and category triggers and constraints: 8.4 (kind fixed), 8.4b (acyclic), 8.5 (investment
status fixed), 8.5b (currency fixed), the category composite FK and the unique-name indexes."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Connection, text

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    FK_VIOLATION,
    RAISE_EXCEPTION,
    RESTRICT_VIOLATION,
    UNIQUE_VIOLATION,
    make_category,
    make_movement,
    rejects,
    scalar,
)

MakeAccount = Callable[..., int]


# ---- categories


def test_category_kind_is_fixed_at_creation(db_conn: Connection) -> None:
    cat = make_category(db_conn, "Food", "expense")
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="kind is fixed at creation"):
        db_conn.execute(text("UPDATE category SET kind = 'income' WHERE id = :i"), {"i": cat})


def test_rewriting_the_same_kind_is_accepted(db_conn: Connection) -> None:
    cat = make_category(db_conn, "Food", "expense")
    db_conn.execute(text("UPDATE category SET kind = 'expense' WHERE id = :i"), {"i": cat})


def test_category_kind_check(db_conn: Connection) -> None:
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="category_kind_check"):
        make_category(db_conn, "X", "savings")


def test_a_child_has_its_parents_kind(db_conn: Connection) -> None:
    parent = make_category(db_conn, "Food", "expense")
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_category_parent_same_kind"):
        make_category(db_conn, "Salary", "income", parent_id=parent)
    make_category(db_conn, "Groceries", "expense", parent_id=parent)


def test_reparenting_across_kinds_is_refused(db_conn: Connection) -> None:
    expense = make_category(db_conn, "Food", "expense")
    income = make_category(db_conn, "Salary", "income")
    child = make_category(db_conn, "Groceries", "expense", parent_id=expense)
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_category_parent_same_kind"):
        db_conn.execute(text("UPDATE category SET parent_id = :p WHERE id = :i"), {"p": income, "i": child})


def test_a_category_cannot_be_its_own_parent(db_conn: Connection) -> None:
    """On UPDATE the BEFORE trigger answers first; on INSERT only the CHECK is left to catch it."""
    cat = make_category(db_conn, "Food")
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="would create a cycle"):
        db_conn.execute(text("UPDATE category SET parent_id = id WHERE id = :i"), {"i": cat})
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="category_check"):
        db_conn.execute(
            text(
                "INSERT INTO category (id, name, kind, parent_id) OVERRIDING SYSTEM VALUE "
                "VALUES (900001, 'Loop', 'expense', 900001)"
            )
        )


def test_two_and_three_step_cycles_are_refused(db_conn: Connection) -> None:
    a = make_category(db_conn, "A")
    b = make_category(db_conn, "B", parent_id=a)
    c = make_category(db_conn, "C", parent_id=b)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="would create a cycle"):
        db_conn.execute(text("UPDATE category SET parent_id = :p WHERE id = :i"), {"p": b, "i": a})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="would create a cycle"):
        db_conn.execute(text("UPDATE category SET parent_id = :p WHERE id = :i"), {"p": c, "i": a})


def test_moving_a_subtree_elsewhere_is_accepted(db_conn: Connection) -> None:
    a = make_category(db_conn, "A")
    b = make_category(db_conn, "B", parent_id=a)
    c = make_category(db_conn, "C")
    db_conn.execute(text("UPDATE category SET parent_id = :p WHERE id = :i"), {"p": c, "i": b})
    db_conn.execute(text("UPDATE category SET parent_id = NULL WHERE id = :i"), {"i": b})
    assert scalar(db_conn, "SELECT parent_id FROM category WHERE id = :i", i=b) is None


def test_deleting_a_category_with_children_or_entries_is_refused(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    parent = make_category(db_conn, "Food")
    make_category(db_conn, "Groceries", parent_id=parent)
    with rejects(db_conn, sqlstate=RESTRICT_VIOLATION, constraint="fk_category_parent_same_kind"):
        db_conn.execute(text("DELETE FROM category WHERE id = :i"), {"i": parent})

    used = make_category(db_conn, "Used")
    _, entry = make_movement(db_conn, make_account(db_conn))
    db_conn.execute(text("UPDATE ledger_entry SET category_id = :c WHERE id = :e"), {"c": used, "e": entry})
    with rejects(db_conn, sqlstate=RESTRICT_VIOLATION, constraint="ledger_entry_category_id_fkey"):
        db_conn.execute(text("DELETE FROM category WHERE id = :i"), {"i": used})


def test_sibling_names_are_unique_case_insensitively_per_kind(db_conn: Connection) -> None:
    make_category(db_conn, "Other", "expense")
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_category_name"):
        make_category(db_conn, "OTHER", "expense")
    make_category(db_conn, "Other", "income")  # the kind keeps the two roots apart


def test_the_same_name_is_allowed_under_different_parents(db_conn: Connection) -> None:
    a = make_category(db_conn, "A")
    b = make_category(db_conn, "B")
    make_category(db_conn, "Misc", parent_id=a)
    make_category(db_conn, "Misc", parent_id=b)
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_category_name"):
        make_category(db_conn, "misc", parent_id=a)


# ---- accounts


def test_account_kind_check(db_conn: Connection, make_account: MakeAccount) -> None:
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="account_kind_check"):
        make_account(db_conn, kind="wallet")


def test_account_currency_is_fixed_even_when_empty(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn, currency="EUR")
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="its currency is fixed"):
        db_conn.execute(text("UPDATE account SET currency = 'USD' WHERE id = :i"), {"i": acct})
    db_conn.execute(text("UPDATE account SET currency = 'EUR' WHERE id = :i"), {"i": acct})


def test_account_currency_must_exist(db_conn: Connection, make_account: MakeAccount) -> None:
    with rejects(db_conn, sqlstate=FK_VIOLATION):
        make_account(db_conn, currency="ZZZ")


@pytest.mark.parametrize(
    ("old", "new"),
    [("checking", "depot"), ("savings", "asset"), ("depot", "checking"), ("asset", "card")],
)
def test_investment_status_is_fixed(
    old: str, new: str, db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn, kind=old)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="kind is fixed"):
        db_conn.execute(text("UPDATE account SET kind = :k WHERE id = :i"), {"k": new, "i": acct})


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("checking", "savings"),
        ("card", "cash"),
        ("loan", "digital_wallet"),
        ("depot", "asset"),
        ("asset", "depot"),
    ],
)
def test_kind_is_fixed_within_its_class(
    old: str, new: str, db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn, kind=old)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="kind is fixed"):
        db_conn.execute(text("UPDATE account SET kind = :k WHERE id = :i"), {"k": new, "i": acct})


def test_external_ref_is_unique_where_set(db_conn: Connection, make_account: MakeAccount) -> None:
    make_account(db_conn, name="A", external_ref="de01")
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_account_external_ref"):
        make_account(db_conn, name="B", external_ref="de01")
    make_account(db_conn, name="C")
    make_account(db_conn, name="D")  # NULLs do not collide


def test_an_account_with_entries_cannot_be_deleted(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=RESTRICT_VIOLATION):
        db_conn.execute(text("DELETE FROM account WHERE id = :i"), {"i": acct})
