"""`match` answers as the plain `candidates` rule does (the index only avoids the scan)."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

from app.core.matching.documents import DocInput, DocTxn, DocWindow, candidates, line_allocation, match
from app.core.matching.lines import Line

D = date(2026, 3, 10)


def naive(txns: list[DocTxn], docs: list[DocInput], window: DocWindow) -> dict[int, int]:
    """§4 read plainly: the candidates of each transaction by scanning every document, then per document
    the set of transactions it is a candidate of."""
    by_entry = {t.entry_id: t for t in txns}
    per = {t.entry_id: candidates(t, docs, window) for t in txns}
    asked: dict[int, list[int]] = defaultdict(list)
    for entry_id, found in sorted(per.items()):
        for d in found:
            asked[d.document_id].append(entry_id)
    by_id = {d.document_id: d for d in docs}
    links: dict[int, int] = {}
    for doc_id, entry_ids in sorted(asked.items()):
        d = by_id[doc_id]
        if any(len(per[e]) != 1 for e in entry_ids) or any(c.confirmed for c in d.carriers):
            continue
        allocation = line_allocation(d, [*d.carriers, *(by_entry[e] for e in entry_ids)])
        if allocation is not None and allocation.keeps:
            links.update(dict.fromkeys(entry_ids, doc_id))
    return links


def test_the_indexed_links_equal_the_scanning_rule_over_random_worlds() -> None:
    rng = random.Random(7)
    for _ in range(80):
        amounts = [-100, -200, -300, 400, -50, -150]
        txns = [
            DocTxn(
                entry_id=i,
                account_id=1,
                booked_on=D + timedelta(days=rng.randrange(0, 12)),
                amount=rng.choice(amounts),
                currency="EUR",
                instructed_amount=rng.choice([None, -150, -250]),
                instructed_currency=rng.choice([None, "USD"]),
                payee_provider=rng.choice(["paypal", "paypal", "amazon", None]),
                confirmed=rng.random() < 0.1,
                document_decided=rng.random() < 0.1,
            )
            for i in range(1, rng.randrange(2, 14))
        ]
        docs = []
        for j in range(rng.randrange(0, 14)):
            lines = tuple(Line(n, rng.choice([-50, -100, -150, -200])) for n in range(1, rng.randrange(1, 4)))
            total = sum(ln.amount for ln in lines) if rng.random() < 0.7 else rng.choice([*amounts, -250])
            carriers = tuple(
                DocTxn(
                    entry_id=500 + 10 * j + k,
                    account_id=1,
                    booked_on=D + timedelta(days=rng.randrange(0, 12)),
                    amount=rng.choice([-50, -100, -150]),
                    currency="EUR",
                    confirmed=rng.random() < 0.3,
                    document_decided=True,
                    document_id=100 + j,
                    line_numbers=frozenset(
                        rng.sample([ln.number for ln in lines], rng.randrange(0, 2) if lines else 0)
                    ),
                )
                for k in range(rng.randrange(0, 3))
            )
            docs.append(
                DocInput(
                    document_id=100 + j,
                    provider=rng.choice(["paypal", "PayPal", "amazon"]),
                    occurred_on=D + timedelta(days=rng.randrange(-3, 15)),
                    total=total,
                    currency=rng.choice(["EUR", "EUR", "USD"]),
                    lines=lines,
                    carriers=carriers,
                )
            )
        window = DocWindow(rng.choice([0, 3, 7]), rng.choice([0, 3, 7]))
        found = match(txns, docs, window)
        assert found.links == naive(txns, docs, window)
        for t in txns:
            plain = candidates(t, docs, window)
            assert [d.document_id for d in found.candidates.get(t.entry_id, [])] == [
                d.document_id for d in plain
            ]


def test_a_document_of_many_lines_is_found_by_its_scan() -> None:
    """More lines than the index sums up (and up to the limit): found within the window all the same."""
    lines = tuple(Line(n, -10) for n in range(1, 13))
    far = DocInput(7, "amazon", D + timedelta(days=40), -120, "EUR", lines)
    near = DocInput(8, "amazon", D + timedelta(days=1), -120, "EUR", lines)
    txn = DocTxn(1, 1, D, -30, "EUR", payee_provider="amazon")
    window = DocWindow(7, 7)
    found = match([txn], [far, near], window)
    assert (
        [d.document_id for d in found.candidates[1]]
        == [8]
        == [d.document_id for d in candidates(txn, [far, near], window)]
    )
    assert found.links == {1: 8}
    too_many = DocInput(9, "amazon", D, -210, "EUR", tuple(Line(n, -10) for n in range(1, 22)))
    assert match([txn], [too_many], window).candidates == {}
