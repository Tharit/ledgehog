# Household ledger — design baseline

Status: draft for review. What the system does — domain model, invariants,
pipeline semantics. See `README.md` for the document map and the rules that
decide which document owns a given decision.

This document is normative. It states behaviour, not the reasoning behind it
or the alternatives that were rejected.

---

## 1. Why this exists

Two people, one household, German banks. The requirement is a shared ledger that
imports transactions over FinTS, suggests sensible categories, and lets either
of them correct those suggestions quickly, in the evening, on a desktop. No
existing tool covers that combination, hence a purpose-built one.

The scope that makes this tractable is that it is *not* a product: two users,
one desktop, one deployment, no tenancy, no mobile, no i18n.

### 1.1 Goals

- One shared ledger; two logins; everything visible to both.
- FinTS import driven from inside the app's own UI, with the PIN typed by hand
  each time. No stored credentials, no scheduler.
- Pluggable importers with reliable deduplication.
- Category and payee suggestions that improve as they are corrected.
- Every imported movement kept exactly as the source reported it, whether it
  is interpreted or kept as a duplicate. The one exception is a movement the
  source implies but does not list, which is marked as such (§5.1).
- Net worth across checking, savings, cards and cash, and across depots and
  other assets valued by hand — held in any currency and reported in one.

### 1.2 Non-goals for v1

Envelope budgeting. Budgets of any kind. Full double-entry. Mobile. Pending
(unbooked) transactions — importers deliver booked records only (§5.1). FX
cost basis or lot tracing, and the exact base-currency cost of foreign
spending. Position-level depot holdings. Receivables / who-owes-whom
tracking. Attachments. An audit log or undo. Public deployment.

### 1.3 Operating assumption

**Synced accounts are synced regularly.** Nothing fetches on its own, and
each user can sync only the credentials they may authenticate (§5.11), so data
arrives when people sync. Several mechanisms assume that it does: how closely
an unexplained difference against a reported balance can be localised
(§5.10), transfers between accounts pairing once both sides have arrived
(§5.7), and staying within the history depth a bank delivers without
additional authentication.

How regularly is not fixed here. Every account shows the age of its data
(§3.11), which makes a lapse visible.

---

## 2. Shape of the system

There are four kinds of row that carry or describe money. Two of them carry
movements of money, and the difference between those two is the idea the
whole design rests on.

A **source transaction** is what a source said: one row per movement of
money, with its raw payload kept. A source is an importer; a user, for the
accounts no importer fetches — "€4.50, coffee at Starbucks" on the cash
account; or a booking, which settling makes on a clearance account from a
document or a transfer (§5.8). An imported row is immutable; a row a user
authored is edited through the form that entered it (§5.6); a booking follows
its source.

A **ledger entry** is the interpretation of a movement: type, category,
payee, tags. Exactly one is created per new source transaction; splitting
it into several is part of interpreting it afterwards. Entries are what the UI
lists, what reports aggregate, and the only rows that count towards a balance.

Every movement has a source transaction, imported, user-authored or booked —
a counter-leg the system creates to complete a transfer included (§5.7). Only
entries derived from stated balances are not movements and have none (§3.9).
Rules tied to a source transaction — the split invariant above all — apply to
every entry that has one.

An **external document** describes money without moving any — an Amazon
order, a receipt. It belongs to no account and never affects a balance
itself. Where a clearance account takes its provider, it is booked onto that
account as a source transaction, one entry per line (§5.8); nothing links it
to the charges that paid it.

A **balance record** states what an account held on a date — reported by an
importer or entered by a user. It is a fact about a balance, not a movement,
and never enters a sum; the entry derived from it does (§3.10).

```
source_transaction ──► ledger_entry        1 entry, or N after a split
   (what the bank said)   (what it means)

(none)             ──► ledger_entry        derived from balance records

external_document  ──► source_transaction  booked on a clearance account,
   (the Amazon order)     (a booking)      one entry per line

balance_record     ──► ledger_entry        one derived entry per record:
   (what it held)         (derived)        the opening, then valuations or
                                           reconciliations
```

### 2.1 Invariants

The rules everything else relies on, each stated once with the section that
defines it. Identifiers are stable: never renumbered, never reused. A retired
invariant leaves the table, and its number stays unused.

| Id | Invariant | § |
|---|---|---|
| I1 | Every source transaction has one origin: an importer; a user, on an unsynced account — through the entry form, or as a counter-leg; or a booking, which settling makes on a clearance account. | 5.6, 5.7, 5.8 |
| I2 | An imported source transaction is immutable after insert, except for whether it is a duplicate (`duplicate_of`); a user-authored one changes only through the entry form, by a commit setting its amount to the sum of its entries, or when its single entry follows a partner in a commit; a booking only as it follows its source. | 5.6, 5.7, 5.8 |
| I3 | The entries of a source transaction that is not a duplicate carry its account, currency and dates and sum to its amount; their amounts change only by a split, by an edit of a user-authored source through the entry form or a commit setting its amount to their sum, when a user-authored single-entry leg on an unsynced account follows its partner, or when a booking follows its source. A duplicate has none. | 3.1, 5.6, 5.7, 5.8, 5.9 |
| I4 | A source transaction's identity — its `source_id` where the source assigns one, its content hash otherwise — is unique per account over all rows, duplicates included. | 5.2 |
| I5 | Every account holds exactly one currency, permanently; every entry and source transaction is in its account's currency. | 3.3, 3.8 |
| I6 | A balance is the sum of the account's ledger entries. Source transactions, documents and balance records never enter an aggregate. | 3.3 |
| I7 | A source transaction gets exactly one entry when it is created or stops being a duplicate, except a document booking, created with one entry per line; only a commit splits an entry, and never a booking's. | 5, 5.8, 5.9 |
| I8 | Only entries with a source transaction may be incomplete; derived entries are complete at creation. | 3.4, 3.9 |
| I9 | A category implies type `flow`; a payee applies only to flows; a category's kind is fixed at creation and a child has its parent's kind; the category tree has no cycles. | 3.4–3.6 |
| I10 | A transfer pair is mutual, on two distinct accounts, with opposite signs; a same-currency pair is exactly equal and opposite. An entry has at most one counterpart. A transfer leg's counter-account is never its own account, and a paired leg's is its partner's account. | 5.7 |
| I11 | A transfer's counter-account is in the currency the money arrived in. | 5.7 |
| I13 | Every counting balance record owns at most one derived entry — the anchor's is the account's opening, dated before every other entry on it — computed from the records and never edited, tagged or annotated. | 3.9, 3.10 |
| I17 | No pass, matcher, settling or import creates an account, category or payee. | 5.9 |
| I18 | Proposals are rederived from current inputs, rules and history; standing values are kept. When an entry's input changes it is resolved afresh, and when a value changes the standing values after it in field order are derived again; a merge's repointing is not a change of value, and a user-authored leg following its partner is not a change of input. | 3.5, 3.6, 5.7, 5.9 |
| I19 | History learns only from confirmed values: a human's, or standing values. | 5.9 |
| I20 | No automatic process changes a reviewed entry, except that a booking follows its source; derived entries, which are never reviewed, are the only other entries recomputed. | 5.8, 5.9, 6 |
| I21 | Review is per unit — the entries of a source transaction and of a transfer pair — and a unit's edits take effect atomically when it is committed. | 6 |
| I22 | A transfer is confirmed only as a pair. | 5.7, 6 |
| I23 | Review flags are derived from current state and never patched. | 6 |
| I24 | No automatic pair is made between legs whose counter-account or end-to-end id distinguishes them. | 5.7 |
| I26 | Review state never excludes an entry from balances or reports. | 6 |
| I27 | Base-currency values are computed, never stored, by one conversion function, and only reporting calls it. | 3.8, 8 |
| I28 | No secret that could authorise a payment is ever stored. | 7 |
| I29 | Importers emit only final, booked records, in ledger sign convention. | 5.1 |
| I30 | Only a transaction run can be reverted, and only while it is the latest successful, non-reverted run on its account, in the order ingest wrote them. | 5.6 |
| I31 | A source transaction has at most one transfer entry. | 5.9 |
| I32 | An incoming row whose identity the account already holds is skipped. Each remaining incoming row is paired one to one with an imported source row of the same booking date and amount that no incoming identity accounted for, and inserted as its duplicate; the first one in wins. Rows of one delivery are never compared with each other. Only ingest marks rows automatically, and only rows it is inserting. | 5.2 |
| I33 | An automatic pair requires a known counter-account on at least one leg. | 5.7 |
| I36 | A reported balance record is never dated after its run's coverage. | 5.1 |
| I37 | Every write ends by settling, after which derived state reflects current data; a model answer arrives later as a write of its own. | 5 |
| I38 | An account's kind is fixed at creation; with it, whether the account is an investment account (depot, asset). | 3.3 |
| I39 | Ingest is serialised per account, settling as a whole. | 5 |
| I40 | User-authored source transactions — entered, or created as counter-legs — exist only on unsynced accounts; those made before an account became synced stay. | 3.3, 3.9, 5.7 |
| I41 | A booking exists only on a clearance account, which never has a source; it exists exactly while its source calls for it, and is never a duplicate nor written through the entry form. | 3.3, 5.8 |

---

## 3. Core concepts

### 3.1 Source record vs ledger entry

A **source transaction** is one immutable row per thing an importer saw: the
amount, the booking and value dates, the counterparty IBAN and name, the
purpose line, the instructed amount where the payment was made in another
currency (§3.8), and the full raw payload. It is never edited.

A **ledger entry** is the interpretation: type, category, payee, tags, notes.
A source transaction has one or more entries, and they must sum to its amount
— except a *duplicate* (§5.6), which has none.

This gives three things at once:

- **Splits with a real invariant.** The €300 transfer to a friend that is part
  dinner and part gift becomes two entries under one record, and the €300 is
  *stored* so the allocation can be checked.
- **Provenance in the UI.** Each entry can render an importer-specific detail
  widget — IBAN, BIC, Verwendungszweck, end-to-end ID for SEPA; other fields for
  other importers — by reading `source_transaction.raw`.
- **Stable dedup.** The identity lives on an immutable row, so editing or
  re-splitting an entry can never disturb it.

### 3.2 One ledger, two users

`app_user` exists for login only. No table is scoped by user: ledger data has
no tenancy, no ownership and no permissions, and both users see and may change
everything. The one thing a user owns is the right to authenticate a
credential (§5.11).

**Who and when are recorded only on event records** — import runs, which are
the log of an activity. Mutable state carries neither: ledger entries,
dimensions, accounts and documents record no creator, editor or
timestamp. If that is ever needed, it is an audit log, not columns.

### 3.3 Accounts

Accounts hold balances: checking, savings, card, cash, digital wallet (a balance
held with a provider outside a bank, such as PayPal or Wise), depot, loan,
other assets valued by hand, and clearance accounts (below). Each holds exactly one currency, permanently
(§3.8). An entry and a source transaction are denominated in their account's
currency, so a balance is always a sum in one currency. **A balance is always
`SUM(ledger_entry.amount)` for the account** — one column, no special case per
type. Source transactions, documents and balance records never enter an
aggregate.

**Sign convention.** Every amount and every balance in the ledger is signed
by the direction of money for that account: positive increases the account's
balance — more assets, or less debt. A card or loan account therefore carries
a negative balance. Importers deliver amounts, reported balances and document
totals in this convention (§5.1).

**Synced and unsynced.** An account is *synced* while it is open and has at
least one `account_source` row — a credential that can fetch it (§5.4) — and
*unsynced* otherwise. Cash, depots and other assets are typically unsynced.
The distinction decides what is fetched, where entries may be made by hand —
user-authored transactions and counter-legs only on unsynced accounts (I40) — whether a
transfer leg pointing at the account may wait for an import to deliver its
partner (§5.7), and what its data age is read from (§3.11). A synced account
holds what its imports deliver, so its reconciliation measures the imports
alone. Balance records may be set on any account, and every one reconciles
(§3.10).

**Investment accounts.** Depots and other assets are *investment accounts*.
An account's kind, and with it whether it is an investment account, is fixed
at creation (I38), because it decides how
the entries derived from its balance records are reported (§3.10, §8);
changing it would move history between report lines silently.

**External reference.** An account's `external_ref` is the identifier the
institution uses for it — an IBAN, a card number, a PayPal pocket. Discovery
sets it for an account it offers (§5.4), and a user may set it on any
account, hand-kept ones included, so that pass 0 recognises transfers to it
(§5.9).

**Clearance accounts.** A *clearance* account clears what is bought through
a provider such as Amazon: the provider's orders and refunds are booked onto
it from their documents (§5.8), and the bank's charges for them are transfers
to it (§5.7), so its balance is zero once everything has arrived, and what is
missing or wrong shows in its balance. Its kind is fixed at creation (I38),
like any account's. It never has an `account_source` — linking it to an
importer is refused by its kind — so it is unsynced, and the rules for unsynced
accounts apply; the entry form works on it, for corrections such as a
cancelled item or a gift-card payment (§3.9).

- **Its providers.** It carries the list of providers whose documents it
  takes: names, trimmed, compared case-insensitively; the known providers —
  the names importers give (§5.5) and those of stored documents — are
  suggested, but any value is accepted. A provider is on at most one
  clearance account per currency, across the ledger: "Amazon" may be on
  "Amazon.de" in EUR and on "Amazon.com" in USD. A list absorbs a provider's
  name variants ("Amazon", "Amazon EU").
- **Its start.** Creating it asks for a start date *D*, and the create form
  writes its opening: a manual balance record of zero at the end of *D*
  (§3.10). The account's start is the date of its anchor; only documents
  dated after it are booked (§5.8), so that purchases the bank side already
  holds as categorised charges are not counted twice.

Beyond that, a clearance account is shown and reported like any other
account.

An account may carry an icon and a colour, presentation only (§3.5).

**Closing.** An account is closed with a `closed_on` date, which may lie in
the future, and is open on dates up to and including it. The date matters only
where an entry's date is judged (rules and history, §5.9); the account's state
changes at once: a closed account is unsynced, so it is no longer fetched and transfer legs pointing at it
no longer wait (§5.7); account discovery no longer offers it, and
pickers list it after the open accounts rather than hiding it. Nothing else
changes: entries dated after `closed_on` — final interest, the payout of the
remaining balance — are accepted, imported or entered by hand (§5.6), and the balance shows what is left. A
remaining balance is settled like any other, with a transfer or a balance
record. Its links stay, so reopening it — clearing `closed_on` — restores it as
it was. A closed account appears in reports for every period in which it holds
entries.

### 3.4 Entry types

`flow · transfer · opening · valuation · reconciliation`

- `flow` — money that entered or left the household. Whether it counts as
  income or expense is the **kind of its category** (§3.5), not a property of
  the entry. The sign is the direction of money and is unconstrained: a refund
  is a positive amount in an expense category and nets against it.
- `transfer` — internal movement, two legs, no category.
- `opening` — the balance that existed before the ledger's history of an
  account begins: the entry derived from the account's anchor (§3.10). Counts
  towards net worth; it is initial state, not a flow.
- `valuation` — the entry derived from a later balance record on an investment
  account (§3.3): a revaluation. Non-cash and unrealised, so it gets its own
  reporting line rather than being blended into income. A depot's balance is
  therefore the transfers into and out of it plus its valuations: a gain
  realised by selling appears as valuation like an unrealised one, because the
  sale itself is a transfer out; dividends and fees paid to the cash account
  are ordinary flows.
- `reconciliation` — the entry derived from a later balance record on any
  other account: the part of the change since the previous record that the
  entries in between do not explain. After a wallet count it is unrecorded
  cash spending; after a balance the bank reported, a difference between the
  bank and the ledger (§5.10).

Openings, valuations and reconciliations are the **derived entries**. They
are excluded from income and expense and each has its own report line;
reconciliations count towards savings (§8).

A category is required exactly for `flow`. The other four are fully
described by their account and type.

**Not yet interpreted is a legal state.** An entry that no resolution pass
could classify has `type` and `category_id` NULL. That is allowed only for
entries with a source transaction (I8), imported or user-authored, and such an
entry is by definition not yet reviewed: confirming it (§6) requires a
complete interpretation. Derived entries are complete at creation. Reports show such entries, and flows
without a category, on an "Unclassified" line (§8), so totals still equal
balances without pretending to know which side they fall on.

Net worth is the sum of all balances, converted to the base currency at the
report date (§3.8), which stays correct for all five types.

### 3.5 Categories

Hierarchical, orthogonal to payees, and each with a **kind**, `income` or
`expense`. A child has its parent's kind. The kind says which side of the
income statement a flow falls on; it does not constrain the sign. A category
therefore serves one side only: gifts received and gifts given are two
categories, not one.

**The kind is fixed at creation.** Moving spending to the other side means
creating a category of the other kind and recategorising the entries in the
review panel, so historical reports never change side silently.

The tree has two roots, **Income** and **Expense**, which are the kinds
themselves, not rows. A top-level category is one with no parent; creating it
"under" a root sets its kind. Reports split by kind first, and the UI shows the
two roots at the top of the tree.

**Entries may be booked to any category**, including one that has children.
Drill-downs then show the parent's own entries as a line of their own beside
its children.

**Icons and colours.** A category, an account (§3.3) and a payee (§3.6) may
each carry an icon and a colour, each a name from a fixed set the UI defines
for that dimension. A category without its own takes its parent's, so
colouring the top-level categories colours the tree; an account or a payee
without one shows a default the UI derives, from the account's kind
(checking, card, cash, …) or the payee's name. They are presentation only: nothing in classification, review,
matching or reporting reads them, and a name the UI does not know renders as
its default.

