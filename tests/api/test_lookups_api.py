"""Read-only category and payee lists for the filter bar and the rows (writes come in step 6)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.fixtures import ledger_seed as seed


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.mark.parametrize("url", ["/api/ledger/categories", "/api/ledger/payees"])
def test_requires_a_session(client: TestClient, url: str):
    assert_envelope(client.get(url), 401, "unauthenticated")


def test_empty_lists(anna: TestClient):
    assert anna.get("/api/ledger/categories").json() == {"categories": []}
    assert anna.get("/api/ledger/payees").json() == {"payees": []}


def test_categories_are_a_flat_tree_in_order(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        food = seed.category(conn, "Food")
        pay = seed.category(conn, "Salary", kind="income")
        beer = seed.category(conn, "Beer", food)
        bread = seed.category(conn, "Bread", food)
        conn.execute(text("UPDATE category SET sort_order = 1 WHERE id = :i"), {"i": pay})
        conn.execute(text("UPDATE category SET sort_order = 2 WHERE id = :i"), {"i": beer})
        conn.execute(text("UPDATE category SET sort_order = 1 WHERE id = :i"), {"i": bread})
        conn.execute(
            text("UPDATE category SET icon = 'utensils', color = 'green' WHERE id = :i"), {"i": food}
        )
    body = anna.get("/api/ledger/categories").json()
    assert body["categories"] == [
        {"id": food, "parent_id": None, "name": "Food", "kind": "expense", "sort_order": 0,
         "icon": "utensils", "color": "green"},
        {"id": pay, "parent_id": None, "name": "Salary", "kind": "income", "sort_order": 1,
         "icon": None, "color": None},
        {"id": bread, "parent_id": food, "name": "Bread", "kind": "expense", "sort_order": 1,
         "icon": None, "color": None},
        {"id": beer, "parent_id": food, "name": "Beer", "kind": "expense", "sort_order": 2,
         "icon": None, "color": None},
    ]  # fmt: skip


def test_payees_are_ordered_by_name_with_presentation_only(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        b = seed.payee(conn, "Bakery")
        a = seed.payee(conn, "Aldi")
        conn.execute(
            text(
                "UPDATE payee SET icon = 'cart', color = 'blue', note = 'n', document_provider = 'amazon'"
                " WHERE id = :i"
            ),
            {"i": a},
        )
    assert anna.get("/api/ledger/payees").json() == {
        "payees": [
            {"id": a, "name": "Aldi", "icon": "cart", "color": "blue", "note": "n"},
            {"id": b, "name": "Bakery", "icon": None, "color": None, "note": None},
        ]
    }  # fmt: skip
