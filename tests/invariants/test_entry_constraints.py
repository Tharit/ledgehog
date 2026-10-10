"""ledger_entry's declarative invariants: row CHECKs, composite FK, and unique partial indexes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Connection, text

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    FK_VIOLATION,
    UNIQUE_VIOLATION,
    fire_deferred,
    make_balance_record,
    make_category,
    make_derived_entry,
    make_entry,
    make_movement,
    make_source,
    rejects,
    scalar,
)

MakeAccount = Callable[..., int]


@pytest.fixture
def uninterpreted(db_conn: Connection, make_account: MakeAccount) -> tuple[int, int, int]:
    """(account, source, entry) of a movement with type NULL: not yet interpreted."""
    acct = make_account(db_conn)
    src = make_source(db_conn, acct)
    return acct, src, make_entry(db_conn, src, type=None)


def test_an_uninterpreted_movement_is_accepted(
    db_conn: Connection, uninterpreted: tuple[int, int, int]
) -> None:
    fire_deferred(db_conn)


def _update(conn: Connection, entry: int, assignment: str) -> None:
    conn.execute(text(f"UPDATE ledger_entry SET {assignment} WHERE id = :i"), {"i": entry})  # noqa: S608


def test_a_category_implies_a_flow(db_conn: Connection, uninterpreted: tuple[int, int, int]) -> None:
    _, _, entry = uninterpreted
    cat = make_category(db_conn, "Food")
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_category_only_flow"):
        _update(db_conn, entry, f"category_id = {cat}")
    _update(db_conn, entry, f"type = 'flow', category_id = {cat}")


def test_a_payee_implies_a_flow(db_conn: Connection, uninterpreted: tuple[int, int, int]) -> None:
    _, _, entry = uninterpreted
    payee = scalar(db_conn, "INSERT INTO payee (name) VALUES ('Shop') RETURNING id")
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_payee_only_flow"):
        _update(db_conn, entry, f"type = 'transfer', payee_id = {payee}")
    _update(db_conn, entry, f"type = 'flow', payee_id = {payee}")


def test_a_counter_account_implies_a_transfer(
    db_conn: Connection, make_account: MakeAccount, uninterpreted: tuple[int, int, int]
) -> None:
    _, _, entry = uninterpreted
    other = make_account(db_conn, name="Other")
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_counter_account_only_transfer"):
        _update(db_conn, entry, f"type = 'flow', counter_account_id = {other}")
    _update(db_conn, entry, f"type = 'transfer', counter_account_id = {other}")


def test_a_counter_account_is_never_the_entrys_own(
    db_conn: Connection, uninterpreted: tuple[int, int, int]
) -> None:
    acct, _, entry = uninterpreted
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_counter_account_not_own"):
        _update(db_conn, entry, f"type = 'transfer', counter_account_id = {acct}")


def test_only_transfers_have_a_counterpart(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    _, e1 = make_movement(db_conn, acct)
    _, e2 = make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_counterpart_only_transfer"):
        _update(db_conn, e1, f"counterpart_entry_id = {e2}")


def test_an_entry_is_not_its_own_counterpart(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    _, e1 = make_movement(db_conn, acct)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_not_self_counterpart"):
        _update(db_conn, e1, "type = 'transfer', counterpart_entry_id = id")


def test_zero_amount_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    src = make_source(db_conn, make_account(db_conn))
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ledger_entry_amount_check"):
        make_entry(db_conn, src, amount=0)


def test_an_entry_is_a_movement_or_derived_never_both_or_neither(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    src = make_source(db_conn, acct)
    rec = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1))
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_entry_kind"):
        make_entry(db_conn, src, type="opening", balance_record_id=rec)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_entry_kind"):
        db_conn.execute(
            text(
                "INSERT INTO ledger_entry (account_id, type, amount, currency, booked_on) "
                "VALUES (:a, 'flow', -1, 'EUR', DATE '2026-02-10')"
            ),
            {"a": acct},
        )


def test_derived_entry_types_follow_the_record_link(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    src = make_source(db_conn, acct)
    rec = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1))
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_balance_types"):
        make_entry(db_conn, src, type="opening")  # an opening without a record
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_balance_types"):
        make_derived_entry(db_conn, acct, rec, type="flow", booked_on=date(2026, 1, 1))


def test_a_derived_entry_is_complete(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    rec = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1))
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_balance_types"):
        db_conn.execute(
            text(
                "INSERT INTO ledger_entry (account_id, balance_record_id, amount, currency, booked_on) "
                "VALUES (:a, :r, 5, 'EUR', DATE '2026-01-01')"
            ),
            {"a": acct, "r": rec},
        )


def test_only_a_movement_carries_a_document(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    rec = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1))
    doc = scalar(
        db_conn,
        "INSERT INTO external_document (provider, external_id, occurred_on, total, currency, raw) "
        "VALUES ('p', 'x', DATE '2026-01-01', -1, 'EUR', '{}') RETURNING id",
    )
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_document_on_movement"):
        make_derived_entry_with_document(db_conn, acct, rec, doc)


def make_derived_entry_with_document(conn: Connection, acct: int, rec: int, doc: int) -> None:
    conn.execute(
        text(
            "INSERT INTO ledger_entry (account_id, balance_record_id, type, amount, currency, "
            "booked_on, document_id) "
            "VALUES (:a, :r, 'opening', 5, 'EUR', DATE '2026-01-01', :d)"
        ),
        {"a": acct, "r": rec, "d": doc},
    )


def test_an_entry_is_denominated_in_its_accounts_currency(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    src = make_source(db_conn, make_account(db_conn, currency="EUR"))
    with rejects(db_conn, sqlstate=FK_VIOLATION, constraint="fk_entry_account_currency"):
        make_entry(db_conn, src, currency="USD")


# ---- unique partial indexes


def test_at_most_one_opening_per_account(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    r1 = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1))
    r2 = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 2))
    make_derived_entry(db_conn, acct, r1, type="opening", booked_on=date(2026, 1, 1))
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_le_one_opening"):
        make_derived_entry(db_conn, acct, r2, type="opening", booked_on=date(2026, 1, 2))
    make_derived_entry(db_conn, acct, r2, type="reconciliation", booked_on=date(2026, 1, 2))


def test_one_derived_entry_per_balance_record(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    rec = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1))
    make_derived_entry(db_conn, acct, rec, type="opening", booked_on=date(2026, 1, 1))
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_le_balance_record"):
        make_derived_entry(db_conn, acct, rec, type="reconciliation", booked_on=date(2026, 1, 1))


def test_deleting_a_balance_record_takes_its_derived_entry_with_it(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    rec = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1))
    entry = make_derived_entry(db_conn, acct, rec, type="opening", booked_on=date(2026, 1, 1))
    db_conn.execute(text("DELETE FROM balance_record WHERE id = :i"), {"i": rec})
    fire_deferred(db_conn)
    assert scalar(db_conn, "SELECT count(*) FROM ledger_entry WHERE id = :i", i=entry) == 0


def test_at_most_one_transfer_entry_per_source(db_conn: Connection, make_account: MakeAccount) -> None:
    """A split produces only additional flows (I31)."""
    acct = make_account(db_conn)
    other = make_account(db_conn, name="Other")
    src = make_source(db_conn, acct, amount=-3000)
    make_entry(db_conn, src, amount=-1000, type="transfer", counter_account_id=other)
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_le_one_transfer_per_source"):
        make_entry(db_conn, src, amount=-2000, type="transfer", counter_account_id=other)
    make_entry(db_conn, src, amount=-2000, type="flow")


def _document(conn: Connection, external_id: str) -> int:
    return int(
        scalar(
            conn,
            "INSERT INTO external_document (provider, external_id, occurred_on, total, currency, raw) "
            "VALUES ('p', :x, DATE '2026-02-10', -1000, 'EUR', '{}') RETURNING id",
            x=external_id,
        )
    )


def test_a_document_is_carried_by_at_most_one_entry(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    doc = _document(db_conn, "d1")
    _, e1 = make_movement(db_conn, acct)
    _, e2 = make_movement(db_conn, acct)
    _update(db_conn, e1, f"document_id = {doc}")
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_le_document"):
        _update(db_conn, e2, f"document_id = {doc}")


def test_a_transaction_has_at_most_one_entry_carrying_a_document(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    src = make_source(db_conn, acct, amount=-3000)
    e1 = make_entry(db_conn, src, amount=-1000)
    e2 = make_entry(db_conn, src, amount=-2000)
    _update(db_conn, e1, f"document_id = {_document(db_conn, 'd1')}")
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_le_document_per_transaction"):
        _update(db_conn, e2, f"document_id = {_document(db_conn, 'd2')}")


def test_a_carried_document_cannot_be_deleted(db_conn: Connection, make_account: MakeAccount) -> None:
    from tests.invariants.helpers import RESTRICT_VIOLATION

    _, e1 = make_movement(db_conn, make_account(db_conn))
    doc = _document(db_conn, "d1")
    _update(db_conn, e1, f"document_id = {doc}")
    with rejects(db_conn, sqlstate=RESTRICT_VIOLATION, constraint="fk_le_document"):
        db_conn.execute(text("DELETE FROM external_document WHERE id = :i"), {"i": doc})
