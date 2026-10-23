"""`list_documents` and `get_document` on a real database (rolled-back connection)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.documents import DocumentFilter, get_document, list_documents
from app.core.ledger import InvalidFilter
from tests.core.units.doc_helpers import make_document, make_payee
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import make_entry, make_source

D = date(2026, 3, 10)


@pytest.fixture
def acct(db_conn: Connection) -> int:
    return seed.account(db_conn)


def lines(conn: Connection, document_id: int, *specs: tuple[str, int]) -> None:
    for n, (description, amount) in enumerate(specs, 1):
        conn.execute(
            text(
                "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                " VALUES (:d, :n, :t, :a)"
            ),
            {"d": document_id, "n": n, "t": description, "a": amount},
        )


def txn(conn: Connection, acct: int, *, amount: int = -1000, on: date = D, **entry: Any) -> int:
    """A transaction with its single original entry (a confirmed flow unless `entry` says otherwise)."""
    columns = entry.pop("columns", None)
    src = make_source(conn, acct, amount=amount, booked_on=on, columns=columns)
    values: dict[str, Any] = {"category_id": seed.category(conn, f"c{src}")}
    values.update(entry)
    return make_entry(conn, src, **values)


def carry(conn: Connection, entry_id: int, document_id: int) -> None:
    conn.execute(
        text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": document_id, "e": entry_id}
    )


def ids(conn: Connection, **kw: Any) -> list[int]:
    return [d.id for d in list_documents(conn, DocumentFilter(**kw), limit=500, offset=0).documents]


def test_row_shape_and_order(db_conn: Connection):
    older = make_document(db_conn, on=date(2026, 3, 1), total=-500)
    newer = make_document(db_conn, "amazon", on=D, total=-1000)
    db_conn.execute(
        text("UPDATE external_document SET merchant_name = 'Shop', title = 'Order' WHERE id = :i"),
        {"i": newer},
    )
    lines(db_conn, newer, ("a", -400), ("b", -600))
    page = list_documents(db_conn, DocumentFilter(), limit=10, offset=0)
    assert [d.id for d in page.documents] == [newer, older]  # newest first
    first = page.documents[0]
    assert (first.provider, first.occurred_on, first.total, first.currency) == ("amazon", D, -1000, "EUR")
    assert (first.merchant_name, first.title, first.line_count, first.version) == ("Shop", "Order", 2, 1)
    assert first.carrier is None and page.documents[1].line_count == 0
    assert page.total == 2


def test_paging(db_conn: Connection):
    made = [make_document(db_conn, on=date(2026, 3, d), total=-100 * d) for d in range(1, 6)]
    page = list_documents(db_conn, DocumentFilter(), limit=2, offset=2)
    assert page.total == 5 and (page.limit, page.offset) == (2, 2)
    assert [d.id for d in page.documents] == [made[2], made[1]]
    assert list_documents(db_conn, DocumentFilter(), limit=2, offset=10).documents == ()


def test_provider_and_date_filters(db_conn: Connection):
    a = make_document(db_conn, "paypal", on=date(2026, 3, 1))
    b = make_document(db_conn, "amazon", on=date(2026, 3, 5))
    c = make_document(db_conn, "paypal", on=date(2026, 3, 9))
    assert sorted(ids(db_conn, providers=("paypal",))) == [a, c]
    assert sorted(ids(db_conn, providers=("paypal", "amazon"))) == [a, b, c]
    assert ids(db_conn, date_from=date(2026, 3, 5), date_to=date(2026, 3, 5)) == [b]
    assert sorted(ids(db_conn, date_from=date(2026, 3, 5))) == [b, c]
    assert ids(db_conn, date_to=date(2026, 3, 4)) == [a]


def test_amount_filter_is_a_magnitude_in_a_currency(db_conn: Connection):
    charge = make_document(db_conn, total=-1500)
    refund = make_document(db_conn, total=1500)
    other = make_document(db_conn, total=-1500, currency="USD")
    small = make_document(db_conn, total=-200)
    assert sorted(ids(db_conn, amount_min=1500, amount_max=1500, currency="EUR")) == [charge, refund]
    assert ids(db_conn, amount_min=1500, amount_max=1500, currency="USD") == [other]
    assert sorted(ids(db_conn, amount_max=300, currency="EUR")) == [small]
    assert sorted(ids(db_conn, amount_min=200, currency="EUR")) == [charge, refund, small]
    assert ids(db_conn, currency="USD") == [other]


def test_text_searches_merchant_title_and_lines_word_by_word(db_conn: Connection):
    a = make_document(db_conn)
    b = make_document(db_conn)
    c = make_document(db_conn)
    db_conn.execute(
        text("UPDATE external_document SET merchant_name = 'Seeed Studio' WHERE id = :i"), {"i": a}
    )
    db_conn.execute(text("UPDATE external_document SET title = 'Order 100%' WHERE id = :i"), {"i": b})
    lines(db_conn, c, ("USB-C cable", -500), ("Raspberry Pi", -500))
    assert ids(db_conn, text="seeed") == [a]
    assert ids(db_conn, text="order") == [b]
    assert ids(db_conn, text="100%") == [b]  # a wildcard is literal
    assert ids(db_conn, text="raspberry cable") == [c]  # every word, in any field of the document's lines
    assert ids(db_conn, text="raspberry seeed") == []


def test_linked_filter_and_the_carrying_transaction(db_conn: Connection, acct: int):
    linked = make_document(db_conn, total=-1000)
    free = make_document(db_conn, total=-2000)
    entry = txn(db_conn, acct, amount=-1000)
    carry(db_conn, entry, linked)
    assert ids(db_conn, linked=True) == [linked]
    assert ids(db_conn, linked=False) == [free]
    assert sorted(ids(db_conn)) == [linked, free]
    row = next(
        d for d in list_documents(db_conn, DocumentFilter(), limit=10, offset=0).documents if d.id == linked
    )
    assert row.carrier is not None
    assert (row.carrier.entry_id, row.carrier.account_id, row.carrier.booked_on) == (entry, acct, D)
    assert (row.carrier.amount, row.carrier.currency) == (-1000, "EUR")
    assert list_documents(db_conn, DocumentFilter(linked=True), limit=10, offset=0).total == 1


@pytest.mark.parametrize(
    "kw, parameter",
    [
        ({"date_from": date(2026, 3, 2), "date_to": date(2026, 3, 1)}, "to"),
        ({"amount_min": 5, "amount_max": 1, "currency": "EUR"}, "amount_min"),
        ({"amount_min": 5}, "currency"),
        ({"currency": "eur"}, "currency"),
        ({"text": "  "}, "q"),
        ({"providers": ("",)}, "provider"),
    ],
)
def test_an_invalid_filter_names_its_parameter(kw: dict[str, Any], parameter: str):
    with pytest.raises(InvalidFilter) as exc:
        DocumentFilter(**kw)
    assert exc.value.parameter == parameter


def test_detail_has_lines_in_order_and_none_for_a_missing_document(db_conn: Connection, acct: int):
    d = make_document(db_conn, total=-1000)
    lines(db_conn, d, ("first", -300), ("second", -700))
    detail = get_document(db_conn, d)
    assert detail is not None
    assert [(x.line_no, x.description, x.amount) for x in detail.lines] == [
        (1, "first", -300),
        (2, "second", -700),
    ]
    assert get_document(db_conn, d + 1000) is None


def test_a_linked_document_lists_no_matches(db_conn: Connection, acct: int):
    d = make_document(db_conn, total=-1000)
    entry = txn(db_conn, acct, amount=-1000)
    txn(db_conn, acct, amount=-1000)  # would match, but the document is carried
    carry(db_conn, entry, d)
    detail = get_document(db_conn, d)
    assert detail is not None and detail.matches == () and detail.document.carrier is not None


def test_reverse_matches_include_confirmed_any_payee_any_account_and_state(db_conn: Connection, acct: int):
    other = seed.account(db_conn, name="Visa", kind="card")
    d = make_document(db_conn, "paypal", total=-1000, on=D)
    provider_payee = make_payee(db_conn, "PayPal", "paypal")
    plain_payee = make_payee(db_conn, "Plain", None)
    confirmed = txn(db_conn, acct, on=D, payee_id=plain_payee)  # a category, no keys: confirmed
    unconfirmed = txn(
        db_conn,
        other,
        on=date(2026, 3, 12),
        payee_id=provider_payee,
        derivation='{"payee": {"pass": "history"}}',
    )
    detail = get_document(db_conn, d)
    assert detail is not None
    assert [(m.entry_id, m.confirmed) for m in detail.matches] == [(confirmed, True), (unconfirmed, False)]
    first = detail.matches[0]
    assert (first.account_id, first.booked_on, first.amount, first.currency) == (acct, D, -1000, "EUR")
    assert first.payee_id == plain_payee and first.document_id is None and first.display_text is None


def test_a_transfer_is_not_a_reverse_match(db_conn: Connection, acct: int):
    other = seed.account(db_conn, name="Savings")
    d = make_document(db_conn, total=-1000, on=D)
    flow = txn(db_conn, acct, on=D)
    txn(db_conn, acct, on=D, type="transfer", category_id=None, counter_account_id=other)
    detail = get_document(db_conn, d)
    assert detail is not None and [m.entry_id for m in detail.matches] == [flow]


def test_reverse_matches_respect_amount_sign_window_and_duplicates(db_conn: Connection, acct: int):
    d = make_document(db_conn, total=-1000, on=D)  # a booking up to 7 days before it and 60 days after it
    inside = txn(db_conn, acct, on=date(2026, 3, 17))
    late = txn(db_conn, acct, on=date(2026, 5, 9))  # 60 days after the document: the back end
    txn(db_conn, acct, on=date(2026, 5, 10))  # one day too far
    early = txn(db_conn, acct, on=date(2026, 3, 3))  # 7 days before it: the ahead end
    txn(db_conn, acct, on=date(2026, 3, 2))  # one day too far
    txn(db_conn, acct, amount=-1001)
    txn(db_conn, acct, amount=1000)  # a refund cannot match a charge document
    target = txn(db_conn, acct, on=date(2026, 3, 11))
    duplicated = db_conn.execute(
        text("SELECT source_transaction_id FROM ledger_entry WHERE id = :e"), {"e": target}
    ).scalar_one()
    make_source(db_conn, acct, amount=-1000, booked_on=D, duplicate_of=duplicated)  # a duplicate has no entry
    detail = get_document(db_conn, d)
    assert detail is not None
    assert [m.entry_id for m in detail.matches] == [target, inside, early, late]


def test_reverse_matches_in_the_instructed_currency_and_with_a_carried_document(
    db_conn: Connection, acct: int
):
    d = make_document(db_conn, total=-2000, currency="USD", on=D)
    abroad = txn(
        db_conn, acct, amount=-1800, columns={"instructed_amount": -2000, "instructed_currency": "USD"}
    )
    carrying = txn(
        db_conn, acct, amount=-1800, columns={"instructed_amount": -2000, "instructed_currency": "USD"}
    )
    held = make_document(db_conn, "amazon", total=-1800, currency="EUR", on=D)
    carry(db_conn, carrying, held)
    detail = get_document(db_conn, d)
    assert detail is not None
    by_entry = {m.entry_id: m for m in detail.matches}
    assert set(by_entry) == {abroad, carrying}
    assert (by_entry[abroad].instructed_amount, by_entry[abroad].instructed_currency) == (-2000, "USD")
    assert by_entry[carrying].document_id == held  # listed with the document it carries


def test_a_splits_original_entry_is_the_match_with_the_transactions_amount(db_conn: Connection, acct: int):
    d = make_document(db_conn, total=-1000, on=D)
    src = make_source(db_conn, acct, amount=-1000, booked_on=D)
    first = make_entry(db_conn, src, amount=-600, category_id=seed.category(db_conn, "a"))
    make_entry(db_conn, src, amount=-400, category_id=seed.category(db_conn, "b"))
    detail = get_document(db_conn, d)
    assert detail is not None
    assert [(m.entry_id, m.amount) for m in detail.matches] == [(first, -1000)]
