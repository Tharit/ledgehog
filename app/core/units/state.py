"""The review state of a unit (spec §6, I20, I22), pure: what `confirmed.py` and `flags.py` judge in SQL.

Given the entries of ONE unit (`closure.units_of`), `unit_state` says per entry which flags it carries,
whether the unit is confirmed and why not. `tests/core/units/test_equivalence.py` pins it to the SQL
over a variety of generated units, so the preview (which has no stored rows to ask) judges a draft
exactly as settling will judge the committed result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.core.plugins.classifier import STANDING_PASSES
from app.core.units.closure import UnitEntry
from app.core.units.documents import DocumentFacts

# `unpaired_transfer` is an unpaired leg of which nothing more is known (no sync facts were given);
# `waiting_for_partner` and `unmatched_transfer` are its two states (spec §5.7), judged like the flags
# `waiting_for_document` and `document_suggested` are a transaction's open document (documents.md §1, §7)
Reason = Literal[
    "incomplete",
    "unpaired_transfer",
    "waiting_for_partner",
    "unmatched_transfer",
    "waiting_for_document",
    "document_suggested",
    "non_standing_keys",
]
LegState = Literal["waiting", "unmatched"]


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


def leg_states_of_flags(flags: Mapping[int, Sequence[str]]) -> dict[int, LegState]:
    """The state of each leg from the review flags settling stored on it (`waiting`, `unmatched_transfer`)."""
    out: dict[int, LegState] = {}
    for entry_id, tokens in flags.items():
        if "waiting" in tokens:
            out[entry_id] = "waiting"
        elif "unmatched_transfer" in tokens:
            out[entry_id] = "unmatched"
    return out


def document_facts_of_flags(entries: Sequence[tuple[int, Sequence[str]]]) -> dict[int, DocumentFacts]:
    """The document facts of each entry from the review flags settling stored on it: `document_suggested`,
    and `waiting` on an entry that is not a transfer leg (a leg waits for its partner, never a document;
    the caller passes only the flows)."""
    return {
        i: DocumentFacts(awaited="waiting" in tokens, suggested="document_suggested" in tokens)
        for i, tokens in entries
    }


def unit_state(
    entries: Sequence[UnitEntry],
    leg_states: Mapping[int, LegState] | None = None,
    documents: Mapping[int, DocumentFacts] | None = None,
) -> UnitState:
    """The state of the unit made of `entries`, all movements (a derived entry is in no unit).

    `leg_states` says per unpaired transfer leg whether it is waiting or unmatched (spec §5.7); the reason
    for it is then `waiting_for_partner` or `unmatched_transfer`. A leg it does not name is the generic
    `unpaired_transfer`. A unit has at most one unpaired leg: a source has one transfer entry (I31) and an
    unpaired leg's unit is its own source.

    `documents` says per entry whether its transaction awaits a document or has suggestions (what the SQL
    reads as `doc_awaited`, `doc_suggested`). It counts only for the original entry of a source (the lowest
    id of its source among `entries`, which holds every entry of each source) that has no `document` key:
    the gate of documents.md §1.
    """
    if any(not e.movement for e in entries):
        raise ValueError("a derived entry is in no unit")
    open_docs = _open_documents(entries, documents or {})
    nonstanding = any(has_nonstanding_key(e) for e in entries)
    incomplete = any(is_unclassified(e) for e in entries)
    unpaired_legs = [e for e in entries if e.type == "transfer" and e.counterpart_entry_id is None]
    unpaired = bool(unpaired_legs)
    reasons: list[Reason] = []
    if incomplete:
        reasons.append("incomplete")
    if unpaired:
        known = {(leg_states or {}).get(e.id) for e in unpaired_legs}
        reasons.append(
            "waiting_for_partner"
            if "waiting" in known
            else "unmatched_transfer"
            if "unmatched" in known
            else "unpaired_transfer"
        )
    if any(f.awaited for f in open_docs.values()):
        reasons.append("waiting_for_document")
    if any(f.suggested for f in open_docs.values()):
        reasons.append("document_suggested")
    if nonstanding:
        reasons.append("non_standing_keys")
    flags = {
        e.id: tuple(
            t
            for t, on in (
                ("document_suggested", open_docs[e.id].suggested if e.id in open_docs else False),
                ("unclassified", is_unclassified(e)),
                ("unconfirmed", nonstanding),
                ("waiting", open_docs[e.id].awaited if e.id in open_docs else False),
            )
            if on
        )
        for e in entries
    }
    return UnitState(confirmed=not reasons, reasons=tuple(reasons), flags=flags)


def _open_documents(
    entries: Sequence[UnitEntry], documents: Mapping[int, DocumentFacts]
) -> dict[int, DocumentFacts]:
    """The facts that count: those of the original entry of each source that has no `document` key."""
    first: dict[int | None, int] = {}
    for e in entries:
        first[e.source_transaction_id] = min(e.id, first.get(e.source_transaction_id, e.id))
    return {
        e.id: documents[e.id]
        for e in entries
        if e.id in documents and e.id == first[e.source_transaction_id] and "document" not in e.derivation
    }
