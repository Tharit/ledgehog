"""What the overlay needs to simulate settle steps 2 and 3 (documents.md §1-§5, §7), pure.

`DocWorld` is the part of the ledger outside the unit that document matching reads: the registry and the
document sources (waiting), the payees that have a provider, the unlinked documents that can matter to the
unit's transactions (the documents no entry OUTSIDE the unit carries) with what the entries' input reads
of them (merchant, lines), and the other transactions step 2 would consider (the original entries of the
ledger outside the unit that have a provider payee and no decided document), against which uniqueness is
judged both ways. The overlay takes the rest from its own rows: which of the unit's originals have a
provider payee and no decided document, and which documents they carry.

The functions here are the pure ones of wave A (`core/matching/documents.py`, `core/units/documents.py`)
applied to those facts; nothing is restated.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

from app.core.matching.documents import DocInput, DocTxn, DocWindow, charged, match
from app.core.resolution.enrich import LinkedDocument
from app.core.units.documents import (
    MATCHER_PASSES,
    DocumentFacts,
    DocumentSource,
    DocumentWait,
    OrderWait,
    document_facts_of,
    rest_awaited,
    waiting_for,
)


@dataclass(frozen=True, slots=True)
class DocumentInfo:
    """A stored document as the draft and the preview read it: what a suggestion shows, what a pick is
    checked against (`version`, `provider`) and what the split along its lines uses."""

    id: int
    version: int
    provider: str
    external_id: str
    occurred_on: date
    total: int
    currency: str
    merchant_name: str | None
    title: str | None
    lines: tuple[tuple[int, int, str], ...] = ()

    @property
    def line_count(self) -> int:
        return len(self.lines)


@dataclass(frozen=True, slots=True)
class DocWorld:
    window: DocWindow
    sources: Sequence[DocumentSource] = ()
    # the `synced_through` of each synced account, None for one never fetched: what the wait for the rest of
    # an order reads (documents.md §7)
    synced: Sequence[date | None] = ()
    payee_providers: Mapping[int, str] = field(default_factory=dict)
    # with their lines and the carriers outside the unit (`DocInput.carriers`); the overlay adds the carriers
    # its own rows are (`_with_carriers`)
    documents: Sequence[DocInput] = ()
    details: Mapping[int, LinkedDocument] = field(default_factory=dict)
    others: Sequence[DocTxn] = ()  # gated original entries outside the unit
    # every document named by the draft (picks, echoed lines) and every one `documents` holds, by id; a
    # picked document may be carried (its carriers are in the unit: the drafted closure holds them)
    infos: Mapping[int, DocumentInfo] = field(default_factory=dict)


def _with_carriers(world: DocWorld, txns: Iterable[DocTxn]) -> list[DocInput]:
    """The documents with the unit's own carriers added: the transactions of `txns` that link a document."""
    inside: dict[int, list[DocTxn]] = defaultdict(list)
    for t in txns:
        if t.document_id is not None:
            inside[t.document_id].append(t)
    return [
        replace(d, carriers=(*d.carriers, *inside[d.document_id])) if d.document_id in inside else d
        for d in world.documents
    ]


def _gated(txns: Iterable[DocTxn]) -> list[DocTxn]:
    return [t for t in txns if t.payee_provider is not None and not t.document_decided]


def _outside(txns: Sequence[DocTxn], world: DocWorld) -> list[DocTxn]:
    own = {t.entry_id for t in txns}
    return [o for o in world.others if o.entry_id not in own]


def facts_of(txns: Sequence[DocTxn], world: DocWorld) -> dict[int, DocumentFacts]:
    """The document facts of each of `txns` (the unit's original entries, carriers among them), by entry id:
    awaited, suggested and candidate as the unit CTE reads them, and `rest` for the rest of an order."""
    found = (
        document_facts_of(
            txns,
            others=_outside(txns, world),
            documents=_with_carriers(world, txns),
            sources=world.sources,
            window=world.window,
        )
        if world.payee_providers
        else {}
    )
    for entry_id in order_waits_of(txns, world):
        found[entry_id] = replace(found.get(entry_id, DocumentFacts()), rest=True)
    return found


def links_of(txns: Sequence[DocTxn], world: DocWorld) -> dict[int, int]:
    """Step 2: {entry id: document id} for the unit's originals that have an automatic link, judged among
    every considered transaction of the ledger (all of a document's candidates are linked together)."""
    if not world.payee_providers:
        return {}
    gated = _gated(txns)
    if not gated:
        return {}
    own = {t.entry_id for t in txns}
    found = match([*gated, *_outside(txns, world)], _with_carriers(world, txns), world.window)
    return {i: d for i, d in found.links.items() if i in own}


def suggestions_of(txns: Sequence[DocTxn], world: DocWorld) -> dict[int, list[DocInput]]:
    """The documents offered for each of `txns` (the unit's original entries), by entry id: the candidates of
    a transaction that has no automatic link (never stored), nearest first. Only for the gated ones."""
    if not world.payee_providers:
        return {}
    gated = _gated(txns)
    if not gated:
        return {}
    own = {t.entry_id for t in gated}
    found = match([*gated, *_outside(txns, world)], _with_carriers(world, txns), world.window)
    return {i: c for i, c in found.suggested.items() if i in own}


def waits_of(txns: Sequence[DocTxn], world: DocWorld) -> dict[int, DocumentWait]:
    """What each gated transaction of `txns` waits for (documents.md §7), by entry id."""
    out: dict[int, DocumentWait] = {}
    for t in _gated(txns):
        assert t.payee_provider is not None
        if wait := waiting_for(t.payee_provider, t.booked_on, world.window, world.sources):
            out[t.entry_id] = wait
    return out


def order_waits_of(txns: Sequence[DocTxn], world: DocWorld) -> dict[int, OrderWait]:
    """What each of `txns` that carries a matcher's link waits for (documents.md §7): the rest of the
    document's order, by entry id. The carriers are the document's, the unit's own among them."""
    carried = [t for t in txns if t.document_id is not None and t.document_pass in MATCHER_PASSES]
    if not carried:
        return {}
    documents = {d.document_id: d for d in _with_carriers(world, txns)}
    out: dict[int, OrderWait] = {}
    for t in carried:
        assert t.document_id is not None
        document = documents.get(t.document_id)
        info = world.infos.get(t.document_id)
        if document is None or info is None or not rest_awaited(document, world.synced, world.window):
            continue
        out[t.entry_id] = OrderWait(
            order=info.external_id,
            provider=info.provider,
            charged=charged(document),
            total=document.total,
            currency=document.currency,
        )
    return out
