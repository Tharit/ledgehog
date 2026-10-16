"""`GET /api/documents` and `GET /api/documents/{id}` (architecture §4.1, spec §5.8, documents.md §9)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.core.documents.test_documents_read import carry, lines, txn
from tests.core.units.doc_helpers import make_document
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import make_source

URL = "/api/documents"
D = date(2026, 3, 10)


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def acct(api_engine: Engine) -> int:
    with api_engine.begin() as conn:
        return seed.account(conn)


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


def test_row_shape_money_and_the_carrying_transaction(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        d = make_document(conn, "paypal", total=-1000, on=D)
        conn.execute(
            text("UPDATE external_document SET merchant_name = 'Shop', title = 'T' WHERE id = :i"), {"i": d}
        )
        lines(conn, d, ("a", -400), ("b", -600))
        entry = txn(conn, acct, amount=-1000)
        carry(conn, entry, d)
        free = make_document(conn, "amazon", total=1500, on=date(2026, 3, 1))
    rows = {r["id"]: r for r in listed(anna)["documents"]}
    assert rows[d] == {
        "id": d,
        "version": 1,
        "provider": "paypal",
        "external_id": rows[d]["external_id"],
        "importer_instance_id": None,
        "occurred_on": "2026-03-10",
        "total": {"amount": -1000, "currency": "EUR"},
        "merchant_name": "Shop",
        "title": "T",
        "line_count": 2,
        "carrier": {
            "entry_id": entry,
            "source_transaction_id": rows[d]["carrier"]["source_transaction_id"],
            "account_id": acct,
            "booked_on": "2026-03-10",
            "amount": {"amount": -1000, "currency": "EUR"},
        },
    }
    assert rows[free]["carrier"] is None and rows[free]["total"] == {"amount": 1500, "currency": "EUR"}


def test_filters_and_the_picker_combination(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        pp = make_document(conn, "paypal", total=-1000, on=date(2026, 3, 1))
        pp_linked = make_document(conn, "paypal", total=-2000, on=date(2026, 3, 5))
        az = make_document(conn, "amazon", total=-1000, on=date(2026, 3, 9))
        conn.execute(
            text("UPDATE external_document SET merchant_name = 'Seeed Studio' WHERE id = :i"), {"i": pp}
        )
        carry(conn, txn(conn, acct, amount=-2000), pp_linked)
    assert sorted(doc_ids(anna, provider="paypal")) == sorted([pp, pp_linked])
    assert doc_ids(anna, provider="paypal", linked="false") == [pp]  # the panel's pick by hand
    assert doc_ids(anna, linked="true") == [pp_linked]
    assert doc_ids(anna, **{"from": "2026-03-05", "to": "2026-03-05"}) == [pp_linked]
    assert sorted(doc_ids(anna, amount_min=1000, amount_max=1000, currency="EUR")) == sorted([pp, az])
    assert doc_ids(anna, q="seeed") == [pp]
    assert listed(anna, provider=["paypal", "amazon"])["total"] == 3


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


def test_detail_of_an_unlinked_document_lists_its_reverse_matches(
    anna: TestClient, api_engine: Engine, acct: int
):
    with api_engine.begin() as conn:
        d = make_document(conn, "paypal", total=-1000, on=D)
        lines(conn, d, ("cable", -400), ("shipping", -600))
        confirmed = txn(conn, acct, amount=-1000, on=D)  # confirmed, and no provider payee
        pending = txn(
            conn, acct, amount=-1000, on=date(2026, 3, 12), derivation='{"category": {"pass": "history"}}'
        )
        other = make_document(conn, "amazon", total=-1000, on=D)
        carrying = txn(conn, acct, amount=-1000, on=date(2026, 3, 11))
        carry(conn, carrying, other)
        source = txn(conn, acct, amount=-1000, on=date(2026, 3, 16))
        conn.execute(
            text("UPDATE ledger_entry SET type = NULL, category_id = NULL WHERE id = :i"), {"i": source}
        )
        dup_src = conn.execute(
            text("SELECT source_transaction_id FROM ledger_entry WHERE id = :i"), {"i": confirmed}
        ).scalar_one()
        make_source(conn, acct, amount=-1000, booked_on=D, duplicate_of=dup_src)
    r = anna.get(f"{URL}/{d}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == d and body["carrier"] is None
    assert [(x["line_no"], x["description"], x["amount"]) for x in body["lines"]] == [
        (1, "cable", {"amount": -400, "currency": "EUR"}),
        (2, "shipping", {"amount": -600, "currency": "EUR"}),
    ]
    matches = {m["entry_id"]: m for m in body["matches"]}
    assert [m["entry_id"] for m in body["matches"]][0] == confirmed  # nearest first
    assert set(matches) == {confirmed, pending, carrying, source}  # the duplicate is not listed
    assert matches[confirmed]["confirmed"] is True and matches[pending]["confirmed"] is False
    assert matches[source]["confirmed"] is False
    assert matches[carrying]["document_id"] == other and matches[confirmed]["document_id"] is None
    assert matches[confirmed]["amount"] == {"amount": -1000, "currency": "EUR"}
    assert matches[confirmed]["instructed_amount"] is None


def test_detail_of_a_linked_document_names_its_carrier_and_has_no_matches(
    anna: TestClient, api_engine: Engine, acct: int
):
    with api_engine.begin() as conn:
        d = make_document(conn, total=-1000, on=D)
        entry = txn(conn, acct, amount=-1000)
        carry(conn, entry, d)
        txn(conn, acct, amount=-1000)
    body = anna.get(f"{URL}/{d}").json()
    assert body["carrier"]["entry_id"] == entry and body["matches"] == [] and body["lines"] == []


def test_an_unknown_document_is_a_404_in_the_envelope(anna: TestClient):
    assert_envelope(anna.get(f"{URL}/999999"), 404, "not_found")
    assert_envelope(anna.get(f"{URL}/0"), 422, "validation_error")


def test_providers_lists_the_registered_providers_sorted(anna: TestClient):
    from app.core.importers.providers import configure_document_providers, reset_document_providers

    reset_document_providers()
    assert anna.get(f"{URL}/providers").json() == {"providers": []}
    try:
        configure_document_providers(
            {"b": frozenset({"paypal", "amazon"}), "a": frozenset({"amazon", "zalando"})}
        )
        assert anna.get(f"{URL}/providers").json() == {"providers": ["amazon", "paypal", "zalando"]}
    finally:
        reset_document_providers()


def test_providers_requires_a_session(client: TestClient):
    assert_envelope(client.get(f"{URL}/providers"), 401, "unauthenticated")
