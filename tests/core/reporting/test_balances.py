"""Balances and net worth at dates (core/reporting/balances.py)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Connection, text

from app.core.reporting import (
    UnvaluedAccounts,
    balances_on,
    balances_report,
    net_worth_at,
    net_worth_of,
)
from app.core.reporting.periods import TooManyPeriods
from tests.core.reporting.helpers import household, rate
from tests.fixtures import ledger_seed as seed

D = date


def _in_schema(conn: Connection, on: date) -> tuple[int, int]:
    row = conn.execute(text("SELECT net_worth, unvalued_accounts FROM net_worth_on(:d)"), {"d": on}).one()
    return int(row.net_worth), int(row.unvalued_accounts)


@pytest.mark.parametrize("with_rate", [False, True])
def test_the_balance_at_each_point_equals_the_schemas_net_worth_on(ledger: Connection, with_rate: bool):
    household(ledger)
    if with_rate:
        rate(ledger, "USD", D(2026, 8, 1), "2.0")
        rate(ledger, "USD", D(2026, 9, 25), "4.0")
    for on in (D(2026, 7, 31), D(2026, 8, 31), D(2026, 9, 30), D(2026, 10, 20)):
        worth = net_worth_of(balances_on(ledger, [on]))
        total, unvalued = _in_schema(ledger, on)
        assert (worth.total or 0, sum(u.accounts for u in worth.unvalued)) == (total, unvalued), on


def test_an_account_with_no_valued_balance_is_on_the_unvalued_line_never_zero(ledger: Connection):
    household(ledger)
    worth, existed = net_worth_at(ledger, D(2026, 9, 30))
    assert existed
    assert worth.unvalued == (UnvaluedAccounts("USD", 30_000, 1),)
    assert worth.total == 100_000 + 5_000 + 300_000 - 8_000 - 2_000 + 500 - 40_000 - 1_500
    only_foreign = net_worth_of([r for r in balances_on(ledger, [D(2026, 9, 30)]) if r.currency == "USD"])
    assert only_foreign.total is None  # balances exist and none could be valued


def test_through_all_takes_entries_after_the_date_and_a_cut_does_not(ledger: Connection):
    acct = seed.account(ledger)
    seed.entry(ledger, acct, amount=1_000, on=D(2026, 10, 1))
    seed.entry(ledger, acct, amount=500, on=D(2026, 11, 1))  # typed ahead of its date
    assert net_worth_at(ledger, D(2026, 10, 20))[0].total == 1_000
    assert net_worth_at(ledger, D(2026, 10, 20), through_all=True)[0].total == 1_500
    assert net_worth_at(ledger, D(2026, 9, 30))[1] is False  # nothing existed yet


def test_the_report_lists_month_ends_with_today_for_the_current_month(ledger: Connection):
    h = household(ledger)
    got = balances_report(ledger, D(2026, 8, 1), D(2026, 10, 31), D(2026, 10, 20))
    assert got.points == (D(2026, 8, 31), D(2026, 9, 30), D(2026, 10, 20))
    series = {a.account_id: a for a in got.accounts}
    giro = series[h.giro]
    assert giro.native[0] == 100_000  # the opening is in the balance
    assert giro.native[1] == 100_000 + 300_000 - 8_000 - 2_000 + 500 - 40_000 - 1_500
    assert giro.base == giro.native  # base currency passes through
    assert series[h.usd].native == (30_000, 30_000, 28_000)
    assert series[h.usd].base == (None, None, None)  # no rate: unvalued, not zero
    assert got.net_worth[0].total == 105_000
    assert got.net_worth[0].unvalued == (UnvaluedAccounts("USD", 30_000, 1),)
    # a reconciliation on 12 Oct is in October's point
    assert giro.native[2] - giro.native[1] == (
        300_000 - 9_000 + 700 + 1_000 + 2_500 - 300 - 700 - 5_000 - 4_000 - 3_000
    )


def test_a_valuation_steps_a_hand_kept_account(ledger: Connection):
    depot = seed.account(ledger, "Depot", kind="depot")
    seed.derived(ledger, depot, type="opening", on=D(2026, 1, 1), amount=10_000)
    seed.derived(ledger, depot, type="valuation", on=D(2026, 2, 15), amount=1_500)
    got = balances_report(ledger, D(2026, 1, 1), D(2026, 3, 31), D(2026, 10, 20))
    (series,) = got.accounts
    assert series.native == (10_000, 11_500, 11_500)


def test_no_balance_yet_is_none_and_a_closed_account_is_listed_only_if_it_held_a_balance(ledger: Connection):
    old = seed.account(ledger, "Old")
    seed.entry(ledger, old, amount=1_000, on=D(2026, 2, 10))
    seed.entry(ledger, old, amount=-1_000, on=D(2026, 3, 10))
    ledger.execute(text("UPDATE account SET closed_on = DATE '2026-03-10' WHERE id = :i"), {"i": old})
    never = seed.account(ledger, "Never used")
    ledger.execute(text("UPDATE account SET closed_on = DATE '2026-01-01' WHERE id = :i"), {"i": never})
    new = seed.account(ledger, "New")
    seed.entry(ledger, new, amount=700, on=D(2026, 3, 5))
    got = balances_report(ledger, D(2026, 1, 1), D(2026, 4, 30), D(2026, 10, 20))
    by_id = {a.account_id: a for a in got.accounts}
    assert never not in by_id  # closed, never held anything
    assert by_id[old].native == (0, 1_000, 0, 0)  # held 1,000 in February: listed, and zero again after
    assert by_id[old].base == (None, 1_000, 0, 0)  # nothing before its first entry; zero is zero
    assert by_id[new].base == (None, None, 700, 700)  # no balance yet


def test_more_than_120_month_ends_is_refused_naming_from(ledger: Connection):
    with pytest.raises(TooManyPeriods) as caught:
        balances_report(ledger, D(2015, 1, 1), D(2026, 12, 31), D(2026, 10, 20))
    assert caught.value.parameter == "from"


def test_each_kind_is_the_net_worth_of_its_listed_accounts_in_the_kind_order(ledger: Connection):
    depot = seed.account(ledger, "Depot", kind="depot")
    seed.derived(ledger, depot, type="opening", on=D(2026, 1, 1), amount=10_000)
    cash = seed.account(ledger, "Cash", kind="cash")
    seed.entry(ledger, cash, amount=400, on=D(2026, 1, 5))
    giro = seed.account(ledger, "Giro")
    seed.entry(ledger, giro, amount=1_000, on=D(2026, 1, 5))
    seed.account(ledger, "Unused savings", kind="savings")  # open, no entries: listed, holds nothing
    got = balances_report(ledger, D(2026, 1, 1), D(2026, 2, 28), D(2026, 10, 20))
    assert [k.kind for k in got.kinds] == ["checking", "savings", "cash", "depot"]  # not by name or creation
    by_kind = {k.kind: k.net_worth for k in got.kinds}
    assert [n.total for n in by_kind["depot"]] == [10_000, 10_000]
    assert [n.total for n in by_kind["savings"]] == [0, 0]
    for i, total in enumerate(got.net_worth):  # all valued: the kinds sum to the net worth
        assert sum(k.net_worth[i].total or 0 for k in got.kinds) == total.total


def test_a_kind_with_unvalued_and_valued_accounts_behaves_as_net_worth_does(ledger: Connection):
    eur = seed.account(ledger, "Card EUR", kind="card")
    seed.entry(ledger, eur, amount=-300, on=D(2026, 1, 5))
    usd = seed.account(ledger, "Card USD", currency="USD", kind="card")
    seed.entry(ledger, usd, amount=-500, on=D(2026, 1, 6), currency="USD")
    only_usd = seed.account(ledger, "Loan USD", currency="USD", kind="debt")
    seed.entry(ledger, only_usd, amount=-9_000, on=D(2026, 1, 6), currency="USD")
    got = balances_report(ledger, D(2026, 1, 1), D(2026, 1, 31), D(2026, 10, 20))
    by_kind = {k.kind: k.net_worth[0] for k in got.kinds}
    assert by_kind["card"].total == -300  # the valued one; the other is a remainder, never zero
    assert by_kind["card"].unvalued == (UnvaluedAccounts("USD", -500, 1),)
    assert by_kind["debt"].total is None  # balances exist and none could be valued
    assert by_kind["debt"].unvalued == (UnvaluedAccounts("USD", -9_000, 1),)


def test_a_closed_account_is_in_its_kind_only_when_it_is_listed(ledger: Connection):
    old = seed.account(ledger, "Old", kind="savings")
    seed.entry(ledger, old, amount=700, on=D(2026, 2, 10))
    ledger.execute(text("UPDATE account SET closed_on = DATE '2026-03-10' WHERE id = :i"), {"i": old})
    never = seed.account(ledger, "Never used", kind="debt")
    ledger.execute(text("UPDATE account SET closed_on = DATE '2026-01-01' WHERE id = :i"), {"i": never})
    got = balances_report(ledger, D(2026, 1, 1), D(2026, 2, 28), D(2026, 10, 20))
    assert [k.kind for k in got.kinds] == ["savings"]  # a kind of closed, empty accounts only is absent
    assert [n.total for n in got.kinds[0].net_worth] == [0, 700]
