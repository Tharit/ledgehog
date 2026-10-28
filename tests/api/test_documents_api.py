"""`GET /api/documents` and `GET /api/documents/{id}` (architecture §4.1, spec §5.8, documents.md §9)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.core.documents.test_documents_read import lines
from tests.fixtures.documents import make_document

URL = "/api/documents"
D = date(2026, 3, 10)


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


def listed(client: TestClient, **params: Any) -> dict[str, Any]:
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def doc_ids(client: TestClient, **params: Any) -> list[int]:
    return [d["id"] for d in listed(client, **params)["documents"]]


def test_both_routes_require_a_session(client: TestClient):
    assert_envelope(client.get(URL), 401, "unauthenticated")
    assert_envelope(client.get(f"{URL}/1"), 401, "unauthenticated")


def test_empty_list(anna: TestClient):
    assert listed(anna) == {"documents": [], "total": 0, "limit": 100, "offset": 0}


def test_row_shape_and_money(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        d = make_document(conn, "paypal", total=-1000, on=D)
        conn.execute(
            text(
                "UPDATE external_document SET merchant_name = 'Shop', title = 'T', reference = 'R-1'"
                " WHERE id = :i"
            ),
            {"i": d},
        )
        lines(conn, d, ("a", -400), ("b", -600))
        free = make_document(conn, "amazon", total=1500, on=date(2026, 3, 1))
    rows = {r["id"]: r for r in listed(anna)["documents"]}
    assert rows[d] == {
        "id": d,
        "version": 1,
        "provider": "paypal",
        "source_id": rows[d]["source_id"],
        "importer_instance_id": None,
        "occurred_on": "2026-03-10",
        "total": {"amount": -1000, "currency": "EUR"},
        "merchant_name": "Shop",
        "title": "T",
        "reference": "R-1",
        "line_count": 2,
        "booking": None,
        "not_booked": {"reason": "no_account", "currency": "EUR", "account_id": None, "start": None},
    }
    assert rows[free]["total"] == {"amount": 1500, "currency": "EUR"}


def test_filters(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        pp = make_document(conn, "paypal", total=-1000, on=date(2026, 3, 1))
        pp_two = make_document(conn, "paypal", total=-2000, on=date(2026, 3, 5))
        az = make_document(conn, "amazon", total=-1000, on=date(2026, 3, 9))
        conn.execute(
            text("UPDATE external_document SET merchant_name = 'Seeed Studio' WHERE id = :i"), {"i": pp}
        )
    assert sorted(doc_ids(anna, provider="paypal")) == sorted([pp, pp_two])
    assert doc_ids(anna, **{"from": "2026-03-05", "to": "2026-03-05"}) == [pp_two]
    assert sorted(doc_ids(anna, amount_min=1000, amount_max=1000, currency="EUR")) == sorted([pp, az])
    assert doc_ids(anna, q="seeed") == [pp]
    assert listed(anna, provider=["paypal", "amazon"])["total"] == 3
    assert sorted(doc_ids(anna, provider="PAYPAL")) == sorted([pp, pp_two])  # case-insensitive


def test_paging(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        made = [make_document(conn, on=date(2026, 3, d), total=-100 * d) for d in range(1, 5)]
    page = listed(anna, limit=2, offset=1)
    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 1)
    assert [d["id"] for d in page["documents"]] == [made[2], made[1]]


@pytest.mark.parametrize(
    "params, parameter",
    [
        ({"from": "2026-03-02", "to": "2026-03-01"}, "to"),
        ({"amount_min": 5}, "currency"),
        ({"amount_min": 9, "amount_max": 1, "currency": "EUR"}, "amount_min"),
    ],
)
def test_an_invalid_filter_is_a_422_at_its_parameter(
    anna: TestClient, params: dict[str, Any], parameter: str
):
    body = assert_envelope(anna.get(URL, params=params), 422, "validation_error")
    assert body["details"][0]["location"] == ["query", parameter]


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 501}, {"offset": -1}, {"currency": "eur"}, {"q": " "}]
)
def test_out_of_range_parameters_are_rejected(anna: TestClient, params: dict[str, Any]):
    assert_envelope(anna.get(URL, params=params), 422, "validation_error")


def test_detail_has_the_lines_in_order_and_its_booking_state(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        d = make_document(conn, "paypal", total=-1000, on=D)
        lines(conn, d, ("cable", -400), ("shipping", -600))
    r = anna.get(f"{URL}/{d}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == d and body["line_count"] == 2
    assert [(x["line_no"], x["description"], x["amount"]) for x in body["lines"]] == [
        (1, "cable", {"amount": -400, "currency": "EUR"}),
        (2, "shipping", {"amount": -600, "currency": "EUR"}),
    ]
    assert {"carriers", "carrier_count", "matches", "fully_charged"} & set(body) == set()
    assert body["booking"] is None and body["not_booked"]["reason"] == "no_account"


def test_an_unknown_document_is_a_404_in_the_envelope(anna: TestClient):
    assert_envelope(anna.get(f"{URL}/999999"), 404, "not_found")
    assert_envelope(anna.get(f"{URL}/0"), 422, "validation_error")


def test_providers_lists_importer_names_and_stored_providers_sorted(anna: TestClient, api_engine: Engine):
    from app.core.importers.providers import configure_document_providers, reset_document_providers

    reset_document_providers()
    assert anna.get(f"{URL}/providers").json() == {"providers": []}
    try:
        configure_document_providers(
            {"b": frozenset({"paypal", "amazon"}), "a": frozenset({"amazon", "zalando"})}
        )
        assert anna.get(f"{URL}/providers").json() == {"providers": ["amazon", "paypal", "zalando"]}
        with api_engine.begin() as conn:  # stored providers join in; a spelling already named is not repeated
            for provider in ("Ebay", "PayPal", "ebay"):
                make_document(conn, provider, source_id=f"p-{provider}")
        assert anna.get(f"{URL}/providers").json() == {"providers": ["Ebay", "amazon", "paypal", "zalando"]}
    finally:
        reset_document_providers()


def test_providers_requires_a_session(client: TestClient):
    assert_envelope(client.get(f"{URL}/providers"), 401, "unauthenticated")


# ---- booking state (spec §5.8, documents.md §1) -----------------------------------------------


def clearance(
    api_engine: Engine, start: date = date(2026, 1, 31), providers: tuple[str, ...] = ("Amazon",)
) -> int:
    from app.core.accounts import create_account

    return create_account(
        api_engine, name="Amazon.de", kind="clearance", currency="EUR", start_date=start, providers=providers
    )


def test_a_booked_document_has_its_booking_and_the_detail_its_entries_in_line_order(
    anna: TestClient, api_engine: Engine
) -> None:
    with api_engine.begin() as conn:
        d = make_document(conn, "Amazon", total=-1000, on=date(2026, 2, 1))
        lines(conn, d, ("cable", -400), ("shipping", -600))
    account = clearance(api_engine)
    (st,) = [
        r.id
        for r in api_engine.connect().execute(
            text("SELECT id FROM source_transaction WHERE source_id = :s AND origin = 'booking'"),
            {"s": f"document:{d}"},
        )
    ]
    row = listed(anna)["documents"][0]
    assert row["booking"] == {"account_id": account, "source_transaction_id": st}
    assert row["not_booked"] is None
    body = anna.get(f"{URL}/{d}").json()
    booking = body["booking"]
    assert (booking["account_id"], booking["source_transaction_id"]) == (account, st)
    assert [(e["amount"], e["source_text"]) for e in booking["entries"]] == [
        ({"amount": -400, "currency": "EUR"}, "cable"),
        ({"amount": -600, "currency": "EUR"}, "shipping"),
    ]
    assert body["not_booked"] is None


def test_each_reason_a_document_is_not_booked(anna: TestClient, api_engine: Engine) -> None:
    with api_engine.begin() as conn:
        zero = make_document(conn, "Amazon", total=0, on=date(2026, 2, 1))
        none = make_document(conn, "Elsewhere", total=-100, on=date(2026, 2, 1))
        early = make_document(conn, "Amazon", total=-100, on=date(2026, 1, 31))
        usd = make_document(conn, "Amazon", total=-100, on=date(2026, 2, 1), currency="USD")
    account = clearance(api_engine)
    got = {d["id"]: d["not_booked"] for d in listed(anna)["documents"]}
    blank = {"currency": None, "account_id": None, "start": None}
    assert got[zero] == blank | {"reason": "zero_total"}
    assert got[none] == blank | {"reason": "no_account", "currency": "EUR"}
    assert got[early] == blank | {"reason": "before_start", "account_id": account, "start": "2026-01-31"}
    assert got[usd] == blank | {"reason": "no_account", "currency": "USD"}
    assert anna.get(f"{URL}/{early}").json()["not_booked"]["reason"] == "before_start"


def test_no_start_when_the_account_has_no_balance_record(anna: TestClient, api_engine: Engine) -> None:
    with api_engine.begin() as conn:
        d = make_document(conn, "Amazon", total=-100, on=date(2026, 2, 1))
    account = clearance(api_engine, providers=())
    with api_engine.begin() as conn:
        conn.execute(text("DELETE FROM balance_record WHERE account_id = :a"), {"a": account})
    from app.core.accounts import set_clearance_providers

    set_clearance_providers(api_engine, account, ["Amazon"])
    got = anna.get(f"{URL}/{d}").json()["not_booked"]
    assert (got["reason"], got["account_id"]) == ("no_start", account)


def test_the_booked_filter(anna: TestClient, api_engine: Engine) -> None:
    with api_engine.begin() as conn:
        yes = make_document(conn, "Amazon", total=-100, on=date(2026, 2, 1))
        no = make_document(conn, "Other", total=-100, on=date(2026, 2, 2))
    clearance(api_engine)
    assert doc_ids(anna, booked="true") == [yes]
    assert doc_ids(anna, booked="false") == [no]
    assert sorted(doc_ids(anna)) == sorted([yes, no])
    assert listed(anna, booked="false")["total"] == 1
    assert_envelope(anna.get(URL, params={"booked": "maybe"}), 422, "validation_error")


def test_the_provenance_of_a_booking_carries_its_origin_and_where_it_was_booked_from(
    anna: TestClient, api_engine: Engine
) -> None:
    with api_engine.begin() as conn:
        d = make_document(conn, "Amazon", total=-1000, on=date(2026, 2, 1))
        lines(conn, d, ("cable", -1000))
    clearance(api_engine)
    with api_engine.connect() as conn:
        st = conn.execute(
            text("SELECT id FROM source_transaction WHERE source_id = :s AND origin = 'booking'"),
            {"s": f"document:{d}"},
        ).scalar_one()
    body = anna.get(f"/api/ledger/sources/{st}").json()
    assert body["origin"] == "booking"
    assert body["booking"] == {
        "kind": "document",
        "id": d,
        "provider": "Amazon",
        "reference": body["booking"]["reference"],
        "account_id": None,
    }
