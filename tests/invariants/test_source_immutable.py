"""trg_source_immutable (8.1) and trg_authored_source_account (8.2c)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, text

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    RAISE_EXCEPTION,
    fire_deferred,
    link_account,
    make_entry,
    make_instance,
    make_movement,
    make_source,
    rejects,
    scalar,
)

MakeAccount = Callable[..., int]

IMMUTABLE = "is immutable"


@pytest.mark.parametrize(
    "assignment",
    [
        "amount = amount - 1",
        "booked_on = booked_on + 1",
        "value_on = DATE '2026-02-11'",
        "purpose = 'changed'",
        "counterparty_ref = 'x'",
        "source_id = 'other'",
        "importer = 'other'",
        "import_run_id = NULL",
        "raw = '{\"a\": 1}'::jsonb",
        "source_format = 'mt940'",
    ],
)
def test_imported_row_columns_are_immutable(
    assignment: str, db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    src, _ = make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=IMMUTABLE):
        db_conn.execute(text(f"UPDATE source_transaction SET {assignment} WHERE id = :i"), {"i": src})  # noqa: S608


def test_imported_row_cannot_change_account(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    src, _ = make_movement(db_conn, a)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=IMMUTABLE):
        db_conn.execute(
            text("UPDATE source_transaction SET account_id = :b WHERE id = :i"), {"b": b, "i": src}
        )


def test_imported_row_cannot_become_user_authored(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    src, _ = make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=IMMUTABLE):
        db_conn.execute(
            text(
                "UPDATE source_transaction SET importer = NULL, import_run_id = NULL, source_format = NULL "
                "WHERE id = :i"
            ),
            {"i": src},
        )


def test_duplicate_of_may_be_set_and_cleared(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    other, other_entry = make_movement(db_conn, acct)

    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": other_entry})
    db_conn.execute(
        text("UPDATE source_transaction SET duplicate_of = :o WHERE id = :i"), {"o": original, "i": other}
    )
    fire_deferred(db_conn)
    assert scalar(db_conn, "SELECT duplicate_of FROM source_transaction WHERE id = :i", i=other) == original

    db_conn.execute(text("UPDATE source_transaction SET duplicate_of = NULL WHERE id = :i"), {"i": other})
    make_entry(db_conn, other)
    fire_deferred(db_conn)
    assert scalar(db_conn, "SELECT duplicate_of FROM source_transaction WHERE id = :i", i=other) is None


def test_a_no_op_update_is_allowed(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    src, _ = make_movement(db_conn, acct)
    db_conn.execute(text("UPDATE source_transaction SET amount = amount WHERE id = :i"), {"i": src})


def test_duplicate_of_together_with_another_column_is_still_refused(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    other, other_entry = make_movement(db_conn, acct)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": other_entry})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=IMMUTABLE):
        db_conn.execute(
            text("UPDATE source_transaction SET duplicate_of = :o, amount = -9 WHERE id = :i"),
            {"o": original, "i": other},
        )


def test_instance_link_may_go_to_null_but_not_to_another_instance(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    inst = make_instance(db_conn, external_id="i1")
    other_inst = make_instance(db_conn, external_id="i2")
    src, _ = make_movement(db_conn, acct, instance_id=inst)

    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=IMMUTABLE):
        db_conn.execute(
            text("UPDATE source_transaction SET importer_instance_id = :o WHERE id = :i"),
            {"o": other_inst, "i": src},
        )
    db_conn.execute(
        text("UPDATE source_transaction SET importer_instance_id = NULL WHERE id = :i"), {"i": src}
    )
    assert scalar(db_conn, "SELECT importer FROM source_transaction WHERE id = :i", i=src) == "test"


def test_deleting_an_instance_nulls_the_link_through_the_trigger(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """The FK's ON DELETE SET NULL runs as an UPDATE and must pass the immutability trigger."""
    acct = make_account(db_conn)
    inst = make_instance(db_conn)
    src, _ = make_movement(db_conn, acct, instance_id=inst)
    db_conn.execute(text("DELETE FROM importer_instance WHERE id = :i"), {"i": inst})
    assert scalar(db_conn, "SELECT importer_instance_id FROM source_transaction WHERE id = :i", i=src) is None
    assert scalar(db_conn, "SELECT importer FROM source_transaction WHERE id = :i", i=src) == "test"


