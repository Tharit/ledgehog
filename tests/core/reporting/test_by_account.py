"""Money by account (core/reporting/by_account.py) on a real database (spec §8, architecture §4.1, §8)."""

from __future__ import annotations

from datetime import date
from itertools import product
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.ledger import LedgerFilter, list_entries
from app.core.reporting import (
    EMPTY,
    AccountLink,
    ByAccount,
    Line,
    Stayed,
    TransferLink,
    add,
    by_account,
    by_category,
    entry_filter,
)
from tests.core.reporting.helpers import Household, household, listed, listed_base_sum, rate
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import pair

D = date
RANGES = [
    (D(2026, 9, 1), D(2026, 9, 30)),
    (D(2026, 10, 1), D(2026, 10, 31)),
    (D(2026, 8, 1), D(2026, 10, 20)),
]
OCT = (D(2026, 10, 1), D(2026, 10, 31))


def link_map(links: tuple[AccountLink, ...] | None) -> dict[int, Line]:
    assert links is not None
    return {k.account_id: k.line for k in links}


def leg(conn: Connection, account: int, amount: int, counter: int | None, on: date = OCT[0]) -> int:
    """A transfer leg with its counter-account (not paired)."""
    e = seed.entry(conn, account, amount=amount, on=on, type="transfer")
    conn.execute(
        text("UPDATE ledger_entry SET counter_account_id = :c WHERE id = :i"), {"c": counter, "i": e}
    )
    return e


def paired(conn: Connection, a: int, b: int, amount: int, on: date = OCT[0]) -> tuple[int, int]:
    """A paired transfer: `amount` (negative) out of `a`, into `b`."""
    out = leg(conn, a, amount, b, on)
    into = leg(conn, b, -amount, a, on)
    pair(conn, out, into)
    return out, into


@pytest.fixture
def seeded(ledger: Connection) -> Household:
    h = household(ledger)
    rate(ledger, "USD", D(2026, 10, 5), "1.25")  # October's USD entry is valued, September's are not
    return h


def _filters(h: Household) -> list[dict[str, Any]]:
    return [{}, {"tag_ids": (h.trip,)}]


@pytest.mark.parametrize("top", [None, 1, 2])
def test_a_kinds_links_sum_to_its_by_category_figures(ledger: Connection, seeded: Household, top: int | None):
    for (start, end), extra in product(RANGES, _filters(seeded)):
        flt = entry_filter(start, end, (), extra.get("tag_ids", ()))
        got = by_account(ledger, flt, top)
        for kind, links in (("income", got.income), ("expense", got.expense)):
            expected = by_category(ledger, flt, kind, top)
            tag = f"{kind} {start}..{end} {extra} top={top}"
            assert links.total == expected.total, tag
            roots = [r for r in expected.categories if r.parent_id is None]
            assert [c.category_id for c in links.categories] == [r.category_id for r in roots], tag
            for c, r in zip(links.categories, roots, strict=True):
                assert c.total == r.total, tag
                assert add(k.line for k in c.accounts) == r.total, tag
            assert add(c.total for c in links.categories) == expected.total, tag
            if top is None:
                assert links.slices is None and links.other is None
            else:
                assert expected.slices is not None
                assert links.slices == tuple(s.category_id for s in expected.slices), tag
                if expected.other is None:
                    assert links.other is None, tag
                else:
                    assert links.other is not None
                    assert add(k.line for k in links.other) == expected.other, tag


def test_a_child_categorys_entries_roll_up_into_its_top_level_parent_per_account(
    ledger: Connection, seeded: Household
):
    got = by_account(ledger, entry_filter(*OCT))
    food = next(c for c in got.expense.categories if c.category_id == seeded.food)
    # groceries (a child) of Giro and Cash, nothing booked to food itself in October
    assert link_map(food.accounts) == {seeded.giro: Line(-9_000, 1), seeded.cash: Line(-1_200, 1)}
    assert [k.account_id for k in food.accounts] == [seeded.giro, seeded.cash]  # by magnitude
    assert food.total == Line(-10_200, 2)
    assert seeded.groceries not in [c.category_id for c in got.expense.categories]  # top-level only


