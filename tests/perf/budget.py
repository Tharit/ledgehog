"""The settle time budget (architecture §5.2). The ONLY place the number lives.

Derivation: `tests/perf/test_settle_budget.py` times `settle()` on the backfill fixture
(`tests/fixtures/backfill.py`: 8000 unconfirmed entries over 4 accounts and a year) right
after a single commit (5-row `ingest_delivery`, `mark_duplicate`) and for the baseline
pass over all units. Measured on the dev machine (Postgres 18, localhost), steady over
three runs: post-commit settle max 17 ms, baseline pass over all 8000 units max 113 ms.
Budget = 2 x the largest measured value, rounded up to a clean number, never below 1.0 s.

Since step 6 the settle includes resolution (pass 0, rules, history over a snapshot loaded once).
Every settle starts with a full pass over all unconfirmed entries, so even a 5-row commit now costs a
pass. Measured on the dev machine (Postgres 18, localhost, a busy laptop), over two sessions:
baseline pass over 8000 unclassified entries (no voters) 330-410 ms; post-commit settle 245-340 ms;
`confirmed_share=0.7` variant (5,600 voters, 2,400 unconfirmed entries, 413 of them resolved by
rules, 2,014 by history, two rounds) 470-680 ms; its second, idle settle 450 ms. The budget stays at
the floor of 1.0 s (2 x the largest, 0.68 s, would be 1.4 s: the stricter number is kept while it is met).

Caveat: transfer pairing (step 8) and document matching (step 9) will register their steps; re-measure
then. If the budget is missed, narrow the first round to a dirty set (architecture §5.2); rounds after
the first are already narrowed to the entries the newly confirmed votes can reach.
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

TAG_APPLY_BUDGET_SECONDS = 0.5
"""Applying a tag to a whole year (`tests/perf/test_tag_apply_budget.py`): the preview and the real run.

Derivation: on the backfill fixture (8000 entries over 6 accounts) the filter `1 Jan .. 31 Dec`
selects all 8000 taggable entries; `apply_tag` is timed as a dry run and for real (settle patched
out: that is `test_settle_budget`), 5 samples each, memberships removed after each. Measured on the
dev machine (Postgres 18, localhost), two sessions: median 108-126 ms, max 140 ms for both. Budget =
2 x the largest measured value (0.28 s), rounded up, never below 0.5 s. No index is needed.
"""

RULE_PREVIEW_BUDGET_SECONDS = 1.0
"""The preview of a rule write (`tests/perf/test_rule_preview_budget.py`): the dry run of a create, an
edit and a delete (matches, would-confirm, lists A and B), as the write transaction computes it.

Derivation: on the backfill fixture (8,000 entries), in two variants: all unconfirmed (the worst case to
rederive) and ~70% confirmed (5,600 history voters, about 2,400 unconfirmed). Measured on the dev machine
(Postgres 18, localhost), max of 5 samples over three runs: create a merchant's rule 0.10-0.19 s; create a
rule matching all 8,000 entries 0.20-0.32 s; edit (narrowing, list B through the GIN index) 0.09-0.14 s;
delete 0.10-0.21 s. Settle after a real rule write: median 0.28-0.46 s, max 0.48 s (the settle budget
applies). 2 x the largest (0.32 s) is 0.64 s, so the floor of 1.0 s is the budget."""
