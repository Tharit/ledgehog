"""trg_entry_source_fixed (8.5c): an entry is never moved between sources."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, text

from tests.invariants.helpers import RAISE_EXCEPTION, fire_deferred, make_movement, rejects, scalar

MakeAccount = Callable[..., int]


def test_moving_an_entry_to_another_source_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    _, entry = make_movement(db_conn, acct)
    other, _ = make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="its source transaction is fixed"):
        db_conn.execute(
            text("UPDATE ledger_entry SET source_transaction_id = :s WHERE id = :e"), {"s": other, "e": entry}
        )


def test_detaching_an_entry_from_its_source_is_refused_by_the_trigger_before_the_check(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    _, entry = make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="its source transaction is fixed"):
        db_conn.execute(
            text("UPDATE ledger_entry SET source_transaction_id = NULL WHERE id = :e"), {"e": entry}
        )


def test_rewriting_the_same_source_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    src, entry = make_movement(db_conn, acct)
    db_conn.execute(
        text("UPDATE ledger_entry SET source_transaction_id = :s WHERE id = :e"), {"s": src, "e": entry}
    )
    fire_deferred(db_conn)


def test_updating_other_columns_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    _, entry = make_movement(db_conn, acct)
    db_conn.execute(text("UPDATE ledger_entry SET note = 'n', description = 'd' WHERE id = :e"), {"e": entry})
    assert scalar(db_conn, "SELECT note FROM ledger_entry WHERE id = :e", e=entry) == "n"
