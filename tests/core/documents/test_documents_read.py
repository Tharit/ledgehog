"""`list_documents` and `get_document` on a real database (rolled-back connection)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.documents import DocumentFilter, get_document, list_documents
from app.core.ledger import InvalidFilter
from tests.fixtures.documents import make_document

D = date(2026, 3, 10)


def lines(conn: Connection, document_id: int, *specs: tuple[str, int]) -> None:
    for n, (description, amount) in enumerate(specs, 1):
        conn.execute(
            text(
                "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                " VALUES (:d, :n, :t, :a)"
            ),
            {"d": document_id, "n": n, "t": description, "a": amount},
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
    assert page.documents[1].line_count == 0
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


def test_detail_has_lines_in_order_and_none_for_a_missing_document(db_conn: Connection):
    d = make_document(db_conn, total=-1000)
    lines(db_conn, d, ("first", -300), ("second", -700))
    detail = get_document(db_conn, d)
    assert detail is not None
    assert [(x.line_no, x.description, x.amount) for x in detail.lines] == [
        (1, "first", -300),
        (2, "second", -700),
    ]
    assert get_document(db_conn, d + 1000) is None


def test_the_provider_filter_ignores_case(db_conn: Connection):
    a = make_document(db_conn, "PayPal", external_id="a")
    b = make_document(db_conn, "paypal", external_id="b")
    make_document(db_conn, "amazon", external_id="c")
    assert sorted(ids(db_conn, providers=("PAYPAL",))) == sorted([a, b])


def test_booked_filter_and_booking_state(db_conn: Connection):
    booked = make_document(db_conn, "Amazon", on=date(2026, 2, 1))
    open_ = make_document(db_conn, "Elsewhere", on=date(2026, 2, 1))
    zero = make_document(db_conn, "Amazon", total=0, on=date(2026, 2, 1))
    account = db_conn.execute(
        text(
            "INSERT INTO account (name, kind, currency) VALUES ('Amazon.de', 'clearance', 'EUR') RETURNING id"
        )
    ).scalar_one()
    st = db_conn.execute(
        text(
            "INSERT INTO source_transaction (account_id, origin, source_id, booked_on, amount, currency, raw)"
            " VALUES (:a, 'booking', :s, DATE '2026-02-01', -1000, 'EUR', '{}') RETURNING id"
        ),
        {"a": account, "s": f"document:{booked}"},
    ).scalar_one()
    assert ids(db_conn, booked=True) == [booked]
    assert sorted(ids(db_conn, booked=False)) == [open_, zero]
    found = get_document(db_conn, booked)
    assert found is not None and found.document.booking is not None
    assert (found.document.booking.account_id, found.document.booking.source_transaction_id) == (account, st)
    assert found.document.not_booked is None
    states = {
        d.id: d.not_booked for d in list_documents(db_conn, DocumentFilter(), limit=9, offset=0).documents
    }
    assert states[zero] is not None and states[zero].reason == "zero_total"
    assert states[open_] is not None and states[open_].reason == "no_account"
