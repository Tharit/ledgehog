"""The closure of a unit (spec §6, I31): which entries are reviewed together, in pure Python.

A unit is the entries of one source transaction plus, through a paired transfer leg, the entries of
the partner's source transaction, plus the entries of every other transaction carrying the same document
(spec I21, I35). A transaction carrying a document has no transfer entry, so a unit is pair-shaped or
document-shaped, never a chain: one step joins it. Entries without a source transaction (derived: opening,
valuation, reconciliation) are in no unit. `core/resolution/confirmed.py` computes the same keys in SQL;
`tests/core/units/test_equivalence.py` pins the two together. No database access here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class UnitEntry:
    """What the judgement of a unit reads from one entry."""

    id: int
    source_transaction_id: int | None  # None: a derived entry, in no unit
    type: str | None
    category_id: int | None
    counterpart_entry_id: int | None
    derivation: Mapping[str, Any] = field(default_factory=dict)
    # the document the entry's transaction carries; stored, only its original entry says (`ledger_entry
    # .document_id`), and one entry of a source saying it is enough to join the source
    document_id: int | None = None

    @property
    def movement(self) -> bool:
        return self.source_transaction_id is not None


def unit_keys(entries: Iterable[UnitEntry]) -> dict[int, int]:
    """The unit key of every movement among `entries`: the lowest source transaction id of its unit.

    `entries` must hold every entry of the sources involved (the loaded closure); a partner outside
    them is not followed, and neither is a carrier of the document that is not among them. Derived
    entries have no key.
    """
    movements = [e for e in entries if e.source_transaction_id is not None]
    source_of = {e.id: e.source_transaction_id for e in movements}
    parent: dict[int, int] = {s: s for s in set(source_of.values()) if s is not None}

    def find(s: int) -> int:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for e in movements:
        partner = source_of.get(e.counterpart_entry_id) if e.counterpart_entry_id is not None else None
        if partner is not None and e.source_transaction_id is not None:
            a, b = find(e.source_transaction_id), find(partner)
            if a != b:
                parent[max(a, b)] = min(a, b)
    carrier: dict[int, int] = {}  # document -> the source that carries it (the first seen)
    for e in movements:
        if e.document_id is not None and e.source_transaction_id is not None:
            first = carrier.setdefault(e.document_id, e.source_transaction_id)
            a, b = find(e.source_transaction_id), find(first)
            if a != b:
                parent[max(a, b)] = min(a, b)
    return {e.id: find(e.source_transaction_id) for e in movements if e.source_transaction_id is not None}


def units_of(entries: Iterable[UnitEntry]) -> dict[int, tuple[UnitEntry, ...]]:
    """The movements grouped by unit key, each unit ordered by entry id."""
    items = list(entries)
    keys = unit_keys(items)
    grouped: dict[int, list[UnitEntry]] = {}
    for e in sorted((e for e in items if e.id in keys), key=lambda e: e.id):
        grouped.setdefault(keys[e.id], []).append(e)
    return {k: tuple(v) for k, v in grouped.items()}
