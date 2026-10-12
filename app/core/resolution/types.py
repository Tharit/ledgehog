"""What resolution returns: each decided field with the pass that decided it and its basis."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.core.plugins.classifier import FIELD_ORDER, Field


@dataclass(frozen=True, slots=True)
class Decided:
    """A value and its key: the `derivation` pass name and the machine-readable basis."""

    value: int | str
    pass_name: str
    basis: Mapping[str, Any]


class Resolved(Mapping[Field, Decided]):
    """An immutable mapping of the decided fields; an undecided field is absent."""

    __slots__ = ("_items",)

    def __init__(self, items: Mapping[Field, Decided] | None = None) -> None:
        ordered = {f: items[f] for f in FIELD_ORDER if items and f in items}
        self._items: Mapping[Field, Decided] = MappingProxyType(ordered)

    def __getitem__(self, key: Field) -> Decided:
        return self._items[key]

    def __iter__(self) -> Iterator[Field]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"Resolved({dict(self._items)!r})"
