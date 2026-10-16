"""`automatic_links` answers as the plain `candidates` rule does (the index only avoids the scan)."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta

from app.core.matching.documents import DocInput, DocTxn, automatic_links, candidates

D = date(2026, 3, 10)


def naive(txns: list[DocTxn], docs: list[DocInput], window: int) -> dict[int, int]:
    per = {t.entry_id: candidates(t, docs, window) for t in txns}
    claimed: dict[int, int] = defaultdict(int)
    for found in per.values():
        for d in found:
            claimed[d.document_id] += 1
    return {
        e: f[0].document_id for e, f in sorted(per.items()) if len(f) == 1 and claimed[f[0].document_id] == 1
    }


def test_the_indexed_links_equal_the_scanning_rule_over_random_worlds() -> None:
    rng = random.Random(7)
    for _ in range(60):
        amounts = [-100, -200, -300, 400]
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
        docs = [
            DocInput(
                document_id=100 + j,
                provider=rng.choice(["paypal", "amazon"]),
                occurred_on=D + timedelta(days=rng.randrange(-3, 15)),
                total=rng.choice([*amounts, -150, -250]),
                currency=rng.choice(["EUR", "USD"]),
                carried=rng.random() < 0.1,
            )
            for j in range(rng.randrange(0, 14))
        ]
        assert automatic_links(txns, docs, 7) == naive(txns, docs, 7)
