"""Duplicates (I2, I32): trg_duplicate_state (deferred), fk_duplicate_same_account and neighbours.

A duplicate is kept but interpreted as nothing: no entries, same account as its original,
never chained, never pointing at a user-authored row.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, text

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    FK_VIOLATION,
    RAISE_EXCEPTION,
    fire_deferred,
    make_entry,
    make_movement,
    make_source,
    rejects,
    scalar,
)

MakeAccount = Callable[..., int]


def _mark(conn: Connection, row: int, of: int) -> None:
    conn.execute(text("UPDATE source_transaction SET duplicate_of = :o WHERE id = :i"), {"o": of, "i": row})


def _two_movements(conn: Connection, make_account: MakeAccount) -> tuple[int, int, int, int, int]:
    acct = make_account(conn)
    a, a_entry = make_movement(conn, acct)
    b, b_entry = make_movement(conn, acct)
    fire_deferred(conn)
    return acct, a, a_entry, b, b_entry


# ---- accepts


def test_insert_a_duplicate_directly(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    make_source(db_conn, acct, duplicate_of=original)
    fire_deferred(db_conn)


def test_mark_a_duplicate_after_removing_its_entry(db_conn: Connection, make_account: MakeAccount) -> None:
    _, a, _, b, b_entry = _two_movements(db_conn, make_account)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": b_entry})
    _mark(db_conn, b, a)
    fire_deferred(db_conn)
    assert scalar(db_conn, "SELECT duplicate_of FROM source_transaction WHERE id = :i", i=b) == a


def test_mark_repointing_rows_that_pointed_at_the_marked_row(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """Marking B as a duplicate of A while C points at B is fine once C is repointed to A in the same tx."""
    acct, a, _, b, b_entry = _two_movements(db_conn, make_account)
    c = make_source(db_conn, acct, duplicate_of=b)
    fire_deferred(db_conn)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": b_entry})
    _mark(db_conn, c, a)
    _mark(db_conn, b, a)
    fire_deferred(db_conn)


def test_clear_a_duplicate_by_creating_its_entry(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    dup = make_source(db_conn, acct, duplicate_of=original)
    fire_deferred(db_conn)
    db_conn.execute(text("UPDATE source_transaction SET duplicate_of = NULL WHERE id = :i"), {"i": dup})
    make_entry(db_conn, dup)
    fire_deferred(db_conn)


def test_deleting_an_original_with_its_duplicates_in_one_statement(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """NO ACTION (not RESTRICT) so one statement can delete a run's rows that point at each other."""
    acct = make_account(db_conn)
    original, entry = make_movement(db_conn, acct)
    dup = make_source(db_conn, acct, duplicate_of=original)
    fire_deferred(db_conn)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry})
    db_conn.execute(text("DELETE FROM source_transaction WHERE id IN (:a, :b)"), {"a": original, "b": dup})
    fire_deferred(db_conn)
    assert scalar(db_conn, "SELECT count(*) FROM source_transaction") == 0


# ---- rejects: entries


def test_marking_a_row_that_still_has_entries_is_refused(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    _, a, _, b, _ = _two_movements(db_conn, make_account)
    _mark(db_conn, b, a)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="duplicate source_transaction"):
        fire_deferred(db_conn)


def test_clearing_a_duplicate_without_creating_its_entry_is_refused(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    dup = make_source(db_conn, acct, duplicate_of=original)
    fire_deferred(db_conn)
    db_conn.execute(text("UPDATE source_transaction SET duplicate_of = NULL WHERE id = :i"), {"i": dup})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="is not a duplicate but its entries sum to 0"):
        fire_deferred(db_conn)


def test_check_uses_the_row_as_it_is_at_commit_not_as_queued(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """An insert queued as a duplicate and cleared again in the same tx is judged as a plain row."""
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    dup = make_source(db_conn, acct, duplicate_of=original)
    db_conn.execute(text("UPDATE source_transaction SET duplicate_of = NULL WHERE id = :i"), {"i": dup})
    make_entry(db_conn, dup)
    fire_deferred(db_conn)


# ---- rejects: chains, direction, authorship


def test_chain_duplicate_of_a_duplicate_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    dup = make_source(db_conn, acct, duplicate_of=original)
    fire_deferred(db_conn)
    make_source(db_conn, acct, duplicate_of=dup)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="which is itself a duplicate"):
        fire_deferred(db_conn)


def test_marking_a_row_others_point_at_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    acct, a, _, b, b_entry = _two_movements(db_conn, make_account)
    make_source(db_conn, acct, duplicate_of=b)
    fire_deferred(db_conn)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": b_entry})
    _mark(db_conn, b, a)  # c still points at b
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="others still point at it"):
        fire_deferred(db_conn)


def test_duplicate_of_a_user_authored_row_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    user_row = make_source(db_conn, acct, importer=None)
    make_entry(db_conn, user_row)
    make_source(db_conn, acct, duplicate_of=user_row)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="cannot duplicate row"):
        fire_deferred(db_conn)


def test_a_user_authored_row_cannot_be_marked(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    user_row = make_source(db_conn, acct, importer=None)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_origin"):
        _mark(db_conn, user_row, original)


# ---- rejects: DDL


def test_duplicate_must_be_on_the_originals_account(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    original, _ = make_movement(db_conn, a)
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_duplicate_same_account"):
        make_source(db_conn, b, duplicate_of=original)


def test_marking_across_accounts_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    original, _ = make_movement(db_conn, a)
    other, other_entry = make_movement(db_conn, b)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": other_entry})
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_duplicate_same_account"):
        _mark(db_conn, other, original)


def test_duplicate_of_a_missing_row_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_duplicate_same_account"):
        make_source(db_conn, acct, duplicate_of=987654321)


def test_a_row_cannot_duplicate_itself(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    src, entry = make_movement(db_conn, acct)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry})
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_duplicate_not_self"):
        _mark(db_conn, src, src)


def test_deleting_an_original_that_duplicates_still_point_at_is_refused(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    original, entry = make_movement(db_conn, acct)
    make_source(db_conn, acct, duplicate_of=original)
    fire_deferred(db_conn)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry})
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_duplicate_same_account"):
        db_conn.execute(text("DELETE FROM source_transaction WHERE id = :i"), {"i": original})
