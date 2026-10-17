# Household ledger — implementation plan

Status: **seed.** What gets built, in what order, and what "done" means for
v1. `spec.md` says what the system does and `architecture.md` how it is put
together; neither says when. See `README.md` for the document map.

This document is expected to churn and to be largely deleted once v1 ships.
Nothing here is a design decision — where a plan item implies one, the
decision belongs in the spec or the architecture and this document just
references it.

---

## v1 scope not implied by the spec

The specification defines the domain and the pipeline. These are additional
deliverables v1 needs that no section of it describes.

- **Dashboard.** Four numbers, not charts: account balances, net worth, this
  month's spend against last, unreviewed count. This month is always the least
  reviewed, so its spend shows the unclassified amount beside it ("€1,240 +
  €310 unclassified") rather than understating it, and the period's
  reconciliations, where cash spent unrecorded ends up (`spec.md` §8); net worth likewise shows
  the transfers still unpaired beside it, since a withdrawal not yet confirmed
  is missing from the cash account (`spec.md` §6). Also where the account
  facts of `spec.md` §3.11 show — accounts sorted by data age, unexplained
  differences — which is how a silently stopped importer gets noticed. The
  "balance not anchored" status belongs on the account view.
- **One report.** Spend by category over a date range, drilling into entries,
  with the reconciliation and unclassified lines beside it so the report
  shows how much of it is explained. Everything else is a filter on the
  ledger list, and tagging applies to a filter's result (`spec.md` §3.7), so
  the filter bar is where the effort belongs.
- **CSV export** of entries with their dimensions joined — escape hatch and
  debugging tool.
- **A tested restore.** The database and its backups are operated externally,
  but a restore must be exercised before the ledger holds real history. A
  bank can resend transactions; it cannot resend months of categorisation,
  payee rules, splits and review decisions.

## Explicitly out of v1

Budgets of any kind. Mobile. Position-level depot holdings. Attachments.
Pending transactions and supersede. An audit log and undo. The AI classifier
pass — its protocol exists so it is a later package rather than a refactor,
but it is not built. A rate importer — non-base-currency accounts work, and
their values show as unvalued until one exists; matching never needs rates,
so cross-currency transfers pair in v1. The PayPal importer. Real document
importers (PayPal, Amazon) — document matching, waiting and split proposals by
document lines are in v1, exercised with a test document importer, so adding a
real one is a package, not a refactor; with no document source enabled
nothing waits for one. OIDC; the
session model accommodates it and the password path ships first. Migrating
categorisation from another tool: its history arrives as source transactions
through a CSV importer, and a handful of rules confirms the bulk of it
(`spec.md` §5.9).

A model-assisted *suggest a profile from a sample* for the CSV importer
(`plugins/importers/csv.md` §9): the profile is data judged by the dry run, so
it can follow the profile form without touching the importer.

The multi-currency *model* is in v1: currencies, one currency per account,
instructed amounts, `base_value()` and the reporting rules (`spec.md` §3.8).

---

## Build order

**Do the DK product registration first, before any code.** It is free, takes
10–15 working days, and is the only dependency with a lead time measured in
weeks.

**Then the CSV importer and the review queue**, against a real statement
export. A CSV importer is nothing more than an instance of the importer
contract, but building it first is a deliberate hedge: registration takes
weeks, some banks are withdrawing FinTS, and most credit cards never offered
it. It also exercises splits, payee resolution, history-based classification
and the queue against real German transaction text well before any FinTS code
exists.

**Link before importing.** Every account that will ever be imported is created
and linked to its source before the first import that points at it — the
Giro's CSV before its savings account is linked otherwise has the savings
account proposing counter-legs, which, once committed, a later import of its
own history duplicates
(`spec.md` §5.4). Linking warns where that has happened. Until FinTS exists, an
account meant for it is linked to a CSV profile — that makes it synced, so
legs pointing at it wait instead of proposing counter-legs — and the FinTS
credential is linked beside it later.

**FinTS after that**, slotting in behind a contract already proven, with the
TAN flow as the only genuinely new work. Its first run on an account that
already has CSV history is where deduplication across sources, and a manual
anchor meeting its first reported balance, are exercised for real.

Rough sequence:

1. DK registration filed.
2. Schema, migrations, integrity views, the two-run test harness against the
   test database, and a backfill-sized fixture — a year of history, thousands
   of unconfirmed entries — to time settling after a single commit, which
   `architecture.md` §5.2 requires to stay within a measured budget. Users
   from the environment, password login and sessions (`architecture.md`
   §5.6, §5.7), so every later step runs behind a real session.
3. Ingest: canonicalisation and hashing, one identity per row, the two-step
   deduplication between source rows, one transaction per run, one entry per
   source transaction, marking and clearing duplicates, and the removal
   routine; with a settling skeleton — review flags — because every write
   ends by settling (`spec.md` I37) from the first one; derived entries join
   it with balance records in step 4.
4. CSV importer + account setup + per-account runs with their coverage +
   balance records, the derived entry of every record, unexplained
   differences and the run summary + revert as a stack of the account's runs.
5. Ledger list and the filter bar; tags, and tagging a filter's result
   (`spec.md` §3.7).
6. Resolution as a pure function: field order, pass 0 (own accounts), passes
   1 and 2 (rules, history by majority), fed by core's read-only history
   source; standing keys, so units decided by
   pass 0 and rules arrive confirmed; rules with combined conditions,
   `mandate_ref` and counter-account rules; the rule editor with its preview
   of the entries a rule would match and the two lists of a rule change;
   creating and editing categories and payees, category and payee merge;
   rederiving unconfirmed entries; settling's resolution
   steps and its repeated rounds (`architecture.md` §5.2) — pairing,
   counter-legs and document matching join in steps 8 and 9.
7. Review: units and the draft/preview/commit core on an overlay
   (`architecture.md` §6.3), built and tested before any panel UI; then the
   entry form for user-authored transactions — amount and purpose, with
   date, account and sign prefilled — creating, editing and deleting them;
   review flags (`unconfirmed`) computed over the unit's closure, as `spec.md`
   §6 defines, not per entry as the step-3 settling skeleton does (steps 7 and
   8: splits and pairing are what make the two differ);
   the panel with splits and re-resolving, the queue ordered by shape with
   one-keystroke commit, the affected-set patching contract; the units of a
   rule's preview opening in the panel.
8. Transfer matching: candidate filters and date-ordered pairing, a pair
   standing once made and falling with a changed guess; waiting as a hint and unmatched legs; the offers of
   every transfer leg — a smaller amount splitting off a fee, re-pairing a
   paired leg, and on unsynced counter-accounts the counter-leg for the
   cash/ATM flow, created only by a commit and proposed where the
   counter-account holds no open offer; open offers proposed only when exact;
   user-authored transactions, counter-legs included, only on unsynced
   accounts — and
   "needs an account". Its offers and counter-legs extend the preview of
   step 7.
9. Document matching, against a test document importer: candidates and
   automatic links needing uniqueness both ways, suggestions, waiting by
   document coverage, enrichment, the split along a document's lines in the
   preview, and the document list with its reverse matches.
10. per account page to view & manage transactions, FinTS importer: discovery, first-fetch start, PIN/TAN; UI for importers (FinTS & CSV), UI for managing importer instances, per-account fetches, sync task and SSE.
11. Dashboard with data age, the one report.

Steps 3 to 9 are where the design is actually tested; everything before is
scaffolding and everything after is comparatively mechanical.

---

## First-week questions to answer with real data

Things the design currently guesses at, cheapest to settle early because they
shape later work:

- **Do both spouses' logins produce identical identities for the same
  shared-account transaction?** If not, deduplication still pairs them by
  booking date and amount and marks the second delivery a duplicate once
  (`spec.md` §5.2), so the stakes are low; check that their booking dates
  agree.
- **Does the CSV export carry the same booking date as FinTS for the same
  booking?** Deduplication across sources pairs by booking date and amount
  (`spec.md` §5.2, §5.3); a format that shifts the date leaves duplicates.
- **Does the bank's closing balance line up with its booking dates?** Check
  whether weekend or late bookings are dated after the balance they are
  included in, and how often the bank books into a day it has already closed
  — each such booking leaves a pair of reconciliations that cancels in the
  account's unexplained difference (`spec.md` §5.10) but still shows on the
  reconciliation line — so the FinTS importer can report the closing balance
  of the last closed day (`spec.md` §5.1). Check too that python-fints exposes the statement-level
  balances (MT940 `60F`/`62F`, camt `CLBD`), not only the transaction lines.
- **Do internal transfers carry a real end-to-end id, and does the purpose
  survive to the receiving account unchanged?** The end-to-end id is a
  pairing filter and the purpose a tie-breaker (`spec.md` §5.7); a bank that
  rewrites the purpose only loses the tie-breaker.
- **What do the bank's `booking_text` values actually look like?** History key
  4 (`spec.md` §5.9) depends on whether they discriminate withdrawals from
  purchases.
- **Does the bank deliver camt or only MT940**, and does camt supply
  `AcctSvcrRef`? Determines whether identities are source ids or content
  hashes with ordinals.
- **Is `AcctSvcrRef` stable across re-fetches**, not just present? An unstable
  reference no longer duplicates — the amount step pairs the row and marks it
  a duplicate — but it adds a duplicate row for every row of the overlap
  window on every sync (`spec.md` §5.2).
- **Does a later fetch always contain every row an earlier fetch delivered for
  the same days** — in particular on the first day of its window? The amount
  step relies on it (`spec.md` §5.2); a bank that filters by entry date rather
  than booking date, or removes a booked row instead of booking a reversal,
  breaks it at the edges.
- **Does the bank deliver the mandate reference** (MT940 `MREF+`, camt
  `MndtId`, a CSV "Mandatsreferenz" column) for card collections and direct
  debits? Rules that tell two cards on one collection account apart rely on it
  (`spec.md` §5.9).
- **How many distinct ATM operators appear in a year of statements?** Sizes the
  case that history-based classification has to cover.
- **What does the credit card export look like?** Whether the
  foreign-currency fee is a separate booking or folded into the purchase,
  whether original amount and currency have their own columns, which sign it
  uses for purchases, whether it states its billing period, and whether it
  carries a running balance — which decides whether the card account
  reconciles against reported balances, or only against balances entered by
  hand from its statements.

## First month of use: what to observe

Some decisions were taken deliberately simple, on the expectation that the
cases they leave rough are rare. A month of real use should confirm it:

- **Partial commits.** A commit keeps what was decided, and settling confirms
  the unit only once it is complete (`spec.md` §6). How often are units committed incomplete, is the
  preview's resulting state noticed, and how often is a waiting unit's work
  redone because its input changed?
- **Partners booked later than the matching window.** Such a partner can be
  neither paired nor offered (`spec.md` §5.7). How long are the real booking
  lags between legs — a card payoff especially — and is the ledger-wide
  window wide enough?
- **Unmatched legs on synced counter-accounts.** They get no counter-leg
  (`spec.md` I40) and are completed by importing what is missing. How often
  does that happen, and is a CSV for the gap always at hand?
- **Counter-legs left over.** A counter-leg stays when its pair breaks, and
  only a commit creates one (`spec.md` §5.7). How often do leftovers sit in
  the queue, and is the offer shown first enough to get them re-paired or
  deleted? How often is a withdrawal typed by hand after its counter-leg was
  committed, leaving two cash legs for one withdrawal?
- **Counter-legs on accounts linked later.** Despite linking first, does an
  import ever overlap counter-legs committed while its account was unsynced
  (`spec.md` §5.4)? If it does more than once, an explicit "kept by hand"
  flag on the account is the upgrade.
- **Mixed payees and history's majority.** Does a payee or counterparty that
  spans categories — a supermarket's household goods, a department store —
  get one category proposed systematically, and confirmed at queue speed?
  History stays at a strict majority until this is seen (`spec.md` §5.9).
- **History's starting parameters.** Lookback, key 5 similarity and token
  rules against a year of real purpose lines.
- **Rules carrying the recurring load.** How many units still reach the queue
  per month once rules exist for rent, salary, card payoffs and withdrawals,
  and which kinds?

The PayPal checks (how a purchase appears in the activity export, whether a
balance is ever held, how card-funded payments are recorded) wait until the
PayPal importer is scheduled.
