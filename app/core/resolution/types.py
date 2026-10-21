"""What resolution returns: each decided field with the pass that decided it and its basis."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.core.plugins.classifier import FIELD_ORDER, NO_PAYEE, Field


@dataclass(frozen=True, slots=True)
class Decided:
    """A value and its key: the `derivation` pass name and the machine-readable basis.

    No value (`None`) is an explained absence: a pass's proposal that the field stays empty, its basis
    saying why and carrying `"none": true` (the key stored on the empty field)."""

    value: int | str | None
    pass_name: str
    basis: Mapping[str, Any]


# A flow's payee is in one of three states: a payee, undecided (NULL, no key) or NO PAYEE BY THE USER'S
# DECISION (NULL with the standing key `{"pass": "user"}`). Resolution carries the third as this decision on
# the payee: the value is the `NO_PAYEE` sentinel (a stored column holds NULL), the pass is `user`.
USER_NO_PAYEE = Decided(NO_PAYEE, "user", {})


def is_user_no_payee(d: Decided | None) -> bool:
    """The user's decision of no payee (the standing third state), never a pass's proposal."""
    return d is not None and d.value == NO_PAYEE and d.pass_name == "user"


def column_of(d: Decided | None) -> int | None:
    """The id a decision stores in its column: none for no decision, an explained absence or the user's
    decision of no payee."""
    return None if d is None or d.value is None or is_user_no_payee(d) else int(d.value)


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
