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

Step 7 (units): the unit CTE adds one indexed self-join on `counterpart_entry_id` and a window over the
unit key, and the flags now read it. Re-measured: baseline 405 ms, post-commit settle 304-319 ms,
`confirmed_share=0.7` resolving settle 753 ms (one run; 470-680 ms before), its idle second settle 439 ms.
Still inside 1.0 s.

Step 8b (transfer pairing, `tests/perf/test_pairing_budget.py`, `confirmed_share=0.7` plus 800 transfer legs:
160 pairs to make, 100 made, 280 unpaired of which 140 waiting): the `pair_transfers` step with real work
(load the unpaired legs, `pair_all`, one write for 320 legs) 12-15 ms, 4 ms idle; the flag statement with the
`waiting`/`unmatched_transfer` joins 46-49 ms idle and 137-219 ms rewriting every flag; the settle over that
ledger 862-1056 ms first (two rounds: the made pairs confirm units, whose votes run a second round; the
resolving step is 555 ms of it) and 495-510 ms idle; the plain resolving settle 818 ms, baseline 430 ms,
post-commit 322-330 ms. Measured with load averages of 8-10 from other work on the machine. The first settle
of this variant is the one that comes closest to the 1.0 s budget (one run in four of them exceeded it at
that load): if it is missed on a quiet machine, narrow the first round (below).

Step 9 wave B (documents, `tests/perf/test_documents_budget.py`): the ~90% confirmed ledger (7,200
voters) plus 3,000 documents and 1,500 unconfirmed provider-payee charges (600 with one unique document,
300 in ambiguous pairs, 300 near misses, 300 waiting), about 2,300 unconfirmed entries, as many as the
70% ledger has. The settle over it: 1.00-1.06 s first (the 600 links and a second round included),
0.52-0.58 s idle. Measured with load averages of 5-10 from other work on the machine, on which the other
variants read higher than their notes above (baseline 526 ms, the 70% resolving settle 861 ms, the
transfer ledger 992 ms). The document steps are about 0.15 s of the first settle: step 2 (the unlinked
documents, the gated charges, the matcher, one write) 15 ms steady and 70-90 ms with the first round's
links; step 3 (a targeted resolve of the 600 linked transactions: the units of their entries 27 ms,
every value derived again) 75-90 ms, and nothing when nothing was linked. The rest is step 1 (about 0.45
s, as in the other variants) and the flags. Step 2 on a settled ledger with nothing to link: 16-20 ms.

What kept it there. The candidate test of the unit CTE (`doc_candidate`, `doc_suggested`) was first a
correlated scan of the documents per charge: about 110 ms per evaluation, and the CTE is evaluated about
seven times per settle (2.4 s first, 1.5-1.8 s idle). It is now one derived table of candidate pairs
found by two hash joins (10 ms per evaluation). The matcher's `automatic_links` finds candidates through
an index of the documents (1 ms for 900 charges and 2,400 documents). Step 2 is left out of a round in
which step 1 wrote nothing (`SettleRun.documents_dirty`). That is the narrowing to a dirty set
architecture §5.2 allows, for steps 2 and 3 only: step 2 reads only the gated subset (provider payee, no
document key) and returns at once when no document waits for a charge, and step 3 only the transactions
linked in this settle. The first settle is the one that comes closest to the 1.0 s budget (over it in
three runs out of four on the loaded machine, by 0.00-0.06 s): if it is missed on a quiet machine,
narrow the first round (below).

Caveat: if the budget is missed, narrow the first round to a dirty set (architecture §5.2); rounds after the
first are already narrowed to the entries the newly confirmed votes can reach.
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

QUEUE_BUDGET_SECONDS = 0.5
"""A request of the review queue (`tests/perf/test_queue_budget.py`): the first page, a page of 500
units, a page by cursor, the new-count and one unit, as the endpoints compute them.

Derivation: on the backfill fixture (8,000 entries), all unconfirmed (a queue of 8,000 units, the worst
case) and the ~70% confirmed variant (2,427 units). Measured on the dev machine (Postgres 18, localhost),
max of 7 samples: first page of 100 units (all three sections) 26-28 ms, a page of 500 units 45-52 ms, a page
by cursor 26-28 ms, new-count 11-15 ms, one unit 3 ms. The unit CTE runs once per request (set-based, no query
per unit); only the entries of the page are loaded. Budget = 2 x the largest (52 ms), never below 0.5 s.
"""

UNIT_PREVIEW_BUDGET_SECONDS = 0.5
"""Opening one unit: `POST /api/units/preview`
(`tests/perf/test_unit_preview_budget.py`), as the endpoint computes it.

The preview loads the closure, the accounts, the rules and the history snapshot (one query over every
voter, indexed in Python, built per request and without the unit's own entries), then lays the draft over
the unit in memory. Measured on the dev machine (Postgres 18, localhost), max of 7 samples over two
sessions: 8,000 unconfirmed entries (no voters) 15-21 ms for an opened unit, a split with a drafted
category and a re-resolved unit; ~70% confirmed (5,600 voters) 60-83 ms for the same. The target was 0.3
s; the snapshot does not dominate, so it is built per request and not cached (nothing to invalidate). 2 x
the largest (83 ms) is 0.17 s; the floor of 0.5 s is the budget.

Step 8d (offers, `test_preview_of_transfer_legs_with_offers_within_budget`, the 800-leg transfer ledger): the
preview also loads every unpaired transfer leg of the ledger, pairs over them in the simulation of settling
and reads the pool of offers around the unit's legs (90 days, `ix_le_date` / `ix_le_account_date`, no
sequential scan: the test EXPLAINs it). Measured, max of 7 samples, over three runs under a load average of
5-8: legs with a counter-account (190 offers over the 7 units) 79-167 ms, legs without one (326 offers: every
account the currency rule allows) 76-139 ms. Inside the same 0.5 s.

A commit and the settle that follows (the same test, ~70% confirmed, after the first settle): median
531-534 ms, max 558 ms, inside the settle budget (`BUDGET_SECONDS`)."""
