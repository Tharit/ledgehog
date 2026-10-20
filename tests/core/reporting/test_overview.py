"""The Overview's figures (core/reporting/overview.py)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection

from app.core.accounts import AccountView, list_accounts
from app.core.reporting import (
    EMPTY,
    Line,
    NetWorthSince,
    Unvalued,
    UnvaluedAccounts,
    accounts_by_data_age,
    by_category,
    entry_filter,
    overview,
    savings_over_time,
)
from tests.core.reporting.helpers import TODAY, household, listed
from tests.fixtures import ledger_seed as seed

D = date


def _view(
    id: int, last: date | None, order: int = 0, closed: date | None = None, balance: int = 0
) -> AccountView:
    return AccountView(
        id=id,
        name=f"A{id}",
        kind="checking",
        currency="EUR",
        external_ref=None,
        closed_on=closed,
        sort_order=order,
        note=None,
        icon=None,
        color=None,
        synced=True,
        synced_through=last,
        last_data_on=last,
        unexplained_difference=None,
        anchored=True,
        balance=balance,
    )


def test_accounts_by_data_age_stalest_first_never_first_ties_by_sort_order_then_id():
    views = [
        _view(1, D(2026, 10, 19)),
        _view(2, D(2026, 9, 1), order=5),
        _view(3, None, order=9),
        _view(4, D(2026, 9, 1), order=1),
        _view(5, D(2026, 9, 1), order=1),
        _view(6, None, order=2),
    ]
    got = accounts_by_data_age(views, TODAY)
    assert [a.view.id for a in got] == [6, 3, 4, 5, 2, 1]
    assert [a.data_age_days for a in got] == [None, None, 49, 49, 49, 1]


def test_a_closed_account_is_listed_only_while_it_holds_a_balance():
    views = [
        _view(1, D(2026, 10, 1), closed=D(2026, 10, 2), balance=0),
        _view(2, D(2026, 10, 1), closed=D(2026, 10, 2), balance=-50),
        _view(3, D(2026, 10, 1)),
    ]
    assert [a.view.id for a in accounts_by_data_age(views, TODAY)] == [2, 3]


def test_accounts_by_data_age_reads_the_real_data_age(ledger: Connection):
    a = seed.account(ledger, "Fed")
    never = seed.account(ledger, "Never fed")
    got = accounts_by_data_age(list_accounts(ledger), TODAY)
    assert {x.view.id for x in got} == {a, never}
    assert all(x.data_age_days is None for x in got)  # nothing was ever synced or recorded


def test_net_worth_today_is_every_balance_and_since_cuts_at_last_months_end(ledger: Connection):
    household(ledger)
    nw = overview(ledger, TODAY).net_worth
    giro = 100_000 + 249_000 + 282_200  # opening, September's flows, October's with the transfers
    cash = 5_000 - 1_200 + 5_000
    assert nw.total == giro + cash == 640_000
    assert nw.unvalued == (UnvaluedAccounts("USD", 28_000, 1),)  # shown, never counted as zero
    sep_30 = (100_000 + 249_000) + 5_000  # the balances at the end of September
    assert nw.since == NetWorthSince(D(2026, 9, 30), nw.total - sep_30)


def test_an_entry_dated_after_today_counts_in_the_figure_and_in_the_change(ledger: Connection):
    acct = seed.account(ledger)
    seed.entry(ledger, acct, amount=1_000, on=D(2026, 9, 1))
    seed.entry(ledger, acct, amount=250, on=D(2026, 11, 3))
    nw = overview(ledger, TODAY).net_worth
    assert nw.total == 1_250
    assert nw.since == NetWorthSince(D(2026, 9, 30), 250)


def test_since_is_none_when_nothing_existed_at_last_months_end(ledger: Connection):
    acct = seed.account(ledger)
    seed.entry(ledger, acct, amount=1_000, on=D(2026, 10, 2))
    nw = overview(ledger, TODAY).net_worth
    assert nw.total == 1_000 and nw.since is None


def test_unpaired_transfers_are_all_legs_without_a_partner_at_any_date(ledger: Connection):
    household(ledger)
    old = seed.account(ledger, "Old")
    seed.entry(ledger, old, amount=-900, on=D(2024, 1, 5), type="transfer")
    got = overview(ledger, TODAY).net_worth.unpaired_transfers
    assert got == Line(-7_900, 3)  # -4000 and -3000 in October, -900 two years ago; the pair is not in
    # the drill-down the Overview links to: transfers carrying the waiting or unmatched flag
    assert listed(ledger, types=("transfer",), flags=("waiting", "unmatched_transfer")) == 2


def test_unpaired_foreign_legs_are_unvalued_not_zero(ledger: Connection):
    usd = seed.account(ledger, "Card", currency="USD", kind="card")
    seed.entry(ledger, usd, amount=-900, on=D(2026, 10, 5), type="transfer")
    assert overview(ledger, TODAY).net_worth.unpaired_transfers == Line(None, 1, (Unvalued("USD", -900, 1),))


def test_the_savings_cards_come_from_the_same_computation_as_the_report(ledger: Connection):
    household(ledger)
    ov = overview(ledger, TODAY)
    months = savings_over_time(ledger, entry_filter(D(2025, 10, 1), D(2026, 9, 30)), "month")
    assert ov.last_12.savings == months.total  # the span's rate, not the mean of twelve
    assert (ov.last_12.start, ov.last_12.end) == (D(2025, 10, 1), D(2026, 9, 30))
    assert ov.last_month.savings == months.savings[-1]
    assert (ov.last_month.start, ov.last_month.end) == (D(2026, 9, 1), D(2026, 9, 30))
    october = savings_over_time(ledger, entry_filter(D(2026, 10, 1), TODAY), "month")
    assert ov.this_month.savings == october.total
    assert (ov.this_month.start, ov.this_month.end) == (D(2026, 10, 1), TODAY)


def test_spend_is_the_by_category_total_of_the_same_range(ledger: Connection):
    household(ledger)
    ov = overview(ledger, TODAY)
    october = by_category(ledger, entry_filter(D(2026, 10, 1), TODAY), "expense")
    assert ov.spend_this_month.spend == october.total
    assert ov.spend_this_month.unclassified_out == october.unclassified_out == Line(-300, 1)
    assert ov.spend_this_month.reconciliations == october.reconciliations == Line(-700, 1)
    sep = by_category(ledger, entry_filter(D(2026, 9, 1), D(2026, 9, 30)), "expense")
    assert ov.spend_last_month.spend == sep.total == Line(-49_500, 4)


def test_last_month_to_date_is_clamped_to_the_shorter_month(ledger: Connection):
    acct = seed.account(ledger)
    food = seed.category(ledger, "Food")
    seed.entry(ledger, acct, amount=-100, on=D(2026, 9, 29), category_id=food)
    seed.entry(ledger, acct, amount=-200, on=D(2026, 9, 30), category_id=food)
    on_31st = overview(ledger, D(2026, 10, 31))
    assert (on_31st.spend_last_month_to_date.start, on_31st.spend_last_month_to_date.end) == (
        D(2026, 9, 1),
        D(2026, 9, 30),
    )
    assert on_31st.spend_last_month_to_date.spend == Line(-300, 2)
    on_30th = overview(ledger, D(2026, 10, 30))
    assert on_30th.spend_last_month_to_date.spend == Line(-300, 2)
    on_29th = overview(ledger, D(2026, 10, 29))
    assert on_29th.spend_last_month_to_date.spend == Line(-100, 1)
    assert on_29th.spend_last_month.spend == Line(-300, 2)  # the whole of last month, whatever the day


def test_the_first_of_the_month_has_nothing_this_month_so_far(ledger: Connection):
    acct = seed.account(ledger)
    food = seed.category(ledger, "Food")
    seed.entry(ledger, acct, amount=-100, on=D(2026, 9, 29), category_id=food)
    ov = overview(ledger, D(2026, 10, 1))
    assert ov.spend_this_month.spend == EMPTY
    assert ov.this_month.savings.rate_bp is None
    assert ov.net_worth.since == NetWorthSince(D(2026, 9, 30), 0)


def test_an_empty_ledger_has_an_overview(ledger: Connection):
    ov = overview(ledger, TODAY)
    assert ov.accounts == () and ov.net_worth.total == 0 and ov.net_worth.since is None
    assert ov.last_12.savings.rate_bp is None
