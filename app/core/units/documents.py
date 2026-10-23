"""Whether a unit has a document open (spec §5.8, §6; documents.md §1, §3, §4, §7), in pure Python.

The twin of the `doc_awaited`, `doc_suggested` and `doc_candidate` columns of the unit CTE
(`core/resolution/confirmed.py`),
pinned to that SQL by `tests/core/units/test_state_documents.py`. The candidate rule is the matcher's
(`core/matching/documents.py`), not restated here; what is added is waiting (§7) and the gate: the test
applies only to the original entry of a transaction whose payee has a provider, that has no `document` key
and is not typed as a transfer (a document explains a flow).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.matching.documents import DocInput, DocTxn, DocWindow, candidates, suggestions


@dataclass(frozen=True, slots=True)
class DocumentFacts:
    """What a transaction's original entry is open for: `awaited` (its document may still arrive),
    `suggested` (documents are offered and no automatic link is possible) and `candidate` (some document
    is a candidate, so settling may link it in step 2: the unit is not confirmed before that, `doc_candidate`
    of the unit CTE; it is no flag, and a suggestion is a candidate too)."""

    awaited: bool = False
    suggested: bool = False
    candidate: bool = False

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


def document_facts(
    txn: DocTxn,
    *,
    others: Iterable[DocTxn],
    documents: Sequence[DocInput],
    sources: Iterable[DocumentSource],
    window: DocWindow,
) -> DocumentFacts:
    """The facts of the original entry `txn`. `others` are the other original entries with a provider and
    no decided document (the transactions a document could be shared with); `txn.document_decided` and a
    missing provider close the gate."""
    if txn.payee_provider is None or txn.document_decided or txn.is_transfer:
        return DocumentFacts()
    return DocumentFacts(
        awaited=awaited(txn.payee_provider, txn.booked_on, window, sources),
        suggested=bool(suggestions(txn, documents, window, others=others)),
        candidate=bool(candidates(txn, documents, window)),
    )
