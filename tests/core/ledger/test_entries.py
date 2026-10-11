"""`list_entries` / `matching_entry_ids` on a real database (rolled-back connection)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.ledger import LedgerFilter, list_entries, matching_entry_ids
from tests.fixtures import ledger_seed as seed

D = date(2026, 3, 10)


def ids(conn: Connection, **kw: Any) -> list[int]:
    return [e.id for e in list_entries(conn, LedgerFilter(**kw), limit=500, offset=0).entries]


def sorted_ids(conn: Connection, **kw: Any) -> list[int]:
    return sorted(ids(conn, **kw))


@pytest.fixture
def acct(db_conn: Connection) -> int:
    return seed.account(db_conn)


def test_row_shape(db_conn: Connection, acct: int):
    p, c, t = seed.payee(db_conn, "Shop"), seed.category(db_conn, "Food"), seed.tag(db_conn, "trip")
    e = seed.entry(
        db_conn,
        acct,
        amount=-1250,
        on=D,
        value_on=date(2026, 3, 11),
        description="Lunch",
        note="n",
        category_id=c,
        payee_id=p,
        tags=(t,),
        counterparty="CP",
        purpose="PU",
        flags=("unconfirmed",),
    )
    (row,) = list_entries(db_conn, LedgerFilter(), limit=10, offset=0).entries
    assert row.id == e and row.version == 1 and row.account_id == acct
    assert (row.booked_on, row.value_on) == (D, date(2026, 3, 11))
    assert (row.amount, row.currency, row.type) == (-1250, "EUR", "flow")
    assert (row.description, row.note, row.counterparty_name, row.purpose) == ("Lunch", "n", "CP", "PU")
    assert (row.payee_id, row.category_id) == (p, c)
    assert row.counter_account_id is None and row.counterpart_entry_id is None
    assert row.source_transaction_id == seed.source_of(db_conn, e) and row.document_id is None
    assert row.review_flags == ("unconfirmed",) and row.tag_ids == (t,)


def test_display_text_falls_back(db_conn: Connection, acct: int):
    a = seed.entry(db_conn, acct, description="D", counterparty="C", purpose="P")
    b = seed.entry(db_conn, acct, counterparty="C", purpose="P")
    c = seed.entry(db_conn, acct, purpose="P")
    d = seed.entry(db_conn, acct)
    page = {e.id: e.display_text for e in list_entries(db_conn, LedgerFilter(), limit=10, offset=0).entries}
    assert page == {a: "D", b: "C", c: "P", d: None}


def test_tag_ids_per_row_sorted_and_empty(db_conn: Connection, acct: int):
    t1, t2, t3 = (seed.tag(db_conn, n) for n in "abc")
    x = seed.entry(db_conn, acct, tags=(t3, t1))
    y = seed.entry(db_conn, acct)
    rows = {e.id: e for e in list_entries(db_conn, LedgerFilter(), limit=10, offset=0).entries}
    assert rows[x].tag_ids == (t1, t3) and rows[y].tag_ids == ()
    assert t2 not in rows[x].tag_ids


def test_unfiltered_includes_derived_entries(db_conn: Connection, acct: int):
    m = seed.entry(db_conn, acct)
    o = seed.derived(db_conn, acct)
    assert sorted_ids(db_conn) == sorted([m, o])
    row = next(e for e in list_entries(db_conn, LedgerFilter(), limit=9, offset=0).entries if e.id == o)
    assert row.source_transaction_id is None and row.counterparty_name is None and row.display_text is None


def test_dates_inclusive(db_conn: Connection, acct: int):
    e = [seed.entry(db_conn, acct, on=D + timedelta(days=i)) for i in range(-2, 3)]
    assert sorted_ids(db_conn, date_from=D, date_to=D + timedelta(days=1)) == sorted(e[2:4])
    assert sorted_ids(db_conn, date_from=D + timedelta(days=2)) == [e[4]]
    assert sorted_ids(db_conn, date_to=D - timedelta(days=2)) == [e[0]]


def test_account_or_within_dimension(db_conn: Connection, acct: int):
    b, c = seed.account(db_conn, "B"), seed.account(db_conn, "C")
    ea, eb, ec = (seed.entry(db_conn, a) for a in (acct, b, c))
    assert sorted_ids(db_conn, account_ids=(acct, c)) == sorted([ea, ec])
    assert sorted_ids(db_conn, account_ids=(b,)) == [eb]


def test_payee_or(db_conn: Connection, acct: int):
    p1, p2, p3 = (seed.payee(db_conn, n) for n in ("P1", "P2", "P3"))
    e1, e2, _e3 = (seed.entry(db_conn, acct, payee_id=p) for p in (p1, p2, p3))
    assert sorted_ids(db_conn, payee_ids=(p1, p2)) == sorted([e1, e2])


def test_category_descendants_default_and_exact(db_conn: Connection, acct: int):
    root = seed.category(db_conn, "Living")
    child = seed.category(db_conn, "Food", root)
    grand = seed.category(db_conn, "Cafe", child)
    other = seed.category(db_conn, "Travel")
    er, ec, eg, eo = (seed.entry(db_conn, acct, category_id=c) for c in (root, child, grand, other))
    assert sorted_ids(db_conn, category_ids=(root,)) == sorted([er, ec, eg])
    assert sorted_ids(db_conn, category_ids=(child,)) == sorted([ec, eg])
    assert sorted_ids(db_conn, category_ids=(root,), category_descendants=False) == [er]
    assert sorted_ids(db_conn, category_ids=(root, other), category_descendants=False) == sorted([er, eo])


def test_uncategorised_means_flows_without_category(db_conn: Connection, acct: int):
    cat = seed.category(db_conn, "Food")
    plain = seed.entry(db_conn, acct)
    seed.entry(db_conn, acct, category_id=cat)
    seed.entry(db_conn, acct, type="transfer")
    seed.entry(db_conn, acct, type=None)
    seed.derived(db_conn, acct)
    assert sorted_ids(db_conn, uncategorised=True) == [plain]
    both = sorted_ids(db_conn, uncategorised=True, category_ids=(cat,))
    assert len(both) == 2 and plain in both


def test_tag_any_of(db_conn: Connection, acct: int):
    t1, t2, t3 = (seed.tag(db_conn, n) for n in "abc")
    e1 = seed.entry(db_conn, acct, tags=(t1,))
    e12 = seed.entry(db_conn, acct, tags=(t1, t2))
    e3 = seed.entry(db_conn, acct, tags=(t3,))
    seed.entry(db_conn, acct)
    assert sorted_ids(db_conn, tag_ids=(t1,)) == sorted([e1, e12])
    assert sorted_ids(db_conn, tag_ids=(t2, t3)) == sorted([e12, e3])
    # an entry with two matching tags is listed once, and counted once
    page = list_entries(db_conn, LedgerFilter(tag_ids=(t1, t2)), limit=10, offset=0)
    assert page.total == 2 and len(page.entries) == 2


def test_amount_is_magnitude_in_one_currency(db_conn: Connection, acct: int):
    usd = seed.account(db_conn, "Card", "USD")
    out_ = seed.entry(db_conn, acct, amount=-500)
    in_ = seed.entry(db_conn, acct, amount=500)
    small = seed.entry(db_conn, acct, amount=-100)
    big = seed.entry(db_conn, acct, amount=9000)
    seed.entry(db_conn, usd, amount=-500)
    assert sorted_ids(db_conn, amount_min=500, amount_max=500, currency="EUR") == sorted([out_, in_])
    assert sorted_ids(db_conn, amount_min=101, currency="EUR") == sorted([out_, in_, big])
    assert sorted_ids(db_conn, amount_max=100, currency="EUR") == [small]
    assert sorted_ids(db_conn, amount_min=0, amount_max=0, currency="EUR") == []
    assert sorted_ids(db_conn, amount_min=500, amount_max=500, currency="EUR", direction="in") == [in_]
    assert sorted_ids(db_conn, amount_min=500, amount_max=500, currency="EUR", direction="out") == [out_]
    assert len(ids(db_conn, currency="USD")) == 1
    assert sorted_ids(db_conn, currency="EUR", direction="in") == sorted([in_, big])


@pytest.mark.parametrize(
    ("q", "kw"),
    [
        ("lunchword", {"description": "A LunchWord here"}),
        ("notetext", {"note": "some NoteText"}),
        ("cptext", {"counterparty": "Some CpText GmbH"}),
        ("purposetext", {"purpose": "PurposeText 12"}),
        ("e2etext", {"end_to_end_id": "E2EText-9"}),
        ("mandtext", {"mandate_ref": "MandText-1"}),
    ],
)
def test_text_matches_each_entry_and_source_field(db_conn: Connection, acct: int, q: str, kw: dict[str, str]):
    hit = seed.entry(db_conn, acct, **kw)
    seed.entry(db_conn, acct, description="nothing relevant")
    assert ids(db_conn, text=q.upper()) == [hit]
    assert ids(db_conn, text=q.lower()) == [hit]


def test_text_matches_payee_and_category_names(db_conn: Connection, acct: int):
    p = seed.payee(db_conn, "Zed Corporation")
    c = seed.category(db_conn, "Quux Things")
    ep = seed.entry(db_conn, acct, payee_id=p)
    ec = seed.entry(db_conn, acct, category_id=c)
    seed.entry(db_conn, acct)
    assert ids(db_conn, text="zed corp") == [ep]
    assert ids(db_conn, text="QUUX") == [ec]


def test_text_wildcards_are_literal(db_conn: Connection, acct: int):
    pct = seed.entry(db_conn, acct, description="100% sure")
    und = seed.entry(db_conn, acct, description="a_b")
    bsl = seed.entry(db_conn, acct, description="c\\d")
    seed.entry(db_conn, acct, description="1000 sure")
    seed.entry(db_conn, acct, description="axb")
    seed.entry(db_conn, acct, description="cd")
    assert ids(db_conn, text="100%") == [pct]
    assert ids(db_conn, text="%") == [pct]
    assert ids(db_conn, text="a_b") == [und]
    assert ids(db_conn, text="_") == [und]
    assert ids(db_conn, text="c\\d") == [bsl]
    assert ids(db_conn, text="\\") == [bsl]


def test_text_words_are_anded_across_fields(db_conn: Connection, acct: int):
    c = seed.category(db_conn, "Groceries")
    both = seed.entry(db_conn, acct, description="weekly shop", category_id=c)
    seed.entry(db_conn, acct, description="weekly shop")
    seed.entry(db_conn, acct, description="other", category_id=c)
    assert ids(db_conn, text="  shop   groceries ") == [both]


def test_text_excludes_derived_entries_but_account_and_date_include_them(db_conn: Connection, acct: int):
    m = seed.entry(db_conn, acct, description="opening balance text")
    o = seed.derived(db_conn, acct)
    p = seed.payee(db_conn, "P")
    seed.entry(db_conn, acct, payee_id=p)
    assert ids(db_conn, text="opening") == [m]
    assert o in ids(db_conn, account_ids=(acct,))
    assert o in ids(db_conn, date_from=seed.DAY, date_to=seed.DAY)
    assert o not in ids(db_conn, payee_ids=(p,))
    assert o not in ids(db_conn, uncategorised=True)


def test_type_or_and_flags(db_conn: Connection, acct: int):
    f = seed.entry(db_conn, acct, flags=("unclassified",), type=None)
    t = seed.entry(db_conn, acct, type="transfer", flags=("unconfirmed",))
    both = seed.entry(db_conn, acct, flags=("unclassified", "unconfirmed"))
    clean = seed.entry(db_conn, acct)
    o = seed.derived(db_conn, acct)
    assert sorted_ids(db_conn, types=("transfer", "opening")) == sorted([t, o])
    assert sorted_ids(db_conn, types=("flow",)) == sorted([both, clean])
    assert sorted_ids(db_conn, flags=("unclassified",)) == sorted([f, both])
    assert sorted_ids(db_conn, flags=("unconfirmed", "unclassified")) == sorted([f, t, both])
    assert clean not in ids(db_conn, flags=("waiting",))


def test_dimensions_are_anded(db_conn: Connection, acct: int):
    other = seed.account(db_conn, "B")
    c = seed.category(db_conn, "Food")
    t = seed.tag(db_conn, "x")
    hit = seed.entry(db_conn, acct, on=D, category_id=c, tags=(t,), amount=-700, description="Pizza")
    seed.entry(db_conn, other, on=D, category_id=c, tags=(t,), amount=-700, description="Pizza")
    seed.entry(
        db_conn, acct, on=D + timedelta(days=9), category_id=c, tags=(t,), amount=-700, description="Pizza"
    )
    seed.entry(db_conn, acct, on=D, tags=(t,), amount=-700, description="Pizza")
    seed.entry(db_conn, acct, on=D, category_id=c, amount=-700, description="Pizza")
    seed.entry(db_conn, acct, on=D, category_id=c, tags=(t,), amount=-900, description="Pizza")
    seed.entry(db_conn, acct, on=D, category_id=c, tags=(t,), amount=-700, description="Pasta")
    flt = dict(
        date_from=D,
        date_to=D,
        account_ids=(acct,),
        category_ids=(c,),
        tag_ids=(t,),
        amount_min=700,
        amount_max=700,
        currency="EUR",
        direction="out",
        text="pizza",
        types=("flow",),
    )
    assert ids(db_conn, **flt) == [hit]


def test_sort_is_date_then_source_desc_nulls_last_then_id_desc(db_conn: Connection, acct: int):
    newest = seed.entry(db_conn, acct, on=D + timedelta(days=1))
    s_low = seed.entry(db_conn, acct, on=D)
    s_high = seed.entry(db_conn, acct, on=D)
    sib1 = seed.entry(db_conn, acct, on=D, source_id=seed.source_of(db_conn, s_high))
    sib2 = seed.entry(db_conn, acct, on=D, source_id=seed.source_of(db_conn, s_high))
    derived_same_day = seed.derived(db_conn, acct, on=D)
    oldest = seed.entry(db_conn, acct, on=D - timedelta(days=1))
    # the split's siblings (same source) are adjacent, id descending inside; NULL source last
    assert ids(db_conn) == [newest, sib2, sib1, s_high, s_low, derived_same_day, oldest]


def test_pagination_pages_and_total(db_conn: Connection, acct: int):
    made = [seed.entry(db_conn, acct, on=D - timedelta(days=i // 3)) for i in range(10)]
    made.append(seed.entry(db_conn, acct, description="odd", on=D))
    whole = ids(db_conn)
    assert len(whole) == 11 and sorted(whole) == sorted(made)
    pages = [list_entries(db_conn, LedgerFilter(), limit=4, offset=o) for o in (0, 4, 8)]
    assert [len(p.entries) for p in pages] == [4, 4, 3]
    assert all(p.total == 11 and p.limit == 4 for p in pages)
    assert [e.id for p in pages for e in p.entries] == whole
    past = list_entries(db_conn, LedgerFilter(), limit=4, offset=50)
    assert past.entries == () and past.total == 11 and past.offset == 50


def test_total_counts_the_filter_not_the_page(db_conn: Connection, acct: int):
    c = seed.category(db_conn, "Food")
    for _ in range(5):
        seed.entry(db_conn, acct, category_id=c)
    seed.entry(db_conn, acct)
    page = list_entries(db_conn, LedgerFilter(category_ids=(c,)), limit=2, offset=0)
    assert (len(page.entries), page.total) == (2, 5)


def test_matching_entry_ids_uses_the_same_predicates(db_conn: Connection, acct: int):
    t = seed.tag(db_conn, "x")
    a = seed.entry(db_conn, acct, tags=(t,), description="hello")
    seed.entry(db_conn, acct, description="hello")
    seed.derived(db_conn, acct)
    flt = LedgerFilter(tag_ids=(t,), text="hello")
    assert matching_entry_ids(db_conn, flt) == [a]
    every = LedgerFilter()
    assert matching_entry_ids(db_conn, every) == sorted(ids(db_conn))


def test_listing_writes_nothing(db_conn: Connection, acct: int):
    seed.entry(db_conn, acct)
    before = db_conn.execute(text("SELECT count(*), sum(version) FROM ledger_entry")).one()
    list_entries(db_conn, LedgerFilter(text="x", tag_ids=(1,)), limit=5, offset=0)
    assert db_conn.execute(text("SELECT count(*), sum(version) FROM ledger_entry")).one() == before
