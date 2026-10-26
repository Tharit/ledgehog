"""A deterministic document importer for development and demonstration (spec §5.5, v1).

It delivers exactly the documents its instance settings list, so a database can be filled with documents
that behave the same on every run. Real document importers come later; this one is what the dev seed
(`scripts/dev_seed.py`) feeds through the same ingest a real one would use.

Settings (`importer_instance.settings`):

    start_date       ISO date: the instance's start date (spec §5.5)
    covered_through  ISO date: how far the "provider" is complete
    documents        list of {provider, external_id, occurred_on, total_minor, currency, merchant_name?,
                     title?, lines?: [{description, amount_minor, qty?}]}
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from datetime import date
from typing import Any

from app.core.plugins.errors import InvalidProfile
from app.core.plugins.fetch import FetchSession, FetchSessionBase, Prompter
from app.core.plugins.importer import (
    DocumentDelivery,
    IncomingDocument,
    IncomingDocumentLine,
)

PROVIDERS = frozenset({"paypal", "amazon"})


def _date(settings: Mapping[str, Any], key: str) -> date:
    value = settings.get(key)
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise InvalidProfile(f"{key} must be an ISO date") from None


def _document(raw: Any) -> IncomingDocument:
    if not isinstance(raw, Mapping):
        raise InvalidProfile("documents must be a list of objects")
    try:
        lines = tuple(
            IncomingDocumentLine(str(x["description"]), int(x["amount_minor"]), x.get("qty"))
            for x in raw.get("lines", ())
        )
        doc = IncomingDocument(
            provider=str(raw["provider"]),
            external_id=str(raw["external_id"]),
            occurred_on=date.fromisoformat(str(raw["occurred_on"])),
            total_minor=int(raw["total_minor"]),
            currency=str(raw["currency"]),
            raw=dict(raw),
            merchant_name=raw.get("merchant_name"),
            title=raw.get("title"),
            lines=lines,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidProfile(f"a document is malformed: {type(exc).__name__}") from None
    if doc.provider not in PROVIDERS:
        raise InvalidProfile(f"a document names a provider the importer does not serve: {doc.provider}")
    return doc


class _Session(FetchSessionBase):
    """The session of a stateless importer: nothing to authenticate, so it only delivers documents."""

    def __init__(self, importer: TestDocumentImporter, settings: Mapping[str, Any]) -> None:
        self._importer = importer
        self._settings = settings

    def fetch_documents(
        self, *, since: date, today: date, minor_units_of: Callable[[str], int]
    ) -> DocumentDelivery:
        return self._importer.fetch(self._settings, since=since, today=today)


class TestDocumentImporter:
    """Satisfies `FetchImporter` (documents only); reads nothing but its settings."""

    __test__ = False  # not a pytest class, whatever its name

    emits: frozenset[str] = frozenset({"documents"})
    providers: frozenset[str] = PROVIDERS

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        _date(settings, "start_date")
        _date(settings, "covered_through")
        documents = settings.get("documents", ())
        if not isinstance(documents, list | tuple):
            raise InvalidProfile("documents must be a list")
        for raw in documents:
            _document(raw)

    def default_fetch_start(self, settings: Mapping[str, Any], *, today: date) -> date:
        return _date(settings, "start_date")

    def open(
        self,
        settings: Mapping[str, Any],
        state: MutableMapping[str, Any],
        prompter: Prompter,
        *,
        today: date,
    ) -> FetchSession:
        return _Session(self, settings)

    def fetch(self, settings: Mapping[str, Any], *, since: date, today: date) -> DocumentDelivery:
        """The documents dated `since` or later (what the session's `fetch_documents` delivers)."""
        documents = tuple(_document(raw) for raw in settings.get("documents", ()))
        return DocumentDelivery(
            documents=tuple(d for d in documents if d.occurred_on >= since),
            covered_through=min(_date(settings, "covered_through"), today),
            covered_from=_date(settings, "start_date"),
        )
