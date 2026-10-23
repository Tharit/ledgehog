"""Document matching (spec/features/documents.md §1-§4, §9): the pure candidate and link rules.

No database, no clock, no rates: a document is matched to transactions by a line allocation
(`core/matching/lines.py`), in the document's currency, either the entry's own or the instructed one; amounts
match exactly and with their sign (§3). A transaction whose original entry links a document is a CARRIER of
it; a document may have several.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import NamedTuple

from app.core.matching.lines import MAX_PARTIAL_LINES, Allocation, Line, Party, allocate


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
    `document_decided` (the original entry holds a link or the user's "none"), and `is_transfer` (an entry of
    the transaction is typed as a transfer: a document explains a flow, spec §5.8).

    A carrier is a `DocTxn` too: `document_id` is the document its original entry links, `line_numbers` the
    lines of that document its entries reference (spec I35), `confirmed` its unit's state.
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
    document_id: int | None = None
    line_numbers: frozenset[int] = frozenset()
    # the `pass` of the `document` key its original entry carries (None: no key); a link a matcher made keeps
    # the transaction waiting for the rest of the order (documents.md §7)
    document_pass: str | None = None

    @property
    def considered(self) -> bool:
        """§1: not a duplicate, unconfirmed, a payee with a provider, no decided document, not a transfer, and
        an amount that is not zero (a zero-amount booking explains nothing)."""
        return (
            self.amount != 0
            and not self.duplicate
            and not self.is_transfer
            and not self.confirmed
            and self.payee_provider is not None
            and not self.document_decided
        )


@dataclass(frozen=True, slots=True)
class DocInput:
    """An external document: `total` is signed (a refund document is positive), in `currency`; `lines` in
    line order; `carriers` the transactions whose original entry links it."""

    document_id: int
    provider: str
    occurred_on: date
    total: int
    currency: str
    lines: tuple[Line, ...] = ()
    carriers: tuple[DocTxn, ...] = ()


def amount_in(txn: DocTxn, currency: str) -> int | None:
    """§3: the transaction's amount in `currency`: its own, or the instructed one; None when it has none."""
    if txn.currency == currency:
        return txn.amount
    if txn.instructed_currency == currency and txn.instructed_amount is not None:
        return txn.instructed_amount
    return None


def charged(document: DocInput) -> int:
    """The sum of the carriers' amounts in the document's currency (a carrier with none counts nothing)."""
    return sum(a for t in document.carriers if (a := amount_in(t, document.currency)) is not None)


def fully_charged(document: DocInput) -> bool:
    """Carried, and the carriers' amounts reach the total (§3: by magnitude, a shortfall is a smaller sum)."""
    return bool(document.carriers) and abs(charged(document)) >= abs(document.total)


def line_allocation(document: DocInput, txns: Sequence[DocTxn]) -> Allocation | None:
    """§3: the proposed line allocation of `document` over `txns` (its carriers and candidates), or None
    where there is none, or where one of them has no amount in the document's currency."""
    parties: list[Party] = []
    for t in txns:
        amount = amount_in(t, document.currency)
        if amount is None:
            return None
        parties.append(Party(t.entry_id, t.booked_on, amount, t.line_numbers))
    return allocate(document.lines, document.total, parties)


def _same_provider(txn: DocTxn, doc: DocInput) -> bool:
    return txn.payee_provider is not None and doc.provider.lower() == txn.payee_provider.lower()


def _within(txn: DocTxn, doc: DocInput, window: DocWindow) -> bool:
    return -window.back <= (doc.occurred_on - txn.booked_on).days <= window.ahead


def _distance(txn: DocTxn, doc: DocInput) -> int:
    return abs((doc.occurred_on - txn.booked_on).days)


def _divides(txn: DocTxn, doc: DocInput) -> bool:
    """Some line allocation exists over the document's carriers and `txn`, keeping the references or not."""
    return line_allocation(doc, [*doc.carriers, txn]) is not None


def candidates(txn: DocTxn, documents: Iterable[DocInput], window: DocWindow) -> list[DocInput]:
    """§2: documents of the payee's provider (compared without regard to case), within the window, for which
    a line allocation exists over the document's carriers and `txn`.

    Empty for a transaction §1 does not consider. Ordered by distance in days, then id.
    """
    if not txn.considered:
        return []
    found = [d for d in documents if _same_provider(txn, d) and _within(txn, d, window) and _divides(txn, d)]
    return sorted(found, key=lambda d: (_distance(txn, d), d.document_id))


# a document of up to this many lines has its subset sums precomputed (at most 2^10 per document); one of
# more is scanned within the window, which is rare
_SUMMED_LINES = 10


def _subset_sums(amounts: Iterable[int]) -> set[int]:
    sums = {0}
    for a in amounts:
        sums |= {s + a for s in sums}
    return sums


@dataclass(slots=True)
class _Index:
    """The documents of one provider, found by what a transaction could take of them: `by_amount` holds
    (currency, amount) -> the documents a transaction of that amount may match, either whole (the total) or in
    part (a subset sum of the lines, for a document whose lines sum to its total); `scanned` are the documents
    of too many lines for that, ordered by date. A hit is only a possible match: `_divides` decides."""

    by_amount: dict[tuple[str, int], list[DocInput]]
    scanned_dates: list[date]
    scanned: list[DocInput]


