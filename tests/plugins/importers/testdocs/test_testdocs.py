"""The development document importer delivers exactly what its settings list."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.plugins.errors import InvalidProfile
from app.core.plugins.fetch import FetchImporter
from app.plugins.importers.testdocs import TestDocumentImporter

DOC: dict[str, Any] = {
    "provider": "paypal",
    "source_id": "A",
    "occurred_on": "2026-06-01",
    "total_minor": -1000,
    "currency": "EUR",
    "merchant_name": "Shop",
    "lines": [{"description": "Item", "amount_minor": -1000, "qty": 1}],
}


def settings(*docs: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {"start_date": "2026-01-01", "covered_through": "2026-06-30", "documents": list(docs), **kw}


def test_it_satisfies_the_protocol_and_serves_two_providers():
    assert isinstance(TestDocumentImporter(), FetchImporter)
    assert TestDocumentImporter.emits == {"documents"}
    assert TestDocumentImporter.providers == {"paypal", "amazon"}


def test_its_session_delivers_what_fetch_does_and_its_default_start_is_the_start_date():
    imp = TestDocumentImporter()
    s = settings(DOC)
    assert imp.default_fetch_start(s, today=date(2026, 7, 1)) == date(2026, 1, 1)
    session = imp.open(s, {}, None, today=date(2026, 7, 1))  # type: ignore[arg-type]
    try:
        out = session.fetch_documents(
            since=date(2026, 1, 1), today=date(2026, 7, 1), minor_units_of=lambda c: 2
        )
        assert [d.source_id for d in out.documents] == ["A"]
        assert session.accounts() == ()
    finally:
        session.close()


def test_fetch_delivers_the_listed_documents_from_since_and_the_coverage():
    older = {**DOC, "source_id": "B", "occurred_on": "2026-05-01"}
    s = settings(DOC, older)
    delivery = TestDocumentImporter().fetch(s, since=date(2026, 5, 15), today=date(2026, 7, 1))
    assert [d.source_id for d in delivery.documents] == ["A"]
    doc = delivery.documents[0]
    assert (doc.total_minor, doc.currency, doc.merchant_name) == (-1000, "EUR", "Shop")
    assert [(x.description, x.amount_minor, x.qty) for x in doc.lines] == [("Item", -1000, 1)]
    assert (delivery.covered_through, delivery.covered_from) == (date(2026, 6, 30), date(2026, 1, 1))


def test_coverage_never_passes_today():
    delivery = TestDocumentImporter().fetch(settings(), since=date(2026, 1, 1), today=date(2026, 6, 10))
    assert delivery.covered_through == date(2026, 6, 10)


def test_valid_settings_pass():
    TestDocumentImporter().validate_settings(settings(DOC))


@pytest.mark.parametrize(
    "bad",
    [
        {"covered_through": "2026-06-30", "documents": []},
        {"start_date": "2026-01-01", "covered_through": "soon", "documents": []},
        settings({**DOC, "provider": "ebay"}),
        settings({k: v for k, v in DOC.items() if k != "total_minor"}),
        settings({**DOC, "occurred_on": "yesterday"}),
        settings(DOC) | {"documents": "none"},
    ],
)
def test_malformed_settings_are_refused_naming_the_problem(bad: dict[str, Any]):
    with pytest.raises(InvalidProfile):
        TestDocumentImporter().validate_settings(bad)
