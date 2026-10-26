"""The document importers this deployment registers, and the provider names they give (spec §5.5),
supplied by the composition root.

Providers are open: a document carries its provider's name as the importer reads it, so there is no list
to check against. What an importer built for fixed providers names is a suggestion only: the names a
clearance account's provider list offers (`GET /api/documents/providers`).

Core may not import the concrete plugins, so the composition root hands core the document importers by name,
the way it hands over the classifiers (`core/resolution/registry.py`). An unconfigured process has none.
That is the state of every process until a document importer is registered, and is not an error.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.plugins.fetch import FetchImporter

_importers: dict[str, FetchImporter] = {}


class _Declared:
    """A document importer built for fixed providers, from their names alone."""

    emits = frozenset({"documents"})

    def __init__(self, providers: frozenset[str]) -> None:
        self.providers = frozenset(providers)


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
    is in the map with the empty set."""
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
    """Every provider some registered document importer names, sorted: what a provider list suggests."""
    return sorted({p for imp in _importers.values() for p in imp.providers})
