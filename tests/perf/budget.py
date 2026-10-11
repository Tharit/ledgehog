"""The settle time budget (architecture §5.2). The ONLY place the number lives.

Derivation: `tests/perf/test_settle_budget.py` times `settle()` on the backfill fixture
(`tests/fixtures/backfill.py`: 8000 unconfirmed entries over 4 accounts and a year) right
after a single commit (5-row `ingest_delivery`, `mark_duplicate`) and for the baseline
pass over all units. Measured on the dev machine (Postgres 18, localhost), steady over
three runs: post-commit settle max 17 ms, baseline pass over all 8000 units max 113 ms.
Budget = 2 x the largest measured value, rounded up to a clean number, never below 1.0 s.

Caveat: measured with the step-3 settle, which runs the review flags only. That is a
LOWER BOUND. Re-measure and re-derive when resolution (step 6), transfer pairing (step 8)
and document matching (step 9) register their steps; if the budget is then missed, narrow
the pass to a dirty set (architecture §5.2) before raising the number.
"""

BUDGET_SECONDS = 1.0

INGEST_BUDGET_SECONDS = 1.0
"""The write transaction of a ~5,000-row delivery (`tests/perf/test_ingest_budget.py`).

Derivation: the transaction holds the settle lock (shared) and the account lock, timed with
settle patched out. Measured on the dev machine (Postgres 18, localhost), median of 3: 2.28 s
with one INSERT per source row, entry and removal; 0.45 s batched (chunks of 1,000 rows, one
set-based entry INSERT per chunk), max 0.56 s. Budget = 2 x the batched median, rounded up to
a clean number, never below 1.0 s.
"""

LIST_BUDGET_SECONDS = 0.5
"""A page of 100 ledger entries plus the matching count (`tests/perf/test_list_budget.py`).

Derivation: on the backfill fixture (8000 entries over 6 accounts, a tag on one in eight) the
request is timed unfiltered, with a date range, one account, a tag, a text search, an amount
range and all of them combined, plus a deep page (offset 7,000). Measured on the dev machine
(Postgres 18, localhost), max of 7 runs, over two sessions: 3-6 ms for no filter, date range,
one account, tag and amount range; 8-9 ms all combined; text search (an unindexed ILIKE scan,
the slowest filter) 19-29 ms; a deep page 10-33 ms. Budget = 2 x the largest measured value
(66 ms), rounded up to a clean number, never below 0.5 s. No index is needed.
"""
