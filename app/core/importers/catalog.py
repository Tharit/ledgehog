"""The importer catalog (architecture §4.1 'The catalog'): what this deployment registers.

The composition root hands over the importer objects; the catalog reads what they declare and nothing
else, so core never imports a plugin. An object is a *file* importer when it satisfies `FileImporter`
(it parses an upload; it emits transactions) and a *fetch* importer otherwise, which declares the kinds
it delivers in `emits` (`FetchImporter`). Either may ship `presets` (settings, by name).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.plugins.importer import FileImporter


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    kind: Literal["file", "fetch"]
    emits: tuple[str, ...]
    presets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def describe(name: str, importer: object) -> CatalogEntry:
    """One importer's catalog entry, derived from the object."""
    is_file = isinstance(importer, FileImporter)
    emits: tuple[str, ...] = ("transactions",) if is_file else tuple(sorted(importer.emits))  # type: ignore[attr-defined]
    return CatalogEntry(
        name=name,
        kind="file" if is_file else "fetch",
        emits=emits,
        presets=dict(getattr(importer, "presets", None) or {}),
    )


def catalog(importers: Mapping[str, object]) -> list[CatalogEntry]:
    """Every registered importer, by name."""
    return [describe(name, importers[name]) for name in sorted(importers)]
