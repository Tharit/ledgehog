"""THE acceptance test of the reporting step: a drill-down equals its number.

For every figure of a seeded ledger (every node of the category tree, own and total; income, expense,
unclassified in and out, reconciliations, unconfirmed; per range and per period; with and without the
ledger's account and tag filters), the entries the ledger list holds for the figure's drill-down filter
are as many as the figure counts, and their base values sum to its total (spec §8, architecture §8).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from itertools import product
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.ledger import LedgerFilter, list_entries
from app.core.reporting import (
    Line,
    by_category,
    categories_over_time,
    entry_filter,
    overview,
    periods,
    savings_over_time,
)
from tests.core.reporting.helpers import TODAY, Household, household, listed_base_sum, rate

D = date
RANGES = [
    (D(2026, 9, 1), D(2026, 9, 30)),
    (D(2026, 10, 1), D(2026, 10, 31)),
    (D(2026, 8, 1), D(2026, 10, 20)),
    (D(2026, 9, 30), D(2026, 10, 1)),  # straddles a month boundary
]


def _filters(h: Household) -> list[dict[str, Any]]:
    return [
        {},
        {"account_ids": (h.giro,)},
        {"tag_ids": (h.trip,)},
        {"account_ids": (h.giro, h.cash), "tag_ids": (h.trip,)},
        {"account_ids": (h.usd,)},
    ]


def _roots(conn: Connection, kind: str) -> tuple[int, ...]:
    rows = conn.execute(
        text("SELECT id FROM category WHERE kind = :k AND parent_id IS NULL ORDER BY id"), {"k": kind}
    )
    return tuple(int(r.id) for r in rows)


def _agrees(conn: Connection, line: Line, what: str, flt: LedgerFilter) -> None:
    """The ledger list's total for the drill-down is the figure's count; its base values sum to its total."""
    got = list_entries(conn, flt, limit=1, offset=0).total
    assert line.count == got, f"{what}: counts {line.count} entries, its drill-down lists {got}"
    assert line.total == (listed_base_sum(conn, flt) if line.count else 0), f"{what}: the total differs"


@pytest.fixture
def seeded(ledger: Connection) -> Household:
    h = household(ledger)
    rate(ledger, "USD", D(2026, 10, 5), "1.25")  # October's USD entry is valued, September's are not
    return h


@pytest.mark.parametrize("kind", ["expense", "income"])
def test_every_cell_of_by_category_equals_its_drilldown(ledger: Connection, seeded: Household, kind: str):
    found = ledger.execute(text("SELECT id FROM category WHERE kind = :k"), {"k": kind})
    everything = {int(r.id) for r in found}
    for (start, end), extra in product(RANGES, _filters(seeded)):
        base = entry_filter(start, end, extra.get("account_ids", ()), extra.get("tag_ids", ()))
        got = by_category(ledger, base, kind, top=3)
        tag = f"{kind} {start}..{end} {extra}"

        def agrees(line: Line, what: str, **narrow: Any) -> None:
            _agrees(ledger, line, f"{tag} {what}", replace(base, **narrow))  # noqa: B023

        agrees(got.total, "total", category_ids=_roots(ledger, kind))
        for row in got.categories:
            cid = row.category_id
            agrees(row.total, f"total of {cid}", category_ids=(cid,))
            agrees(row.own, f"own of {cid}", category_ids=(cid,), category_descendants=False)
        for cid in everything - {r.category_id for r in got.categories}:  # left out: nothing in the range
            _agrees(ledger, Line(0, 0), f"{tag} left out {cid}", replace(base, category_ids=(cid,)))
        agrees(got.unclassified_out, "unclassified out", uncategorised=True, direction="out")
        agrees(got.unclassified_in, "unclassified in", uncategorised=True, direction="in")
        agrees(got.reconciliations, "reconciliations", types=("reconciliation",))
        unconfirmed = list_entries(ledger, replace(base, flags=("unconfirmed",)), limit=1, offset=0)
        assert got.unconfirmed_count == unconfirmed.total
        assert got.slices is not None
        for s in got.slices:  # a slice's drill-down is its category
            agrees(s.total, f"slice {s.category_id}", category_ids=(s.category_id,))


def test_every_cell_of_over_time_equals_its_drilldown(ledger: Connection, seeded: Household):
    for (start, end), extra in product(RANGES, _filters(seeded)):
        base = entry_filter(start, end, extra.get("account_ids", ()), extra.get("tag_ids", ()))
        tag = f"{start}..{end} {extra}"
        cuts = [(p.start, p.end) for p in periods(start, end, "month")]
        savings = savings_over_time(ledger, base, "month")
        for (a, b), s in zip(cuts, savings.savings, strict=True):
            period = replace(base, date_from=a, date_to=b)
            for line, what, narrow in (
                (s.income, "income", {"category_ids": _roots(ledger, "income")}),
                (s.expense, "expense", {"category_ids": _roots(ledger, "expense")}),
                (s.unclassified, "unclassified", {"uncategorised": True}),
                (s.reconciliations, "reconciliations", {"types": ("reconciliation",)}),
            ):
                _agrees(ledger, line, f"{tag} {what} {a}", replace(period, **narrow))
        for kind in ("expense", "income"):
            got = categories_over_time(ledger, base, "month", kind)
            for series in got.categories:
                c = series.category_id
                for (a, b), total, own in zip(cuts, series.total, series.own, strict=True):
                    period = replace(base, date_from=a, date_to=b)
                    _agrees(ledger, total, f"{tag} {kind} {c} total {a}", replace(period, category_ids=(c,)))
                    own_filter = replace(period, category_ids=(c,), category_descendants=False)
                    _agrees(ledger, own, f"{tag} {kind} {c} own {a}", own_filter)
                _agrees(ledger, series.sum, f"{tag} {kind} {c} sum", replace(base, category_ids=(c,)))


def test_the_overviews_unpaired_transfers_drilldown(ledger: Connection, seeded: Household):
    line = overview(ledger, TODAY).net_worth.unpaired_transfers
    flt = LedgerFilter(types=("transfer",), flags=("waiting", "unmatched_transfer"))
    _agrees(ledger, line, "unpaired transfers", flt)