def test_slices_and_other_cut_per_account(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    big, mid, small = (seed.category(ledger, n) for n in ("Big", "Mid", "Small"))
    seed.entry(ledger, a, amount=-900, on=OCT[0], category_id=big)
    seed.entry(ledger, a, amount=-300, on=OCT[0], category_id=mid)
    seed.entry(ledger, b, amount=-200, on=OCT[0], category_id=mid)
    seed.entry(ledger, a, amount=-50, on=OCT[0], category_id=small)
    seed.entry(ledger, b, amount=-70, on=OCT[0], category_id=small)
    got = by_account(ledger, entry_filter(*OCT), top=1).expense
    assert got.slices == (big,) and got.total == Line(-1_520, 5)
    assert [c.category_id for c in got.categories] == [big, mid, small]
    assert link_map(got.other) == {a: Line(-350, 2), b: Line(-270, 2)}
    assert [k.account_id for k in got.other or ()] == [a, b]
    assert by_account(ledger, entry_filter(*OCT), top=3).expense.other is None


def test_a_link_with_no_entries_is_absent(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    food = seed.category(ledger, "Food")
    seed.entry(ledger, a, amount=-100, on=OCT[0], category_id=food)
    got = by_account(ledger, entry_filter(*OCT))
    assert link_map(got.expense.categories[0].accounts) == {a: Line(-100, 1)}
    assert b not in link_map(got.expense.categories[0].accounts)
    assert got.income.categories == () and got.income.total == EMPTY
    assert got.unclassified_in == got.unclassified_out == got.reconciliations == ()
    assert got.transfers == () and got.undrawn == EMPTY and got.stayed == ()


def test_unclassified_and_reconciliations_are_one_link_per_account(ledger: Connection, seeded: Household):
    got = by_account(ledger, entry_filter(*OCT))
    assert link_map(got.unclassified_in) == {seeded.giro: Line(2_500, 1)}
    assert link_map(got.unclassified_out) == {seeded.giro: Line(-300, 1)}  # an untyped entry included
    assert link_map(got.reconciliations) == {seeded.giro: Line(-700, 1)}
    # two reconciliations of opposite sign on one account are one net link; another account has its own
    cash = seeded.cash
    seed.derived(ledger, cash, type="reconciliation", on=D(2026, 10, 20), amount=900)
    seed.derived(ledger, cash, type="reconciliation", on=D(2026, 10, 21), amount=-400)
    again = by_account(ledger, entry_filter(*OCT))
    assert link_map(again.reconciliations) == {seeded.giro: Line(-700, 1), cash: Line(500, 2)}
    assert [k.account_id for k in again.reconciliations] == [seeded.giro, cash]  # by magnitude


def test_a_paired_transfer_is_counted_once_by_its_outgoing_leg(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    paired(ledger, a, b, -5_000)
    got = by_account(ledger, entry_filter(*OCT))
    assert got.transfers == (TransferLink(a, b, Line(-5_000, 1)),)
    assert got.undrawn == EMPTY  # the incoming leg is in neither


def test_a_transfer_there_and_back_is_two_links(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    paired(ledger, a, b, -5_000)
    paired(ledger, b, a, -1_200)
    paired(ledger, a, b, -300)
    got = by_account(ledger, entry_filter(*OCT))
    assert got.transfers == (
        TransferLink(a, b, Line(-5_300, 2)),
        TransferLink(b, a, Line(-1_200, 1)),
    )


def test_each_leg_is_valued_at_its_own_rate_and_unvalued_is_listed(ledger: Connection):
    usd = seed.account(ledger, "Card", currency="USD", kind="card")
    cash = seed.account(ledger, "Cash", currency="USD", kind="cash")
    rate(ledger, "USD", D(2026, 10, 1), "2.0")
    paired(ledger, usd, cash, -2_000, D(2026, 10, 3))  # -1000
    paired(ledger, usd, cash, -500, D(2026, 10, 30))  # 29 days past the rate: unvalued
    got = by_account(ledger, entry_filter(*OCT))
    (only,) = got.transfers
    assert only.line.total == -1_000 and only.line.count == 2
    assert [(u.currency, u.amount, u.count) for u in only.line.unvalued] == [("USD", -500, 1)]


def test_legs_without_a_counter_account_and_unpaired_incoming_legs_are_the_undrawn_line(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    leg(ledger, a, -1_000, None)  # outgoing, no counter-account
    leg(ledger, a, 700, None)  # incoming, no counter-account
    leg(ledger, a, 400, b)  # incoming, a counter-account, no partner entry
    leg(ledger, a, -250, b)  # outgoing with a counter-account, no partner entry: a link, not undrawn
    paired(ledger, a, b, -3_000)  # in neither: its outgoing leg is the link, the incoming leg stands for it
    got = by_account(ledger, entry_filter(*OCT))
    assert got.undrawn == Line(-1_000 + 700 + 400, 3)
    assert got.transfers == (TransferLink(a, b, Line(-3_250, 2)),)


def test_a_paired_incoming_leg_is_in_neither_even_when_its_partner_is_outside_the_range(
    ledger: Connection,
):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    out = leg(ledger, a, -5_000, b, D(2026, 9, 30))
    into = leg(ledger, b, 5_000, a, D(2026, 10, 1))
    pair(ledger, out, into)
    got = by_account(ledger, entry_filter(*OCT))  # holds the incoming leg only
    assert got.transfers == () and got.undrawn == EMPTY


def test_transfers_follow_the_tag_filter_and_the_range(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    t = seed.tag(ledger, "trip")
    out, _ = paired(ledger, a, b, -5_000)
    paired(ledger, a, b, -700, D(2026, 11, 2))  # outside the range
    ledger.execute(
        text("INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:e, :t)"), {"e": out, "t": t}
    )
    assert by_account(ledger, entry_filter(*OCT)).transfers == (TransferLink(a, b, Line(-5_000, 1)),)
    tagged = by_account(ledger, entry_filter(*OCT, (), (t,)))
    assert tagged.transfers == (TransferLink(a, b, Line(-5_000, 1)),)
    assert by_account(ledger, entry_filter(*OCT, (), (t + 1000,))).transfers == ()


def _stayed(got: ByAccount) -> dict[int, int]:
    return {s.account_id: s.amount for s in got.stayed}


def test_stayed_is_what_an_account_received_less_what_it_transferred_out(
    ledger: Connection, seeded: Household
):
    got = by_account(ledger, entry_filter(*OCT))
    # Giro: salary 300000 + gifts 1000 + unclassified in 2500 (the -700 reconciliation does not count),
    # less the 5000 transferred to Cash; the undrawn legs are in no link
    assert got.stayed == (Stayed(seeded.giro, 298_500),)
    # the same with `top`: the categories beyond it are "other", counted just the same
    assert by_account(ledger, entry_filter(*OCT), top=1).stayed == got.stayed


def test_stayed_counts_the_positive_links_only_and_is_floored_at_zero(ledger: Connection):
    a, b, c = (seed.account(ledger, n) for n in "ABC")
    salary = seed.category(ledger, "Salary", kind="income")
    seed.entry(ledger, a, amount=1_000, on=OCT[0], category_id=salary)
    seed.entry(
        ledger, a, amount=-200, on=OCT[0], category_id=salary
    )  # a refund-like entry nets within the link
    seed.derived(ledger, a, type="reconciliation", on=OCT[0], amount=-900)  # not positive: not counted
    paired(ledger, a, b, -300)
    seed.entry(ledger, b, amount=50, on=OCT[0], category_id=salary)
    paired(ledger, b, c, -500)  # more passed on than received: floored at zero, absent
    paired(ledger, c, a, -100)  # C received nothing on the income side
    got = by_account(ledger, entry_filter(*OCT))
    assert _stayed(got) == {a: 800 - 300}  # B: 50 - 500 < 0; C: 0 - 100 < 0


def test_stayed_is_absent_when_zero(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    salary = seed.category(ledger, "Salary", kind="income")
    seed.entry(ledger, a, amount=1_000, on=OCT[0], category_id=salary)
    paired(ledger, a, b, -1_000)
    assert by_account(ledger, entry_filter(*OCT)).stayed == ()


def test_stayed_counts_unclassified_in_and_positive_reconciliations(ledger: Connection):
    a = seed.account(ledger, "A")
    seed.entry(ledger, a, amount=400, on=OCT[0])  # unclassified in
    seed.derived(ledger, a, type="reconciliation", on=OCT[0], amount=250)
    assert by_account(ledger, entry_filter(*OCT)).stayed == (Stayed(a, 650),)


def test_without_top_every_income_category_counts_as_a_slice(ledger: Connection):
    a = seed.account(ledger, "A")
    s1, s2 = seed.category(ledger, "S1", kind="income"), seed.category(ledger, "S2", kind="income")
    seed.entry(ledger, a, amount=600, on=OCT[0], category_id=s1)
    seed.entry(ledger, a, amount=100, on=OCT[0], category_id=s2)
    assert by_account(ledger, entry_filter(*OCT)).stayed == (Stayed(a, 700),)
    # with `top=1`: S1 is a slice, S2 is "other"; the same 700
    assert by_account(ledger, entry_filter(*OCT), top=1).stayed == (Stayed(a, 700),)


def test_an_unvalued_transfer_counts_as_nothing_passed_on(ledger: Connection):
    usd = seed.account(ledger, "Card", currency="USD", kind="card")
    b = seed.account(ledger, "B", currency="USD", kind="card")
    salary = seed.category(ledger, "Salary", kind="income")
    rate(ledger, "USD", D(2026, 10, 1), "1.0")
    rate(ledger, "USD", D(2026, 10, 20), "1.0")
    seed.entry(ledger, usd, amount=1_000, on=OCT[0], category_id=salary)
    paired(ledger, usd, b, -400, D(2026, 10, 25))  # valued at the rate of the 20th
    assert by_account(ledger, entry_filter(*OCT)).stayed == (Stayed(usd, 600),)
    paired(ledger, usd, b, -300, D(2026, 11, 30))  # a rate too old, but outside the range: no effect
    assert by_account(ledger, entry_filter(*OCT)).stayed == (Stayed(usd, 600),)
    # the 25th's rate falls away (the 1st's is too old): the leg is unvalued and counts as 0 passed on
    ledger.execute(text("DELETE FROM fx_rate WHERE rate_date = :d"), {"d": D(2026, 10, 20)})
    assert by_account(ledger, entry_filter(*OCT)).stayed == (Stayed(usd, 1_000),)


# ---- a drill-down equals its number


def _agrees(conn: Connection, line: Line, what: str, flt: LedgerFilter) -> None:
    """The ledger list's total for the drill-down is the link's count; its base values sum to its total."""
    got = list_entries(conn, flt, limit=1, offset=0).total
    assert line.count == got, f"{what}: counts {line.count} entries, its drill-down lists {got}"
    assert line.total == (listed_base_sum(conn, flt) if line.count else 0), f"{what}: the total differs"


def test_every_link_of_a_household_equals_its_drilldown(ledger: Connection, seeded: Household):
    def narrow(start: date, end: date, tags: tuple[int, ...], **kw: Any) -> LedgerFilter:
        return LedgerFilter(date_from=start, date_to=end, tag_ids=tags, **kw)

    for (start, end), extra, top in product(RANGES, _filters(seeded), (None, 1)):
        tags = extra.get("tag_ids", ())
        got = by_account(ledger, entry_filter(start, end, (), tags), top)
        where = f"{start}..{end} {extra} top={top}"
        for kind, links in (("income", got.income), ("expense", got.expense)):
            for c in links.categories:
                for k in c.accounts:
                    _agrees(
                        ledger,
                        k.line,
                        f"{where} {kind} {c.category_id} x {k.account_id}",
                        narrow(start, end, tags, account_ids=(k.account_id,), category_ids=(c.category_id,)),
                    )
            if links.other is not None:
                rest = tuple(
                    c.category_id
                    for c in links.categories
                    if c.category_id not in (links.slices or ())
                    and not (
                        c.total.total is not None and c.total.total * (1 if kind == "income" else -1) < 0
                    )
                )
                for k in links.other:
                    _agrees(
                        ledger,
                        k.line,
                        f"{where} {kind} other x {k.account_id}",
                        narrow(start, end, tags, account_ids=(k.account_id,), category_ids=rest),
                    )
        for name, direction in (("unclassified_in", "in"), ("unclassified_out", "out")):
            for k in getattr(got, name):
                _agrees(
                    ledger,
                    k.line,
                    f"{where} {name} x {k.account_id}",
                    narrow(
                        start, end, tags, account_ids=(k.account_id,), uncategorised=True, direction=direction
                    ),
                )
        for k in got.reconciliations:
            _agrees(
                ledger,
                k.line,
                f"{where} reconciliations x {k.account_id}",
                narrow(start, end, tags, account_ids=(k.account_id,), types=("reconciliation",)),
            )
        for t in got.transfers:
            _agrees(
                ledger,
                t.line,
                f"{where} transfer {t.from_account_id} -> {t.to_account_id}",
                narrow(
                    start,
                    end,
                    tags,
                    account_ids=(t.from_account_id,),
                    counter_account_ids=(t.to_account_id,),
                    types=("transfer",),
                    direction="out",
                ),
            )


def test_every_transfer_link_equals_its_drilldown_there_and_back(ledger: Connection):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    paired(ledger, a, b, -5_000)
    paired(ledger, b, a, -1_200)
    leg(ledger, a, -250, b)
    got = by_account(ledger, entry_filter(*OCT))
    assert len(got.transfers) == 2
    for t in got.transfers:
        _agrees(
            ledger,
            t.line,
            f"{t.from_account_id} -> {t.to_account_id}",
            LedgerFilter(
                date_from=OCT[0],
                date_to=OCT[1],
                account_ids=(t.from_account_id,),
                counter_account_ids=(t.to_account_id,),
                types=("transfer",),
                direction="out",
            ),
        )


def test_the_undrawn_line_is_the_unpaired_legs_less_the_outgoing_ones_with_a_counter_account(
    ledger: Connection,
):
    a, b = seed.account(ledger, "A"), seed.account(ledger, "B")
    leg(ledger, a, -1_000, None)
    leg(ledger, a, 700, None)
    leg(ledger, a, 400, b)
    leg(ledger, a, -250, b)
    paired(ledger, a, b, -3_000)
    got = by_account(ledger, entry_filter(*OCT))
    # no ledger filter selects it directly; the entries are the transfer legs minus the link's and the
    # paired incoming leg
    everything = listed(ledger, date_from=OCT[0], date_to=OCT[1], types=("transfer",))
    links = sum(t.line.count for t in got.transfers)
    paired_in = ledger.execute(
        text(
            "SELECT count(*) FROM ledger_entry WHERE type = 'transfer' AND amount > 0"
            " AND counterpart_entry_id IS NOT NULL"
        )
    ).scalar_one()
    assert got.undrawn.count == everything - links - paired_in == 3
