"""trg_transfer_pair / check_transfer_pair (8.3, I10): mutual, distinct accounts, opposing signs,
equal-and-opposite amounts within one currency, counter-account = partner's account. Deferred."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, text

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    RAISE_EXCEPTION,
    UNIQUE_VIOLATION,
    fire_deferred,
    make_entry,
    make_source,
    pair,
    rejects,
    scalar,
)

MakeAccount = Callable[..., int]


def _leg(conn: Connection, account: int, amount: int, counter: int | None, currency: str = "EUR") -> int:
    src = make_source(conn, account, amount=amount, currency=currency)
    return make_entry(conn, src, type="transfer", counter_account_id=counter)


def _pair_of_legs(conn: Connection, make_account: MakeAccount) -> tuple[int, int, int, int]:
    a = make_account(conn, name="A")
    b = make_account(conn, name="B")
    ea = _leg(conn, a, -500, b)
    eb = _leg(conn, b, 500, a)
    pair(conn, ea, eb)
    fire_deferred(conn)
    return a, b, ea, eb


def test_a_proper_pair_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    _pair_of_legs(db_conn, make_account)


def test_an_open_leg_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    _leg(db_conn, a, -500, b)
    _leg(db_conn, a, -700, None)
    fire_deferred(db_conn)


def test_a_cross_currency_pair_needs_only_opposing_signs(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    a = make_account(db_conn, name="A")
    u = make_account(db_conn, name="U", currency="USD")
    ea = _leg(db_conn, a, -1000, u)
    eu = _leg(db_conn, u, 1090, a, currency="USD")
    pair(db_conn, ea, eu)
    fire_deferred(db_conn)


def test_a_non_mutual_link_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    a, b, ea, eb = _pair_of_legs(db_conn, make_account)
    db_conn.execute(
        text("UPDATE ledger_entry SET counterpart_entry_id = NULL WHERE id IN (:a, :b)"), {"a": ea, "b": eb}
    )
    fire_deferred(db_conn)
    db_conn.execute(
        text("UPDATE ledger_entry SET counterpart_entry_id = :b WHERE id = :a"), {"a": ea, "b": eb}
    )
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="counterpart link is not mutual"):
        fire_deferred(db_conn)


def test_clearing_one_leg_of_a_pair_is_refused_through_the_partner_check(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """The partner the row pointed at before is re-checked, so a half-broken pair cannot commit."""
    _, _, ea, _ = _pair_of_legs(db_conn, make_account)
    db_conn.execute(text("UPDATE ledger_entry SET counterpart_entry_id = NULL WHERE id = :a"), {"a": ea})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="another entry still points at it"):
        fire_deferred(db_conn)


def test_clearing_both_legs_together_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    _, _, ea, eb = _pair_of_legs(db_conn, make_account)
    db_conn.execute(
        text("UPDATE ledger_entry SET counterpart_entry_id = NULL WHERE id IN (:a, :b)"), {"a": ea, "b": eb}
    )
    fire_deferred(db_conn)


def test_retyping_one_leg_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    """type is a watched column. The type CHECKs fire first, so also clear what only a transfer may hold."""
    _, _, ea, eb = _pair_of_legs(db_conn, make_account)
    db_conn.execute(
        text(
            "UPDATE ledger_entry SET type = 'flow', counterpart_entry_id = NULL, "
            "counter_account_id = NULL WHERE id = :a"
        ),
        {"a": ea},
    )
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="another entry still points at it"):
        fire_deferred(db_conn)
    assert eb


def test_both_legs_on_one_account_are_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    ea = _leg(db_conn, a, -500, b)
    ea2 = _leg(db_conn, a, 500, b)
    pair(db_conn, ea, ea2)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="both transfer legs are on account"):
        fire_deferred(db_conn)


def test_same_sign_legs_are_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    ea = _leg(db_conn, a, -500, b)
    eb = _leg(db_conn, b, -500, a)
    pair(db_conn, ea, eb)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="opposing signs"):
        fire_deferred(db_conn)


def test_same_currency_amounts_must_be_equal_and_opposite(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    ea = _leg(db_conn, a, -500, b)
    eb = _leg(db_conn, b, 499, a)
    pair(db_conn, ea, eb)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="equal and opposite"):
        fire_deferred(db_conn)


def test_counter_account_must_be_the_partners_account(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    c = make_account(db_conn, name="C")
    ea = _leg(db_conn, a, -500, c)  # claims to be going to C, but is paired with B
    eb = _leg(db_conn, b, 500, a)
    pair(db_conn, ea, eb)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="is not its partner's account"):
        fire_deferred(db_conn)


def test_a_missing_counter_account_on_a_paired_leg_is_refused(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    ea = _leg(db_conn, a, -500, None)
    eb = _leg(db_conn, b, 500, a)
    pair(db_conn, ea, eb)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="is not its partner's account"):
        fire_deferred(db_conn)


def test_two_entries_cannot_claim_the_same_partner(db_conn: Connection, make_account: MakeAccount) -> None:
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    ea = _leg(db_conn, a, -500, b)
    ea2 = _leg(db_conn, a, -500, b)
    eb = _leg(db_conn, b, 500, a)
    db_conn.execute(
        text("UPDATE ledger_entry SET counterpart_entry_id = :b WHERE id = :a"), {"a": ea, "b": eb}
    )
    with rejects(db_conn, sqlstate=UNIQUE_VIOLATION, constraint="ux_le_counterpart"):
        db_conn.execute(
            text("UPDATE ledger_entry SET counterpart_entry_id = :b WHERE id = :a"), {"a": ea2, "b": eb}
        )


def test_changing_the_amount_of_one_leg_is_rechecked(db_conn: Connection, make_account: MakeAccount) -> None:
    """amount is a watched column. User-authored legs, so the source can follow and only the pair is off."""
    a = make_account(db_conn, name="A")
    b = make_account(db_conn, name="B")
    sa = make_source(db_conn, a, importer=None, amount=-500)
    ea = make_entry(db_conn, sa, type="transfer", counter_account_id=b)
    sb = make_source(db_conn, b, importer=None, amount=500)
    eb = make_entry(db_conn, sb, type="transfer", counter_account_id=a)
    pair(db_conn, ea, eb)
    fire_deferred(db_conn)
    db_conn.execute(text("UPDATE source_transaction SET amount = -600 WHERE id = :s"), {"s": sa})
    db_conn.execute(text("UPDATE ledger_entry SET amount = -600 WHERE id = :a"), {"a": ea})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="equal and opposite"):
        fire_deferred(db_conn)


def test_deleting_one_leg_leaves_the_other_an_open_leg(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """DELETE queues no pair check; the FK's SET NULL on the partner is an UPDATE of counterpart_entry_id,
    which the trigger accepts because nobody points at the survivor any more.  The source of the deleted
    leg goes with it, or its split check would object."""
    _, b, ea, eb = _pair_of_legs(db_conn, make_account)
    src_a = scalar(db_conn, "SELECT source_transaction_id FROM ledger_entry WHERE id = :i", i=ea)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": ea})
    db_conn.execute(text("DELETE FROM source_transaction WHERE id = :i"), {"i": src_a})
    fire_deferred(db_conn)
    row = db_conn.execute(
        text("SELECT counterpart_entry_id, counter_account_id, account_id FROM ledger_entry WHERE id = :i"),
        {"i": eb},
    ).one()
    assert row.counterpart_entry_id is None
    assert row.counter_account_id is not None  # kept: the counter-account survives the unpairing by deletion
    assert row.account_id == b


def test_pairing_checks_fire_for_the_row_that_is_gone(db_conn: Connection) -> None:
    db_conn.execute(text("SELECT check_transfer_pair(-1)"))


def test_a_transfer_leg_cannot_name_its_own_account_as_counter(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    a = make_account(db_conn, name="A")
    src = make_source(db_conn, a)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_counter_account_not_own"):
        make_entry(db_conn, src, type="transfer", counter_account_id=a)
