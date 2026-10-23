"""Which importer instances deliver documents for which provider (spec §5.5, documents.md §7), supplied by
the composition root.

Providers are open: a payee names any provider as free text and a document carries its provider's name, so
there is no list to check against. What the registry answers is per instance whether it delivers a
provider (`FetchImporter.delivers`, from the instance's settings: an importer built for fixed providers
answers from its names, one that reads receipts of any provider from its settings). Settling and the review
queue read the answer to judge whether a transaction waits for a document.

Core may not import the concrete plugins, so the composition root hands core the document importers by name,
the way it hands over the classifiers (`core/resolution/registry.py`). An unconfigured process has none: no
document source, so nothing waits. That is the state of every process until a document importer is
registered, and is not an error.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, text

from app.core.plugins.fetch import FetchImporter, delivers_declared

_importers: dict[str, FetchImporter] = {}


class _Declared:
    """A document importer built for fixed providers, from their names alone."""

    emits = frozenset({"documents"})

    def __init__(self, providers: frozenset[str]) -> None:
        self.providers = frozenset(providers)

    def delivers(self, settings: Mapping[str, Any], provider: str) -> bool:
        return delivers_declared(self.providers, provider)


def configure_document_providers(providers: Mapping[str, frozenset[str]]) -> None:
    """Install importers built for fixed providers, {importer name: providers} (replacing any earlier set)."""
    global _importers
    _importers = {name: _Declared(frozenset(p)) for name, p in providers.items() if p}  # type: ignore[misc]


def reset_document_providers() -> None:
    """Forget the document importers (tests, and their teardown)."""
    global _importers
    _importers = {}


def document_providers() -> Mapping[str, frozenset[str]]:
    """{importer name: the providers it names}; empty when none was configured. An importer that names none
    (it answers from its settings) is in the map with the empty set."""
    return {name: frozenset(imp.providers) for name, imp in _importers.items()}


def register_document_importers(importers: Mapping[str, object]) -> None:
    """Install the registered importers that emit documents. The composition root and the dev seed call it
    with the importers they register."""
    global _importers
    _importers = {
        name: imp
        for name, imp in importers.items()
        if isinstance(imp, FetchImporter) and "documents" in imp.emits
    }


def importer_names() -> list[str]:
    """Every provider some registered document importer names, sorted: the suggestions a payee offers."""
    return sorted({p for imp in _importers.values() for p in imp.providers})


_INSTANCES = text("SELECT id, importer, settings FROM importer_instance ORDER BY id")
_PAYEE_PROVIDERS = text(
    "SELECT DISTINCT lower(document_provider) AS provider FROM payee WHERE document_provider IS NOT NULL"
)


def instance_deliveries(conn: Connection) -> dict[int, frozenset[str]]:
    """{instance id: the lower-cased providers it delivers}, judged for every provider some payee names, for
    every instance of a registered document importer (disabled ones too: the caller says what disabled
    means). An instance of an importer that is not registered delivers nothing."""
    if not _importers:
        return {}
    wanted = [str(p) for p in conn.execute(_PAYEE_PROVIDERS).scalars()]
    out: dict[int, frozenset[str]] = {}
    for r in conn.execute(_INSTANCES):
        imp = _importers.get(r.importer)
        if imp is None:
            continue
        settings = dict(r.settings or {})
        out[int(r.id)] = frozenset(p for p in wanted if imp.delivers(settings, p))
    return out


def delivery_pairs(conn: Connection) -> tuple[list[int], list[str]]:
    """`instance_deliveries` as two parallel lists (instance id, lower-cased provider), sorted, for a SQL
    `unnest`."""
    pairs = sorted((i, p) for i, ps in instance_deliveries(conn).items() for p in ps)
    return [i for i, _ in pairs], [p for _, p in pairs]
