"""The review state of a unit (spec §6, I20, I22), pure: what `confirmed.py` and `flags.py` judge in SQL.

Given the entries of ONE unit (`closure.units_of`), `unit_state` says per entry which flags it carries,
whether the unit is confirmed and why not. `tests/core/units/test_equivalence.py` pins it to the SQL
over a variety of generated units, so the preview (which has no stored rows to ask) judges a draft
exactly as settling will judge the committed result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.core.plugins.classifier import STANDING_PASSES
from app.core.units.closure import UnitEntry

Reason = Literal["incomplete", "unpaired_transfer", "non_standing_keys"]


@dataclass(frozen=True, slots=True)
class UnitState:
    confirmed: bool
    reasons: tuple[Reason, ...]  # empty iff confirmed; in the fixed order incomplete, unpaired, keys
    flags: dict[int, tuple[str, ...]]  # per entry id, tokens sorted


def has_nonstanding_key(entry: UnitEntry) -> bool:
    """A derivation key that awaits a human: a proposal, or a key without a pass (schema comment)."""
    return any(
        not (isinstance(k, dict) and k.get("pass") in STANDING_PASSES) for k in entry.derivation.values()
    )


def is_unclassified(entry: UnitEntry) -> bool:
    return entry.type is None or (entry.type == "flow" and entry.category_id is None)


def unit_state(entries: Sequence[UnitEntry]) -> UnitState:
    """The state of the unit made of `entries`, all movements (a derived entry is in no unit)."""
    if any(not e.movement for e in entries):
        raise ValueError("a derived entry is in no unit")
    nonstanding = any(has_nonstanding_key(e) for e in entries)
    incomplete = any(is_unclassified(e) for e in entries)
    unpaired = any(e.type == "transfer" and e.counterpart_entry_id is None for e in entries)
    reasons: list[Reason] = []
    if incomplete:
        reasons.append("incomplete")
    if unpaired:
        reasons.append("unpaired_transfer")
    if nonstanding:
        reasons.append("non_standing_keys")
    flags = {
        e.id: tuple(t for t, on in (("unclassified", is_unclassified(e)), ("unconfirmed", nonstanding)) if on)
        for e in entries
    }
    return UnitState(confirmed=not reasons, reasons=tuple(reasons), flags=flags)
