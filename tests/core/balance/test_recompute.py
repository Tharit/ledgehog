"""recompute_derived: opening, reconciliation and valuation entries (spec §3.10, §5.10)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import Connection, text

from tests.core.balance.scene import Scene, day, prev
from tests.invariants.helpers import make_run

Make = Callable[..., int]

# ---- the anchor -----------------------------------------------------------------------------


def test_first_record_derives_the_opening_from_the_movements_up_to_its_date(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 10), -100)
    s.move(day(2, 1), 50)
    s.move(day(4, 5), -999)  # after the anchor: not in its interval
    s.manual(day(3, 31), 1000)
    s.recompute()
    assert s.derived() == [("opening", day(1, 9), 1050)]
    s.check()


def test_an_anchor_older_than_every_movement_dates_the_opening_the_day_before_the_anchor(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(2, 1), -100)
    s.manual(day(1, 1), 500)
    s.recompute()
    assert s.derived() == [("opening", prev(day(1, 1)), 500)]
    s.check()


def test_an_account_with_no_movements_dates_the_opening_the_day_before_the_anchor(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(3, 31), 500)
    s.recompute()
    assert s.derived() == [("opening", day(3, 30), 500)]
    s.check()


def test_a_depots_anchor_is_an_opening_and_the_next_record_a_valuation(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="depot")
    s.manual(day(1, 1), 5_000_000)
    s.manual(day(2, 1), 5_400_000)
    s.recompute()
    assert s.derived() == [("opening", date(2025, 12, 31), 5_000_000), ("valuation", day(2, 1), 400_000)]
    s.check()


def test_an_asset_account_derives_valuations_too(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account, kind="asset")
    s.manual(day(1, 1), 100)
    s.manual(day(2, 1), 90)
    s.recompute()
    assert s.derived()[1] == ("valuation", day(2, 1), -10)
    s.check()


# ---- the spec §4 worked examples ------------------------------------------------------------


def test_a_new_wallet_with_a_first_count_of_100_euro_opens_with_plus_10000(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="cash", name="Wallet")
    s.manual(day(1, 1), 10_000)
    s.recompute()
    assert s.derived() == [("opening", prev(day(1, 1)), 10_000)]


def test_counting_40_euro_against_a_ledger_of_80_reconciles_minus_4000(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="cash")
    s.manual(day(1, 1), 10_000)
    s.move(day(1, 5), -2_000)  # ledger 80
    s.manual(day(1, 31), 4_000)
    s.recompute()
    assert s.derived()[1] == ("reconciliation", day(1, 31), -4_000)
    s.check()


def test_counting_120_euro_against_a_ledger_of_80_reconciles_plus_4000(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="cash")
    s.manual(day(1, 1), 10_000)
    s.move(day(1, 5), -2_000)
    s.manual(day(1, 31), 12_000)
    s.recompute()
    assert s.derived()[1] == ("reconciliation", day(1, 31), 4_000)
    s.check()


def test_a_depot_valued_at_54000_against_a_ledger_of_50000_gets_a_valuation_of_400000(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="depot")
    s.manual(day(1, 1), 5_000_000)
    s.manual(day(2, 1), 5_400_000)
    s.recompute()
    assert s.derived()[-1] == ("valuation", day(2, 1), 400_000)
    s.check()


# ---- zero results ---------------------------------------------------------------------------


def test_a_zero_result_gives_no_entry_a_later_change_creates_one_and_back(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    second = s.manual(day(2, 1), 900)
    s.move(day(1, 15), -100)
    s.recompute()
    assert s.derived_of(second) is None  # 900 - 1000 - (-100) == 0
    assert len(s.derived()) == 1
    db_conn.execute(text("UPDATE balance_record SET balance = 850 WHERE id = :i"), {"i": second})
    s.recompute()
    assert s.derived_of(second) == ("reconciliation", day(2, 1), -50)
    db_conn.execute(text("UPDATE balance_record SET balance = 900 WHERE id = :i"), {"i": second})
    s.recompute()
    assert s.derived_of(second) is None
    s.check()


def test_a_zero_anchor_result_gives_no_opening(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 5), -100)
    s.manual(day(1, 31), -100)
    s.recompute()
    assert s.derived() == []
    s.check()


# ---- intervals ------------------------------------------------------------------------------


def test_an_entry_added_inside_an_interval_shrinks_that_intervals_reconciliation(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 10_000)
    second = s.manual(day(2, 1), 4_000)
    s.recompute()
    assert s.derived_of(second) == ("reconciliation", day(2, 1), -6_000)
    s.move(day(1, 20), -6_000)  # the toy sale
    s.recompute()
    assert s.derived_of(second) is None
    s.check()


def test_movements_after_the_last_record_belong_to_no_interval(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    s.move(day(3, 1), -400)
    s.recompute()
    assert s.derived() == [("opening", date(2025, 12, 31), 1000)]
    s.check()


def test_same_date_records_are_ordered_by_id_and_derived_entries_are_not_counted(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    run1 = make_run(db_conn, s.account, covered_through=day(3, 1))
    run2 = make_run(db_conn, s.account, covered_through=day(3, 1))
    s.move(day(1, 20), -300)
    a = s.reported(day(2, 1), 600, run_id=run1)
    b = s.reported(day(2, 1), 650, run_id=run2)
    s.recompute()
    assert s.derived_of(a) == ("reconciliation", day(2, 1), -100)  # (600-1000)-(-300)
    assert s.derived_of(b) == ("reconciliation", day(2, 1), 50)  # empty interval: 650-600
    s.check()


def test_a_movement_on_the_record_date_counts_towards_it(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    second = s.manual(day(2, 1), 900)
    s.move(day(2, 1), -100)
    s.recompute()
    assert s.derived_of(second) is None


# ---- idempotence ----------------------------------------------------------------------------


def test_a_second_recompute_changes_nothing_and_bumps_no_version(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 10), -100)
    s.manual(day(1, 31), 1000)
    s.manual(day(2, 28), 700)
    s.recompute()
    before = s.snapshot()
    assert len(before) == 2
    s.recompute()
    assert s.snapshot() == before  # same rows, same versions, no row rewritten (xmin)


def test_a_changed_amount_updates_in_place_keeps_the_id(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    second = s.manual(day(2, 1), 700)
    s.recompute()
    (before,) = [r for r in s.snapshot() if r.balance_record_id == second]
    s.move(day(1, 15), -100)
    s.recompute()
    (after,) = [r for r in s.snapshot() if r.balance_record_id == second]
    assert after.id == before.id and after.amount == -200 and after.version == before.version + 1
    s.check()


# ---- backfills ------------------------------------------------------------------------------


def test_a_backfill_before_the_opening_moves_it_and_preserves_the_balance_at_the_anchor(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(4, 1), -1000)  # the sync starts on 1 April
    s.manual(day(3, 31), 5_000)  # anchor; the opening is +5000 on 31 March - nothing before it
    s.recompute()
    assert s.derived() == [("opening", day(3, 30), 5_000)]
    s.move(day(1, 10), -100)
    s.move(day(2, 10), -200)
    s.recompute()
    # the movements netting -300 up to 31 March: the opening grows by 300, dated before the earliest
    assert s.derived() == [("opening", day(1, 9), 5_300)]
    s.check()


def test_a_backfill_that_reports_its_own_earlier_balance_becomes_the_new_anchor(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    old = s.manual(day(3, 31), 5_000)
    s.move(day(4, 10), -100)
    s.recompute()
    assert s.derived_of(old) == ("opening", day(3, 30), 5_000)
    s.move(day(2, 1), -300)
    new = s.reported(day(2, 15), 4_000)  # earlier than the old anchor
    s.recompute()
    assert s.derived_of(new) == ("opening", day(1, 31), 4_300)
    # (5000 - 4000) - (movements in (15 Feb, 31 Mar] = 0) = 1000
    assert s.derived_of(old) == ("reconciliation", day(3, 31), 1_000)
    s.check()


def test_the_old_depot_anchor_becomes_a_valuation_when_an_earlier_record_arrives(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="depot")
    old = s.manual(day(3, 31), 5_000)
    s.recompute()
    new = s.manual(day(1, 31), 4_000)
    s.recompute()
    assert s.derived_of(new) == ("opening", day(1, 30), 4_000)
    assert s.derived_of(old) == ("valuation", day(3, 31), 1_000)
    s.check()


def test_withdrawals_backfilled_before_the_first_count_adjust_the_opening(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="cash")
    s.manual(day(12, 31), 8_000)  # wallet counted EUR 80 first
    s.recompute()
    assert s.derived() == [("opening", day(12, 30), 8_000)]
    for month in range(1, 13):
        s.move(day(month, 5), 25_000)  # the counter-legs, in the wallet: a year netting +3000 EUR
    s.recompute()
    # opening = 8000 - 300000 = -292000 (EUR -2920), dated before the earliest entry
    assert s.derived() == [("opening", day(1, 4), -292_000)]
    s.check()


def test_a_count_dated_before_the_earliest_entry_becomes_the_anchor_and_today_reconciles_the_year(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="cash")
    today = s.manual(day(12, 31), 8_000)
    for month in range(1, 13):
        s.move(day(month, 5), 25_000)
    s.recompute()
    first = s.manual(day(1, 4), 10_000)  # EUR 100, the day before the earliest entry
    s.recompute()
    assert s.derived_of(first) == ("opening", day(1, 3), 10_000)
    # (8000 - 10000) - 300000: the unrecorded cash spending of the year
    assert s.derived_of(today) == ("reconciliation", day(12, 31), -302_000)
    s.check()


def test_deleting_the_anchor_makes_the_next_record_the_anchor(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 15), -100)
    first = s.manual(day(1, 1), 1000)
    second = s.manual(day(2, 1), 700)
    s.recompute()
    assert s.derived_of(second) == ("reconciliation", day(2, 1), -200)
    db_conn.execute(text("DELETE FROM balance_record WHERE id = :i"), {"i": first})
    s.recompute()
    assert s.derived() == [("opening", day(1, 14), 800)]
    assert s.derived_of(second) == ("opening", day(1, 14), 800)
    s.check()


def test_a_record_that_stops_counting_loses_its_derived_entry_at_the_next_recompute(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    run = make_run(db_conn, s.account, covered_through=day(3, 1))
    reported = s.reported(day(2, 1), 700, run_id=run)
    s.recompute()
    assert s.derived_of(reported) is not None
    db_conn.execute(
        text("UPDATE import_run SET status = 'reverted', reverted_at = finished_at WHERE id = :r"),
        {"r": run},
    )
    s.recompute()
    assert s.derived_of(reported) is None
    s.check()


def test_a_reverted_anchor_hands_the_opening_to_the_next_record(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    run = make_run(db_conn, s.account, covered_through=day(3, 1))
    reported = s.reported(day(1, 1), 1000, run_id=run)
    manual = s.manual(day(2, 1), 700)
    s.recompute()
    assert s.derived_of(reported) == ("opening", date(2025, 12, 31), 1000)
    db_conn.execute(
        text("UPDATE import_run SET status = 'reverted', reverted_at = finished_at WHERE id = :r"),
        {"r": run},
    )
    s.recompute()
    assert s.derived() == [("opening", day(1, 31), 700)]
    assert s.derived_of(manual) == ("opening", day(1, 31), 700)
    s.check()


def test_a_manual_anchor_meeting_its_first_reported_record_leaves_a_non_zero_reconciliation(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)  # the user's number
    s.move(day(1, 20), -100)
    reported = s.reported(day(2, 1), 800)  # the bank: 800, the ledger says 900
    s.recompute()
    assert s.derived_of(reported) == ("reconciliation", day(2, 1), -100)
    s.check()


# ---- records of other accounts, currency, anchoring -----------------------------------------


def test_derived_entries_carry_the_account_currency(db_conn: Connection, make_account: Make) -> None:
    acct = make_account(db_conn, name="Dollar", currency="USD")
    from tests.invariants.helpers import make_balance_record

    make_balance_record(db_conn, acct, balance_on=day(1, 1), balance=100, currency="USD")
    from app.core.balance.derived import recompute_derived

    recompute_derived(db_conn, acct)
    cur = db_conn.execute(
        text("SELECT currency, value_on, category_id, payee_id FROM ledger_entry WHERE account_id = :a"),
        {"a": acct},
    ).one()
    assert tuple(cur) == ("USD", None, None, None)


def test_an_account_without_records_has_no_derived_entries(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 10), -100)
    s.recompute()
    assert s.derived() == []
    s.check()


def test_recompute_touches_only_its_own_account(db_conn: Connection, make_account: Make) -> None:
    a = Scene(db_conn, make_account, name="A")
    b = Scene(db_conn, make_account, name="B")
    a.manual(day(1, 1), 100)
    b.manual(day(1, 1), 200)
    a.recompute()
    assert a.derived() != [] and b.derived() == []


def test_settling_leaves_derived_entries_alone(isolated_engine: object, make_account: Make) -> None:
    from sqlalchemy import Engine

    from app.core.settle.settle import settle

    engine: Engine = isolated_engine  # type: ignore[assignment]
    with engine.begin() as conn:
        s = Scene(conn, make_account)
        s.move(day(1, 10), -100)
        s.manual(day(1, 1), 1000)
        s.manual(day(2, 1), 500)
        s.recompute()
        account = s.account
    sql = (
        "SELECT id, version, review_flags, derivation::text AS d, xmin::text AS x FROM ledger_entry "
        "WHERE account_id = :a AND balance_record_id IS NOT NULL ORDER BY id"
    )
    with engine.connect() as conn:
        before = list(conn.execute(text(sql), {"a": account}).all())
    result = settle(engine)
    assert result.error is None
    with engine.connect() as conn:
        after = list(conn.execute(text(sql), {"a": account}).all())
    assert len(before) == 2 and before == after
    assert all(r.review_flags == [] for r in after)
