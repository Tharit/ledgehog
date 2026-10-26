"""trg_le_version (8.6): the optimistic-concurrency token bumps on user-meaningful change only.

Structural columns (account, amount, counterpart, source text) bump whoever writes them;
the user-facing ones (type, category, payee, dates, text, counter-account, currency) bump unless
settling is rewriting (`ledger.settling = 'on'`); flags and derivation never bump.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Connection, text

from tests.invariants.helpers import make_category, make_movement, scalar

MakeAccount = Callable[..., int]


def _version(conn: Connection, entry: int) -> int:
    return int(scalar(conn, "SELECT version FROM ledger_entry WHERE id = :i", i=entry))


def _update(conn: Connection, entry: int, assignment: str, settling: bool) -> int:
    """Apply an UPDATE and return the version delta."""
    before = _version(conn, entry)
    conn.execute(text(f"SET LOCAL ledger.settling = '{'on' if settling else 'off'}'"))
    conn.execute(text(f"UPDATE ledger_entry SET {assignment} WHERE id = :i"), {"i": entry})  # noqa: S608
    return _version(conn, entry) - before


@pytest.fixture
def entry(db_conn: Connection, make_account: MakeAccount) -> int:
    acct = make_account(db_conn)
    make_account(db_conn, name="Other")
    _, e = make_movement(db_conn, acct)
    return e


def test_a_new_entry_starts_at_version_one(db_conn: Connection, entry: int) -> None:
    assert _version(db_conn, entry) == 1


# structural: bumps whoever writes it, settling included
@pytest.mark.parametrize("settling", [False, True])
def test_amount_change_bumps_even_when_settling(db_conn: Connection, entry: int, settling: bool) -> None:
    assert _update(db_conn, entry, "amount = amount - 1", settling) == 1


@pytest.mark.parametrize("settling", [False, True])
def test_account_change_bumps_even_when_settling(
    db_conn: Connection, entry: int, make_account: MakeAccount, settling: bool
) -> None:
    other = make_account(db_conn, name="Third")
    assert _update(db_conn, entry, f"account_id = {other}", settling) == 1


@pytest.mark.parametrize("settling", [False, True])
def test_source_text_change_bumps_even_when_settling(db_conn: Connection, entry: int, settling: bool) -> None:
    assert _update(db_conn, entry, "source_text = 'Seeed Studio: jumper wires'", settling) == 1


@pytest.mark.parametrize("settling", [False, True])
def test_counterpart_change_bumps_even_when_settling(
    db_conn: Connection, make_account: MakeAccount, settling: bool
) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    _, ea = make_movement(db_conn, a)
    _, eb = make_movement(db_conn, b, amount=1000)
    db_conn.execute(
        text("UPDATE ledger_entry SET type = 'transfer' WHERE id IN (:a, :b)"), {"a": ea, "b": eb}
    )
    assert _update(db_conn, ea, f"counterpart_entry_id = {eb}", settling) == 1


# user-facing: bumps unless settling
USER_FACING = [
    "type = 'transfer'",
    "booked_on = DATE '2026-02-11'",
    "value_on = DATE '2026-02-11'",
    "description = 'd'",
    "note = 'n'",
]


@pytest.mark.parametrize("assignment", USER_FACING)
def test_user_facing_change_bumps_when_not_settling(db_conn: Connection, entry: int, assignment: str) -> None:
    assert _update(db_conn, entry, assignment, settling=False) == 1


@pytest.mark.parametrize("assignment", USER_FACING)
def test_user_facing_change_does_not_bump_when_settling(
    db_conn: Connection, entry: int, assignment: str
) -> None:
    assert _update(db_conn, entry, assignment, settling=True) == 0


def test_category_change_bumps_unless_settling(db_conn: Connection, entry: int) -> None:
    cat = make_category(db_conn, "Food")
    assert _update(db_conn, entry, f"category_id = {cat}", settling=True) == 0
    assert _update(db_conn, entry, "category_id = NULL", settling=True) == 0
    assert _update(db_conn, entry, f"category_id = {cat}", settling=False) == 1


def test_payee_change_bumps_unless_settling(db_conn: Connection, entry: int) -> None:
    payee = scalar(db_conn, "INSERT INTO payee (name) VALUES ('Shop') RETURNING id")
    assert _update(db_conn, entry, f"payee_id = {payee}", settling=True) == 0
    assert _update(db_conn, entry, "payee_id = NULL", settling=False) == 1


def test_counter_account_change_bumps_unless_settling(
    db_conn: Connection, entry: int, make_account: MakeAccount
) -> None:
    other = make_account(db_conn, name="Counter")
    db_conn.execute(text("UPDATE ledger_entry SET type = 'transfer' WHERE id = :i"), {"i": entry})
    assert _update(db_conn, entry, f"counter_account_id = {other}", settling=True) == 0
    assert _update(db_conn, entry, "counter_account_id = NULL", settling=False) == 1


# never bumps
@pytest.mark.parametrize("settling", [False, True])
def test_flags_and_derivation_never_bump(db_conn: Connection, entry: int, settling: bool) -> None:
    assert _update(db_conn, entry, "review_flags = ARRAY['unconfirmed','unclassified']", settling) == 0
    assert _update(db_conn, entry, 'derivation = \'{"type": {"pass": "rule"}}\'::jsonb', settling) == 0


@pytest.mark.parametrize("settling", [False, True])
@pytest.mark.parametrize(
    "assignment",
    ["amount = amount", "booked_on = booked_on", "note = note", "type = type", "account_id = account_id"],
)
def test_an_identical_update_does_not_bump(
    db_conn: Connection, entry: int, assignment: str, settling: bool
) -> None:
    """Settle idempotence: rewriting what is already there leaves the token alone."""
    assert _update(db_conn, entry, assignment, settling) == 0


def test_a_second_identical_settle_style_rewrite_leaves_the_version_unchanged(
    db_conn: Connection, entry: int
) -> None:
    db_conn.execute(text("SET LOCAL ledger.settling = 'on'"))
    stmt = text(
        "UPDATE ledger_entry SET review_flags = ARRAY['unclassified'], derivation = '{}'::jsonb, "
        "note = 'x' WHERE id = :i"
    )
    db_conn.execute(stmt, {"i": entry})
    first = _version(db_conn, entry)
    db_conn.execute(stmt, {"i": entry})
    assert _version(db_conn, entry) == first == 1


def test_one_statement_changing_several_columns_bumps_once(db_conn: Connection, entry: int) -> None:
    assert (
        _update(db_conn, entry, "amount = amount - 1, note = 'n', booked_on = DATE '2026-02-12'", False) == 1
    )


def test_the_setting_is_read_per_statement_and_unset_means_not_settling(
    db_conn: Connection, entry: int
) -> None:
    before = _version(db_conn, entry)
    db_conn.execute(
        text("UPDATE ledger_entry SET note = 'n' WHERE id = :i"), {"i": entry}
    )  # setting never set
    assert _version(db_conn, entry) == before + 1


def test_version_counts_each_bumping_update(db_conn: Connection, entry: int) -> None:
    for n in range(3):
        db_conn.execute(text("UPDATE ledger_entry SET note = :n WHERE id = :i"), {"n": f"v{n}", "i": entry})
    assert _version(db_conn, entry) == 4