# ---- user-authored rows: editable, but keep their account, currency and user-authored status


def _user_row(conn: Connection, make_account: MakeAccount, **account_kw: Any) -> tuple[int, int, int]:
    acct = make_account(conn, **account_kw)
    src = make_source(conn, acct, importer=None, amount=-1000)
    entry = make_entry(conn, src)
    fire_deferred(conn)  # the row is committed state; only the edit below is pending
    return acct, src, entry


def test_user_authored_row_is_editable_with_its_entry(db_conn: Connection, make_account: MakeAccount) -> None:
    _, src, entry = _user_row(db_conn, make_account)
    db_conn.execute(
        text("UPDATE source_transaction SET amount = -2500, purpose = 'edited' WHERE id = :i"), {"i": src}
    )
    db_conn.execute(text("UPDATE ledger_entry SET amount = -2500 WHERE id = :i"), {"i": entry})
    fire_deferred(db_conn)


def test_user_authored_edit_without_updating_the_entry_fails_at_commit(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """trg_source_entries re-checks the split when a source's copied columns change."""
    _, src, _ = _user_row(db_conn, make_account)
    db_conn.execute(text("UPDATE source_transaction SET amount = -2500 WHERE id = :i"), {"i": src})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="split allocation mismatch"):
        fire_deferred(db_conn)


def test_user_authored_row_cannot_change_account(db_conn: Connection, make_account: MakeAccount) -> None:
    _, src, _ = _user_row(db_conn, make_account)
    other = make_account(db_conn, name="Other")
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="keeps its account and currency"):
        db_conn.execute(
            text("UPDATE source_transaction SET account_id = :o WHERE id = :i"), {"o": other, "i": src}
        )


def test_user_authored_row_cannot_change_currency(db_conn: Connection, make_account: MakeAccount) -> None:
    _, src, _ = _user_row(db_conn, make_account)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="keeps its account and currency"):
        db_conn.execute(text("UPDATE source_transaction SET currency = 'USD' WHERE id = :i"), {"i": src})


def test_user_authored_row_cannot_become_imported(db_conn: Connection, make_account: MakeAccount) -> None:
    _, src, _ = _user_row(db_conn, make_account)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_origin"):
        db_conn.execute(text("UPDATE source_transaction SET importer = 'x' WHERE id = :i"), {"i": src})


def test_a_source_keeps_its_origin(db_conn: Connection, make_account: MakeAccount) -> None:
    _, src, _ = _user_row(db_conn, make_account)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="keeps its origin"):
        db_conn.execute(text("UPDATE source_transaction SET origin = 'booking' WHERE id = :i"), {"i": src})


# ---- trg_authored_source_account


def test_user_authored_row_refused_on_a_synced_account(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    link_account(db_conn, acct, make_instance(db_conn))
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="is synced"):
        make_source(db_conn, acct, importer=None)


def test_user_authored_row_accepted_once_the_synced_account_is_closed(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    link_account(db_conn, acct, make_instance(db_conn))
    db_conn.execute(text("UPDATE account SET closed_on = DATE '2026-01-01' WHERE id = :i"), {"i": acct})
    src = make_source(db_conn, acct, importer=None)
    make_entry(db_conn, src)
    fire_deferred(db_conn)


def test_imported_row_is_accepted_on_a_synced_account(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    link_account(db_conn, acct, make_instance(db_conn))
    make_movement(db_conn, acct)
    fire_deferred(db_conn)


def test_editing_a_user_row_is_not_rechecked_against_syncedness(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """Entry is the only moment to check (trigger is BEFORE INSERT only)."""
    acct = make_account(db_conn)
    src = make_source(db_conn, acct, importer=None)
    entry = make_entry(db_conn, src)
    link_account(db_conn, acct, make_instance(db_conn))
    db_conn.execute(
        text("UPDATE source_transaction SET purpose = 'x', amount = -5 WHERE id = :i"), {"i": src}
    )
    db_conn.execute(text("UPDATE ledger_entry SET amount = -5 WHERE id = :i"), {"i": entry})
    fire_deferred(db_conn)
