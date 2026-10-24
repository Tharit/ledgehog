"""A deterministic document importer for tests: it delivers exactly what it was given."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from datetime import date
from typing import Any

from app.core.plugins.fetch import FetchSession, FetchSessionBase, Prompter
from app.core.plugins.importer import (
    DocumentDelivery,
    IncomingDocument,
    IncomingDocumentLine,
)


class _FakeSession(FetchSessionBase):
    def __init__(self, importer: FakeDocumentImporter) -> None:
        self._importer = importer

    def fetch_documents(
        self, *, since: date, today: date, minor_units_of: Callable[[str], int]
    ) -> DocumentDelivery:
        return self._importer.fetch({}, since=since, today=today)


class FakeDocumentImporter:
    """Satisfies `FetchImporter` (documents). `fetch` returns the documents dated `since` or later."""

    emits = frozenset({"documents"})

    def default_fetch_start(self, settings: Mapping[str, Any], *, today: date) -> date:
        return date(2026, 1, 1)

    def open(
        self, settings: Mapping[str, Any], state: MutableMapping[str, Any], prompter: Prompter, *, today: date
    ) -> FetchSession:
        return _FakeSession(self)

    def __init__(
        self,
        documents: Sequence[IncomingDocument] = (),
        *,
        providers: frozenset[str] = frozenset({"paypal"}),
        covered_through: date = date(2026, 6, 30),
        covered_from: date | None = None,
    ) -> None:
        self.documents = tuple(documents)
        self.providers = providers
        self.covered_through = covered_through
        self.covered_from = covered_from
        self.calls: list[tuple[date, date]] = []

    def delivers(self, settings: Mapping[str, Any], provider: str) -> bool:
        return provider.lower() in {p.lower() for p in self.providers}

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        return None

    def fetch(self, settings: Mapping[str, Any], *, since: date, today: date) -> DocumentDelivery:
        self.calls.append((since, today))
        return DocumentDelivery(
            documents=tuple(d for d in self.documents if d.occurred_on >= since),
            covered_through=self.covered_through,
            covered_from=self.covered_from,
        )


def line(description: str = "Item", amount: int = -1000, qty: int | None = None) -> IncomingDocumentLine:
    return IncomingDocumentLine(description, amount, qty)


def document(external_id: str = "D1", **kw: Any) -> IncomingDocument:
    base: dict[str, Any] = {
        "provider": "paypal",
        "external_id": external_id,
        "occurred_on": date(2026, 6, 1),
        "total_minor": -1000,
        "currency": "EUR",
        "raw": {"n": 1},
        "merchant_name": "Seeed Studio",
        "title": "Order",
        "lines": (line(),),
    }
    base.update(kw)
    return IncomingDocument(**base)
