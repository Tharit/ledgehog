"""One identity per source row (I4): ck_one_identity, ux_source_source_id, ux_source_content_hash,
plus the neighbouring row-level CHECKs and composite FKs of source_transaction."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Connection

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    FK_VIOLATION,
    UNIQUE_VIOLATION,
    fire_deferred,
    make_entry,
    make_movement,
    make_run,
    make_source,
    rejects,
)

MakeAccount = Callable[..., int]


def test_source_id_alone_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    make_movement(db_conn, acct, source_id="bank-1")
    fire_deferred(db_conn)


def test_content_hash_alone_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    make_movement(db_conn, acct, content_hash="abc123")
    fire_deferred(db_conn)


def test_both_identities_are_rejected(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_one_identity"):
        make_source(db_conn, acct, source_id="a", content_hash="b")


def test_neither_identity_is_rejected(db_conn: Connection, make_account: MakeAccount) -> None:
    from sqlalchemy import text

    acct = make_account(db_conn)
    run = make_run(db_conn, acct)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_one_identity"):
        db_conn.execute(
            text(
                "INSERT INTO source_transaction (importer, import_run_id, account_id, source_format, "
                "amount, currency, booked_on, raw) "
                "VALUES ('t', :r, :a, 'camt053', -1, 'EUR', DATE '2026-02-10', '{}')"
            ),
            {"r": run, "a": acct},
        )


def test_source_id_unique_per_account(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    make_source(db_conn, acct, source_id="same")
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_source_source_id"):
        make_source(db_conn, acct, source_id="same")


def test_content_hash_unique_per_account(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    make_source(db_conn, acct, content_hash="h")
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_source_content_hash"):
        make_source(db_conn, acct, content_hash="h")


def test_identities_are_scoped_to_the_account(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    make_movement(db_conn, a, source_id="same")
    make_movement(db_conn, b, source_id="same")
    make_movement(db_conn, a, content_hash="h")
    make_movement(db_conn, b, content_hash="h")
    fire_deferred(db_conn)


def test_a_source_id_and_a_content_hash_with_the_same_text_do_not_collide(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    make_movement(db_conn, acct, source_id="x")
    make_movement(db_conn, acct, content_hash="x")
    fire_deferred(db_conn)


def test_a_duplicate_row_keeps_blocking_its_identity(db_conn: Connection, make_account: MakeAccount) -> None:
    """The index covers duplicates too, so the next fetch cannot re-import a duplicate (I4, I32)."""
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct, source_id="orig")
    make_source(db_conn, acct, source_id="dup", duplicate_of=original)
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_source_source_id"):
        make_source(db_conn, acct, source_id="dup")


def test_identity_is_free_again_once_the_row_is_deleted(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """Reverted rows are deleted, so their identities are free (schema comment on ux_source_*)."""
    from sqlalchemy import text

    acct = make_account(db_conn)
    src, entry = make_movement(db_conn, acct, source_id="gone")
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry})
    db_conn.execute(text("DELETE FROM source_transaction WHERE id = :i"), {"i": src})
    make_movement(db_conn, acct, source_id="gone")
    fire_deferred(db_conn)


def test_zero_amount_is_rejected(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="source_transaction_amount_check"):
        make_source(db_conn, acct, amount=0)


def test_user_authored_row_has_no_importer_run_or_format(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    from sqlalchemy import text

    acct = make_account(db_conn)
    run = make_run(db_conn, acct)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_user_row"):
        # importer NULL but a run attached
        db_conn.execute(
            text(
                "INSERT INTO source_transaction (import_run_id, account_id, source_id, amount, currency, "
                "booked_on, raw) VALUES (:r, :a, 'u', -1, 'EUR', DATE '2026-02-10', '{}')"
            ),
            {"r": run, "a": acct},
        )
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_user_row"):
        # importer set but no run
        db_conn.execute(
            text(
                "INSERT INTO source_transaction (importer, source_format, account_id, source_id, amount, "
                "currency, booked_on, raw) "
                "VALUES ('t', 'camt053', :a, 'u', -1, 'EUR', DATE '2026-02-10', '{}')"
            ),
            {"a": acct},
        )


def test_user_authored_row_is_accepted_on_an_unsynced_account(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    source = make_source(db_conn, acct, importer=None)
    make_entry(db_conn, source)
    fire_deferred(db_conn)


def test_user_authored_row_cannot_be_a_duplicate(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_user_row"):
        make_source(db_conn, acct, importer=None, duplicate_of=original)


def test_source_currency_must_be_its_accounts(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn, currency="EUR")
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_source_account_currency"):
        make_source(db_conn, acct, currency="USD")


def test_source_must_be_on_its_runs_account(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    run_on_a = make_run(db_conn, a)
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_source_run_account"):
        make_source(db_conn, b, run_id=run_on_a)


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        ({"instructed_amount": -5}, "ck_instructed_pair"),
        ({"instructed_amount": -5, "instructed_currency": "EUR"}, "ck_instructed_foreign"),
        ({"instructed_amount": 5, "instructed_currency": "USD"}, "ck_instructed_sign"),
    ],
)
def test_instructed_amount_rules(
    cols: dict[str, object], constraint: str, db_conn: Connection, make_account: MakeAccount
) -> None:
    from sqlalchemy import text

    acct = make_account(db_conn)
    run = make_run(db_conn, acct)
    params = {"r": run, "a": acct, "ia": cols.get("instructed_amount"), "ic": cols.get("instructed_currency")}
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint=constraint):
        db_conn.execute(
            text(
                "INSERT INTO source_transaction (importer, import_run_id, account_id, source_id, "
                "source_format, amount, currency, booked_on, raw, instructed_amount, instructed_currency) "
                "VALUES ('t', :r, :a, 's', 'camt053', -100, 'EUR', DATE '2026-02-10', '{}', :ia, :ic)"
            ),
            params,
        )


def test_valid_instructed_amount_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    from sqlalchemy import text

    acct = make_account(db_conn)
    run = make_run(db_conn, acct)
    src = db_conn.execute(
        text(
            "INSERT INTO source_transaction (importer, import_run_id, account_id, source_id, "
            "source_format, amount, currency, booked_on, raw, instructed_amount, instructed_currency) "
            "VALUES ('t', :r, :a, 's', 'camt053', -100, 'EUR', DATE '2026-02-10', '{}', -120, 'USD') "
            "RETURNING id"
        ),
        {"r": run, "a": acct},
    ).scalar_one()
    make_entry(db_conn, src)
    fire_deferred(db_conn)
