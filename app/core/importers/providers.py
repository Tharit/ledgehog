"""Which importer provides documents for which provider (spec §5.5, documents.md §7), supplied by the
composition root.

An instance's providers are declared by its importer, not stored (`importer_instance` has no providers
column), and core may not import the concrete plugins. So the composition root hands core a map from
importer name to the providers its documents are for, the way it hands over the classifiers
(`core/resolution/registry.py`). Settling and the review queue read it to judge whether a transaction
waits for a document.

An unconfigured process has an empty map: no document source, so nothing waits. That is the state of
every process until a document importer is registered, and is not an error.
"""

from __future__ import annotations

from collections.abc import Mapping

_providers: dict[str, frozenset[str]] = {}


def configure_document_providers(providers: Mapping[str, frozenset[str]]) -> None:
    """Install the map {importer name: providers it delivers documents for} (replacing any earlier one)."""
    global _providers
    _providers = {name: frozenset(p) for name, p in providers.items() if p}


def reset_document_providers() -> None:
    """Forget the map (tests, and their teardown)."""
    global _providers
    _providers = {}


def document_providers() -> Mapping[str, frozenset[str]]:
    """The installed map; empty when none was configured."""
    return dict(_providers)


def provider_pairs() -> tuple[list[str], list[str]]:
    """The map as two parallel lists (importer, provider), sorted, for a SQL `unnest`."""
    pairs = sorted((name, p) for name, ps in _providers.items() for p in ps)
    return [n for n, _ in pairs], [p for _, p in pairs]
