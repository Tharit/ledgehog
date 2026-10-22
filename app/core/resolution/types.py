"""What resolution returns: each decided field with the pass that decided it and its basis."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.core.plugins.classifier import FIELD_ORDER, MAY_BE_EMPTY, Field


@dataclass(frozen=True, slots=True)
class Decided:
    """A value and its key: the `derivation` pass name and the machine-readable basis.

    No value (`None`) is an explained absence: a pass's proposal that the field stays empty, its basis
    saying why and carrying `"none": true` (the key stored on the empty field)."""

    value: int | str | None
    pass_name: str
    basis: Mapping[str, Any]


# An empty field with a key: a standing key is a decision to leave it empty (only a field that may be empty
# permits that, `MAY_BE_EMPTY`: NULL with the key `{"pass": "user"}`), a proposal's key explains why it is
# empty. An empty field without a key is undecided, which is also what an empty result stores.
def is_decided_empty(d: Decided | None) -> bool:
    """A decision to leave the field empty: `Decided(None, "user", {})`, never a pass's proposal."""
    return d is not None and d.value is None and d.pass_name == "user"


def is_explained_absence(d: Decided | None) -> bool:
    """A pass's proposal that the field stays empty (its basis says why)."""
    return d is not None and d.value is None and d.pass_name != "user"


def stands_for(d: Decided | None) -> tuple[int | str | None, bool]:
    """What a decision stands for, to tell whether a field has changed along the walk: its value, and
    whether it is a decision to leave the field empty. That decision is not the same as no decision or an
    explained absence, though all three store NULL."""
    return (None, False) if d is None else (d.value, is_decided_empty(d))


def check_may_be_empty(field: Field, d: Decided | None) -> None:
    """Only a field that may be empty may be decided empty: any other with a decided empty is a bug."""
    if field not in MAY_BE_EMPTY and is_decided_empty(d):
        raise ValueError(f"a decided empty is only valid for a field that may be empty, not {field}")


def column_of(d: Decided | None) -> int | None:
    """The id a decision stores in its column: none for no decision, an explained absence or a decided
    empty."""
    return None if d is None or d.value is None else int(d.value)


class Resolved(Mapping[Field, Decided]):
    """An immutable mapping of the decided fields; an undecided field is absent."""

    __slots__ = ("_items",)

    def __init__(self, items: Mapping[Field, Decided] | None = None) -> None:
        ordered = {f: items[f] for f in FIELD_ORDER if items and f in items}
        for f, d in ordered.items():
            check_may_be_empty(f, d)
        self._items: Mapping[Field, Decided] = MappingProxyType(ordered)

    def __getitem__(self, key: Field) -> Decided:
        return self._items[key]

    def __iter__(self) -> Iterator[Field]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"Resolved({dict(self._items)!r})"
