"""Document matching (spec/features/documents.md §1-§4, §9): the pure candidate and link rules.

No database, no clock, no rates: amounts match exactly and with their sign (§3), in the document's
currency, either the entry's own or the instructed one.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple


class DocWindow(NamedTuple):
    """The document window (spec §5.8): a document matches a transaction when its date is within
    [booked_on - back, booked_on + ahead]; the transaction waits for a document until booked_on + ahead."""

    back: int
    ahead: int


@dataclass(frozen=True, slots=True)
class DocTxn:
    """The original entry of a source transaction, as document matching reads it.

    Amounts are signed minor units; `instructed_amount` is in `instructed_currency` (spec §3.8).
    `payee_provider` is the `document_provider` of the entry's payee, or None. The eligibility facts
    of §1 are those the caller judged: `duplicate`, `confirmed` (the unit, spec I20) and
    `document_decided` (the original entry holds a link or the user's "none"), and `is_transfer` (the original
    entry is typed as a transfer: a document explains a flow, spec §5.8).
    """

    entry_id: int
    account_id: int
    booked_on: date
    amount: int
    currency: str
    instructed_amount: int | None = None
    instructed_currency: str | None = None
    payee_provider: str | None = None
    duplicate: bool = False
    confirmed: bool = False
    document_decided: bool = False
    is_transfer: bool = False

    @property
    def considered(self) -> bool:
        """§1: not a duplicate, unconfirmed, a payee with a provider, no decided document, not a transfer."""
        return (
            not self.duplicate
            and not self.is_transfer
            and not self.confirmed
            and self.payee_provider is not None
            and not self.document_decided
        )


@dataclass(frozen=True, slots=True)
class DocInput:
    """An external document: `total` is signed (a refund document is positive), in `currency`."""

    document_id: int
    provider: str
    occurred_on: date
    total: int
    currency: str
    carried: bool = False


def amount_matches(txn: DocTxn, doc: DocInput) -> bool:
    """§3: the total equals the entry amount in its currency, or the instructed amount in its."""
    if doc.currency == txn.currency and doc.total == txn.amount:
        return True
    return (
        txn.instructed_currency is not None
        and txn.instructed_amount is not None
        and doc.currency == txn.instructed_currency
        and doc.total == txn.instructed_amount
    )


def _same_provider(txn: DocTxn, doc: DocInput) -> bool:
    return txn.payee_provider is not None and doc.provider.lower() == txn.payee_provider.lower()


def _within(txn: DocTxn, doc: DocInput, window: DocWindow) -> bool:
    return -window.back <= (doc.occurred_on - txn.booked_on).days <= window.ahead


def _distance(txn: DocTxn, doc: DocInput) -> int:
    return abs((doc.occurred_on - txn.booked_on).days)


def candidates(txn: DocTxn, documents: Iterable[DocInput], window: DocWindow) -> list[DocInput]:
    """§2: documents of the payee's provider (compared without regard to case), carried by none,
    amount-matching, within the window.

    Empty for a transaction §1 does not consider. Ordered by distance in days, then id.
    """
    if not txn.considered:
        return []
    found = [
        d
        for d in documents
        if not d.carried and _same_provider(txn, d) and amount_matches(txn, d) and _within(txn, d, window)
    ]
    return sorted(found, key=lambda d: (_distance(txn, d), d.document_id))


def _indexed(documents: Iterable[DocInput]) -> dict[tuple[str, str, int], list[DocInput]]:
    """Uncarried documents by (lower-cased provider, currency, total): where `amount_matches` can hold."""
    index: dict[tuple[str, str, int], list[DocInput]] = defaultdict(list)
    for d in documents:
        if not d.carried:
            index[(d.provider.lower(), d.currency, d.total)].append(d)
    return index


def _candidates_indexed(
    txn: DocTxn, index: dict[tuple[str, str, int], list[DocInput]], window: DocWindow
) -> list[DocInput]:
    """`candidates` over an index: the same rule, without scanning every document for every transaction."""
    if not txn.considered or txn.payee_provider is None:
        return []
    provider = txn.payee_provider.lower()
    keys = [(provider, txn.currency, txn.amount)]
    if txn.instructed_currency is not None and txn.instructed_amount is not None:
        keys.append((provider, txn.instructed_currency, txn.instructed_amount))
    seen: dict[int, DocInput] = {}
    for key in keys:
        for d in index.get(key, ()):
            if amount_matches(txn, d) and _within(txn, d, window):
                seen[d.document_id] = d
    return sorted(seen.values(), key=lambda d: (_distance(txn, d), d.document_id))


def automatic_links(
    transactions: Iterable[DocTxn], documents: Sequence[DocInput], window: DocWindow
) -> dict[int, int]:
    """§4: {entry_id: document_id} where a transaction has exactly one candidate and that document is
    a candidate of no other transaction (uniqueness both ways).

    Same answer as `candidates` per transaction, found through an index of the documents, so a settle over
    thousands of each does not compare every pair."""
    index = _indexed(documents)
    per_txn = {t.entry_id: _candidates_indexed(t, index, window) for t in transactions}
    claimed: dict[int, int] = defaultdict(int)
    for found in per_txn.values():
        for d in found:
            claimed[d.document_id] += 1
    return {
        entry_id: found[0].document_id
        for entry_id, found in sorted(per_txn.items())
        if len(found) == 1 and claimed[found[0].document_id] == 1
    }


def suggestions(
    txn: DocTxn,
    documents: Sequence[DocInput],
    window: DocWindow,
    *,
    others: Iterable[DocTxn] = (),
) -> list[DocInput]:
    """§4: the candidates, when `txn` has no automatic link among `others` (the other considered
    transactions); never stored."""
    everyone = [txn, *(o for o in others if o.entry_id != txn.entry_id)]
    if txn.entry_id in automatic_links(everyone, documents, window):
        return []
    return candidates(txn, documents, window)


def reverse_matches(document: DocInput, transactions: Iterable[DocTxn], window: DocWindow) -> list[DocTxn]:
    """§9: for a document carried by no entry, the non-duplicate transactions on any account whose
    amount matches by §3 and whose booked_on is within the window of occurred_on (as `_within`);
    confirmed ones and any payee included; a transaction typed as a transfer is not offered. Ordered by
    distance in days, then entry id."""
    if document.carried:
        return []
    found = [
        t
        for t in transactions
        if not t.duplicate
        and not t.is_transfer
        and amount_matches(t, document)
        and _within(t, document, window)
    ]
    return sorted(found, key=lambda t: (_distance(t, document), t.entry_id))
