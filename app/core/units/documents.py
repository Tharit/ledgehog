"""Whether a unit has a document open (spec §5.8, §6; documents.md §1, §3, §4, §7), in pure Python.

The twin of the `doc_awaited`, `doc_suggested` and `doc_candidate` columns of the unit CTE
(`core/resolution/confirmed.py`),
pinned to that SQL by `tests/core/units/test_state_documents.py`. The candidate rule is the matcher's
(`core/matching/documents.py`), not restated here; what is added is waiting (§7) and the gate: the test
applies only to the original entry of a transaction whose payee has a provider, that has no `document` key.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.matching.documents import DocInput, DocTxn, candidates, suggestions


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
    """An importer instance as waiting reads it: `start_date` None = no lower bound, `covered_through`
    None = never run."""

    importer: str
    disabled: bool = False
    start_date: date | None = None
    covered_through: date | None = None


def awaited(
    provider: str,
    booked_on: date,
    window: int,
    sources: Iterable[DocumentSource],
    providers: Mapping[str, frozenset[str]],
) -> bool:
    """§7: some source that is not disabled, provides `provider`, has a start date not after `booked_on`
    and has not covered `booked_on` plus the window. With no such source nothing waits."""
    horizon = booked_on + timedelta(days=window)
    return any(
        not s.disabled
        and provider in providers.get(s.importer, frozenset())
        and (s.start_date is None or s.start_date <= booked_on)
        and (s.covered_through is None or s.covered_through < horizon)
        for s in sources
    )


def document_facts(
    txn: DocTxn,
    *,
    others: Iterable[DocTxn],
    documents: Sequence[DocInput],
    sources: Iterable[DocumentSource],
    providers: Mapping[str, frozenset[str]],
    window: int,
) -> DocumentFacts:
    """The facts of the original entry `txn`. `others` are the other original entries with a provider and
    no decided document (the transactions a document could be shared with); `txn.document_decided` and a
    missing provider close the gate."""
    if txn.payee_provider is None or txn.document_decided:
        return DocumentFacts()
    return DocumentFacts(
        awaited=awaited(txn.payee_provider, txn.booked_on, window, sources, providers),
        suggested=bool(suggestions(txn, documents, window, others=others)),
        candidate=bool(candidates(txn, documents, window)),
    )