def _indexed(documents: Iterable[DocInput]) -> dict[str, _Index]:
    """The documents by lower-cased provider, so a transaction looks up its amount and not every document."""
    index: dict[str, _Index] = {}
    big: dict[str, list[DocInput]] = defaultdict(list)
    for d in documents:
        found = index.setdefault(d.provider.lower(), _Index({}, [], []))
        keys = {d.total}
        if 2 <= len(d.lines) <= MAX_PARTIAL_LINES and sum(ln.amount for ln in d.lines) == d.total:
            if len(d.lines) <= _SUMMED_LINES:
                keys |= _subset_sums(ln.amount for ln in d.lines)
            else:
                big[d.provider.lower()].append(d)
        for amount in keys - {0}:  # a transaction of amount zero is never considered (§1)
            found.by_amount.setdefault((d.currency, amount), []).append(d)
    for provider, docs in big.items():
        docs.sort(key=lambda d: (d.occurred_on, d.document_id))
        index[provider].scanned = docs
        index[provider].scanned_dates = [d.occurred_on for d in docs]
    return index


def _candidates_indexed(txn: DocTxn, index: dict[str, _Index], window: DocWindow) -> list[DocInput]:
    """`candidates` over an index: the same rule, without scanning every document for every transaction."""
    if not txn.considered or txn.payee_provider is None:
        return []
    found = index.get(txn.payee_provider.lower())
    if found is None:
        return []
    possible: dict[int, DocInput] = {}
    keys = [(txn.currency, txn.amount)]
    if txn.instructed_currency is not None and txn.instructed_amount is not None:
        keys.append((txn.instructed_currency, txn.instructed_amount))
    for key in keys:
        for d in found.by_amount.get(key, ()):
            possible[d.document_id] = d
    if found.scanned:
        lo = bisect_left(found.scanned_dates, txn.booked_on - timedelta(days=window.back))
        hi = bisect_right(found.scanned_dates, txn.booked_on + timedelta(days=window.ahead))
        for d in found.scanned[lo:hi]:
            possible[d.document_id] = d
    hits = [d for d in possible.values() if _within(txn, d, window) and _divides(txn, d)]
    return sorted(hits, key=lambda d: (_distance(txn, d), d.document_id))


class Matching(NamedTuple):
    """What settling and the unit read of transactions against the documents: the candidates of each (by entry
    id, only those §1 considers and that have one), and the automatic links."""

    candidates: dict[int, list[DocInput]]
    links: dict[int, int]

    @property
    def suggested(self) -> dict[int, list[DocInput]]:
        """§4: the candidates of each transaction that has no automatic link (never stored)."""
        return {i: found for i, found in self.candidates.items() if i not in self.links}


def match(transactions: Iterable[DocTxn], documents: Sequence[DocInput], window: DocWindow) -> Matching:
    """§4: the candidates of each transaction, and {entry_id: document_id} for the automatic links.

    For each document d that is a candidate of considered transactions, S being those: all of S are linked to
    d at once when d is the only candidate of every one of them, a line allocation KEEPING the committed
    references exists over d's carriers and S together, and no carrier of d is confirmed. For a single
    transaction taking every line this is the one-to-one rule. Found through an index of the documents, so a
    settle over thousands of each does not compare every pair."""
    index = _indexed(documents)
    txns = {t.entry_id: t for t in transactions}
    found = {i: c for i, t in txns.items() if (c := _candidates_indexed(t, index, window))}
    by_doc: dict[int, list[int]] = defaultdict(list)
    docs: dict[int, DocInput] = {}
    for entry_id, cands in sorted(found.items()):
        for d in cands:
            by_doc[d.document_id].append(entry_id)
            docs[d.document_id] = d
    links: dict[int, int] = {}
    for doc_id, entry_ids in sorted(by_doc.items()):
        d = docs[doc_id]
        if any(len(found[i]) != 1 for i in entry_ids) or any(c.confirmed for c in d.carriers):
            continue
        allocation = line_allocation(d, [*d.carriers, *(txns[i] for i in entry_ids)])
        if allocation is not None and allocation.keeps:
            links.update(dict.fromkeys(entry_ids, doc_id))
    return Matching(found, links)


def automatic_links(
    transactions: Iterable[DocTxn], documents: Sequence[DocInput], window: DocWindow
) -> dict[int, int]:
    """§4: {entry_id: document_id}, see `match`."""
    return match(transactions, documents, window).links


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
    return match(everyone, documents, window).suggested.get(txn.entry_id, [])


def reverse_matches(document: DocInput, transactions: Iterable[DocTxn], window: DocWindow) -> list[DocTxn]:
    """§9: for a document not fully charged, the non-duplicate transactions on any account with no transfer
    entry (`is_transfer`), other than its carriers, for which a line allocation exists over the carriers and
    the transaction (§3) and whose booked_on is within the window of occurred_on (the mirror of `_within`);
    confirmed ones and any payee included. Ordered by distance in days, then entry id."""
    if fully_charged(document):
        return []
    carriers = {c.entry_id for c in document.carriers}
    found = [
        t
        for t in transactions
        if t.amount != 0
        and not t.duplicate
        and not t.is_transfer
        and t.entry_id not in carriers
        and _within(t, document, window)
        and _divides(t, document)
    ]
    return sorted(found, key=lambda t: (_distance(t, document), t.entry_id))
