"""Whether a unit has a document open (spec §5.8, §6; documents.md §1, §3, §4, §7), in pure Python.

The twin of the `doc_awaited`, `doc_suggested` and `doc_candidate` columns of the unit CTE
(`core/resolution/confirmed.py`),
pinned to that SQL by `tests/core/units/test_state_documents.py`. The candidate rule is the matcher's
(`core/matching/documents.py`: carriers and lines), not restated here; what is added is waiting (§7) and the
gate: the test applies only to the original entry of a transaction whose payee has a provider, that has no
`document` key and no entry typed as a transfer (a document explains a flow).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.matching.documents import DocInput, DocTxn, DocWindow, charged, match


@dataclass(frozen=True, slots=True)
class DocumentFacts:
    """What a transaction's original entry is open for: `awaited` (its document may still arrive),
    `suggested` (documents are offered and no automatic link is possible) and `candidate` (some document
    is a candidate, so settling may link it in step 2: the unit is not confirmed before that, `doc_candidate`
    of the unit CTE; it is no flag, and a suggestion is a candidate too)."""

    awaited: bool = False
    suggested: bool = False
    candidate: bool = False
    # the transaction carries a matcher's link to a document whose order is not all charged yet and waits
    # for the rest of it (documents.md §7): a flag and a queue line, never a reason to hold the unit
    rest: bool = False

    @property
    def open(self) -> bool:
        return self.awaited or self.suggested or self.candidate


@dataclass(frozen=True, slots=True)
class DocumentSource:
    """An importer instance as waiting reads it: `delivers` the lower-cased providers it delivers
    (`core/importers/providers.py`), `start_date` None = no lower bound, `covered_through` None = never
    run."""

    delivers: frozenset[str] = frozenset()
    disabled: bool = False
    start_date: date | None = None
    covered_through: date | None = None


def awaited(
    provider: str,
    booked_on: date,
    window: DocWindow,
    sources: Iterable[DocumentSource],
) -> bool:
    """§7: some source that is not disabled, delivers `provider`, has a start date not after `booked_on`
    and has not covered `booked_on` plus the window's ahead. With no such source nothing waits."""
    horizon = booked_on + timedelta(days=window.ahead)
    key = provider.lower()
    return any(
        not s.disabled
        and key in s.delivers
        and (s.start_date is None or s.start_date <= booked_on)
        and (s.covered_through is None or s.covered_through < horizon)
        for s in sources
    )


@dataclass(frozen=True, slots=True)
class DocumentWait:
    """What a transaction waits for (documents.md §7): documents of `provider`, from the sources that still
    hold it. `covered_through` is the earliest coverage among them, None when one has never run."""

    provider: str
    covered_through: date | None


def waiting_for(
    provider: str,
    booked_on: date,
    window: DocWindow,
    sources: Iterable[DocumentSource],
) -> DocumentWait | None:
    """The sources `awaited` counts, as a line the queue shows ("from <provider>, covered through <date>");
    None where nothing is awaited."""
    horizon = booked_on + timedelta(days=window.ahead)
    key = provider.lower()
    holding = [
        s
        for s in sources
        if not s.disabled
        and key in s.delivers
        and (s.start_date is None or s.start_date <= booked_on)
        and (s.covered_through is None or s.covered_through < horizon)
    ]
    if not holding:
        return None
    never = any(s.covered_through is None for s in holding)
    through = None if never else min(s.covered_through for s in holding if s.covered_through is not None)
    return DocumentWait(provider, through)


# the keys of a link settling made: the wait for the rest of an order follows them (a link the user made or
# accepted ends it)
MATCHER_PASSES = frozenset({"matcher_decision", "matcher_proposal"})


@dataclass(frozen=True, slots=True)
class OrderWait:
    """What a transaction waits for when its document's order is not all charged (documents.md §7): the
    order's `external_id` of `provider`, what its carriers `charged` of its `total` (both signed like the
    document's total, in `currency`: compared by magnitude)."""

    order: str
    provider: str
    charged: int
    total: int
    currency: str

    @property
    def remainder(self) -> int:
        """Not yet charged, in magnitude: what the queue's line says."""
        return abs(self.total) - abs(self.charged)


def rest_awaited(document: DocInput, synced: Iterable[date | None], window: DocWindow) -> bool:
    """§7: the amounts of the document's carriers (the one asking is among them) fall short of its total in
    magnitude, and some synced account has not reached the document's date plus `back`; `synced` holds the
    `synced_through` of each synced account, None for one never fetched (which holds it too). With no synced
    account nothing holds it."""
    if abs(charged(document)) >= abs(document.total):
        return False
    horizon = document.occurred_on + timedelta(days=window.back)
    return any(s is None or s < horizon for s in synced)


def document_facts_of(
    txns: Sequence[DocTxn],
    *,
    others: Iterable[DocTxn],
    documents: Sequence[DocInput],
    sources: Iterable[DocumentSource],
    window: DocWindow,
) -> dict[int, DocumentFacts]:
    """The facts of the original entries `txns` that pass the gate, by entry id. `others` are the other
    original entries with a provider and no decided document (the transactions a document could be shared
    with: the matcher judges them together, once); `document_decided`, a missing provider and a transfer entry
    close the gate. A document's carriers are those it holds (`DocInput.carriers`)."""
    gated = [t for t in txns if t.payee_provider is not None and not t.document_decided and not t.is_transfer]
    own = {t.entry_id for t in gated}
    found = match([*gated, *(o for o in others if o.entry_id not in own)], documents, window)
    sources = list(sources)
    out: dict[int, DocumentFacts] = {}
    for t in gated:
        assert t.payee_provider is not None
        has = bool(found.candidates.get(t.entry_id))
        out[t.entry_id] = DocumentFacts(
            awaited=awaited(t.payee_provider, t.booked_on, window, sources),
            suggested=has and t.entry_id not in found.links,
            candidate=has,
        )
    return out


def document_facts(
    txn: DocTxn,
    *,
    others: Iterable[DocTxn],
    documents: Sequence[DocInput],
    sources: Iterable[DocumentSource],
    window: DocWindow,
) -> DocumentFacts:
    """The facts of the original entry `txn`; `document_facts_of` for one."""
    found = document_facts_of([txn], others=others, documents=documents, sources=sources, window=window)
    return found.get(txn.entry_id, DocumentFacts())