A category with no entries, no rules referencing it and no children can be
deleted. One
that is in use is merged instead, like a payee (§3.6), into another category
of the same kind: its entries and rules are repointed, its children move under
the target, and it is deleted. A child whose name the target already uses
among its own children is merged into that child the same way, so a merge
may descend the tree; the preview shows every category it merges. Moving a
category under one of its own descendants is refused: the tree has no cycles
(I9). So is merging a category into one of its descendants, whose outcome
would not be obvious: the user merges the descendants upwards instead, and
renames. Merging a category into one of its own ancestors is allowed: its
children move under the ancestor, and the source itself is not counted among
the ancestor's children when same-named children are matched. A merge repoints
values without deciding them anew: entries and
rules keep their keys, nothing is derived again, and nothing returns to
review; the repointed entries' versions do bump, like any user-meaningful
change, so an open panel on them is refused and reloads. A merged-away category is simply an id that no longer exists, with no
redirect: a write that still names it (an open panel's draft, a stale picker)
is refused as a conflict with the code `stale_reference`, never as a generic
validation error, and the client reloads its lookups on that code. The target
keeps its own icon and colour. There is no archived state. Pickers rank
categories by recent use, so dormant ones sink without being hidden.

### 3.6 Payees

A first-class table with pattern-based resolution and merging. A payee is a
**curated reporting dimension** — it exists because someone wants to report on
that merchant, not because a counterparty appeared. Most counterparties never
become payees, and nothing requires one: an ATM operator used once or every
week needs no payee. Payees apply to flows only.

Merchant and category are independent dimensions: Amazon spans Electronics,
Books and Household, so encoding merchants as category leaves would scatter one
merchant across the tree and break the moment a split assigns two categories to
one payee.

A payee may carry an icon and a colour, presentation only (§3.5).

Merging two payees repoints their entries, the rules that set the payee and the
payee conditions naming it, then deletes the merged
one; as for categories (§3.5), the repointed values keep their keys, nothing is
derived again or returned to review, and the entries' versions bump (§3.5).
The target's attributes win: its name, note, icon and colour are kept. A
write that names a merged-away payee, or
a deleted category, payee or account, is refused as a `stale_reference`
conflict (§3.5). A payee no entry references can be deleted, together with the rules that set it;
a rule whose payee condition names it stays, shown as "Payee deleted" in the
editor, and never matches (ids are never reused). The preview lists both the
rules it deletes and the rules left with such a condition; a payee in use is
merged instead, which repoints the rules and the conditions. Entry keys that name a
deleted rule stay, and render as "rule deleted".

### 3.7 Tags

User-authored, flat, many-to-many, on entries other than derived ones (never on
source transactions). A tag's span is **derived** — the minimum and maximum
`booked_on` over its entries — never stored: it self-maintains as the trip's
real extent becomes known. Membership stays explicit so the one non-holiday
expense can be removed. A tag may carry a colour from the same set as
categories (§3.5), presentation only.

Tagging every entry the ledger list's current filter selects is one action —
a date range, perhaps narrowed to some accounts, is the usual filter — and it
applies to every selected entry that can carry tags, reviewed or not; derived
entries in the selection are skipped and counted. It is previewed — how many
entries it would tag, how many already carry the tag, how many were skipped —
and confirmed before it runs, and if the filter's result has changed since
the preview, nothing is written. A filter that restricts nothing would tag the
whole ledger, and is refused. Elsewhere than in the work panel tags are
direct writes, on unreviewed entries too; in the panel they are part of the
draft (§6).

A tag's name is unique, compared without regard to case. A tag comes off one
entry at a time, or goes with the tag. Removing a tag from a filter's result
and merging two tags are not in v1.

Tags answer "which episode" — a trip, a project, a renovation; categories
answer "what kind of spending". Keeping both dimensions intact is what makes
"restaurant spend during a given trip" a single group-by.


### 3.8 Currencies

**Every account holds exactly one currency, permanently.** Institutions that
offer "multi-currency accounts" hold one balance per currency; each such
pocket is an account here. Moving value between pockets is a conversion,
recorded as a cross-currency transfer. An account's balance is therefore
always a sum in one currency.

**The ledger has one base currency**, fixed when the ledger is first started
and never changed, because rates are stored against it. Every report is
expressed in it. It is not a property of any entry, and no entry stores a
base-currency value. Two further ledger-wide settings — the maximum rate age
(§3.8) and the matching window (§5.7) — belong to the deployment's
configuration, not to the ledger's data: they are changed by reconfiguring and
restarting, and the ledger settles on start (§5). Both are 7 days unless
configured.

**Currencies are reference data**: ISO code and minor-unit exponent. Every
amount is an integer in the minor units of its own currency — JPY has none,
BHD three.

**Instructed amount.** Where a payment was made in a currency other than the
account's — a card payment abroad, a camt `InstdAmt` — the source usually
reports the original amount. The importer extracts it into
`instructed_amount` / `instructed_currency`, signed like `amount`, as a fact
the source reported, however the format encodes it. It is not a hash input
(§5.2), and nothing aggregates it. It exists for two things: creating a
cross-currency counter-leg exactly — a booked one on a clearance account
included (§5.7) — and pairing cross-currency transfers exactly (§5.7). It is
never used for valuation: the entry is in the account's currency already.

**Conversion to the base currency is computed, never stored**, by one
function, and only reporting calls it (I27). Matching never converts (§5.7).
The function:

- Entries use the rate on their own `booked_on`.
- Balances and net worth use the rate on the report date.
- The rate used is the latest one on or before the date, provided it is no
  older than the **maximum rate age**, a single ledger-wide setting. With no
  usable rate, the value is *unvalued*: reports show it as such and never
  treat it as zero.
- Rounding is per entry, half-even, to the base currency's minor unit. Totals
  are sums of rounded entries, so a drill-down always adds up.

Rates are reference data too — one rate per currency per day against the base
currency — delivered by an importer emitting `rates` (§5.1). A non-base
account is fully usable before any rate source exists; its values are simply
unvalued in reports.

**FX translation.** Over any period:

```
change in net worth = income + expense + unclassified + transfers (net)
                    + openings + valuations + reconciliations + FX translation
```

- **FX translation** is computed per account, never booked: the account's base
  value at the end of the period, minus its base value at the start, minus the
  base values of its entries in the period, each at its own `booked_on` rate.
  It is exactly zero for a base-currency account. It holds rate movements on
  foreign balances, and is reported on its own line for the same reason as
  `valuation`. Where any of these terms is unvalued for an account, that
  account's FX translation is shown as unvalued, never as a figure.
- **Transfers (net)** is the sum of transfer legs in the period at their
  `booked_on` rates. It is zero when every pair settles within the period and
  in one currency. It is non-zero for a pair whose legs fall in different
  periods, for a leg whose partner has not arrived yet, and for the spread of
  a conversion between currencies.

**No funding-chain tracing.** A foreign entry is valued on its own date,
whatever money paid for it. JPY spent from a USD pocket that a friend's
transfer filled is valued JPY→base on the day it was spent; the friend's USD
was valued on the day it arrived; the difference is FX translation.


### 3.9 Where entries come from

Every ledger entry is one of two kinds, told apart by what it references:

| Kind | References | Created by | Subject to |
|---|---|---|---|
| **movement** | its source transaction | ingest; the entry form; a commit's counter-leg (§5.7); settling, as a booking (§5.8) | any type, may be incomplete; split invariant, resolution, review. An imported source is marked as a duplicate, never deleted; a user-authored one is edited or deleted through the entry form (§5.6); a booking follows its source (§5.8) |
| **derived** | the balance record it is derived from | settling (§5.10) | `opening`, `valuation`, `reconciliation`; amount follows the records; never resolved, never reviewed |

Whether a movement was imported, entered or booked is a fact about its
source — its `origin`: `import`, `user` or `booking` (§5.6) — not a property
of the entry.

**A user enters a movement as a source transaction**, through a small form:
the amount and a purpose ("groceries at REWE") are its visible fields; the
date, the account and the sign are prefilled — today, the cash account, an
expense — and can be changed when entering; a row's account is fixed once it
is entered. The form creates the source transaction and its
one entry, settling resolves it like an import — rules on the purpose, history,
later the model (§5.9) — and the review panel opens on the unit, to split it
or commit it. A manual entry therefore differs from an
imported one only in where its source came from.

**User-authored transactions exist only on unsynced accounts** (I40): cash
spending, a hand-kept loan or depot. On a synced account, what an import got
wrong or missed is fixed through imports — a CSV for a gap, marking duplicates
(§5.6) — so the account holds only what its sources delivered. Rows entered by
hand before an account was linked, counter-legs included, stay as its history,
and its first fetch is prefilled to start after them (§5.4). User-authored rows
take no part in deduplication (§5.2).

A manual transfer may point at any account: its counter-leg is created with it
where the counter-account is unsynced — on a clearance account it is booked
(§5.7) — and where it is synced — cash paid into
the bank — the leg waits, and pairs when that account's import delivers its
partner (§5.7). Only the leg is hand-made; the synced account receives nothing
by hand.

Entries derived from balance records are the **derived entries** (§3.4): one per balance
record that explains anything (§3.10). Their amounts are recomputed whenever
the account's entries or records change, and are never edited directly, tagged
or annotated; to correct one, the user corrects the balance record. Each is a
consequence of a record, not a proposal, so it is never resolved and never
reviewed.

### 3.10 Balance records

A **balance record** states that an account held balance *B* at the end of
date *D*, in the account's currency and the ledger sign convention: every
entry dated on *D* counts towards it. There are two kinds, and the kind only
says where the number came from:

| Kind | Written by |
|---|---|
| **reported** | an importer, for the account its run covered: the booked closing balance of the last day before the fetch (§5.1) |
| **manual** | a user, through "set balance", on any account, as the balance at the end of a date the user chooses |

Records of a reverted run do not count. Where this document refers to an
account's records, it means the records that count.

**Every record reconciles.** Its difference from the ledger is explained by a
derived entry, never left as an error. Whether an account's sources report a
balance is observed from the records it holds, never declared.

**Correcting records.** Any record can be deleted, reported ones included;
manual records can also be edited. Deleting a record merges its interval into
the next one.

**One formula.** Every record owns one derived entry — the part of the change
since the previous record that the entries in between do not explain:

```
derived entry for record i = (Bᵢ − Bᵢ₋₁) − Σ movements dated in (Dᵢ₋₁, Dᵢ]
```

Only *movements* — entries with a source transaction — enter these sums.
Derived entries never do, so records sharing a date, as two logins' reports of
one closed day do, cannot count each other's entries.

**The anchor** is the account's earliest record, whatever its kind. It has no
previous record: B₀ is zero and its interval is everything up to the anchor
date, so

```
opening = anchor balance − Σ movements dated up to the anchor date
```

The anchor's derived entry is the account's **opening**, dated the day before
the earlier of the account's earliest movement and the anchor date. Every
later record's derived entry is dated on the record's date: a **valuation** on
an investment account (§3.3), a **reconciliation** on any other. A zero result
means no entry. Records on the same date are ordered by id. An account has
at most one manual record per date: setting a balance on a date that already
has one edits it. An account with no
records has no derived entries, and once it holds entries it shows *balance
not anchored* (§3.11).

What a reconciliation means depends on where the number came from. After a
manual count it is the ordinary explanation of the change — unrecorded cash
spending. After a reported record it says that the bank's balance and the
ledger disagree in that interval: either the bank booked into a day it had
already closed, which the next record's reconciliation cancels, or something
is missing or duplicated, which persists until the cause is fixed. What
persists is the account's *unexplained difference* (§3.11).

### 3.11 Account and currency status

A few facts are surfaced on an account or currency. Each is derived from
current state, stored nowhere, and is not a review flag: it belongs to the
account or currency, not to any entry.

| Fact | Applies to | Shown as |
|---|---|---|
| **data age** | every account | days since its `synced_through` (§5.4) for a synced account, since its latest balance record for an unsynced one; "never" where it has none |
| **unexplained difference** | any account with reported records | the sum of the reconciliations of every record from its first reported record through its latest, in record order, where non-zero: how far the ledger and the bank disagree as of the latest reported balance. Shown with the reported records since that running sum was last zero, which localise it (§5.10) |
| **balance not anchored** | any account | it holds entries but no balance record: its balance rests on no stated balance and starts from zero (§5.10) |
| **rate age** | currencies | days since its latest rate; a value whose rate is older than the maximum rate age is unvalued (§3.8) |

Data age is what makes a lapse visible: the Overview lists accounts sorted by
it, so a stalled importer rises to the top. No threshold decides when an age
is too old; a Giro synced weekly, a card fed by a monthly file and a depot
valued quarterly differ, and the reader knows which is which. The **maximum
rate age** is the single ledger-wide setting here, and it belongs to valuation
(§3.8), not to status.

---

## 4. Worked examples

**Simple expense** — €47.31 at REWE.

```
source_transaction  #1  Giro  -4731  purpose='REWE SAGT DANKE'
ledger_entry   #10 Giro  -4731  flow  cat=Groceries (expense)  payee=REWE
```

**Split** — €300 to a friend: €120 dinner, €180 gift.

```
source_transaction  #2  Giro  -30000  counterparty='Thomas M'
ledger_entry   #11 Giro  -12000  flow  cat=Dining
ledger_entry   #12 Giro  -18000  flow  cat=Gifts given
```

The €300 is stored once; the invariant `sum(children) = record` is enforced.
Entry #11 is the original, kept as the residual of the split; #12 is the
child the user added in the review panel (§5.9).

**Transfer with a fee** — €100 to savings, €0.50 charged in the same booking.

```
source_transaction  #3  Giro     -10050  counterparty_ref=<Savings IBAN>
source_transaction  #4  Savings  +10000

ledger_entry   #13 Giro     -10000  transfer  counterpart=#15
ledger_entry   #14 Giro        -50  flow      cat='Bank fees'
ledger_entry   #15 Savings  +10000  transfer  counterpart=#13
```

Ingest creates one −10050 entry. Pass 0 types it `transfer` to Savings,
because its `counterparty_ref` is the Savings account's IBAN (§5.9). It
cannot pair automatically — nothing on Savings has the opposing amount — and
waits for its partner — or, once Savings has synced through the window, is
unmatched — but its offers already include the +10000 on Savings, by
account, sign and window (§5.7). Picking it splits the difference off the larger leg: the preview shows #13 as
the residual, keeping its transfer typing and now paired with #15, and #14 as
a new flow of −50 for the user to categorise; one commit writes all of it
(§5.9, §6). The fee falls out of the split machinery, and nothing distorts the
transfer amount.

**Cash** — two withdrawals at the same ATM operator, into an unsynced cash
account.

*First withdrawal.* No pass recognises the operator yet.

```
source_transaction  #20  Giro  -20000  counterparty_name='EURONET 4711'
                                       booking_text='Lastschrift'
ledger_entry   #30 Giro  -20000  type=NULL
```

In the review panel, the user converts #30 to a transfer and picks the cash
account. The cash account is unsynced, so the leg is unmatched at once: with no
candidate on the cash account, the preview offers a counter-leg, and the
commit creates it — a user-authored transaction on the cash account — pairs
it and confirms the pair (§5.7). Both
values are the user's choice, so both carry keys of pass `user` (§5.9).

```
ledger_entry   #30 Giro  -20000  transfer  counterpart=#31
ledger_entry   #31 Cash  +20000  transfer  counterpart=#30  (user-authored source)
```

*Second withdrawal.* History now knows the operator: key 2 matches the
counterparty name and booking text of #30, and the paired #30 is evidence
that such withdrawals go to the cash account. The entry arrives typed, with
its destination, and no counter-leg yet.

```
source_transaction  #21  Giro  -10000  counterparty_name='EURONET 4711'
                                       booking_text='Lastschrift'
ledger_entry   #32 Giro  -10000  transfer  → Cash
```

```json
{ "type":            {"pass": "history",
                      "basis": {"matched_on": "counterparty_name+booking_text",
                                "agree": 1, "of": 1, "since": "2026-03-02"}},
  "counter_account": {"pass": "history",
                      "basis": {"matched_on": "counterparty_name+booking_text",
                                "agree": 1, "of": 1, "since": "2026-03-02",
                                "account_id": 7}} }
```

One precedent is thin evidence, and the review queue shows it as 1 of 1
(§6); being unanimous, it is a majority and proposes (§5.9). Confirming #32
creates its cash leg #33 and confirms the pair in one keystroke. Each
confirmation adds evidence; after a few, these withdrawals arrive backed by
several precedents, sorted next to each other in the queue and confirmed one
keystroke each. A rule — counterparty name `EURONET 4711`, counter-account
Cash (§5.9) — makes even that certain: its keys are standing, so each withdrawal
arrives decided, with its cash leg proposed, and is confirmed in one keystroke
that creates the leg (§5.7). Individual cash
expenses are entered on the cash account through the entry form (§3.9).

**Cash abroad** — the first trip to the US, three withdrawals, no USD cash
account yet.

```
source_transaction  #22  Giro  -18734 EUR  instructed=-20000 USD
                                           booking_text='Lastschrift'
ledger_entry   #34 Giro  -18734 EUR  type=NULL
```

No history key knows a foreign operator, so #34 arrives unclassified, as the
first withdrawal at home did. In the review panel the user converts it to a
transfer; its counter-account cannot be the cash account, which holds euros,
because the money arrived in dollars (the currency rule, §5.7). It is an
unmatched transfer that needs an account in USD, and so is each of the other
two once converted. The review queue groups such entries by the currency they
need:

```
3 withdrawals need an account in USD          [ add account … ]
```

Creating the account from there — prefilled with USD — creates the account
and nothing else. The unit it was added from takes it as the user's choice;
each of the others offers it in its counter-account picker, and is confirmed
on its own. Each commit creates a counter-leg for the negated instructed
amount, exactly the dollars received.

```
ledger_entry   #34 Giro      -18734 EUR  transfer  counterpart=#37
ledger_entry   #37 Cash-USD  +20000 USD  transfer  counterpart=#34  (user-authored source)
```

From the next trip on, history has paired evidence of withdrawals going to
the dollar account and proposes it directly. The withdrawal is never booked
into the EUR wallet, because those are dollars. Spending from Cash-USD is
valued at the rate of each spending day (§3.8).

**Card payment abroad** — $1,885.95 on a EUR credit card, with the issuer's
foreign-currency fee as a separate booking.

```
source_transaction  #6  Card  -174210  instructed=-188595 USD
source_transaction  #7  Card    -3049  purpose='AUSLANDSEINSATZENTGELT …'

ledger_entry   #18 Card  -174210  flow  cat=Electronics
ledger_entry   #19 Card    -3049  flow  cat='Bank fees'
```

The account is EUR, so nothing is converted; the instructed amount is
provenance (§3.8). An issuer that
folds the fee into the same booking is the transfer-with-fee pattern above: one
record, split into purchase and fee.

**Refund** — an €80 Amazon return arrives as `+8000`, `type='flow'`,
`cat=Electronics`, so the expense category nets correctly.

**Orders through a clearance account** — the clearance account Amazon.de
(EUR) takes the provider "Amazon", from its start on 31 May (§3.3). An order
of 2 June: a cable at €12.99 and a book at €34.99, €1.99 shipping not
itemised, paid by a charge on the Giro.

```
external_document   #5   Amazon  2026-06-02  total -4997
                         lines 'USB-C cable' -1299, 'Paperback' -3499
source_transaction  #60  Amazon.de  -4997  source_id='document:5'   (booking)
ledger_entry   #61 Amazon.de  -1353  flow  cat=Electronics  source_text='USB-C cable'
ledger_entry   #62 Amazon.de  -3644  flow  cat=Books        source_text='Paperback'

source_transaction  #63  Giro  -4997  counterparty_name='AMAZON PAYMENTS'
ledger_entry   #64 Giro       -4997  transfer  counterpart=#66
source_transaction  #65  Amazon.de  +4997  source_id='transfer:64'  (booking)
ledger_entry   #66 Amazon.de  +4997  transfer  counterpart=#64
```

Settling books the order as a purchase on the account, one entry per line,
the shipping spread over the lines in proportion (§5.8); rules, history and
the model categorise the entries by their source text like any entry. A rule —
counterparty name starts with `AMAZON`, counter-account Amazon.de — types the
charge a transfer; its other side is booked by itself, and the pair arrives
confirmed (§5.7). The account's balance is zero. Two orders in one charge, an
order charged in parts, a discount that is not itemised need nothing more: the
balance is zero once every order and charge is in, and until then it shows
what is missing. A cancelled item is an entry on the account, through the
entry form, in the item's category.

**Standing confirmation** — the monthly rent, with a payee rule on the
landlord's IBAN and a category rule on that payee.

```
source_transaction  #9   Giro  -125000  counterparty_ref=<landlord IBAN>
ledger_entry   #24 Giro  -125000  flow  payee=Landlord  cat=Rent
```

```json
{ "type":     {"pass": "rule", "basis": {"rule_id": 12}},
  "payee":    {"pass": "rule", "basis": {"rule_id": 12}},
  "category": {"pass": "rule", "basis": {"rule_id": 13}} }
```

Every value comes from a rule, so every key is standing and the unit arrives
confirmed: it never enters the review queue, and history learns from it like
any confirmed entry (§5.9). Had history supplied the category instead, the
unit would be reviewed like any other.

**Balances on hand-kept accounts** — the user states a balance as of a date,
and the ledger derives what follows from it (§3.10):

| Situation | Record | Derived entry |
|---|---|---|
| New wallet, €100 in it today | manual, first | `opening` +10000 |
| Wallet counted at €40, ledger says €80 | manual, later | `reconciliation` −4000 |
| Wallet counted at €120, ledger says €80 | manual, later | `reconciliation` +4000 |
| Depot valued at €54 000, ledger says €50 000 | manual, later | `valuation` +400000 |

A difference left unexplained on a cash account is a reconciliation, on its
own line in reports: a running −€60 means €60 left the wallet unrecorded,
which is worth seeing next to the spend report rather than hidden inside it. A
difference with a known explanation — a toy sold for €10 — is entered as what
it is, in an income category; the reconciliation of the record whose interval
contains it then shrinks by itself, because the toy explains part of the
change.

**Backfilled withdrawals before the first count** — the wallet was counted
at €80 today, its first balance record, and a year of Giro statements is then
imported as CSV. History types the old withdrawals as transfers to cash, and
confirming them creates their counter-legs, a year back.

The opening is still derived from the anchor, so today's balance stays €80.
But a year of withdrawals, €3 000, now precedes the count with no cash
spending recorded against it, and the derived opening becomes −€2 920 a year
ago — a wallet that never held minus €2 920, which its history shows plainly.
An estimated starting balance fixes it: a record of €100 as of the day before
the earliest entry becomes the anchor, the opening is +€100, and today's count,
now a later record, reconciles the year — the unrecorded cash spending appears
as one reconciliation on today's date, on its own report line.

**Card payoff** — both cards are charged by the issuer from one collection
account; only the mandate reference tells them apart.

```
source_transaction  #44  Giro  -84310  counterparty_ref=<issuer IBAN>
                                       mandate_ref='KK-4711-01'
ledger_entry   #45 Giro  -84310  transfer  → Card (Anna)
```

```json
{ "type":            {"pass": "rule", "basis": {"rule_id": 31}},
  "counter_account": {"pass": "rule", "basis": {"rule_id": 31}} }
```

Pass 0 cannot know the issuer's IBAN, and on the IBAN alone history pools both
cards. A rule on the IBAN and the mandate reference declares the destination
(§5.9). The card is synced by its monthly CSV, so #45 waits for its partner
and pairs when it arrives; where the card's side is typed by a rule too, the
pair carries only standing keys and is confirmed when it is made (§5.7).

**Shared account** — a joint Giro reached by both users' logins. Anna syncs
on Monday; Ben syncs on Tuesday, overlapping her window. Where the two logins
render a booking alike, Ben's rows carry the identities Anna's run stored and
are skipped; where they render it differently, the amount step pairs Ben's row
with Anna's and inserts it as its duplicate (§5.2); from then on Ben's row is
skipped by its identity, which also accounts for Anna's. Ben's run summary
lists the duplicates; nothing waits for a decision.

**Loan payment** — €1,000 a month to a loan kept by hand, €800 of it
principal and €200 interest.

```
source_transaction  #50  Giro  -100000  counterparty_ref=<loan account>
ledger_entry   #51 Giro   -80000  transfer  counterpart=#53
ledger_entry   #52 Giro   -20000  flow      cat=Interest
ledger_entry   #53 Loan   +80000  transfer  counterpart=#51  (user-authored source)
```

Pass 0 types the payment a transfer to the loan, a hand-kept account, so the
unit arrives decided, with its counter-leg proposed, and one keystroke commits
both (§5.7). Splitting off the interest
in the panel leaves the residual paired with its counter-leg, whose amount the
same commit sets to the residual's (§5.7). Left unsplit, the counter-leg is +100000 each month, and the
next balance from the loan statement turns the year's interest into one
reconciliation: on its own report line, outside expense, but inside savings
(§8).

---

## 5. Import pipeline

Five words are used throughout this section and name distinct stages with
distinct owners. Where a stage relies on something defined later, the forward
reference is given inline.

**Importer** — code that talks to the outside world. One per source type
(`fints`, `paypal`, `amazon`, `csv`), configured per credential as an
`importer_instance`. It knows URLs, logins, TAN flows and file formats. It
knows *nothing* about the ledger: it fetches, parses, and emits records.

**Ingest** — the shared, importer-agnostic step that receives those records
and decides what to do with them. It determines each row's identity and
deduplicates (§5.2), writes `source_transaction` rows and reported balance
records, and creates the initial `ledger_entry` for each new source
transaction. Every importer goes through the same ingest, so importers cannot
each get dedup subtly wrong.

**Resolution** — the passes that propose a new entry's type, payee, category
and counter-account (§5.9).

**Matching** — transfer legs paired with each other (§5.7). A pair, once
made, stands (§5.7).

**Settling** — bringing derived state up to date (below).

A full sync runs:

```
1. fetch    each instance signs in, then delivers each linked
            account it is asked for and each accountless kind it emits
            (documents, rates) — one import run each
2. ingest   transactions → identity, deduplication, rows and the reported
                           balance record, one ledger entry per new row
            documents    → on (provider, source_id), inserted, or
                           replaced or kept by the importer's mode (§5.5)
            rates        → upsert on (currency, date)
3. settle   bring derived state up to date
```

**Every write ends by settling** (I37), after which derived state reflects
current data: the bookings on clearance accounts (§5.8), the proposals and
pairings of unconfirmed entries (§5.9, §5.7), derived entries (§5.10) and
review flags (§6). Bookings are the one place settling writes source
transactions, and only on clearance accounts. Writes
include a sync, a file upload, a revert, a commit, entering, editing or
deleting a user-authored transaction,
marking or clearing a duplicate, saving or deleting a rule, a merge, changing a category or a payee, creating,
closing, reopening, linking or unlinking an account, changing a clearance
account's providers, a balance record and a
changed configuration, which takes effect when the deployment restarts.
Settling is also available as a standalone action, because it is idempotent:
settling twice changes nothing. Whether it works incrementally or as a full
pass is not specified here. The one input that arrives later is the model's
answer (§5.9): settling never waits for it, and its arrival is a write of its
own.

**Ingest and settling are serialised** (I39): ingest per account — a whole
delivery under one lock, in one transaction — because its amount step reads what
the account holds before it writes (§5.2); settling as
a whole, because it pairs legs across accounts, and two settles running at
once could pair one leg twice.

Only after this does a user see anything: review is a separate activity
against the queue, never a step inside an import (§6).

### 5.1 Importer contract

An importer declares the set of kinds it emits in `importer_instance.emits`.
The test for each record is: *does it move money, or describe money?*

- **transactions** move money — FinTS, CSV statements, PayPal balance
  movements, credit cards, broker cash accounts.
- **documents** describe money — Amazon orders and refunds, receipts,
  invoices, and PayPal payments that PayPal passed through to a card.
- **rates** are reference exchange rates against the base currency (§3.8).

**An importer emits as source transactions exactly the movements of the
account's own balance, in the account's currency.** Events that do not change
that balance — a payment PayPal passed straight through to a card, the
sub-balance events of a conversion that nets to zero — are documents or
nothing. So is a booking of amount zero (a bank's notice, a verification
charge): it moves nothing, so the importer drops it and reports how many it
dropped, which the run's statistics record.

**A movement the source implies but does not list** may be emitted as a
**synthetic** source transaction: a card statement that shows purchases and
never the payment that settles them, whose payment is the statement's net
sum. It is a movement of the account's balance like any other and goes through
ingest like any other row. It differs in three ways: its `source_format` marks
it synthetic; its `raw` records what it was derived from — the statement's row
count, sum and date — in place of a source line; and it is dated after the
run's coverage, so that the balance record the run reports, dated at the
coverage, does not include it and the interval's derived entry (§3.10) stays
zero. It has no `source_id`, so its identity is the content hash, and the same
file delivers the same row again, which is skipped (§5.2). The importer
decides whether and when a statement implies one; an importer that does not
list a movement and does not imply it leaves the account to reconcile (§5.10).

**Importers emit only final, booked records.** Pending states — card
pre-authorisations, PayPal holds — are never imported; waiting for them to
settle is the accepted cost (§9).

**Ledger sign convention.** Every amount, reported balance and document total
an importer emits is signed as in §3.3: positive increases the account's
balance. Normalising a source's own convention — card statements that show
purchases as positive, a debt reported as a positive balance — is the
importer's job. A CSV profile has separate sign-inversion settings for amounts
and for its balance column.

**The credential once per sync, one run per account.** The user enters an
instance's PIN or password once per sync; the bank may still ask for a
challenge as it sees fit — a TAN at sign-in or for a single request. The instance is asked for
each linked account in turn, from that account's fetch start (§5.4), and for
each accountless kind it emits; each request is its own `import_run`. An
importer is never asked for "its accounts": which accounts a run covers is
decided outside it. A failing account or document fetch leaves the other runs
intact and independently retryable — unless the failure is the sign-in or the
bank itself (a wrong PIN, an unanswered TAN, an unreachable bank), which ends
the instance: its remaining runs fail with the same error, one failed run per
account, so each can be retried. Every row's `import_run_id` points at a run of
the right account and kind.

**A run succeeds as a whole or fails.** A failed run writes nothing: no rows,
no balance record, no coverage. Ingest writes a transaction run's rows, entries
and balance record in one database transaction, so a failure at any row leaves
nothing behind. An importer that obtained only part of what it
was asked for either fails, or succeeds with the part it delivered and a
coverage that claims no more than that part; a fetch from the new sync
position then picks up the rest.

**Ingest does not repair, skip or count a record that breaks the importer's
contract.** The run fails, writes nothing, and names the rule that was broken.
The cases: a record whose currency differs from its account's; a record of
amount zero; the same `source_id` twice in one delivery; a successful
transaction run that reports no coverage.

For each transaction record the importer delivers:

- the normalised columns — amount, currency, booking and value date,
  counterparty reference, BIC and name, end-to-end id, mandate reference,
  booking text, and `purpose`: the remittance text only, **free of format
  artefacts** (its subfields joined, markers such as `SVWZ+` stripped;
  references that have columns of their own, such as `EREF+` and `MREF+`, go
  there). This is transcription of the format and the importer defines it;
- `source_id` when the source assigns a stable one, NULL otherwise (§5.2);
- the instructed amount and currency where the source reports them (§3.8);
- `source_format` — the statement format the record came from (`mt940`,
  `camt053`, a CSV profile), kept as provenance;
- `raw` — the importer-typed payload, which **must include the original,
  unparsed source data** (the MT940 field 86 text, the camt element, a CSV
  row's cells as read). Should normalisation ever have to change, a migration
  can then re-derive the columns from it and rehash.

**Coverage.** Every successful run reports the date it covered *through* —
the last day up to which its data is believed complete. That is the best the
run knows, not a guarantee: a bank may still book into a day it has closed,
which the overlap of the next fetch catches (§5.4), and reconciliation catches
whatever the overlap misses (§5.10). Coverage is set by these rules and
nothing else:

- a fetch covers through the day before the fetch, whether or not it
  returned any rows;
- a file covers through its stated period end, else its last booking date —
  but never through the day it was exported or uploaded. A file with neither a
  stated period end nor a row has no coverage, and the run fails;
- a document run covers through the date up to which its documents are
  complete (§5.5).

A run also records where its data starts, for the import log; nothing in the
domain reads it.

**Closing balance.** Where the source reports one, the importer also delivers
the account's closing balance, which ingest writes as a reported balance
record (§3.10). It is the **booked** balance, excluding pending items, at the
end of the **last day before the fetch** — a day the bank has closed — so that
bookings still arriving for the fetch day fall after the record rather than
inside it. Its date must be consistent with the rule that the balance equals
the sum of entries booked on or before that date, and it is never after the
run's coverage (I36).

What the source states is the **figure**: a balance together with the date the
source gives it. The record is dated at the earliest of the figure's own date,
the last closed day (the day before the export date, or before the fetch; the
upload date where the file states none) and the run's coverage. Where that date
is earlier than the figure's date, the amounts of the booked, unfiltered rows
dated after it, up to the figure's date, are subtracted from the figure. An
export made during the day, which states the balance of that day, is thus dated
at the closed day, and a quiet account, whose last booking is earlier than the
closed day, reports its balance dated at its coverage. The figure is taken to be
the booked balance; a source whose figure may include pending items reports
none, as below. Where the figure comes from:

- A statement format: the closing balance of the last statement dated before
  the fetch date. Its own date is the statement's balance date — or, where the
  statement includes lines booked after that date (a bank that dates weekend
  payments forward but includes them in the balance), the latest of those
  lines, since the figure must equal the sum of the entries booked on or before
  the date it carries.
- A CSV profile: the running balance ("Saldo") column of the last row dated
  before the export date, where the profile can read one, and before the upload
  date otherwise, dated at that row's booking date. It may instead take a
  figure the file states outside its rows — a balance with its date, in a
  header or a footer.
- Where the source reports only a current balance, which may include pending
  items, the run reports none; the account reconciles against balances entered
  by hand (§5.10).

Where the format guarantees that a statement's opening balance plus its lines
equals its closing balance — MT940 and camt do — the importer checks this for
every statement before emitting anything, and a mismatch is a parse failure,
not a ledger problem. The run fails, the account's other runs are unaffected,
and a CSV export of the same period is the fallback.

### 5.2 Identity and duplicates

Every source transaction has one **identity**: its `source_id` where the
source assigns one, its **content hash** otherwise. The identity is unique per
account over all rows, duplicates included (I4): a duplicate keeps blocking it,
which is what stops the next fetch re-importing it. It is scoped to the
account, not the credential, so two credentials on a shared account produce
the same identities wherever they render a booking alike.

**`source_id` is a fact, not a decision.** The importer emits it when the
source assigns one (camt's `AcctSvcrRef`, PayPal's transaction id) and NULL
when it does not (MT940 has no stable identifier, nor does any CSV profile). It
is scoped per account: a bank reference is per account, and two credentials on
a shared account see the same one.

**The content hash is computed by ingest**, not by importers, over the
normalised columns: `amount`, `currency`, `booked_on`, `counterparty_ref`,
`purpose`, and the row's ordinal (below). The inputs are encoded with each
field tagged by name, so no combination of values in one field can reproduce
another field's input. Text inputs are canonicalised aggressively before
hashing — Unicode NFKC, casefolded, **alphanumerics only** — so whitespace,
punctuation and line-joining differences cannot move the hash at all, and an
IBAN hashes the same with or without spaces.

There are two layers here with two owners: the importer removes *format
artefacts* when it fills `purpose`; ingest removes *formatting variance* when
it hashes. There is no hash version column: the hash is a pure function of
stored columns, so changing the canonicalisation is a rehash migration, and
because `raw` keeps the unparsed original (§5.1), even a change in how the
columns are derived can be migrated.

**The ordinal** separates genuinely distinct payments that are identical in
every hashed field — two €5.00 bakery purchases on the same day, €20 sent to
a friend twice with the same purpose. It is the index of the row among rows
identical to it in every other hashed field within the same fetch. Rows with a
`source_id` need none, because the id already tells them apart.

Excluded from the hash, though stored, displayed and searchable:

- `end_to_end_id`, `mandate_ref`, `counterparty_name` and the instructed
  amount, whose
  presence and formatting in the parsed output depend on the statement format;
- `value_on`, which a bank may adjust;
- `source_format`, which is provenance.

**The content hash** is SHA-256 over these fields, each written as its name and
its value, both length-prefixed so that no value can imitate another field's
text: `amount` (integer minor units), `currency`, `booked_on` (ISO date),
`counterparty_ref` and `purpose` (both as canonical text), and `ordinal`. It is
stored as the lowercase hex of the digest.

**Canonical text** is Unicode NFKC, then case-folded, then reduced to letters
and digits: spacing, punctuation and line-joining cannot move the hash, an IBAN
hashes the same with or without spaces, and an absent value equals an empty
one. A character that is neither a letter nor a digit after NFKC — a combining
mark that does not compose, a symbol — is dropped.

**The ordinal** is the row's 0-based position among the rows of one delivery
that are equal in every other hashed field (compared as canonical text), in
delivery order. A row with a `source_id` has none.

Changing any of this changes every stored hash and needs a rehash migration
from `raw` (§5.1).

#### What ingest does with an incoming row

A record whose currency differs from its account's breaks the importer's
contract (§5.1): the run fails. Nothing is converted. For pocket providers, a balance in a new currency surfaces through
account discovery instead (§5.4).

Every other row is checked against what the account already holds, **per
account and booking day**, in two steps:

1. **By identity.** A row whose identity the account already holds —
   duplicates included — is skipped.
2. **By amount.** Each remaining incoming row is paired, one to one, with a
   remaining existing row on that day of the same amount, and inserted as its
   duplicate (§5.6).

Everything else is inserted (I32).

*Remaining* means not accounted for by identity in this delivery. An identity
match uses up the existing row it hits — and, where that row is a duplicate,
the row it duplicates — so what is left on a day has not been accounted for by
this delivery: it came from another importer or from an older rendering of
this one. An **existing row** is a source transaction that is not a duplicate,
compared by its amount whatever its split. Rows of one delivery are never
compared with each other. Where an incoming row could pair with more than one
existing row, one whose canonicalised purpose equals its own is preferred,
then the one with the lowest id; incoming rows take their pick in the order
they were delivered.

**Only imported source rows take part.** A user-authored row is never
deduplicated, and nothing is deduplicated against it: two identical coffees on
one day are two purchases, and a person's account of a movement shares neither
wording nor reliable dates with a bank's (§3.9). Its identity is a random id
the entry form generates before submitting, so a repeated submission is
skipped like a re-delivered row. Nor is a booking deduplicated, or anything
against it: its identity names its source (§5.8). Derived entries are never compared either. Ingest marks only the rows it is inserting, which have no entries
yet, so deduplication never changes or removes anything that exists.

**The core does not rank sources.** A CSV file may have been edited, another
tool's export entered by hand; how trustworthy a source is depends on the
source, and the core does not judge it. The first one in wins: an existing row
is never displaced, and an incoming duplicate stays viewable with its raw
payload.

**The amount step applies only where identity has nothing to say.** Within one
source and one rendering, identity is complete, and matching by amount there
would merge two genuine €5 purchases on the same day — which is why only
*remaining* rows take part. Where identity is silent, the amount is the best
evidence there is, and its risk is confined to the days on which two sources
overlap. The same holds for a `source_id` that changes between fetches: the
identity misses, and the amount step marks the row a duplicate.

This relies on one property of sources: **a later delivery contains every row
an earlier one delivered for the same days.** A bank's bookings for a day only
grow, so a fetch made during the day, whose last day is incomplete, is no
exception: the next delivery contains everything it did.

Ingest is serialised per account (I39), so these checks and the inserts that
follow them cannot interleave with another sync of the same account.

### 5.3 Where sources meet

The same booking can reach an account more than once:

- **through two importers** — a CSV first, then FinTS for some months, a CSV
  again to fill a gap after a holiday;
- **through one importer after a format change** — a bank that changes how it
  renders descriptions re-delivers its overlap window (§5.4) under new
  hashes;
- **through two credentials** — two users' logins to one shared account, each
  fetching it in turn from the account's sync position, whoever fetched last.

§5.2 settles both with the same rule, at import, without asking anyone. There
is no special case for either. A movement entered by hand and later imported is
not one of them: user-authored rows take no part in deduplication (§3.9).

**Accepted limitations.** The amount step needs the same booking date on both
sides. Where the dates differ — two formats that disagree on the booking
date — both rows stay, as a duplicate. Where two
genuinely different movements share a day and an amount, and the existing one is
unaccounted for, the incoming one is marked a duplicate wrongly. A gap between two
files is not detected.

**Correction.** The summary of every run lists the rows it inserted as
duplicates, each with the row it duplicates, and how many it skipped by
identity. A duplicate that slipped through is marked as one; a row marked
wrongly is cleared (§5.6). On an account whose sources
report a balance, reconciliation against it (§5.10) shows whether anything
remains. On an account whose sources report none, nothing does.

### 5.4 Credentials, accounts and sync position

An **importer instance** is a *credential*, not a set of accounts. One FinTS
login reaches several accounts; a shared checking account is reachable from
both users' logins. So the relationship is many-to-many (`account_source`),
and an account carries no importer column. An account with at least one
`account_source` row is synced (§3.3).

The link carries no primary, no enabled flag and no coverage range:

- **The credentials on a shared account are equal.** When both users sync the
  same evening, the second run skipping rows is the correct outcome.
- **An untracked account simply has no row.** Account discovery is therefore
  an explicit "refresh accounts" action in the wizard, never something that
  runs on every sync.
- **Which source covers which days** is a fact recorded per run, and
  duplicates between sources are settled row by row at import (§5.2).

Because dedup is scoped to the account and not to the credential, the shared
account works with no special case: whoever syncs second finds the same
identities and skips them. Where the two credentials render a booking
differently, the identities differ and the amount step pairs the second
delivery with the first (§5.2).

**State splits two ways**, by what it is a property of:

| State | Lives on | Why |
|---|---|---|
| `system_id`, tokens, the TAN mechanism and medium, what the importer learned about the bank | `importer_instance.state` | property of the credential |
| coverage | `import_run` | a fact about one fetch of one account, or one document fetch |

Settings hold only what the user typed — a URL, a bank code, a login. The TAN
mechanism and medium are chosen when the bank asks and remembered, so resetting
an instance returns it to asking.

**`synced_through`** is the latest *through* among the account's non-reverted
runs (§5.1): the last closed day up to which the account's data is believed
complete, whichever credential fetched it. It is the only coverage the domain
reads. It is derived, never stored:

- a reverted run's coverage stops counting, as its balance record does
  (§5.6);
- a stale run cannot roll it back, because the latest coverage wins by
  definition;
- unlinking leaves it as history, so a relinked account continues where it
  stopped.

A NULL `synced_through` means the account has never been fetched. Transfer
legs that point at it keep waiting for their partner (§5.7), and its data age
shows "never" (§3.11). Coverage is set only by the rules of §5.1, because a
position ahead of them would make the next fetch skip the days in between.

**Fetch start.** Where a fetch starts is derived when the run starts, never
stored. An account with coverage is fetched from its sync position, with the
overlap (below); a relinked account therefore continues where it stopped.
Without coverage, the fetch starts the day after the account's latest entry,
derived entries included, so that hand-kept history and the import meet
without overlapping; with no entry, at the importer's default, which the
importer defines, since banks differ in how much history they deliver. A fetch
without coverage is shown with its start prefilled, and the user may change it
for that run. This applies to importers that fetch by date — a file covers
what it covers.

**When a credential last ran** is read from its runs, for diagnostics and for
noticing a broken login. It is a different question from `synced_through`
and appears in a different place in the UI.

**Account discovery is an explicit action**, not part of a sync. After
authenticating, the importer lists what the credential can reach — for a
multi-currency provider, one entry per currency pocket (§3.8); the UI matches
those against existing accounts by `external_ref` and offers create-or-link for
the rest. Linking is how a shared account acquires its second `account_source`
row. Linking an account that holds user-authored rows — entered, or
counter-legs — shows how many it holds
and over which dates, and says that imports overlapping them are not
deduplicated against them (§5.2): an account that will be imported is best
linked before anything points at it. A pocket in a new currency appearing between discoveries surfaces as a
discovery offer, not as an error. Closed accounts are not offered.

**Always fetch with an overlap**: from `synced_through` minus seven days, but
never before the day after the account's latest user-authored row — the
history kept by hand before the account was linked, which imports are not
deduplicated against (§5.2).
Bookings appear late and banks occasionally backfill; dedup makes the overlap
free. The one place the domain needs today's date is the fetch day (§5.1) and
the entry form's and "set balance"'s defaults: it is the day in the
household's own time zone, a deployment setting. Nothing else depends on a
time zone: `booked_on` and `value_on` are calendar dates as the institution
reported them and are never converted.

### 5.5 Document importers

Documents come from importers too, and reuse the same machinery:
`importer_instance` for credentials and settings, `import_run` for the log. An
instance emitting both kinds (§5.1), such as a PayPal credential, produces
separate runs for each.

Ingest routes by the kind of the run, without loading importer code:

- `transactions` → identified and deduplicated per account (§5.2), become
  source transactions.
- `documents` → keyed on `(provider, source_id)`, belong to no account.

What a document importer delivers:

- **An order or a refund, complete as the provider shows it.** A partial
  view of an order, such as a shipping notice, is not a document. One document
  per order and one per refund, each dated on the day the provider gives it —
  an order on the day it was placed — however the provider charges it.
- **A signed total** in ledger convention: negative for an order, positive for
  a refund or credit note. Its lines are signed the same way: an order's lines
  are negative.
- **Its provider's name, the merchant's name and the line descriptions**,
  where the provider reports them. The provider maps the document to a
  clearance account (§3.3), the lines become the booking's entries (§5.8), and
  the merchant is shown as provenance; nothing resolves on it.
- **Its identity, `source_id`** — the id its source gives it, as `source_id`
  is on a transaction (§5.2): the importer's own key for this document, stable
  across deliveries so that a re-delivery finds the stored document. Unlike a
  transaction's it is never null, and no content hash stands in for it: an
  importer whose source names nothing usable synthesises one. With `provider`
  it keys the document.
- **Its reference**, where the provider names one: the order, invoice or
  booking number as a person would quote it. It is shown and searched
  (`ux/views/documents.md`), and nothing resolves on it. It is the
  **provider's**, never the importer's — a receipt fetched from a mailbox is
  *keyed* by the mail it arrived in and *referenced* by the order number the
  shop printed, and those are not the same thing.
- **Its coverage**: the date up to which its documents are known to be
  complete, in the dates of the documents it delivers, recorded as the run's
  coverage (§5.1).

The core imports every document an instance emits, whatever its provider,
subject to the instance's **start date**, chosen once when the instance is set
up and kept in its settings under the key `start_date` (an ISO date): no
document dated before it is imported.

**Re-delivery.** An importer declares how it takes a document whose
`(provider, source_id)` is already stored: `replace` updates the stored
document in place — its date, total, lines and payload — for an importer that
re-reads the same record, whose later view carries what matters:
cancellations, partial shipments; `keep` leaves the stored document as it is,
and the run counts it as kept. A document moves no money, so it needs no
immutability. Each document carries a version, which increments whenever its
content changes. A changed date, total, currency or set of lines re-derives
its booking in the same write (§5.8); a change elsewhere in the payload
changes nothing.

Consequences:

- **The documents kind has no accounts.** `synced_through` does not apply. The
  sync orchestrator therefore cannot assume every run has an account.

### 5.6 Who authors source transactions

**A source transaction comes from an importer, a user or a booking** (I1),
and its `origin` says which — `import`, `user` or `booking`. A user's row is
on an unsynced account (I40), entered through the entry form (§3.9) or
created as a counter-leg by a commit (§5.7). A booking is on a clearance
account, made by settling from a document or a transfer (§5.8); it belongs to
no run, is never edited or deleted through the entry form, never follows a
partner in a commit, is never a duplicate nor deduplicated (§5.2), and never
bounds a fetch (§5.4).

**Imported rows are immutable** (I2): they say what the bank said, and that is
what makes them a defensible record. Every import is a run, logged and
revertible as a unit; a hand-uploaded CSV is still an import, and the core
makes no claim about who produced the file (§5.2). A correction worth keeping
(a garbled purpose line, a wrong counterparty name) goes on the ledger entry's
`description` or `note`; the source keeps saying what the bank said. History
from another tool is migrated through a CSV importer with a real run.

**User-authored rows are the user's to change.** They belong to no run, so
revert never touches them, and they are edited or deleted through the form
that entered them — the panel's two exceptions are the amount it may set to
the sum of a split (below) and a user-authored single-entry leg on an unsynced
account following its partner (§5.7). The form edits
the amount, the date and the purpose; the account is fixed, and moving a row
to another account means deleting it and entering it there. An edit is an
input change: applying it fits the entries to the row (I3) — they take a new
date; the residual absorbs a new amount, or, where it would change sign or
reach zero, the split collapses into the original entry; a changed amount breaks a
same-currency pair, and a changed sign breaks any pair, whose partner is then
left behind like any other (below),
while a changed date leaves a pair standing, its partner keeping its own date —
and the edit resolves the entries afresh (§5.9), on a confirmed unit as on any
other, settling doing the rest. The form always
says so ("entries that cannot absorb the change are collapsed into one, a pair
whose amounts no longer match is broken, and the entries' values are derived
again") rather than checking first, and asks for confirmation (§6). Deleting a row
deletes its entries through the removal routine below. Where a draft's split
no longer sums to a user-authored amount, the review panel offers to set the
amount to the sum of the entries; the commit then writes both together.

**`source_transaction` has no `created_at`.** An imported row's arrival time is
`import_run.started_at`, one join away, with `ON DELETE RESTRICT` so that join
can never break; runs are never deleted, a reverted one included. When a user
entered a row is not recorded, as for every other interpretation (§3.2).

`external_document`'s `import_run_id` is nullable too, because a receipt may
one day be added by hand rather than fetched.

How ledger entries come about is §3.9.

#### Removing an entry and its consequences

Marking a row as a duplicate (below), reverting a run (below), breaking a
transfer pair (§5.9) and deleting a user-authored transaction (above) all apply one routine to whatever depended on
the entry being removed or unpaired:

- **A partner** loses its counterpart, and a counter-account its pair set
  (§5.7), and keeps its other values, a counter-leg the system created
  included. An
  unpaired transfer cannot be reviewed (§6), so it returns to review by that
  alone, and the matcher may find it a new partner.
- **A booking** whose source no longer calls for it — the counter-leg of a
  charge that is removed, or no longer a transfer to its clearance account —
  is removed with its entries and their tags by the settling that ends the
  operation (§5.8); it is not left behind as a partner, and the operation's
  preview shows it among what it removes (§6).
- **Derived entries** of every affected account are recomputed (§5.10).

#### Duplicates

A **duplicate** is a source transaction kept but interpreted as nothing: its
`duplicate_of` names the row on the same account that reports the same
movement, and it has no ledger entries; the split invariant does not apply to
it. It **keeps blocking its identity** (§5.2), because the next fetch from the
same source re-delivers the same row, and without the block it would
re-import forever. Its raw payload stays viewable.

A duplicate always points at a row that is not one: marking a row that others
point at repoints them to the row it now duplicates. Rows become duplicates in
two ways:

- **At import** (§5.2) — the routine case, and the only automatic one. Ingest
  marks only rows it is inserting, which have no entries yet.
- **By hand, from the account's statement** (its source transactions,
  `ux/views/account.md`), for a duplicate deduplication did not catch:
  *mark as duplicate of* another row on the same account, by default the
  newer of the two. The marked row's entries are deleted and the removal
  routine applies; the preview shows what each direction would remove (§6),
  so the user can mark whichever row loses less.

**Not a duplicate** is the inverse: the row gets one entry, as ingest would
create it, which settling resolves and review sees like any new entry. It
restores a row marked wrongly. Where a revert deletes a row that others
duplicate (below), the lowest-id of them stops being a duplicate the same way,
and the rest point at it instead.

Marking a row as a duplicate is the only way to remove an imported source
transaction's effect from balances; its entries cannot be deleted. A
user-authored transaction is deleted through the entry form instead (above).

#### Reverting a run

A run that should not have happened — a wrong CSV mapping, a flipped sign, the
wrong target account — is **reverted**, then re-imported correctly.

**Runs revert as a stack, per account.** A transaction run belongs to one
account (§5.1). Only the account's latest successful, non-reverted run can be
reverted (I30), whatever the later runs did; to revert an earlier run, the
user reverts the later ones first, newest first. *Latest* is the order in
which ingest wrote the runs, not the order they started: two syncs of a shared
account may fetch at once, and the one written second may have skipped the
other's rows. Failed runs wrote nothing
(§5.1) and do not count. Later runs that only skipped rows are no exception:
what they skipped may be the very rows being deleted, and their coverage and
balance record would otherwise still vouch for them.

**Document and rate runs are never reverted.** They write in place (§5.5), so
there is no earlier state to return to; a wrong rate is corrected by the next
fetch from its source, a wrong document by the next fetch of an importer that
replaces documents (§5.5).

Reverting deletes, in one transaction, the run's source transactions —
duplicates included — and their entries, applying the removal routine. Rows
of other runs that duplicate a deleted row get a new original: the one with
the lowest id stops being a duplicate (above), and the others now duplicate
it. The run's reported balance record and its coverage stop counting, and
the account's derived entries are recomputed from the records that remain
(§5.10); a revert never edits an opening itself. The run is kept, marked
`reverted`. Like every operation that removes confirmed entries, it shows them
before it runs (§6).

Immutability means a source row is never *edited*. A misparsed import is not
something the source said, so deleting it does not contradict that. Revert is
**not** a fix for duplicates: deleted rows no longer block their identities, so
the next fetch would re-import them. That is what marking a duplicate is for.

### 5.7 Transfer matching

A transfer between two synced accounts produces two source transactions, days
apart. Legs may exist unpaired — a normal state, not an error.

A leg an importer synthesises (§5.1) is an ordinary leg: pass 0 types it from
its counterparty reference and it pairs like any other. It is what lets a card
whose statements list no payments pair with the payoff on the account that
pays it.

**A counter-account must be in the currency the money arrived in.** Where a
transfer leg has an instructed amount (§3.8), its counter-account is in the
instructed currency: a withdrawal abroad delivers dollars, so it can only go to
a dollar account. Where it has none, a machine-proposed counter-account is in
the leg's own currency; a user may choose another, and enters the amount
received (below). The rule is applied by one function, used by resolution
(§5.9), the review preview and the matcher alike.

**A transfer leg's counter-account is stored on the entry**
(`counter_account_id`), keyed `counter_account` like any derived value
(§5.9). It is set from pass 0, a rule, history or the user, may be unset
while the leg awaits one, and is never the leg's own account. Once the leg is
paired it is the partner's account (I10): a pair made with a leg that had no
counter-account sets it **as part of the pair** — its key has the pair's pass
and the basis `{"from": "counterpart"}`; writing it is not a change of value that derives the
fields after it again (§5.9); and it is cleared with the pair. A
counter-account the leg had before it was paired is its own, and stays. The
pair key `counterpart` itself, on both legs, has an empty basis `{}`.

Matching considers only legs already typed `transfer` — by resolution or by
the user. Pairing never turns a flow into a transfer; it only decides which
transfer legs belong together. **Nothing in matching converts** between
currencies (I27).

#### Candidates

A leg's **candidates** are the unpaired transfer legs on another account that:

- have the opposite sign;
- are booked within the **matching window** of it, a single ledger-wide
  setting in days;
- match its amount exactly — equal and opposite in the same currency; across
  currencies, one leg's instructed amount equals the other leg's amount,
  negated (an importer that knows both sides of a conversion reports the other
  side as the instructed amount);
- and are not distinguished from it by their metadata:
  - where either leg's counter-account is known — from pass 0, a rule,
    history or the user (§5.9) — the other leg is on that account;
  - where both carry a real end-to-end id, the ids are equal (the placeholders
    `NOTPROVIDED` and `NONREF`, and an empty id, compared case-insensitively,
    count as absent).

The purpose is not a filter: banks often rewrite it on the receiving side. It
only breaks ties (below).

**An automatic pair requires a known counter-account on at least one leg**
(I33). Legs of which neither knows its counter-account are offered in review,
never paired automatically.

#### Pairing

Unpaired legs are processed in order of booking date, ties by id. Where a leg
has more than one candidate, those whose purpose equals its own after the
canonicalisation of §5.2 are preferred, if there are any. The leg is then
paired with its closest-dated remaining candidate; at equal distance in days
the one with the earlier `booked_on`, then the lower entry id. A leg with no
candidate stays unpaired.

**A pair, once made, stands.** The matcher's pairing is a standing value
(§5.9): it is not recomputed when other legs arrive, and falls only when a
leg's type or counter-account changes (I18) or a user re-pairs it. A paired
leg of an unconfirmed unit is re-derived by settling like any other (§5.9);
when its type or its own counter-account changes, the pair is released on both
legs and may be made again in the same round. Which of
several candidates a leg pairs with can therefore depend on the order in which
they arrived; the candidates share both accounts and the exact amount and are
not told apart by an end-to-end id, so the order changes only which dates sit
together, never a balance, and re-pairing (§5.9) covers it. The matcher only
ever pairs legs that are unpaired.

#### Waiting and unmatched legs

A leg that stays unpaired is in one of two states.

**Waiting** — its counter-account is synced (§3.3), and that account's
`synced_through` is NULL or has not yet reached the leg's `booked_on` plus the
matching window, so an import may still deliver the partner. A credit-card
payoff seen on the Giro on day 1 waits for its card leg in the monthly card
CSV on day 20; its destination is the leg's counter-account, from pass 0,
a rule or history (§5.9). **Waiting is a hint, not a rule**: it tells the user
that the partner has probably not been imported yet. A waiting leg shows its
destination ("→ Credit card") and its offers (below), can be edited like any
unit, cannot be confirmed until it is paired (I22), and is paired when its
partner arrives. A destination the user picks for it is kept by a commit like
any value, and as a decided counter-account it is paired without review once
its partner arrives (below). Where
the counter-account's source has stopped delivering, unlinking it makes the
account unsynced, and the leg unmatched.

**Unmatched** — everything else: the counter-account is unsynced, or has synced
past the window without delivering a partner, or the leg has no
counter-account yet. On an unsynced counter-account the user completes it with
a counter-leg. On a synced one there is none (I40): the partner is missing from
its import, which a CSV for the gap supplies (§5.10), or the leg is not the
transfer it seems.

#### Offers

Every transfer leg has **offers**, computed when read; nothing is stored for
them:

- **legs and entries on its counter-account** within the matching window,
  with the opposite sign and of any amount, its own partner aside: unpaired
  transfer legs and untyped entries first (an untyped entry only if it is its
  source's original, I31), then legs paired elsewhere, shown
  with their partner; within each group exact matches first, then by distance
  in date;
- for a leg without a counter-account, **every opposite-sign candidate in the
  window on every account the currency rule allows**, in the same groups and
  order; a pick sets the counter-account as the pair's (above), with a key of
  pass `user`;
- for a leg without a partner whose counter-account is unsynced, **a
  counter-leg**, which the commit creates (below), on an account that is open
  on the leg's date and takes the instructed currency.

An **open offer** is an offer of the first group that could still be this
leg's: an unpaired transfer leg or an untyped entry on the counter-account,
opposite in sign and within the window, of any amount — excluding an unpaired
leg whose own known counter-account is another account. Open offers decide
what the preview proposes (below).

For a partner booked later than the window allows, the picker can **widen the
window** for that one pick, by a bounded request parameter of at most 90 days
that the server checks the pick against: the preview against the window
requested, the commit against the 90-day cap, so a pick the widened preview
accepted commits. Automatic pairing keeps the window.

A pick joins the picked row to the unit being reviewed. Picking a leg paired
elsewhere breaks that pair too, so up to two former partners — the reviewed
leg's and the picked leg's — go through the removal routine (§5.6), and the
preview shows both. There is no pick of "no partner": a wrong pair is
corrected by picking the right one, once it has arrived. A swap takes one
pick when the legs it frees keep a counter-account of their own; a leg whose
counter-account its pair set loses it with the pair, so it has nothing to
pair by and needs a pick of its own. A cycle of *n* wrong pairs takes *n* − 1
picks at best.

The preview proposes an exact open offer where there is one, or else, where
the leg has no open offer at all, the counter-leg where one is offered. Open
offers of another amount are listed first but never proposed: where there are
any and none is exact, nothing is proposed, and the user picks one of them or
the counter-leg. A leg paired elsewhere is never proposed, only picked. The user may pick another. **In the preview a
proposal counts as the pick it proposes:** the pair, the resulting state and the keys are shown as if
chosen, and an explicit pick, counter-leg or re-resolve overrides it. A pick is the user's
choice and carries a key of pass `user`. An offer that is not a
candidate by the filters above is never paired automatically. Two picks have
further consequences, both previewed:

- an **untyped entry** is typed `transfer` — a savings statement often shows
  an internal transfer without the sender's IBAN;
- a **same-currency offer of a different amount** splits the difference off
  the larger leg as a new flow entry, in the same draft (§5.9) — a fee charged
  in the same booking.

#### Counter-legs

A **counter-leg** is the other side of a transfer, created for the user on an
unsynced account (I40), where no import will ever deliver it: a user-authored
source transaction and its entry on the counter-account, with the partner's
`booked_on`, paired with it. Its source has a random id, like a row from the
entry form, the partner's purpose ("GA-AUSZAHLUNG Sparkasse"), so it reads
well and teaches history, and a `raw` that records the entry it was created
for — provenance that nothing reads. **Only a commit creates one**, except on
a clearance account, where the counter-leg is a booking settling makes
(below): the panel offers it for a leg without a partner whose counter-account
is unsynced and not a clearance account, and proposes it where the leg has no
open offer (above); nothing else automatic ever creates a counter-leg, so one
the user deletes stays deleted. A leg whose
counter-account is decided therefore arrives with its counter-leg proposed and
is confirmed in one keystroke. The counter-leg's entry is
typed `transfer`, with its partner's account as its counter-account, and its
type, counter-account and pair carry the key `user` (§5.9). These keys
are standing, so resolution does not derive them again. Once created it is an
ordinary user-authored transaction — the same
as a cash withdrawal typed by hand and paired with its Giro leg. It is never
changed or deleted automatically: if its pair breaks it stays, as a transfer
leg without a partner (§5.9), and is deleted through the entry form if it was
only there to complete the pair. A withdrawal typed by hand only after settling
created the counter-leg is not compared with it: the two are separate rows,
and the hand-typed one shows as an unpaired leg. A counter-leg dated before the
counter-account's history is absorbed by its opening (§3.10), so the balance at
its anchor is unchanged; where an account kept with counter-legs later
receives an importer, its first fetch is prefilled to start after its latest
entry (§5.4).

**Its amount.** In the same currency, the negated amount of its partner (I10).
Across currencies, the partner's instructed amount, negated, where there is
one; otherwise the user types the amount received, a positive magnitude whose sign
is the opposite of the partner's, and which is refused where the amount is
already known: the counter-leg carries no estimate, because conversion happens
only in reporting (I27). A cross-currency destination without an
instructed amount only ever comes from a user's choice — machine proposals obey
the currency rule — so a user is always there to enter it. A later correction
goes through the entry form, like any user-authored amount.

**A counter-leg follows its partner.** Where a draft changes the amount of a
leg paired in the same currency with a user-authored leg that is its source's
only entry, on an unsynced account — a counter-leg, or a withdrawal typed by
hand — the commit sets that source's amount, and so its entry's, to the
negated new amount, and the pair stays equal. The preview shows it, as a
`changed` consequence of the follower. Nothing follows if the draft breaks the
pair, or if the new amount has the other sign, where the pair shows invalid,
as below. Following is not a change of the row's input (§5.9): its values stay. On an account
that has since become synced the row is left as it is, and the remedies below
apply.

**A draft that otherwise makes a same-currency pair unequal** — a split taking
a fee or interest off one leg — keeps showing the pair, marked invalid with the
difference, and the commit is refused until it is resolved (§6). The panel
offers to split the difference off the larger leg as a flow, whichever kind of
source it has, or to re-pick. Where the larger leg is user-authored and the
difference is in fact a mistyped amount, the user undoes that split and
corrects the amount through the entry form.

#### Needing an account

A leg without a counter-account is first given one in review: the picker
offers the accounts the currency rule allows, and "new account", prefilled
with the required currency (§5.9).

**A leg whose counter-account does not exist yet** — the first withdrawal on a
trip, with no cash account in that currency — stays unmatched. Nothing is
created automatically: creating an account is a user action (§5.9). The review
queue explains the leg when read — "needs an account in USD", derived from its
instructed currency — and offers the existing accounts in that currency or
"add account", prefilled with the currency. Adding the account creates
nothing else; the unit it was added from takes it as the user's choice, and
the legs that need it offer it first in the counter-account picker. Nothing
proposes it: a counter-account is proposed only from evidence (history, a
rule), the same for every currency, and the first assignment is what history
learns from. Each unit is confirmed on its own (§6).

A leg **needs an account** when it is an unpaired transfer leg with no
counter-account, has an instructed currency, and no open non-own account in
that currency exists (by the currency rule). A leg without an instructed
currency and without a counter-account does not: it stays in pending review.

#### Keys on pairs

A pair carries a `counterpart` key on both legs, written in one transaction
and cleared together. It names its maker: pass `matcher_decision` for a pair
settling made, pass `user` for one a commit wrote, a counter-leg's
included, and pass `booking` for a transfer booking's (below). All are standing (§5.9); their basis is empty (`{}`). Whether the pair needs review is
decided by the legs' other keys, chiefly where the counter-account came from:

- **Decided** — carrying a standing key (§5.9): pass 0, a rule, a user, or
  settling's own pair, on ingest or on a leg left behind by a broken pair
  (§5.6) alike — a counter-account its pair set leaves with the pair, so a leg
  left behind is decided only by what it had before. The pair is confirmed
  when it is made; a leg on an unsynced counter-account waits in review with
  its counter-leg proposed (above); one whose synced counter-account has synced
  through the window without a partner stays unmatched (above). For a leg left
  behind, the result of the operation that left it shows what settling did
  with it (§6).
- **Guessed** — by history or the model. The pair is made, but the
  counter-account's key is a proposal, so the unit is reviewed once. If the
  guess changes, the pair falls with it (I18).

**A transfer is confirmed only as a pair** (I22), and a pair is reviewed as one
unit (§6): the match is reviewed together with both legs' values. Waiting and
unmatched legs stay in the queue until they are paired, converted to a flow, or
given a different counter-account (§5.9).

ATM withdrawals are the common case of a counter-leg: history or a rule types
a withdrawal as a transfer to the cash account (§5.9), and committing it
creates the cash leg (§4).

#### Transfers to a clearance account

A leg whose type and counter-account are decided — under standing keys, from
pass 0, a rule or a commit (§5.9) — as a transfer to a clearance account
(§3.3) is the source of a **transfer booking** on that account (§5.8):
`source_id` `transfer:<entry id>`, with the leg's `booked_on` and purpose and
no counterparty name, like any counter-leg (above), and one entry, typed `transfer`, its counter-account the leg's account, paired
with the leg. The booking's type and counter-account, and the pair on both
legs, carry the standing key `booking`. Its amount is the leg's, negated;
across currencies, the leg's instructed amount, negated. A clearance account
takes a leg only in the currency the money arrived in by the leg's own report
— its instructed currency, or its own where it has none: the user's choice of
another currency, with the amount received typed, does not apply.
A leg dated on or before the clearance account's start (§3.3) is the source of
no booking: it stays an unpaired transfer leg in review, to be typed otherwise.

The booking follows its leg (§5.8): converting the leg to a flow, changing its
counter-account, or removing it — marked as a duplicate, reverted, deleted —
removes the booking; a changed date, amount or purpose, a split of the leg,
re-derives it. The
pair is therefore complete as soon as the leg is decided, and the unit is
confirmed when the leg's keys are all standing — a transfer is still
confirmed only as a pair (I22). A leg whose counter-account is only proposed,
by history or the model, has no booking until a commit decides it; the
preview shows the booking the commit leads to.

Transfers on a clearance account are bookings only. A leg pointing at a
clearance account is paired only with its booking, and an entry on a
clearance account is a transfer only as a transfer booking: neither is ever a
candidate, an offer or a pick, no pass proposes `transfer` for any other entry
there, and converting one to a transfer is refused. A clearance account has
no imported or hand-made movements to keep apart from machine-made ones — its
movements are bookings, plus the user's corrections — which is why its
counter-legs are made automatically and nowhere else.

### 5.8 Bookings

A **booking** is a source transaction that settling makes on a clearance
account (§3.3) from a source the ledger already holds. There are two sources:
a document, booked as the order or refund it describes (below), and a transfer
leg decided to the account, booked as its counter-leg (§5.7). Booking works
the same for both:

- **Origin and identity.** A booking's `origin` is `booking` (§5.6). Its
  `source_id` names its source as `<kind>:<id>` — `document:42`,
  `transfer:17` — and is unique per account (I4); a source has at most one
  booking. Nothing else links the two. Its `raw` holds only a marker: the
  source is the record.
- **Its fields are written from its source.** A booking carries a date, an
  amount, a purpose and, where its source gives one, a counterparty name —
  the source's, as stated below and in §5.7 — and no other bank field. It
  rewrites them as it follows its source. A list shows them as it shows any
  row's fields: nothing in a list is specific to a booking but its origin.
- **Made by settling, in one step.** Settling (§5) maintains every booking on
  clearance accounts: it books what a source calls for and is not yet booked,
  re-derives a booking whose source changed, and removes one whose source no
  longer calls for it. Settling twice changes nothing.
- **The start decides only where a source not yet booked goes.** A booking
  already made stays when the clearance account's start changes, whatever its
  source.
- **A booking follows its source**, confirmed or not — the one exception to
  I20. Re-deriving keeps what the source did not change: an entry whose part
  of the source is unchanged keeps its values and keys; one whose amount
  changed is updated; one whose part is gone is deleted, a consequence, with
  its tags; a new part gets a new entry; an entry whose source text changed is
  resolved afresh (§5.9). The user's decisions on what is unchanged stay; only
  what the source changed returns to review, as new data.
- **Its structure is its source's.** Its entries are not split, merged,
  reallocated, converted or re-paired in the review panel (§6); their values,
  description, note and tags are reviewed and edited like any entry's.

#### Documents as a booking source

- **Which account.** A document is booked on the clearance account that takes
  its provider in its currency (§3.3), when it is dated after that account's
  start. A booking never converts: a converted amount would never balance
  against the bank's charge, made at the bank's own rate.
- **Not booked.** A document is not booked when its total is zero — paid with
  vouchers or store credit, or refunded to store credit: nothing to clear;
  when no clearance account takes its provider in its currency ("no Amazon
  account in USD"); when the account that takes it has no balance record, and
  so no start; or when it is dated on or before the account's start. It stays
  in the documents list, marked not booked, with the first of these reasons
  that applies, derived when read (`features/documents.md` §1).
- **The mapping decides only where a document not yet booked goes.** Adding a
  provider to an account books that provider's documents dated after the
  account's start. Removing a provider or moving it to another account leaves
  existing bookings where they are, as a change of the start does (above). A document
  whose own change leaves it unbookable on its account — another currency, a
  total of zero — loses its booking.
- **The booking** is dated on the document's `occurred_on`; its amount is the
  document's total — an order negative, a refund positive — in the account's
  currency. Its counterparty name is the document's provider, and its
  purpose "Order *reference*", or "Refund *reference*" for a positive
  total; where the document has no reference, "Order" or "Refund" alone.
- **One entry per line**, in the order of the document's lines, each with
  the line's description as its source text (`source_text`, §5.9). The
  unitemised amount — the total minus the sum of the lines: a discount not
  itemised, shipping, a fee — is spread over the lines of the total's sign, in
  proportion to their amounts, rounded half-even to the minor unit. A line of
  the opposite sign — a listed coupon — stays as listed, an entry of its own.
  A line of zero gets no entry, and no entry is zero. With no line of the
  total's sign, one entry carries the total, without a source text. The exact
  arithmetic, rounding remainder included, is `features/documents.md` §2.
- **Re-deriving matches entries to lines by position**: the booking's entries
  in their order against the lines that get an entry, in theirs
  (`features/documents.md` §3). A matched entry takes its line's new amount
  and description; extra entries are deleted, extra lines get new entries.
- **Type `flow`**, under the key `booking` (§5.9). A document booking's
  entries are never transfers, and never transfer candidates or offers
  (§5.7).
- **What resolution reads** of such an entry is its account and its source
  text (§5.9): the document's merchant is displayed, never read, and its
  provider only maps it to an account. A share the spread got wrong is
  corrected by an entry on the account, through the entry form (§3.9).

**Documents can be browsed on their own**, each with its booking, or the
reason it is not booked.

### 5.9 Resolution

Ingest creates an entry with only what the source asserted. Everything else —
type, payee, category, a counter-account — is *derived*, by four passes in
descending order of authority.

**Resolution is a pure function** of an entry's inputs — its source
transaction, and its account and source text — the review draft if there is
one (§6), rules, history and the model's stored answer (pass 3, below). An
entry's **source text** (`source_text`) is the text its source gives that
entry, where the source gives each entry one — a booking gives each entry its
line's description (§5.8); it is set by whatever creates the entry from its
source, never by a user, and other entries have none. Resolution reads it
knowing nothing of where it came from. The source row is never changed. It returns values and how each was arrived at; writing them is a
separate step. Ingest, settling and the review preview all call it.

**Proposals are rederived; decided values are not** (I18, I20). A proposal
always reflects current inputs, rules and history: when a confirmation adds
history or a rule changes, the proposals it bears on are resolved again. A
**standing value** — set by pass 0, a rule, a matcher decision, a booking or a
user (below) — is decided: it is not rederived when rules or history change.
Two events reopen standing values. Automatically they reach only entries that
are not reviewed: nothing automatic changes a reviewed entry (I20), and a
reviewed entry gets new input only when a user edits its user-authored source
(§5.6) — a user's operation, which says so and asks first (§6) — or when a
booking follows its source (§5.8), the stated exception; either then reopens
the unit wherever the result is a proposal:

- **The entry's input changes.** Its input is its source row and its source
  text. A user-authored leg whose amount follows its partner (§5.7) has not
  changed its input, nor has a booking entry whose source text a
  re-derivation leaves as it was: what else a booking rewrites — amounts,
  dates, its counterparty name and purpose — is no input to its entries
  (§5.8). When it
  changes, the entry is resolved afresh: every
  value is derived again, a user's values included, because new input is
  exactly when a decision deserves a second look. The write that changes the
  input resolves the entry afresh itself, in its own transaction — an edit
  through the entry form, or the settling that re-derives a booking (§5.8);
  settling then does the rest.
- **A value changes.** Every standing value after it in field order (below) is
  derived again, the pairing last: a category rule may read the payee, and the
  matcher reads type and counter-account. A counter-account a pair set is part
  of the pair, not a value before it (§5.7), and repointing by a merge is not a
  change of value (§3.5, §3.6). A changed guess for the
  counter-account therefore undoes the pair made with it (§5.7). After a commit
  every value is standing, so nothing earlier in the order changes on its own,
  and in the review panel the same cascade is simply the draft's top-down
  resolution (§6).

On derived entries, which are complete at creation, resolution does nothing.

| Pass | Source of truth | Nature |
|---|---|---|
| 0. Own account | the household's own accounts | a **fact**: the money went to one of our accounts |
| 1. Rules | `rule` | a **declaration**: always do this |
| 2. History | previously confirmed values | an **observation**: this is what was done before |
| 3. AI model | an LLM over the entry's text | a **guess** |

#### Field order

The fields constrain each other — a category implies a flow, a booking fixes
the type, a payee applies only to flows, a counter-account only to
transfers — so they are resolved in a
fixed order, and no pass proposes a value that contradicts a field already
decided:

1. **Type**, by the first pass to decide it. A booking decides it first, under
   the key `booking`: `flow` for a document booking's entries, `transfer` for
   a transfer booking's (§5.8); no pass proposes over it, and none proposes
   `transfer` for another entry on a clearance account (§5.7). Otherwise: pass 0 decides `transfer`; rules
   decide `transfer` when a counter-account rule matches and `flow` when
   otherwise a payee rule, or a category rule that has no payee condition,
   matches — counter-account rules come first (Pass 1, below); a category
   rule that has a payee condition cannot be judged before the payee is, so it
   never decides the type, and applies in the category field only; history proposes the type a strict
   majority of its matches share; the model decides `flow` when it proposes a
   category. A pass
   that proposes a payee or a category thereby proposes `flow`, one that
   proposes a counter-account `transfer`. The type carries its own key: the pass
   that decided it, with the same basis as the value it came with.
2. **Then the fields the type allows:**
   - for a transfer, the **counter-account**, from pass 0, rules or history,
     filtered by the currency rule (§5.7);
   - for a flow, the **payee**, then the **category**, each by rules, then
     history, then the model. The payee comes first because category rules and
     history may key on it.

**A field holds a value, and empty is a value too.** A standing key fixes the
value it carries, whatever it is, empty included: rederiving keeps it, and no
pass proposes over it (I18, I20). Whether a field may be empty is the field's
own rule. A flow's payee is optional (§3.6) and may be decided empty; a type,
a flow's category and a transfer's counter-account may not, because without
them an entry is not complete (§3.4) — clearing one removes its value and
its key, whatever set them, and the passes propose again. There is no deciding
"no category": a flow without a category is unclassified (§3.4, §6).

An empty field with no key is **undecided**: nothing is decided, and either
no pass found anything or a pass's result was empty, which stores nothing
(below). A value decided
empty is a decision like any other: it does not make a unit unconfirmed,
picking a value or re-resolving replaces it, and a type the field does not
belong to drops it with its key (I9).

A field fixed by the review draft (§6) is taken as decided, and the fields
after it are resolved around it.

**Rederiving an unconfirmed entry** walks the fields in this order. A field
with a standing key is kept and joins the fixed set the later fields are
resolved around; a field with a proposal key, or no key, is resolved afresh.
When a field's value changes, the later fields that are standing are derived
again (I18). A paired leg is walked like any other: when its type or its own
counter-account changes, the pair is released on both legs and may be made again
in the same round (§5.7). Settling writes only the differences, so a second
settle writes nothing.

For each field, the first pass to produce a result wins; on a field that may
be empty, empty is a result too (above). A pass without the evidence it
requires produces nothing, and the next pass is tried. An empty result stores
no key: a field that may be empty needs no review when it is empty, so it
never keeps a unit unconfirmed — a stored proposal would hold back units whose
category a rule already decided. Pass 0 and
rules are certain when they match, history needs a majority (below) and on the
category gives way to the model unless its votes are unanimous, and the model
always answers as a guess. Whatever wins carries its basis, shown in
review (§6). What pass 0 and rules decide is **standing**: a fact or a
declaration needs no review (below). What history and the model propose is
confirmed only by a human. **A single unanimous precedent is a majority**: the
first confirmation of a new counterparty is enough for the next one to arrive
with a proposal, shown as 1 of 1.

#### Pass 0 — own account

Where an entry's `counterparty_ref` equals the `external_ref` of one of the
household's accounts, both canonicalised as in §5.2, the entry is a `transfer`
to that account. The entry's own account is excluded, as is an account that
would break the currency rule (§5.7). Closing is not: the match is a fact, and the payout of a closed
account's remaining balance is still a transfer from it (§3.3). The pass
writes keys like any other, and they are standing; their basis is
`{"account_id": n}`, the account matched. Changing an account's
`external_ref` therefore changes no standing value, like changing a rule
(below): only an entry resolved after it — a new one, or a field not yet
decided — sees the new reference.

Where the counterparty IBAN is not known — a card issuer's collection account
seen on the Giro — pass 0 cannot apply. History recognises such a transfer
after the first, and a rule declares it (below). One collection account may
charge several cards, which only their mandate references tell apart.

#### Pass 1 — rules

Hand-written. A rule is a standing declaration: "always book this payee to that
category, whatever was done last time", or "this collection is the payoff of
that card". Its values need no review, so a rule is how a recurring entry —
rent, salary, a subscription, a card payoff, a cash withdrawal — leaves the
queue for good. Because rules confirm the units they decide completely, a rule
is shown before it is saved with the entries it would match and the units it
would confirm (the preview, below). A rule is applied when an entry is resolved — to a new entry,
and to the fields of an unconfirmed one that neither a human nor a standing
value has decided — and what it set stays as it was set (above).

**A rule has a name**, trimmed, not blank and unique case-insensitively, as
for tags and payees: the name is how evidence explains the rule ("rule: Rent")
and how a user finds it again. A rule has no enabled flag and no version:
deleting it is the off switch, and the last write wins, since a rule write
changes no entry.

**What a rule sets:** a payee, a category, or a counter-account, which makes
the entry a transfer. What it sets is fixed at creation, like a category's
kind, so that a key's rule keeps its meaning; its target value, conditions,
priority and name can be edited. A counter-account rule obeys the currency rule (§5.7):
where its account is in the wrong currency for the entry — a withdrawal abroad
against a rule for the euro wallet — it does not match, and the next rule or
pass is tried. Nor does it match where its account is not open on the booking
date (§3.3), so a closed wallet stops receiving withdrawals.

**What a rule matches:** a list of conditions, all of which must hold (an
implicit AND). A condition is `{field, op, value}`. The fields are
`counterparty_name`, `counterparty_ref`, `purpose`, `booking_text` and
`mandate_ref`, which take the operators `equals`, `starts_with`, `contains`
and `regex`; `source_text`, which takes the same operators and fails on an
entry without a source text (above); and `account` and `payee`, which take
`is` only. The same field may appear in
several conditions, and a condition on a field the entry lacks fails. At least
one condition is required, and a blank value is refused. A
`regex` is at most 200 characters and must compile (case-insensitive, `search`
on the raw value); it is refused otherwise, on any field. Validation names the
field and never quotes the value.

**The payee condition** is `{"field":"payee","op":"is","value":"<payee id>"}`,
the id as a digit string; several may appear, and only a category rule may
carry them. It is judged on the payee resolved so far in the same resolution, a
proposed one included (field order, above). Core checks at write time that the
payee exists; a rule whose payee has since been deleted stays and never matches
(§3.6). **The account condition** is
`{"field":"account","op":"is","value":"<account id>"}`, judged on the entry's
own account; any rule may carry it. Core checks at write time that the
account exists, and a rule whose account has since been deleted stays and
never matches, like one whose payee was. Rules are stored as a list of such objects;
the format leaves room for grouping and negation later without a schema change.

Values are compared per plugin: rules compare `counterparty_ref` and
`mandate_ref` as canonical text on both sides (§5.2: spaces, case and
punctuation ignored, so an IBAN prefix works), and `counterparty_name`,
`purpose`, `booking_text` and `source_text` with the
rules plugin's name normalisation (NFKC,
casefolded, whitespace collapsed, trimmed, punctuation kept); history key 2
compares canonical text (§5.2).

**Rule order.** Rules are one kind of thing, told apart by what they set, and
are evaluated by it: counter-account rules first, then payee rules, then
category rules. Within each, the lower priority number comes first and the
rule id breaks a tie, so that resolution stays deterministic. A matching
counter-account rule therefore makes the entry a transfer whatever payee or
category rules would also match, and a category rule may read the payee a
payee rule set. The preview of a rule shows where another rule takes
precedence over it — a counter-account rule matching the same entries as a
payee rule, say. Text
conditions matter mainly for card payments, where the merchant is buried in
the descriptor — counterparty name starts with 'PAYPAL *' is the typical case.

**Saving, changing or deleting a rule** changes no standing value (I20); the
proposals of unconfirmed entries follow it, as they follow any change (above).
A rule is applied at a point in time: a standing key records the rule a value
came from, which may since have changed or been deleted. The preview lists two
sets of entries: those the rule matches that hold a different value, and those
carrying its standing key that it no longer matches — all of them, for a
deletion. The first list holds only entries whose value the settle that
follows will leave as it is — confirmed entries, and values under a standing
key; an entry holding a mere proposal is rederived by that settle and is not
listed. Every unit in either list opens in the review panel, to be
corrected there one unit at a time. Nothing is changed in bulk. Re-resolving a unit in the review panel
shows what the rules propose now.

**The preview of a rule write** (create, change or delete) shows: (a) the
entries the rule matches, each with the earlier rule that takes precedence
over it, if any; (b) the units it would confirm, computed per entry — the
value is complete and every key is standing — and refined by unit closure
once units are added; (c) the two lists above, exactly as described.

A preview row is an entry with its source (architecture §4.1): its own fields
— booked date, account, amount, the current value and key of what the rule
sets — and its source fields. The client shows the source fields that the
rule's conditions read, always the counterparty, under their own headers. Rows
open the review panel once units exist.

**Nothing writes rules automatically.** A correction is not a rule; it is a
confirmed value, and confirmed values are already the input to pass 2. A rule
is written in the rule editor, which starts from an example: an entry the user
picks there with a find box, or one the editor is opened with, as the review
panel does. The editor shows the example's fields beside the conditions in two groups,
from the source transaction and from the entry (account, payee, source text);
nothing is ticked or prefilled, and the user writes the conditions with the
example in view.

#### Pass 2 — history

Reads past entries joined to their source transactions, so every source field
of every past case is available. **Booking entries take no part in history**
(§5.8): they neither vote nor are asked. A document booking's entries share
one source row, whose fields describe none of them, and item titles rarely
repeat; a transfer booking follows its leg, whose own decision is the vote.
Rules and the model classify booking entries. History keys on source
signals, raw on both sides. **It learns only from confirmed entries with
a source transaction** (I19) — confirmed by a human, or standing — because no
other entry carries the source signals it keys on. A user-authored row brings
only its purpose among the bank's fields, so no key on source fields applies
to it; key 3 does once its payee is decided — which is what lets a typed
"coffee at Starbucks" find its category the next time its payee is picked. A value still awaiting review never
teaches, so one wrong guess cannot become history that the next similar
transaction repeats with more weight. **Each ledger entry is one vote**; the
entries of a split source transaction vote separately. When the review panel
re-resolves a unit (§6), that unit's own entries are left out of history, or it would mostly propose what it already has.

History keys on **source signals**, not on the payee. The payee is one of its
outputs. Keys, most specific first:

1. exact `counterparty_ref`, refined by `mandate_ref` where the entry has
   one: past entries with a different mandate reference are left out, those
   without one still count. One creditor collecting several contracts keeps
   their evidence apart, and history from a format that carries no mandate is
   not lost;
2. normalised `counterparty_name` (canonicalised as in §5.2), refined by
   `booking_text`;
3. `payee_id`, where one has resolved — for the category only, since the type
   and counter-account are resolved before the payee; it pools evidence across
   a curated merchant's varying descriptors.

**Every key is refined by the purpose.** A key's matches whose purpose
resembles the entry's are counted first, and all its matches only where those
give no majority: what one counterparty is paid for is often in the purpose —
rent and a shared pizza sent to the same friend, the merchant behind a payment
intermediary's direct debit. History never compares an entry with entries it
shares no key with: wording alone — the bank's "Kartenzahlung girocard" on two
unrelated card payments — is no evidence.

The booking text is never a key on its own: a bank's booking texts are
categories of payment ("Lastschrift", "Dauerauftrag"), shared by unrelated
counterparties, and a majority among them proposes for one counterparty what
others were. It only refines key 2.

For each key — its similar-purpose matches first, then all of them — it counts
the matches within a lookback period and proposes the value a strict majority
of them share; the basis records how many agree, of how many, and since when
— "3 of 4 since March". A set of matches without a majority proposes nothing,
and the next is tried. A
majority for empty, on a field that may be empty such as the payee, is a
result like any other (field order): the field stays empty, with no key, and
neither a later key nor a later pass is tried. The length of the lookback period
is a tuning parameter of the history pass, not a rule of the ledger.

**On the category, history proposes over the model only when its votes are
unanimous.** Where the matches that produced the majority disagree — 3 of 5 —
the counterparty is mixed, and the entry's own text may tell this case apart:
the proposal gives way to the model (pass 3), which is asked with the
categories history saw. Until the model's answer is stored, and where there is
no model at all, history proposes as before, so a deployment without one keeps
history's majority. A single precedent is unanimous. The type, payee and
counter-account have no such reviewer — the model proposes none of them — and
keep the strict majority.

**Hard constraints filter history's evidence; they never transform its
result.** For a counter-account, history considers only past cases whose
counter-account satisfies the currency rule (§5.7) — for a dollar withdrawal,
only past withdrawals that went to a dollar account — and proposes the value a
strict majority of those share. Accounts not open on the booking date (§3.3)
are filtered out the same way, so a replaced wallet stops being proposed. With
no compatible evidence it
proposes no counter-account; a `transfer` type stands on its own evidence,
which is not filtered. A past leg contributes counter-account evidence only
once it is paired. So the first trip to the US yields "transfer, account
needed", and every later one proposes the dollar cash account, with no special
logic in either case (§4).

This is what handles recurring merchants and recurring transfers after one
classification each. An ATM operator is recognised by key 2 once one of its
withdrawals is confirmed — which also separates the bank's own withdrawals
from its fees; an operator seen for the first time is left to the model, which
may propose it, and otherwise to the user, or to a rule. A payment
intermediary collecting for many merchants under one IBAN — PayPal's direct
debits — is one counterparty to key 1: its payee follows from the IBAN, and
its category from the purpose, which names the merchant; where the purpose
does not tell, the votes disagree and the model decides. PayPal's card
descriptors (`PAYPAL *SPOTIFY`) differ per merchant and are learnt one by one
by key 2; a rule on the name's prefix gives them all the PayPal payee (pass
1).

#### Pass 3 — AI model

Runs for the category whenever passes 0 to 2 produce none, and where history's
proposal is not unanimous (pass 2), whether or not the counterparty has been
seen before — mixed history is often exactly where the purpose text tells
cases apart. Its answer then replaces history's proposal, a "no category fits"
included. It is not asked for a payee.
It answers what kind of
spending an entry is: it exists because no rule and no history can know that
`AUCAT BAR CUBELLES N BA` is a Catalan motorway toll, knowledge that matters
precisely when travelling, which is when unfamiliar counterparties cluster.

Constraints on pass 3:

- **It selects, it never creates.** A proposal must reference an existing
  category. Creating entities is a separate flow (below), never part
  of deriving.
- **Never auto-confirmed.** Its output is always shown as a guess, with the
  model's rationale, one short line, and lands in the review queue.
- **Asked once per input while its answer stands.** The model is slow and
  may be costly: its answer is the `llm` key of the field it answers, kept
  with a fingerprint of the payload it was given, and reused whenever the
  entry is resolved again with the same payload. It gives way to a pass of
  higher authority — to history only where history's votes are unanimous — or
  a user's value, and the answer goes with the key it
  replaces: the core keeps nothing else of it. It is asked anew when the
  payload changes — a booking entry's source text, say — or when the field
  falls to pass 3 again.
  Settling never waits for it: an answer is stored when it arrives, and that
  write settles like any other.
- **Asked in the background.** An entry whose category falls to the model
  waits on a list in memory for one worker, which asks the model one at a time
  and stores each answer as it arrives. While an entry is on that list
  the review queue and the panel say the model is still looking at it; this
  is not a review flag, and nothing of it is stored. When the model is
  unreachable the list empties and its entries keep what the earlier passes
  proposed, as with no model — history's proposal where it gave way, otherwise
  nothing; they are asked when it answers again.
- **Limited payload.** The counterparty name, booking text and purpose, and
  for an entry with a source text, its source text and its account's name;
  and where history counted votes for the category, the categories they
  hold — at most three, the most frequent, given by path in path order,
  without counts and without the text of past entries. These are the
  household's own category names, already in the list the model chooses
  from. Never the counterparty IBAN, BIC, end-to-end id
  or other reference fields, and never amounts, dates or balances, nor an
  account but the one an entry with a source text is on.
  Where the payload would be empty, the pass does not run. Limited is not
  anonymous: counterparty names and purpose lines include **private persons'
  names** and other personal details (a SEPA transfer to a friend, a note on
  it), so a hosted endpoint receives third-party personal data. This is stated
  plainly wherever the endpoint is configured.
- **The model is external and configurable per deployment.** Which model
  answers, and where it runs, is a deployment choice rather than a property of
  the software; an on-premise model is the expected configuration. Absent
  configuration, pass 3 does not run at all and entries fall through to the
  queue unclassified, which remains a fully usable state.

**Creating a category, payee or account is a user action, not a
derivation.** When nothing existing fits, the review UI may offer to create
one — and may use the AI model to suggest a name for a category or payee —
but the entity comes into existence only on explicit confirmation, and is then
applied like any other manual classification. No pass, matcher, settling or
import ever adds a row to the dimension tables or accounts (I17). Creating an
account from the queue creates nothing else; the transfer legs that need it
then offer it first (§5.7).

Each pass feeds the one above it without any explicit write: a confirmed model
proposal becomes a confirmed value, which is history, which pass 2 finds next
time. The system ratchets toward determinism as it is used.

**Results are stored on the entry.** Reviewed entries never change, so reports
over reviewed periods do not reshuffle as rules and history evolve; the
proposals of unconfirmed entries may.

#### Derivation: how a value was arrived at

Every derived value records its basis in one column, `ledger_entry.derivation`,
keyed by the field it explains: `type`, `payee`, `category`,
`counter_account`, `counterpart`. The second withdrawal
in §4 shows a history-derived transfer. A card purchase:

```json
{ "payee":    {"pass": "rule", "basis": {"rule_id": 47}},
  "category": {"pass": "llm",
               "basis": {"model": "…", "rationale": "…"}} }
```

**Every derived value carries a key.** A key of pass `history` or `llm` is a
**proposal**: it stays until a user confirms the value. All other keys are
**standing**, and a standing value is decided:

- `own_account` and `rule` — what pass 0 or a rule produced;
- `matcher_decision` — a pair settling made (§5.7);
- `booking` — what a booking sets: its entries' type, a transfer booking's
  counter-account, and its pair, on both legs (§5.7, §5.8); its basis is
  empty (`{}`);
- `user` — what a user decided in a commit.

A proposal may also explain an absence: the field stays empty and its key says why (`"none": true`). The model's is the one so far: when it finds no category that fits, its key carries its rationale, which says what would fit. It stays while its classifier proposes it, like any proposal, and the model is not asked again for the same payload.

In review a `rule` key reads "rule: its name", linking to the rule; a key
whose rule has since been deleted (its basis holds only `rule_id`) reads
"rule deleted".

A **commit** keeps every standing key whose value it leaves unchanged. A
proposal the user accepts unchanged becomes `user`, with the proposal's key as
its basis — a snapshot of the evidence it was accepted on, shown as "confirmed
by you, proposed by history (3 of 4)". The basis is nested under the `user`
key — `{"pass": "user", "basis": {"pass": "history", "basis": {…}}}` — and a
commit derives every key itself from the values it is sent: a value equal to a
shown proposal becomes `user` with the proposal's key as its basis, a `user`
value left unchanged stays, anything else is `user` without a basis. The client
may name a basis only of pass `history` or `llm`; it is
stored wrapped under `user` and never trusted as evidence, and a client can
never assert `rule`, `own_account` or any other standing key. A value the user
sets or picks by hand becomes `user` without a basis, empty included where the
field may be empty (field order); an empty field that may not be empty carries
no key. A counter-account a pair fills is the pair's,
with the basis `{"from": "counterpart"}` (§5.7). A `user` key left unchanged by a later commit
stays as it is, so one never wraps another. An entry without a `user` key is
one no commit has decided: a unit confirmed by pass 0, rules, matcher
decisions and bookings alone. A commit decides every value the user saw.

Which values get a key is a deliberate rule, because the keys that are not
standing *are*, with completeness and pairing, the review state (§6):
**every value a pass, the matcher, a booking or a commit sets carries a key**, so every
value shows its basis. A unit whose keys are all standing is confirmed as soon
as it meets every requirement of confirming
(§6), and history learns from it as from any confirmed unit. That is not batch
confirmation: what a human decided is the rule, written once with its matches
in view. History and the model never confirm.

Consequences:

- **Review state is not stored separately.** Whether a unit is reviewed is
  read from its entries' keys, completeness and pairing (§6).
- **A pairing's key is written to both legs.** Pairing is a claim about a
  relationship, not a field of one entry. Both copies are written in one
  transaction and cleared together.
- **`derivation` is not provenance and not an audit record.**
  `source_transaction.raw` records what the source said — immutable forever
  for an imported row; `derivation` records how the system interpreted it, one key per
  derived value, and after review holds only standing keys. It records who
  decided a value — a pass, the matcher or a user — not when, nor which user.

#### What a user may change

Every field of a ledger entry falls into one of four groups:

| Group | Fields | Editable |
|---|---|---|
| **Copied** from its source transaction or account | `account_id`, `currency`, `booked_on`, `value_on`, `source_text`; the amounts, as a sum (I3) | Never — an amount only by a split; a user-authored source through the entry form or set to the sum of its entries by a commit (§5.6), a user-authored single-entry leg on an unsynced account following its partner (§5.7), or a booking following its source (§5.8) |
| **Derived by a pass** — carrying a key wherever they hold a value (below) | `type`, `payee_id`, `category_id`, `counter_account_id`, `counterpart_entry_id` | In the review panel |
| **Derived from other rows** | the amount of a derived entry | Never directly — change the record |
| **Authored** by a human | `description`, `note`, tags, the split allocation — a booking's excepted (§5.8) | In the review panel, tags too; tags also directly outside it |

**Every change to an entry's interpretation is a commit of its unit** (§6),
with two exceptions that work on many units at once: merging a payee (§3.6)
and merging a category (§3.5). Each is previewed, runs in one transaction,
and repoints values with their keys, deciding nothing anew. The user edits
in the review panel — values, split, a transfer's destination or partner —
sees the consequences previewed, and commits the whole state at
once. The same panel edits confirmed units, which stay confirmed. Tags are
part of the panel's draft and also stay editable directly everywhere else.

This yields a useful way to state the split invariant to users: **an amount
cannot be changed, only divided.** The total is what the bank said; what is
editable is its allocation across entries. It also means an entry can never
drift away from its source, which is what keeps reconciliation against
reported balances (§5.10) meaningful indefinitely.

What the panel offers, each previewed before the commit:

- **Converting to a transfer.** A transfer needs a counter-account, which the
  user supplies, and has no payee or category. The preview then applies §5.7 to
  the unit: pair with a candidate where there is one; on a clearance account,
  its booking; otherwise, on an
  unsynced counter-account, a counter-leg, which the commit creates; on a
  synced one the leg is committed with its destination and waits, and is
  paired when its partner is imported (§5.7). The picker offers accounts satisfying the currency
  rule, and "new account", prefilled with the required currency. Converting is
  refused where another entry of the same source transaction is already a
  transfer (I31), and for an entry on a clearance account (§5.7).

  How much the user supplies is a ladder, not a fixed prompt. A resolvable
  `counterparty_ref` is already pass 0; a counterparty converted before is
  preselected by pass 2 — and from the second withdrawal at a given ATM
  operator onward the entry usually arrives already typed as a transfer. The
  full picker is a once-per-counterparty event.
- **Re-pairing.** A different partner for a leg, from its offers (§5.7),
  which include legs paired elsewhere; picking one breaks that pair too.
- **Converting a transfer to a flow**, with a category.
- **Changing the counter-account** of a transfer leg. Its old pair breaks
  (below); the leg is paired with a candidate on the new account, given a
  counter-leg where that account is unsynced, or waits for its partner.
- **Splitting, merging and reallocating.** The original entry stays as the
  **residual**: it keeps its id, type and tags, and absorbs the remainder, so
  the invariant holds throughout the edit. A new entry copies account,
  currency and dates from the source and inherits the original's tags and
  description; the tags are editable in the draft like any entry's. A new entry is always a flow: a source transaction has at most
  one transfer entry (I31). Removing an entry returns its amount to the
  residual. The residual is never zero: an allocation that would leave it
  zero is refused in the preview, because an entry has a non-zero amount. Splitting a paired leg can leave a same-currency pair unequal; the
  preview shows it invalid and offers the remedies of §5.7.
- **Clearing a value.** Clearing a field that may be empty, such as the payee,
  makes it empty, whatever value it showed, a proposal included, and the commit
  decides it so. Clearing a field that may not be empty — type, category,
  counter-account — removes its value and its key, whatever set them, and the
  passes propose again; it changes something only where the passes would now
  propose otherwise, as for a value the user decided (§5.9, field order).
- **Re-resolving** a unit: a preview of what resolution proposes now, to keep
  or adjust — for values a human decided, what the passes would say instead.
- **Creating a rule from a change.** Where the draft changes a value a rule
  set, the panel offers to create a rule from the transaction (§5.9, rule
  editor). Only values a rule set earn
  the offer: there the rule is what keeps coming back.

**Breaking a pair.** Re-pairing, converting to a flow and changing the
counter-account can each leave a former partner behind, and re-pairing with a
leg paired elsewhere leaves two. The leg the user acted on takes the state the
user chose; a leg left behind goes through the removal routine of §5.6 and
returns to review as a transfer without a partner, a counter-leg the system
created included, losing a counter-account its pair set (§5.7). Where it can
be paired, settling pairs it as on ingest (§5.7), and the operation's result
shows it; on an unsynced counter-account it waits with its counter-leg
proposed. The preview shows this before the commit.

There is no operation that rejects a value without saying what is right
instead: each of the above leaves a state the matcher and resolution will not
undo.

`source_transaction_id` is the one field that is structurally fixed. An
entry's provenance is what it *is*; repointing it would break the split
invariant and detach the entry from its own history. Nor can an imported
entry be deleted. To remove a source transaction's effect from balances and
reports, mark it as a duplicate (§5.6).

#### Reviewed entries are left alone

No automatic process changes a reviewed entry (I20): not resolution, not the
matcher, and not ingest, which marks as duplicates only the rows it is
inserting (§5.2). The one exception is a booking, which follows its source
confirmed or not (§5.8). Derived entries are recomputed from their records,
but they are never reviewed (§3.9).

A user's operation may change any interpretation, and may return the entries
it affects to review: a partner left behind when a pair is broken, marked as a
duplicate or reverted (§5.6). A merge returns nothing to review (§3.5,
§3.6). What it removes
or returns is shown before it runs (§6).

### 5.10 Balance records: reconciliation and the opening

Balance records are defined in §3.10. This section is how the pipeline writes
them and what follows from them.

**Reported records** are written by ingest for the account of each
transaction run whose importer delivered a closing balance (§5.1). **Manual
records** are written by the "set balance" action on any account, as the
balance at the end of a date the user chooses, defaulting to today; the
action's help text says that the record counts everything dated on that day.

**Derived entries are recomputed, never adjusted.** An account's derived
entries are recomputed by the rules of §3.10 whenever its entries or records
change — an import, marking or clearing a duplicate, a revert, a commit,
entering, editing or deleting a user-authored transaction, a
created, edited or deleted record, among others — as part of settling (§5). A
derived entry whose result is zero is deleted; one whose result becomes
non-zero is created. Derived entries are never resolved and never reviewed:
each is a consequence of a record.

The consequences of deriving the opening from the anchor:

- **Backfill.** Importing older history adds entries before the opening; the
  opening moves earlier and changes by exactly what was added, so the balance
  at the anchor date is preserved. With FinTS starting on 1 April and an
  opening of +5 000 on 31 March, a backfill of January to March netting −300
  gives an opening of +5 300 on 31 December. A backfill that reports its own
  balance becomes the new anchor, being earlier, and the old anchor's
  derived entry then shows whether the backfill is complete.
- **The anchor explains nothing.** The opening absorbs whatever precedes it, so
  the history up to the first record is never reconciled. Reconciliation
  starts with the next record; agreement on day one is not evidence that the
  importer is correct.
- **Revert** never edits an opening. The reverted run's record stops counting,
  and the opening is recomputed from the records that remain (§5.6).

#### Reconciling against reported balances

A reported record is the cheapest guard in the system, and the only one that
catches *false sameness* — a genuine transaction wrongly marked as a
duplicate (§5.3). Its scope is the account, not the run: every ledger entry on
the account in the record's interval is summed, not only the rows a run wrote.

**Reconciliations are summed from the first reported record on.** The sum
runs over the reconciliations of every record from the account's first
reported record through its latest, in record order, manual records included.
Derived entries telescope, so a manual record between two reported ones
cancels in the sum whatever its error, and the sum measures how far the latest
reported balance and the ledger disagree. A booking the bank dated back into a
day it had already closed leaves a pair of opposite reconciliations on
consecutive records, which cancels in the sum; a missing or duplicated row
leaves a reconciliation that later records do not cancel. A non-zero sum is
the account's **unexplained difference** (§3.11), and the
summary of the run that caused or changed it says so. It is a notice, never a
prompt and never a review item. The entries themselves are reconciliations, on
their own report line (§8).

A difference is localised to the reported records since the running sum was
last zero — with regular syncs, a few days (§1.3). The remedies are to import
what is missing (a CSV for the gap, deduplicated against what exists, §5.2), to
mark what is duplicated or clear a row marked wrongly (§5.6), to delete a
user-authored transaction an import now duplicates (§3.9), or to correct or delete a manual
record whose number was wrong. Once the cause is fixed, the
reconciliation recomputes to zero and disappears.

**A manual anchor meets its first reported balance.** An account that began
with a manual record — a CSV profile without a balance column, a balance set
before linking, an account kept by hand — later gains a source that reports
balances. The manual record stays the anchor, and the first reported record
reconciles against it. A non-zero reconciliation says one of two things: the
user's number was wrong, or the history since is incomplete or duplicated.
Fixing the rows resolves the second — importing what is missing, marking
duplicates, or deleting user-authored transactions an import now duplicates; correcting or
deleting the manual record resolves the first.

#### Hand-kept accounts and the history before a record

On an account without a source that reports balances, every manual record
after the anchor owns its derived entry (§3.10). The user corrects a count or
a valuation by editing or deleting the record, never the entry.

Where an entry on any account is dated before its earliest record — a forgotten
receipt, a backfill, counter-legs from a backfilled checking account (§4) — the
opening absorbs it, and the balance from the anchor on is unaffected. Where
that leaves the history before the anchor implausible, as a negative wallet, a
starting balance recorded before the earliest entry becomes the new anchor.
That is for hand-kept accounts: on an account whose sources report balances,
the reported anchor is already exact, and an estimated earlier one would leave
a lasting unexplained difference. An account that holds entries but no record
at all shows *balance not anchored* (§3.11), offering to add one: its balance
then starts from zero.

### 5.11 Starting a sync

A credential is personal even though the ledger is shared: one user cannot
enter another's PIN. `importer_instance.owner_id` and `access` record **who
may authenticate an instance**, and with it who may manage it: run it, refresh
its accounts, link and unlink accounts, change its settings, reset, disable or
delete it. They restrict nothing else — every source transaction it produces
lands in the one shared ledger regardless of who ran it.

| `access` | Meaning |
|---|---|
| `owner` | only `owner_id` may run it — a personal bank login |
| `shared` | either user may run it — e.g. a minor child's account both parents manage |

An instance that holds no credential at all — a CSV profile, a public rate
source — is always `shared`: either user may upload to it or run it. `shared`
is otherwise always a stated decision, never an unset column.

**"Sync everything" means every instance the current user can authenticate**:
the ones they own plus the shared ones, except instances a user has disabled.
Instances owned by the other user are listed, read-only, with whose they are
and their last run, so a connection that has not run in nine days is apparent
to both.

**A sync is a foreground sequence, not a background job.** Most instances
require a PIN and a TAN, so instances run one after another, each asking for
its input in turn. It must be abandonable at any point: stopping it writes
nothing more — a fetch under way when it stops is not written, the instance
under way leaves its remaining runs failed as abandoned, to retry, and the
instances not yet reached are left alone. Every run is independent — one bank
failing leaves failed runs to retry and does not stop the others. Nothing in a
sync waits for a decision about data: duplicates are settled at import (§5.2).

A user has one sync at a time, and an instance runs in one sync at a time:
starting a second is refused, and "sync everything" leaves out an instance
that another sync is running.

Needing input is not a declared property of the importer: an expired token
makes an otherwise unattended instance interactive for one run. Every instance
therefore runs in its turn and asks for what it needs.

**Every sync ends by settling** (§5), not at some point when all of the
household's importers have run — there is no such point. A transfer between
two accounts cannot pair until both sides have been imported, and the two
users sync hours apart, so it is the later sync that completes the pair.
Because settling is idempotent, running it after every write costs nothing and
requires no coordination.

---

## 6. Review workflow

Review is **not** tied to an importer. Several importers may need to run before
review makes sense, and a transfer's partner may arrive days after its leg.

**Review is per unit.** A **unit** is a set of entries reviewed together: the
entries of a source transaction and the two legs of a transfer pair, joined
transitively — a split whose residual is a paired leg forms one unit with its
partner. A unit is
**reviewed** when it meets every requirement of confirming (below) and its
entries carry no derivation keys other than standing ones (§5.9); the whole
unit is confirmed together. A leg whose partner still carries keys that are not
standing is therefore unreviewed even if it has none itself: the match is
reviewed together with the partner. *Reviewed* and *confirmed*, like
*unreviewed* and *unconfirmed*, are synonyms throughout this document; the
state belongs to the unit, and an entry has the state of its unit.

**Review is one atomic action.** The review panel holds a **draft** — the
user's choices for the unit, laid over its stored state:

- a transfer's partner or destination (§5.7);
- splits of any source transaction in the unit (§5.9), the partner's included;
- field values;
- a **tag change** per entry: the tag ids added and the tag ids removed,
  relative to the tags the entry had when loaded, never the full set — so a
  tag written elsewhere in the meantime is not overwritten. A draft that does
  not touch an entry's tags carries nothing for it. Re-resolving never touches
  tags, and Reset drops tag changes with everything else.

Every function the panel shows — resolution (§5.9) and transfer offers
(§5.7) — takes the stored state with the
draft over it, and nothing is written until the unit is committed. The preview
shows the unit as it will stand after settling, so a partner that settling would
pair with a leg of the draft joins it, and a booking that settling would make
or remove for it (§5.7) is shown. The draft is resolved top-down: the split,
then each entry's fields, in field order (§5.9). A choice made on a row that
disappears — a booking the draft's choices remove — is dropped, as is a value
that contradicts a choice above it.

**The panel is anchored on what it was opened from**: an entry's source
transaction, imported or user-authored. The draft's unit
is the anchor's closure under the draft — picking a partner adds its whole
source transaction, breaking a pair removes the partner's — and an
entry that leaves it is shown as a consequence ("returns to review", "is
deleted", "is unpaired"), not
as part of the unit. A split made on a partner's side leaves with it, and is
committed with it.

**A commit writes the full state the user saw**, in one transaction — the
split, the values, a counter-leg where §5.7 creates one —
with the keys of §5.9: every proposal shown is accepted, and every value left
as it is is decided as it is, empty included where the field may be empty
(§5.9, field order). A field that may not be empty and is empty stays so and
carries no key. **A commit does not
confirm**; confirmation is never an action. Settling then derives the unit's
state like any other (above): it is confirmed when it meets every requirement
of confirming, and otherwise stays in review — waiting for its partner,
or unclassified — with everything the user committed kept. A commit needs the result to be valid, not complete: the
invariants must hold (a split sums to its amount, a counter-account obeys the
currency rule), but
a category, a counter-account or a partner may still be
missing. It is refused only where the result would be invalid, or where the
unit's structure changed since the preview: it gained or lost a member — the
chosen partner was paired elsewhere, say. Proposals
that changed in the meantime do not matter: the user commits what they saw. A partner or
counter-leg the preview proposed is accepted as chosen: where the commit cannot make it, the
commit is refused with the problem a chosen one would raise.
**Tag changes are applied in the same transaction, after the entries exist**,
idempotently: adding a present tag and removing an absent one are no-ops. A
commit that changes only tags is valid. A tag deleted meanwhile refuses the
commit as a conflict naming the tag. An entry the draft removes takes its tags
with it. Tag changes are never listed as consequences and affect no state,
flag or proposal.
The preview shows the state the commit leads to — "confirmed", "waits for its
partner", "stays unclassified", "stays without a partner", "proposals to check" — so the one keystroke is never a surprise.

Nothing in a draft outlives the panel except through a commit. Committing a
waiting unit is how its work is kept: the leg, its split and its destination
are committed, and the partner completes it on arrival without touching them.

**The same panel edits confirmed units**, and opens on a new user-authored
transaction once the entry form has created it (§3.9). Saving a
confirmed unit is a commit like any other; the unit stays confirmed while it
still meets the requirements of confirming.
Re-resolving is available for every unit: a preview of what resolution would
propose now (§5.9).

**On a booking the panel is leaner.** A booking's structure is its source's
(§5.8), so the panel hides the partner, convert and split controls on its
entries; their values, description, note and tags are edited as on any entry.

**Every interpretation edit goes through the panel**, wherever it is opened —
from the queue, the ledger list or a rule's preview — and for any unit,
confirmed or not; the merges of §5.9 are the only other writers. Inline edits
without a preview are not offered, because the preview is what shows a pair
breaking or a partner returning to review. Tags are part of the panel's draft;
elsewhere they are direct writes, and tagging a filter's result applies to
every selected entry that can carry tags (§3.7). A user-authored transaction can be edited
or deleted through the entry form at any time (§5.6).

`ledger_entry.review_flags` is a derived array of tokens from a closed set; an
entry is clean when it is empty:

| Token | Meaning |
|---|---|
| `unconfirmed` | the entry's unit carries derivation keys other than standing ones: values awaiting a human (§5.9) |
| `unclassified` | an entry not fully interpreted: `type` NULL, or a flow without a category (§3.4) |
| `waiting` | the entry waits for information that has not had its chance to arrive: a partner leg (below) |
| `unmatched_transfer` | a transfer leg without a partner that is not waiting (§5.7) |

Rules:

- **`unconfirmed` is judged over the unit.** It marks every entry of a unit
  that carries a non-standing key, a complete sibling of an unclassified split
  entry included. The other flags stay with the entry they describe:
  `unclassified` marks the incomplete entry, and the pairing flags the
  unpaired leg. The review queue is the units not confirmed, whether or not
  any of their entries is flagged.
- The array is rewritten wholesale by a single pure function derived from
  current state, as part of settling (§5), never by appending or stripping
  tokens at call sites.
- **Nothing about review is persisted beyond the derivation keys.** When a
  unit was reviewed, and by whom, is audit.
- **Confirming** requires:
  - a complete interpretation (§3.4) — a type and, for a flow, a category;
  - for a transfer, its pair (I22).
- **Units are confirmed one at a time.** There is no batch confirmation: a
  group of units cannot be confirmed without looking at each, and seeing each
  is the point of review. A unit whose keys are all standing arrives
  confirmed, because a human already decided its values — in a rule, or
  earlier in this unit (§5.9).
- **Nothing automatic returns a reviewed entry to review** (I20), except a
  booking following its source (§5.8): what its source changed returns to
  review as new data, and what its source no longer calls for is removed,
  without asking — the source changed, not a decision of the user's. A user's
  operation may — a pair broken, marked as a duplicate or reverted elsewhere
  (§5.6). The entry keeps its values — all but a counter-account its broken
pair set (§5.7) — and returns because its unit no longer
  meets the requirements of confirming; its whole unit returns to review with
  it, and is confirmed together again. The operation's result shows what it
  touched, so the user who caused the change sees it highlighted.
- **Every user operation that removes confirmed entries or returns entries to
  review says so before it runs, and runs only once the user confirms.** The
  panel's preview shows exactly which entries; other operations, such as
  editing a user-authored transaction, may warn in general terms. Marking a
  duplicate shows what each direction would remove (§5.6).

**Waiting.** An entry waits (flag `waiting`) while information that would
complete it has not had its chance to arrive — judged from coverage, never from
elapsed time, and derived, with no state and no cron. Waiting is a hint: the
unit stays editable. A transfer leg waits for its partner as defined in §5.7,
and cannot be confirmed until it is paired.

**Review state never excludes an entry from balances or reports.** Unreviewed
and unclassified entries count in balances and net worth, and appear in
reports. Review is about classification quality, not validity. What review can
still change is what is missing: until a leg is paired, its counter-account
lacks the movement — a withdrawal not yet confirmed is missing from the cash
account — so net worth differs by the unpaired legs, which is what the
transfers (net) line shows (§8). Account and currency status (§3.11) is not
a review flag: it belongs to the account or currency, not to any entry.

---

## 7. Credential policy

**No secret that could authorise a payment is ever stored.** A secret may be
stored only if it is *verifiably scoped read-only* — a claim that has to be
true at the provider, not merely in intent — so anything unverified defaults
to not stored. A FinTS PIN fails this outright: it can initiate transfers. A
verifiably read-only session token may live in `importer_instance.state`, and
an importer may always decline to store one even where it would be permitted;
maximum caution is never wrong.

**Verifiably** means both of the following, as far as the provider allows:

- **documented** — the importer names the scopes the provider grants, and
  cites the provider's own documentation showing that those scopes can neither
  initiate a payment nor change account data;
- **checked** — where the provider offers introspection of granted scopes, the
  importer checks them when it stores the token, and refuses to store a token
  whose scopes are broader.

Where neither documentation nor a check exists, the token is not stored.

Three consequences.

**Interactive is a state, not a property.** Whether an instance needs input at
run time is simply whether it currently holds a usable credential — nothing is
declared anywhere. An expired token makes an otherwise unattended instance
interactive for one run (§5.11).

**A PIN is interactive by policy, not by protocol.** It is storable in
principle; this specification declines to store it. Only a TAN or an
equivalent challenge is inherently unstorable. A later reader should not take
PIN entry for a technical constraint and "fix" it with a credentials table.

**Session state inherits the classification of what produced it.** A partially
completed authentication dialog is credential-grade whether or not it contains
the secret verbatim: it lives in memory or a short-TTL encrypted row, and is
wiped when the flow completes or times out. So is a challenge shown to the
user, a photoTAN image included: it lives in memory, only until it is
answered. What may persist indefinitely is
the non-secret part — a `system_id`, for instance, which some banks require to
be stable to avoid a TAN on every login, and which therefore belongs in
`importer_instance.state`.

### 7.1 FinTS product registration

An operational constraint rather than a design one. Registration with the
Deutsche Kreditwirtschaft is mandatory and free. Register the *application*
(category "Web-Server"), not the library — library registration numbers may
not be used in live operation. Registration also unlocks the FinTS
Bankenliste.

The registration number belongs to the deployment, not to a login: whoever runs
the ledger sets it once, and every FinTS login uses it. Without it, a sync or a
refresh of accounts stops before asking for a PIN and says that the
registration is missing.

---

## 8. Reporting semantics

Every figure is in the base currency (§3.8). Periods bucket entries by
`booked_on` — the same date that selects an entry's rate.

| Question | Query |
|---|---|
| Account balance | `SUM(amount)` for the account, in the account's currency |
| Net worth | every account's balance, converted at the report-date rate: the sum of those that can be valued, the rest on the unvalued line |
| Income, expense | categorised flows in income-kind and expense-kind categories, each at its `booked_on` rate |
| Unclassified | entries with `type` NULL, and flows without a category |
| Savings | income and expense, the Unclassified line and reconciliations |
| Savings rate | savings ÷ income |
| Starting balances | openings, at their `booked_on` rate |
| Valuation | valuations, grouped by account, at their `booked_on` rate |
| Reconciliation | reconciliations, grouped by account, at their `booked_on` rate |
| Transfers (net) | transfer legs, at their `booked_on` rate (§3.8) |
| FX translation | per account, as defined in §3.8 |
| Spend by category | expense-kind flows, grouped by category, date range — refunds net |
| Spend at a merchant | flows, grouped by payee |
| Cost of a trip | flows ∩ tag |

- **Savings** includes unclassified entries and reconciliations, so it is true
  to the money: before review is finished, and where money left without an
  entry — cash spent unrecorded, interest a hand-kept loan absorbed. The
  **savings rate** shows "—" when income is zero or negative, and carries a
  marker when the period has unclassified entries, reconciliations or unvalued
  amounts, because its income or spending may then be incomplete. Over a range
  it is the range's savings over its income, not the mean of its periods'
  rates.
- **Transfers are not flows.** They are excluded from income, expense and
  savings, and appear only in the transfers (net) line — which, until a leg is
  paired, also holds what its counter-account is still missing (§6).
- **Derived entries are not flows.** Openings, valuations and reconciliations
  are excluded from income and expense, each has its own line, and all count
  towards net worth. Only reconciliations count towards savings: they are
  changes of money the entries do not explain, while an opening is initial state
  and a valuation is not money arriving or leaving. The reconciliation line
  doubles as a measure of a report's accuracy: it is what the ledger does not
  explain, from unrecorded cash to a difference against the bank.
- **Refunds net.** A category's spend can be negative in a period where its
  refunds exceed its purchases; reports show it as it is.
- **A period's spend** is the *Spend by category* row summed over the period,
  so that a figure beside a category report and the report agree. Unclassified
  entries and reconciliations stand beside it, not in it.
- **Unclassified is two figures where it stands beside a spend or income
  figure:** the money out and the money in. Savings takes it as one net line.
- **Net worth today** takes every account's full balance, as the account list
  shows it; a net worth at an earlier date, and its history, cut the entries at
  that date and convert at its rate.
- **Older history can change earlier reports.** A backfill moves the opening
  earlier and changes it by what was added (§5.10), so net worth before the old
  anchor date changes; from the anchor date on it does not.

Two further lines appear wherever they apply rather than being hidden:
**Unclassified** — entries not yet interpreted (§3.4), which keep totals equal
to balances — and **unvalued** — foreign amounts with no usable rate (§3.8),
which are never counted as zero.

Every conversion goes through one function, and only reporting calls it
(I27).

Filters are multiplicative: date ∩ account ∩ category ∩ payee ∩ tag ∩ amount
range ∩ text, and the entry's type and review flag narrow it further. Several
values of one dimension are alternatives; the dimensions combine. One good
filter bar replaces most reports.

- **Dates** select by `booked_on` and are inclusive at both ends.
- **A category includes its descendants,** unless the filter asks for exactly
  that category. **Uncategorised** selects the entries that could have a
  category and have none — flows, and entries with no type yet, never
  transfers or derived entries — and is an alternative to the categories
  chosen beside it.
- **An amount range compares magnitudes,** in the one currency it names: a
  range across currencies is meaningless, and nothing is converted for it
  (I27). A direction narrows it to money in or money out.
- **Text** is searched in the entry's description, note and source text, the
  source transaction's counterparty, purpose, end-to-end id and mandate
  reference,
  the payee's name and the category's name; every word of the text must be
  found, in any of them.
- **The list holds entries.** Derived entries are among them unless the type
  excludes them; a duplicate has none (I3) and never appears.

---

## 9. Open questions

- **Rate source.** ECB reference rates are EUR-based and cover the major
  currencies. Currencies they do not publish need a fallback source, or remain
  unvalued (§3.8).
- **An exact base-currency value** for single-hop conversions, if the
  reference-rate approximation for pocket spending ever matters.
- **Audit log and undo**: a change log written by a database trigger, with
  undo applied per operation and refused where affected entries have since
  changed.
- **Automatic depot valuation.** An importer reporting a depot's value without
  its movements would reconcile like any source (§3.10), but it would make the
  depot synced, and a synced account takes no counter-legs (I40): a transfer
  into it would stay unmatched unless the importer delivers the depot's cash
  movements too.
- **Attachments (receipt photos)** — probably a fourth thing alongside source
  records and documents, not a column.
- **Highlighting a stale account** whose data age is well above its own usual
  cadence, derived from its runs — a presentation feature, should the sorted
  list prove insufficient.
- **Asking the other user to review a unit.** One user completes a unit and
  flags it for the other to confirm. A sketch: a key that is not standing,
  carrying the user it is addressed to, which keeps the unit unconfirmed while
  present (§6) and is removed when that user commits the unit. It would be the
  first key naming a user, which `derivation` otherwise does not record (§5.9).
  Deferred until the tool has been used: whether committing what one knows and
  leaving the rest in review (§6) is handoff enough.
- **Asking the model again.** An answer stands while its payload is
  unchanged (§5.9, pass 3), so a category added after the model found none
  fitting, or another model configured, does not reach it; the user sets the
  category in the panel instead. Two sketches: an "Ask again" in the panel
  that drops the entry's answer, so settling asks anew; or the
  category tree in the fingerprint, so a changed tree re-asks every standing
  answer. Deferred until stale answers show up in use.
- **Editing documents by hand.** A documents editor: an edit of a document is
  a change of its input, previewed like any edit, and its booking follows it
  (§5.8) — no new mechanism; the document's version detects a conflicting
  edit, as an entry's does. Planned.
- **A document's provider from its sender, or by hand.** An importer reading
  mail may map a sender's domain — of the mail, or of the original of a
  forward — to a provider in its settings, so that no model reading decides a
  provider. Later, a document's provider edited by hand, which books it anew
  like a change of the mapping (§5.8). Planned.
- **A clearance account's balance signal.** A clearance account is shown like
  any other (§3.3). A balance away from zero is normal while charges lag
  behind orders, so how the account view makes it meaningful — what is older
  than the matching window and not offset, a record date with nothing in
  flight, a condition on the Overview — is decided once the accounts are in
  use. So is creating a clearance account from a document that is not booked.
