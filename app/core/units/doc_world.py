"""What the overlay needs to simulate settle steps 2 and 3 (documents.md §1-§5, §7), pure.

`DocWorld` is the part of the ledger outside the unit that document matching reads: the registry and the
document sources (waiting), the payees that have a provider, the unlinked documents that can matter to the
unit's transactions (the documents no entry OUTSIDE the unit carries) with what enrichment reads of them, and
the other transactions step 2 would consider (the original entries of the ledger outside the unit that have
a provider payee and no decided document), against which uniqueness is judged both ways. The overlay takes
the rest from its own rows: which of the unit's originals have a provider payee and no decided document, and
which documents they carry.

The functions here are the pure ones of wave A (`core/matching/documents.py`, `core/units/documents.py`)
applied to those facts; nothing is restated.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.core.matching.documents import DocInput, DocTxn, automatic_links
from app.core.resolution.enrich import LinkedDocument
from app.core.units.documents import DocumentFacts, DocumentSource, document_facts


@dataclass(frozen=True, slots=True)
class DocWorld:
    window: int
    providers: Mapping[str, frozenset[str]] = field(default_factory=dict)
    sources: Sequence[DocumentSource] = ()
    payee_providers: Mapping[int, str] = field(default_factory=dict)
    # no entry outside the unit carries them (`carried` is False; the overlay marks what its rows carry)
    documents: Sequence[DocInput] = ()
    details: Mapping[int, LinkedDocument] = field(default_factory=dict)
    others: Sequence[DocTxn] = ()  # gated original entries outside the unit


def _marked(world: DocWorld, carried: Collection[int]) -> list[DocInput]:
    return [replace(d, carried=True) if d.document_id in carried else d for d in world.documents]


def _gated(txns: Iterable[DocTxn]) -> list[DocTxn]:
    return [t for t in txns if t.payee_provider is not None and not t.document_decided]


def facts_of(txns: Sequence[DocTxn], world: DocWorld, carried: Collection[int]) -> dict[int, DocumentFacts]:
    """The document facts of each of `txns` (the unit's original entries), by entry id: awaited, suggested
    and candidate as the unit CTE reads them. `carried` are the documents the unit's rows carry now."""
    if not world.payee_providers:
        return {}
    gated = _gated(txns)
    if not gated:
        return {}
    own = {t.entry_id for t in txns}
    everyone = [*gated, *(o for o in world.others if o.entry_id not in own)]
    documents = _marked(world, carried)
    return {
        t.entry_id: document_facts(
            t,
            others=everyone,
            documents=documents,
            sources=world.sources,
            providers=world.providers,
            window=world.window,
        )
        for t in gated
    }


def links_of(txns: Sequence[DocTxn], world: DocWorld, carried: Collection[int]) -> dict[int, int]:
    """Step 2: {entry id: document id} for the unit's originals that have an automatic link, judged among
    every considered transaction of the ledger (uniqueness both ways)."""
    if not world.payee_providers:
        return {}
    gated = _gated(txns)
    if not gated:
        return {}
    own = {t.entry_id for t in txns}
    everyone = [*gated, *(o for o in world.others if o.entry_id not in own)]
    found = automatic_links(everyone, _marked(world, carried), world.window)
    return {i: d for i, d in found.items() if i in own}
