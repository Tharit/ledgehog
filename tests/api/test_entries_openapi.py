"""The entries operation is typed in the OpenAPI document (generated TypeScript types follow it)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, get_args

import pytest

from app.api import create_app
from app.api.openapi import build_openapi
from app.core.ledger import ENTRY_TYPES, REVIEW_FLAGS
from app.utils.config import Config
from app.utils.db.engine import make_engine

ENV = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "1",
    "POSTGRES_DB": "nodb",
    "POSTGRES_USER": "nobody",
    "POSTGRES_PASSWORD": "unused-pw",
    "BASE_CURRENCY": "EUR",
    "TIMEZONE": "UTC",
}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    cfg = Config.from_env(ENV)
    return build_openapi(create_app(replace(cfg, expose_openapi=True), make_engine(cfg)))


def test_the_200_response_references_entry_page_out(schema):
    op = schema["paths"]["/api/ledger/entries"]["get"]
    ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/EntryPageOut"


def test_a_sample_row_validates_against_the_model():
    from app.api.routers.entries import EntryPageOut

    row = {
        "id": 1,
        "version": 1,
        "account_id": 2,
        "booked_on": "2026-03-10",
        "value_on": None,
        "amount": {"amount": -5, "currency": "EUR"},
        "type": "flow",
        "description": None,
        "note": None,
        "display_text": None,
        "source_text": None,
        "payee_id": None,
        "category_id": None,
        "counter_account_id": None,
        "counterpart_entry_id": None,
        "source_transaction_id": None,
        "review_flags": ["unconfirmed"],
        "tag_ids": [3],
        "source": {
            "amount": {"amount": -1250, "currency": "EUR"},
            "counterparty_name": "CP",
            "counterparty_ref": None,
            "counterparty_bic": None,
            "purpose": None,
            "booking_text": None,
            "end_to_end_id": None,
            "mandate_ref": None,
            "instructed_amount": {"amount": -7, "currency": "USD"},
            "source_format": "csv",
            "booking": None,
        },
        "derivation": {"category": {"pass": "history", "basis": {"from": "similar"}}},
        "unit_key": 7,
        "authored": False,
        "origin": "import",
        "partner": {
            "entry_id": 9,
            "account_id": 4,
            "booked_on": "2026-03-10",
            "amount": {"amount": 5, "currency": "EUR"},
        },
    }
    page = EntryPageOut.model_validate(
        {
            "entries": [row],
            "total": 1,
            "sums": [{"amount": -1250, "currency": "EUR"}],
            "limit": 100,
            "offset": 0,
        }
    )
    assert page.model_dump(mode="json")["entries"] == [row]


def test_enums_are_named_and_match_core(schema):
    entry = schema["components"]["schemas"]["EntryOut"]["properties"]
    types = [s for s in entry["type"]["anyOf"] if "enum" in s][0]["enum"]
    assert tuple(types) == ENTRY_TYPES
    assert tuple(entry["review_flags"]["items"]["enum"]) == REVIEW_FLAGS


def test_literals_cover_core_tokens():
    from app.api.routers.entries import EntryType, ReviewFlag

    assert get_args(EntryType) == ENTRY_TYPES
    assert get_args(ReviewFlag) == REVIEW_FLAGS


def test_get_ledger_entry_is_documented(schema):
    op = schema["paths"]["/api/ledger/entries/{entry_id}"]["get"]
    assert op["operationId"] == "get_ledger_entry"
    assert op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/EntryOut"
    )


def test_source_is_nullable_and_shared_with_the_rule_preview(schema):
    comps = schema["components"]["schemas"]
    refs = [s.get("$ref") for s in comps["EntryOut"]["properties"]["source"]["anyOf"]]
    assert "#/components/schemas/SourceTransactionOut" in refs
    refs = [s.get("$ref") for s in comps["PreviewRowOut"]["properties"]["source"]["anyOf"]]
    assert "#/components/schemas/SourceTransactionOut" in refs
    assert set(comps["SourceTransactionOut"]["properties"]) == {
        "amount", "counterparty_name", "counterparty_ref", "counterparty_bic", "purpose", "booking_text",
        "end_to_end_id", "mandate_ref", "instructed_amount", "source_format", "booking",
    }  # fmt: skip
    assert "counterparty_name" not in comps["EntryOut"]["properties"]
