# Household ledger — design decisions

Status: living record. Why `spec.md` is the way it is: each decision with the
alternatives that were considered and rejected. `spec.md` states what the
system does and stays normative; this document keeps the reasoning out of its
way. See `README.md` for how the two relate.

Conventions:

- **Identifiers are stable.** `D<n>` is never renumbered or reused. A decision
  that is later partly reversed stays in place, marked *partly superseded by
  D<m>*, with its stale passages moved to `decisions-archive.md` and its text
  corrected; one that is wholly reversed moves there whole, marked
  *superseded by D<m>*. The new decision is added at the end. A reference to
  an archived decision is resolved there.
- **Nothing here is normative.** Where an entry states behaviour, it restates
  `spec.md`; if the two disagree, `spec.md` wins and this entry is corrected.
- **References point one way.** Entries cite the sections and invariants they
  explain — `spec §x`, `spec I<n>`, `architecture §x` — and each other as
  `D<n>`. No other document cites this one: before changing a section or an
  invariant, search this document for it.

---

## D1 Two layers instead of transactions-as-atoms

Rejected: parsing straight into transactions (ezBookkeeping, Firefly). The
source is then consumed at import time, so the provenance widget is impossible,
split allocations are unverifiable, and dedup metadata sits on rows that editing
can destroy. Systems that only group children — Firefly's transaction groups —
cannot check a split at all, because the parent amount exists nowhere; here it
is the stored source amount (spec §3.1).

## D2 No general grouping abstraction — *partly superseded by D146*

Considered and rejected: a `transaction_group` or generic `entry_group` table.
Every candidate use turned out to be covered already:

| Need | Covered by |
|---|---|
| Split | `source_transaction_id` |
| Transfer pair | `counterpart_entry_id` |
| Transfer + fee | sibling splits of one source transaction |
| Refund, reimbursement | same category, opposite sign; nets |
| Trip, project, "related" | tags |
| A booking delivered twice | a duplicate naming its original (spec §5.6) |
| Installments, recurring | a future schedule feature, not a group |

Also rejected: building the table now with `type='transfer'` and extending
later. Transfer pairing is exclusive and capped at two; every semantic grouping
is many-to-many. The later thing wants a different shape, so the early table
would be dead weight carrying one type forever.

## D3 Transfers as a self-FK, not a parent table

A parent table would give structural symmetry and cheaper integrity queries. It
was rejected because every attribute proposed for it turned out to be derivable
or misplaced: the FX rate is `|amount_b| / |amount_a|`, the fee is a sibling
split, the dates are on the legs. A parent with nothing on it is ceremony.

Cross-currency transfers tested the same question again and gave the same
answer. A `foreign_amount` pair on the entry was considered and rejected: for a
transfer both legs exist, each correct in its own currency, so the counter-value
and the rate are read from the partner. A conversion between currency pockets
(spec §3.8) is exactly such a pair. Twice now an attribute has been proposed for
the pairing and turned out to be derivable from it, which is the strongest
available evidence that the parent was correctly declined.

Mitigations for the self-FK's weakness: both sides are written in one statement,
a deferred constraint trigger enforces mutuality, distinct accounts and opposing
signs — and equal amounts for a same-currency pair, while cross-currency legs
need only opposite signs (D43) — and a partial unique index on
`counterpart_entry_id` structurally prevents two entries claiming the same
partner (spec I10).

Also rejected: one row with `counter_account_id`. A single amount and date
cannot express a fee, an FX pair, or legs that settle on different days.

## D5 No merchants-as-accounts

Firefly makes every payee an account, producing two parallel taxonomies that
drift, and putting the IBAN on the account rather than the transaction — so an
entry cannot show what the bank actually sent when a payee uses two IBANs. That
is precisely the provenance widget this design exists to support.

## D6 Income or expense is a property of the category

An earlier draft put `income` and `expense` on the entry and gave categories no
kind, on the grounds that refunds, reimbursements and cash differences carry
both signs in one category. That argument confused two things: a *kind* says
which side of the income statement a category is on; a *sign constraint* says
which direction money may move. The kind is kept and the constraint dropped
(D7). With the kind on the entry instead, contradictory states were possible
(Groceries typed income), the type was a second copy of what the category
implied, and one residual — cash difference — was split across both sides,
inflating both totals.

Most tools in fact place it on the category: GnuCash, hledger and Beancount
root Income and Expenses in the account tree with free signs; tools that show
an Expense/Income toggle on entry use it to set the sign and filter the
category picker, which a manual-entry form here may do as pure UI.

The accepted cost: a category serves one side. Gifts received and gifts given
are two categories.

Rejected: no kind anywhere, with the side taken from the sign. A refund would
then count as income, which is what D7 exists to prevent.

Rejected: storing Income and Expense as two root rows. The kind column and
the composite foreign key already guarantee that every category, and every
subtree, sits on exactly one side. Root rows would add two protected rows that
must never be deleted, renamed or re-parented, a rule that no entry may be
booked to a root, and an extra level in every picker and drill-down — and
either duplicate the kind or, if the kind were derived by walking up to the
root, turn every report into a recursive query. The roots are the kinds,
shown as such (spec §3.5).

## D7 No sign constraint by entry type or category kind

A positive flow in an expense category is a refund. Forbidding it would force
refunds into income, where they would not net against the original category and
would overstate both income and spending. The kind means which side; the sign
means direction of money.

## D8 Review flags as a derived array, not a table — *partly superseded by D163 and D169*

A table was the first draft, justified by "don't re-ask me". But that state
already lives elsewhere — a rejected document link is
`source_transaction_document.status`, a correction is an accepted value that
pass 2 reads — so flags are pure presentation of current state and can be
recomputed freely. Flags are a closed, machine-written set of tokens — five
since `orphaned_auto_leg` went with the auto-leg replacement (D59) — which is a
constrained array column, not tags. Not even "reviewed" is persisted: it is
read from the unit's keys, completeness and pairing (spec §6). The flags themselves cannot serve
as that proof, because they are the output of the function that would read it.

## D9 Supersede is not built

An earlier draft built supersede — a source re-delivering a changed event,
answered by retiring the old row and writing a successor — for PayPal's pending
states. It is not built: FinTS and CSV deliver booked records only, booked
records do not change, and importers emit only final records by contract (spec
§5.1). A source rewriting a booked event is rejected visibly instead (spec
§5.2). The design reasoning is kept in spec §9 for the day a source makes
waiting unbearable; adding it then is additive while no superseded rows exist.

## D10 Importer instances are credentials, not accounts

The first draft had `bank_connection` plus a type-keyed `importer_config`, and
`account.bank_connection_id`. Both were wrong. Its one field was an
instance-level choice, not a type-level one, which left it with nothing on it
that belonged there. And a one-to-many account link cannot express the actual
household: two logins, two personal accounts each, and shared checking accounts
visible from both.

One table for every importer instance, with `settings` (user-set) and `state`
(importer-written) kept apart so "reset this connection" is well defined, and
one many-to-many link table. Everything that is filtered, joined or constrained
on — `external_id`, `emits` — stays a real column; the rest is JSON,
validated in app code against a per-importer schema.

## D11 Naming: source transaction vs ledger entry — *partly superseded by D169*

`source_transaction` keeps the domain word while staying unambiguous against
database transactions — ingest code manipulates both in the same function, and
`transaction.amount` beside `tx.commit()` is a genuinely confusing read.

`ledger_entry` deliberately does **not** become `ledger_transaction`. The two
layers exist precisely because these rows are *not* the transaction, they are
an interpretation of one; naming both "transaction" re-flattens the
distinction and makes the split awkward to describe — "this transaction has
three transactions". "Entry" is also what the UI calls it: a line in a ledger.

`app_user` keeps its prefix because `user` is reserved in PostgreSQL and would
need quoting in every hand-written query.

Join tables are `parent_a_parent_b`: `ledger_entry_tag`,
`source_transaction_document`. `account_source` is the deliberate exception —
it carries its own field (`external_ref`) and means "a way to fetch
this account", which the mechanical name `account_importer_instance` would
obscure.

## D12 No kind discriminator on counterparty references

`counterparty_ref` holds an IBAN for SEPA and an email or merchant id for
PayPal, with no column saying which. The kind is not stable per account (a
PayPal counterparty may be either; a FinTS cash withdrawal has neither), so it
would have to be per record — but nothing reads it. The provenance widget
already switches on `importer`; rule matching compares literal strings and
IBANs never collide with emails; validation is the only real consumer and is
not needed for two users. Same reasoning for `account.external_ref`.

## D13 Derived over stored, where the read pattern allows it — *partly superseded by D168*

Several fields were removed in review for encoding something already
recoverable: `ledger_entry.split_index` (order by id), `tag.starts_on` /
`ends_on` (min/max over tagged entries, `v_tag_span`),
`payee.merged_into_id` (nothing references the loser once entries are
repointed and rules moved, so it is deleted outright — `ON DELETE RESTRICT`
makes the FK enforce that order), `payee_rule.source` (every rule is
user-approved at creation; if silent learning is ever added, the column comes
back so machine-written rules can be audited or purged), `category.archived`
(D41), `account.opened_on` (D40), `importer_instance.last_sync_at` (read from
its runs), and the creation and decision timestamps on dimensions and document
links (D21).

The counter-example is `review_flags`, which *is* denormalised, because the
read pattern is every list view and the alternative is a correlated subquery
everyone must remember to write. It is recomputed wholesale (D44), so storing
it costs no correctness. The assertion result, by contrast, is no longer
stored at all (D74).

`origin`, once stored as the exception, is gone: an entry is a movement or
derived, told apart by the reference it sets (D168).

`derivation` (spec §5.9) is a third case again: not denormalised and not
derivable. It records *how* a value was arrived at, which nothing else retains
once resolution has run, and it is the reason several review flags need no
storage of their own.

## D14 No institution corpus for detecting cash withdrawals

A card cash withdrawal and a card purchase are indistinguishable by booking
text: the purpose line of a withdrawal carries a street name as often as a
terminal code. The discriminator is the counterparty *name* — the acquirer of
a withdrawal is always a bank, while a purchase shows the merchant — so
matching that name against the Bundesbank's quarterly Bankleitzahlendatei
(whose short-name field is built for exactly this kind of payee
identification) would work domestically.

Rejected anyway, for two reasons. Withdrawals abroad are not covered by a
German register, and they cluster during travel — so the corpus would fail
precisely in the period producing the most withdrawals in a year. And a
household uses a handful of ATM operators: after one manual classification
each, pass 2 recognises them by counterparty name and booking text (spec §5.9),
which is a better source than any register for a set that small. The residual
case — a first-time ATM, especially a foreign one — is what pass 3 is for.

## D15 Money as integer minor units

Exact sums, no float, no rounding tolerance in the split invariant. Minor units
are per currency (spec §3.8): cents for EUR, none for JPY. `numeric` is an
equally exact alternative; integers were chosen for arithmetic simplicity in
application code. Exchange rates are exact decimals, not money.

## D16 Text + CHECK instead of PostgreSQL enums

Adding or removing a permitted value is a constraint change rather than
`ALTER TYPE` surgery. The type list is expected to move during v1.

## D17 Currency pockets are accounts

Every account holds one currency, permanently (spec §3.8). Rejected: a
multi-currency account whose entries carry their own currencies. Its balance
would be a sum across currencies, every balance query would need conversion,
and the composite foreign keys that make "a balance is a sum of one currency"
structural would have to go. At the institution a multi-currency account is a
set of single-currency balances anyway; modelling each as an account keeps
that truth, and turns a conversion into an ordinary transfer (D3).

## D18 Base-currency values are computed, not stored

Rejected: a stored `base_amount` on every entry. Under the valuation rule (spec
§3.8) it is fully determined by the rate table, and storing it adds a second
split invariant and a second amount to reconcile everywhere.

Rejected for now: a nullable exact base value, set where an importer knows
the exact base-currency leg of a conversion. Exactness exists only for a single
hop — foreign spending funded directly from the base currency — while the
household's real foreign spending, by card, is already a base-currency entry.
It stays addable later without loss, because source rows keep the instructed
amounts it would be filled from.

Rejected: cost-basis tracing — valuing a foreign expense at the rate at which
the money that paid for it arrived. It needs lots, FIFO and partial
consumption, which is investment accounting.

A consequence worth having: since nothing stores base values, changing the base
currency would mean rebuilding `fx_rate`, and nothing in the ledger.

## D19 Void rather than delete; revert deletes — *partly superseded by D103 and D146*

A duplicate is voided, not deleted, because a deleted row no longer blocks its
hash and the next fetch would re-import it. A bad run is reverted by deletion,
because the corrected re-import needs exactly those hashes free again, and a
misparse is not something the source said. One mechanism per purpose; neither
can stand in for the other (spec §5.6). Both remove entries through the same
routine as breaking a pair (D53), and revert works as a stack per account
(D55).

## D21 No audit log or undo in v1; who and when only on event records — *partly superseded by D163*

`derivation` is not made to double as audit: it records which pass, the
matcher or a user decided a value, never when or which user (D163). Considered:
a small confirmation record serving only batch undo; rejected together with undo
itself. Audit and undo are coupled — a trigger-written change log would serve
both — and both are left out until they are missed (spec §9). The same test
decides attribution and timestamps: ledger entries carry no `created_by`,
`created_at`, `updated_at` or review time, because each of those is a
question only an audit log answers properly. Needing one of them is the
signal to build the log, not to add the column. A mistaken confirmation is
corrected by editing.

The rule is general (spec §3.2): **who and when are recorded only on rows that
are themselves records of an event** — import runs, which are the log of an
activity. Mutable state carries neither. That removed `decided_by` and
`decided_at` from document links, `created_at` from accounts, categories,
payees, rules, tags, importer instances and documents, `linked_at` from account
links, and `app_user.is_admin`: two equal users need no administrator, and
creating a user is a bootstrap concern. Run attribution stays, because it is
diagnostics on a row that is already a log entry.

## D22 No per-institution time zone — *partly superseded by D109*

An earlier draft recorded each institution's time zone so that `synced_through`
never advanced past the last fully closed booking day, to keep hash ordinals
stable. The ordinals are stable without it (spec §5.2): rows sharing an ordinal
group are identical in every hashed field, including the booking date, so a
partially delivered day cannot shift them. The zone, the closed-day rule and
the clock function that computed it were removed; `synced_through` is the end
of the last successful fetch. Booking dates are calendar dates as reported and
are never converted. The one rule that once compared a run's start time with a
booking date — document waiting — now uses the document source's coverage date
instead (D76), so the statement holds without exception.

## D23 No balance checkpoints

Considered: storing every balance a source reports — each statement closing,
each running-balance row — as its own immutable row, to localise an assertion
failure to a single day. Rejected: per-run balance records already bracket a
failure between the last passing run and the failing one, which with regular
syncs is a few days, and everything else checkpoints offered works from one
closing balance per run and account (spec §5.10). Those records have since
moved from the run's statistics into a table of their own, still one per run
and account, because the opening is derived from them (D54).

## D24 Payees are curated; history keys on source signals — *partly superseded by D144*

Considered: allowing payees on transfers, so that history could learn "this
counterparty is a transfer to cash" through the payee. Rejected: it turns the
payee from a reporting dimension into a registry of every counterparty, down to
each ATM operator. History keys on the source fields of past cases instead (spec
§5.9), where the counterparty name is available anyway. Transfers that pass 0
(D64) cannot recognise are learnt by history or declared by a counter-account
rule (D144).

## D27 History filters evidence; it does not adapt results

Considered: when history's learned counter-account is in the wrong currency,
substituting the account of the same kind in the right one — Cash EUR becomes
Cash USD. Rejected: it makes a plain lookup carry a semantic assumption (that
the *kind* of a past counter-account is what matters) and an ambiguity rule
for when several accounts qualify. Filtering the evidence by the hard
constraint before taking the modal value reaches the same results in the
cases that matter, and generalises to any later constraint (spec §5.9). Also
rejected: storing what account a leg "would need" in its derivation; the need
follows from the instructed currency and is computed when read.

## D28 A waiting transfer keeps its destination in its derivation — *partly superseded by D156 and D172*

An unpaired transfer to a synced account has nowhere to keep its destination
until the partner arrives (spec §5.7). Kept in the `counter_account` derivation
key, with the leg waiting, because review, waiting and derivation are one piece
of functionality. The cost is one explicit exception: that key may hold a
user-chosen value while the leg waits (spec §5.9).

Rejected: a `counter_account_id` column on every entry, redundant once a pair
exists and needed on very few rows; the same column populated only while
unpaired, for the same reason; a side table of pending transfers, state beside
the derivation keys serving the same machinery; and a placeholder leg on the
target account, replaced on its next import — it would make the target's
balance assertion fail whenever the issuer books after its statement date,
unless the assertion special-cased placeholders, and it would put non-source
entries on a synced account.

Waiting is judged from sync positions, not elapsed time, for documents too
(spec §6): a fixed 48 hours expired regardless of whether the document source
had run. For documents the position is the source's coverage date (D76).

The key lives until the leg is paired: no automatic process removes it from an
unpaired leg, and an unpaired transfer cannot be confirmed (D69), so the
destination is never lost by confirming.

## D29 Two identity columns, not one — *partly superseded by D103*

Rejected: merging `source_id` and `content_hash` into one identity. "Same
event, changed" and "different event" both fail an exact match on a combined
value. The source id is deliberately *insensitive* to content and the hash
deliberately *sensitive* to it; one column cannot be both (spec §5.2). Where a
row has a source id, the id is also an input to its hash in place of the
ordinal (D46).

## D30 The account–source link is bare; sync position belongs to the account — *partly superseded by D109*

Rejected: `is_primary` on the link. A shared account has no owner, and the
concurrency it was meant to solve — both users syncing the same evening — is
already handled by the content-hash unique index; the second run skipping rows
is the correct outcome, not something to prevent by designating a winner.

Rejected: `enabled` on the link. An untracked account simply has no row; with
an enabled flag, discovery would have to run on every sync, and a declined
account would be re-offered forever.

Rejected: a coverage range on the link, because regimes alternate on one
account (D20).

Rejected: the sync position on the importer instance. A second user's sync
would refetch weeks already held — harmless thanks to dedup, but wrong in
principle and slow. The position is a property of the data, not of who fetched
it (spec §5.4).

## D31 Rules are never written automatically

An earlier draft offered to create a rule on every correction. Rejected: a
correction is an accepted value, and accepted values are already pass 2's
input. An auto-written rule is a materialised index over past decisions,
buying an O(1) lookup that is irrelevant at household scale, at the cost of a
prompt on every correction and a slow accumulation of hundreds of
near-duplicate rows. Deriving from history is self-maintaining and never stale
(spec §5.9).

## D32 Document sources share the importer machinery

Rejected: a parallel `document_source` table. An Amazon scraper needs
everything a FinTS connection needs — tokens, enable/disable, error text, a
last-run timestamp — so it would be a copy of `importer_instance` with one
field changed (spec §5.5).

## D35 A purpose-built tool rather than an existing one

Nothing off the shelf covers a shared two-user ledger with FinTS import and
correctable suggestions (spec §1). ezBookkeeping has the right transaction
model and a UI worth copying, but its data is locked to a single user and
there is no shared-ledger concept. Firefly III has the right import ecosystem
and a working FinTS bridge, but sharing has been "in progress" for years, its
merchants-as-accounts model creates two competing taxonomies (D5), and every
FinTS integration for it lives in a separate web wizard on a separate port.
Beancount and Fava demand full double-entry and a toolchain per import.
Actual Budget has real multi-user but is envelope-based. Sure has multi-user
and a good UI but no FinTS.

## D36 Regular syncing is an assumption, made visible — *partly superseded by D113*

Without a scheduler and with the PIN typed each time, data arrives only when
someone syncs (spec §1.3). Several mechanisms quietly depended on that: how
closely a failed assertion is localised, cross-account transfer pairing, and
the history depth banks deliver without extra authentication. The assumption
is stated, and one ledger-wide staleness threshold turns a lapse into an
*overdue* account status (spec §3.11).

Rejected: a fixed cadence in the spec, which nobody would check; a per-account
threshold, which is configuration nobody needs at this scale.

Depots and other assets valued by hand are overdue by the same threshold,
measured from their latest balance record, because their balance *is* the
valuation and a stale one misstates net worth. Cash is not: its balance is kept
current by its entries, and a wallet count is an occasional check that would
otherwise be permanently overdue.

## D37 Depots and assets are valued by hand

Position-level holdings are a non-goal, so nothing reports a depot's value
(spec §1.1, §3.4). A depot's balance is the transfers into and out of it plus
valuations from balance records; a realised gain is a valuation like an
unrealised one, because selling is a transfer out. This keeps market movement
out of the savings rate. Importing a depot's value automatically is not ruled
out but is not "just another importer" (spec §9): it would make the account
synced without its movements being imported.

## D39 One sign convention for every amount

Issuers commonly use the opposite convention — card purchases as positive, a
debt as a positive balance — and an inverted closing balance would solve a
wrong opening that passes its first assertion vacuously. So every amount,
reported balance and document total is in ledger convention, and normalising
is the importer's job (spec §3.3, §5.1, I29). A CSV profile carries separate
inversion settings for amounts and for its balance column.

Rejected: naming `card` and `loan` as liability kinds so the UI can show debt
as positive. That is presentation, and the split is derivable from the account
kind whenever a report wants it. Rejected for documents: a positive total plus a
direction column, which is the same information in a second convention.

## D40 Closing requires a zero balance — *partly superseded by D87, D115 and D136*

`opened_on` duplicated the opening entry or could contradict it, and was
dropped. Closing became a date with defined effects — no fetching, no
discovery, no pickers, no entries after it — and requires a zero balance on
that date, so closing an account can never change net worth (spec §3.3).
Rejected: a UI-only hidden flag, which defers the question of what closing
does to sync and matching.

## D41 A category's kind is fixed; there is no archived state — *partly superseded by D145*

Changing a kind would silently move every past entry to the other side of
every report, so the kind is fixed at creation and moving spending across
means recategorising (spec §3.5, I9).

`archived` was dropped. Its one real use — retiring a category whose history
should stay distinct — only buys a shorter picker, and ranking pickers by
recent use gives that without a stored flag. History needs no flag either: its
recency weighting stops proposing a dormant category. Rejected: leaf-only
booking, which forces an "Other" child under every parent that needs one.

## D42 FX translation is computed per account — *partly superseded by D113*

The net-worth identity once computed FX translation as a residual. That also
absorbed transfers whose legs fall in different periods, legs whose partner
had not arrived, and unvalued amounts — so a household holding only euros would
have shown currency effects most months. FX translation is now computed per
account, exactly zero for base-currency accounts, and the identity gains a
transfers (net) line (spec §3.8). Rejected: keeping the residual under a
neutral name, which leaves currency effects and timing mixed in one figure.

A maximum rate age was added: a rate feed that stopped would otherwise value
later years silently at old rates. A value past it is unvalued, and the
currency shows its rate age (spec §3.11). Rejected: valuing anyway with a stale marker, which
shows an unknown value as if it were known.

## D43 A split keeps the original row as its residual — *partly superseded by D163 and D168*

The original entry stays as the residual child and keeps its id, type, keys
and tags; new children carry only what the user gives them (spec §5.9). This disturbs
least — the row id survives under a keyboard cursor — and leaves unconfirmed
values unconfirmed rather than confirming them by the act of splitting.
Rejected: replacing the entry with N new keyless rows, which treats a split as
a review of everything on the entry.

The pair trigger was tightened to require equal amounts for same-currency
pairs, which the matcher already required but the database did not (spec I10).
A split that leaves a pair unequal is shown invalid and resolved by splitting
off the difference (D168).

## D44 Flags are recomputed for every entry — *partly superseded by D114*

Some flags depend on state outside the entry: whether a leg still waits
depends on another account's sync position, which an import of that account
changes without touching the leg. Every post-import phase therefore ends with
a set-based recompute of all flags (spec §6, I23). Rejected: a dependency map
naming which events recompute which entries, which every future token would
have to keep correct; and computing the non-local tokens when read, which
splits flag logic in two and brings back the correlated subqueries D13
avoided. At household scale the full recompute is negligible, and it is the
repair path the design already promised, used routinely.

## D46 A source id replaces the ordinal in the hash — *partly superseded by D103*

The ordinal separates rows identical in every hashed field within one fetch.
For rows without an id, its order is meaningless and it is stable: rows in an
ordinal group are identical in every hashed field, including the booking date,
so a day delivered partially — one of two identical rows, then both — yields
ordinal 0, then 0 and 1, and the second is correctly inserted. This holds
without constraining how far a fetch reaches (D22).

For rows *with* a source id it fails. The id makes the rows distinguishable, so
the ordinal binds to a particular row: delivered in another order, both rows
match their id with a different hash and are rejected as changed bookings;
delivered partially, the newcomer's hash collides with the stored row and it
is silently dropped despite its own id. So for those rows the id itself is the
discriminator in the hash (spec §5.2). Rejected: ordering the group by id,
which fixes reordering but not partial delivery; and making hash uniqueness
partial, which weakens the one-index invariant the rest of ingest relies on.

The cost is that identical content delivered by an id regime and by a no-id
regime no longer collides; the amount step of deduplication handles that
case (spec §5.2).

## D50 A file's coverage is never overstated — *partly superseded by D109, D116 and D135*

A file has no fetch window. Overstating its coverage — taking the upload date —
would make the next FinTS sync start after the gap and never fetch it, silently.
Understating — taking the last booking date — costs only a slightly longer wait
for transfer partners. So coverage is the period end where the profile can
read one, otherwise the last booking date, and is never asked for (spec §5.4).
Rejected: asking on every upload, which would be confirmed unread and protect
nothing.

## D53 One routine removes an entry and its consequences — *partly superseded by D169*

Unpair deleted a matcher partner and revert deleted mirror legs, but void did
not, leaving an auto-created cash leg inflating the wallet, and a void row kept
its document links, blocking the documents from matching the surviving row.
Void, revert and every operation that breaks a pair now share one routine
(spec §5.6). A removed entry frees its document (D169). Rejected: refusing to void a paired or linked
row until the user has cleaned up by hand, which costs clicks and reaches the
same state.

## D54 Openings and reconciling entries are derived from balance records — *partly superseded by D83 and D105*

The opening had accumulated five mechanisms: solving it on the first reported
balance, moving it on backfill, re-solving a manual opening once, an
evidence-based re-solve for a later error, and undo on revert with an ordering
rule on top. Together they hand-maintained the history of one number, and an
error baked into a solved opening had no remedy short of reverting the first
run.

Now every stated balance is a **balance record**, reported or manual, and the
opening is derived from the earliest (spec §3.10, §5.10, I12). Solve, move and
re-solve are the same formula; revert recomputes instead of undoing; a fix
dated before the anchor simply changes the opening, and a fix after it is a
real assertion failure. History before the earliest record was never
verifiable under any design, so nothing is lost.

The same model covers accounts kept by hand. A later manual record does not
assert; it **reconciles**: its derived entry is the unexplained part of the
change since the previous record — a valuation on a depot, a flow on cash.
Because it is derived, a forgotten receipt entered later shrinks the cash
difference by itself, and correcting a miscount means editing the record. The
treatment follows the kind of record, which follows from the account: an
importer's records are asserted, a user's are reconciled.

Rejected along the way:

- **Precedence of a reported anchor over a manual one**, with a notice to the
  user. The earliest record anchors whatever its kind. A reported record that
  disagrees with the user's anchor makes the account out of balance, which is
  the signal — the user's number was wrong, or the history since is
  incomplete — and stays visible until resolved, instead of being replaced
  silently or announced once.
- **A special "Cash difference" category** referenced from settings, or a
  category stored on records or accounts. Reconciling flows go through
  resolution and review like imports, and history learns the category from the
  account's previous ones (D79). A category stored on the entry alone would be
  lost when a residual passes through zero.
- **Prefilling the category in the set-balance dialog** with the entry
  complete at creation. That stopped working once the entries became derived:
  a recomputation can recreate an entry outside any dialog.
- **Choosing the outcome of "set balance" by user choice** each time.

## D55 Runs revert as a stack per account — *partly superseded by D109, D120, D172 and D177*

Reverting an earlier run under a later one undid a state the later one had
built on. A run can now be reverted only if no later non-reverted run wrote
rows to its accounts (spec §5.6, I30). This also replaces the separate rule
about runs that trimmed against it, since such a run necessarily wrote to the
same account. Rejected: one global stack, which would make reverting Monday's
CSV require reverting the other user's Tuesday sync of unrelated accounts; and
a dependency rule for openings, which derived openings made unnecessary (D54).

## D56 Indistinguishable transfer legs pair in date order — *partly superseded by D95, D111 and D118*

Supersedes D26's "pair only on exactly one candidate". Uniqueness checked from
one side lets the result depend on processing order and can make a wrong pair.
But where the candidates are genuinely indistinguishable — two €500 transfers
to savings — a "wrong" pairing is immaterial: the second partner pairs with the
leg left over, and balances and reports are identical either way. D26's real
concern, a wrong pair blocking the true partner, applies only where the legs
*are* distinguishable.

So the matcher filters candidates by everything that can tell legs apart — the
counter-account in both directions, a real end-to-end id, the canonicalised
purpose — and pairs among the rest in date order, closest date first (spec
§5.7, I24). Rejected: mutual uniqueness, which leaves interchangeable legs in
the queue for no gain; and a closest-date tie-break without the filters, which
guesses where the data says the legs differ.

Proposals are still not stored, for D26's original reason: a suggestion table
would be new storage and a state machine for something derivable.

## D57 Review is per entry — *partly superseded by D88, D99, D100 and D107*

Review is atomic: the user settles an entry, then confirms it as a whole; no
value is approved or rejected on its own (spec §6, I21). That removed the
per-field reject and its "restore the previous value" rule.

An unreviewed entry is read-only outside review, authored fields included,
because editing before the derived values are settled invites mistakes. Bulk
tagging of a range is refused while the range holds an unreviewed entry,
rather than silently skipping those entries. Rejected: letting edits outside
review confirm the entry, which would accept a derived category the user never
looked at; and allowing tags only, which leaves a bulk action that does
different things to different rows of one range.

Open document suggestions block confirmation until the user picks one or
"none of these", so a batch can never reject suggestions unseen. A document
that matches an already reviewed entry is always a suggestion and returns the
entry to review, without re-deriving anything on it.

## D58 A pairing is changed by stating the right one — *partly superseded by D119*

Rejecting an automatic pairing set it to NULL, and the next post-import phase
re-paired the same candidate, since proposals are not stored. Instead of
storing rejected pairs, there is no standalone rejection: the user re-pairs,
swaps, converts to a flow, or changes the counter-account, each of which leaves
a state the matcher will not undo (spec §5.9). Under D56 a wrong automatic
pair can only join legs that are indistinguishable, where it is immaterial, or
follow a wrong type or counter-account, where the fix belongs on the leg.
Rejected: a table of rejected pairs, as document links have.

## D60 History before the first balance is a status, not a notice — *partly superseded by D110 and D125*

Backfilling a checking account creates mirror legs into a cash account dated
before its first count; the derived opening keeps today right but makes the
past look wrong. The account shows a passive status offering a starting
balance (spec §3.11), which turns the gap into one reconciling flow. It is a
status, not an interruption, because a forgotten receipt entered after a count
causes the same condition harmlessly. It applies to accounts kept by hand
only: on synced accounts, history before the first reported balance is normal
and nothing can be done about it. Rejected: creating no mirror legs before the
anchor, which would teach history that the same ATM operator is sometimes a
transfer and sometimes a flow.

## D61 Untyped entries are offered as transfer partners, never paired — *partly superseded by D117*

A savings statement often shows an internal transfer without the sender's
IBAN, so the partner arrives untyped and was never offered. An untyped entry is
not yet interpreted rather than a flow, so offering it does not contradict
"pairing never turns a flow into a transfer" (spec §5.7). It is offered only:
the user's pick types it, and history learns from that pick, so the next one
is typed on arrival. Rejected: pairing untyped entries automatically, which
saves only the first pick.

## D63 A document is input to resolution, not a pass of its own — *partly superseded by D230*

Matching a document's merchant against payee names needs either exact names,
which rarely agree, or an alias list someone maintains. Instead, an entry booked from a document line carries the line's text as its source text (spec §5.9). Rules,
history and the model then work as usual — the model can categorise an
unfamiliar merchant from real product names — and the separate "document"
authority tier disappears.

## D64 Pass 0 recognises transfers to the household's own accounts — *partly superseded by D133, D144 and D150*

Examples and the matcher relied on "resolution types it a transfer by its IBAN",
but no pass did: rules declare no transfers, history needs a precedent, the
model never sees IBANs. Pass 0 matches the counterparty IBAN against the
household's accounts and types the entry a transfer to that account (spec §5.9).
It writes keys like any pass, so every import is still seen once; internal
transfers batch-confirm in one keystroke. Rejected for now: writing no keys,
which would auto-confirm one class of entry ahead of the general decision on
auto-confirmation (spec §9).

## D65 Fields are resolved in a fixed order

Resolving each field independently let passes produce combinations the schema
rejects — a rule's payee on an entry history typed as a transfer. The type is
decided first, and a proposed payee or category is a proposal for a flow; then
only the fields the type allows are resolved, payee before category (spec
§5.9). Rejected: independent resolution followed by a consistency check, which
is harder to predict and still needs its own answer for ordering within
history.

## D66 Each entry is one history vote

The entries of a split source transaction vote separately (spec §5.9). This
slightly dilutes agreement for a counterparty whose charges are sometimes split,
which is rare, and needs no rule for which child speaks for a source. Rejected:
splits not counting, which loses learning where splits are systematic; and one
vote per source from the largest child, which is a special case for little
gain now that pass 0 types own-account transfers.

## D68 The model runs whenever earlier passes miss — *partly superseded by D106*

"Only for a counterparty never seen before" and "only after rules and history
miss" disagreed for counterparties with mixed history. The model runs whenever
passes 0 to 2 produce nothing confident for a field (spec §5.9): one rule, and
with the purpose in its payload (D80) it can sometimes tell apart what history
cannot. Its output is low confidence and confirmed individually (D67), so a
wrong guess costs one correction.

## D69 A transfer can be confirmed only while paired — *partly superseded by D107*

Confirming an unmatched leg deleted its destination and left a confirmed
transfer with no partner and no counter-account. A transfer is now complete
only when paired (spec §5.7, §6, I22). A leg left in the queue says something
real: either its partner has not arrived, or it is not a transfer to that
account. This also removed any need for a terminal "confirmed but unpaired"
state. Rejected: allowing it with a stored counter-account column, which D28
rejected as redundant once a pair exists.

## D70 Breaking a pair returns the leg left behind to review — *partly superseded by D168*

A former partner left behind by re-pairing, converting to a flow or changing
the counter-account was said to "stay", which is not a state: often it was a
confirmed transfer without a partner. It goes through the removal routine
and returns to review as a transfer without a partner, a counter-leg included
(spec §5.9). Rejected: requiring the user to decide both legs
in one dialog, which makes every unpair a two-entry decision.

## D71 A confirmed entry is never changed silently — *partly superseded by D91, D100 and D107*

After D56–D70, nothing automatic overwrites a confirmed value: the matcher pairs
only unpaired legs, a confirmed transfer is always paired, resolution runs only
on new entries, and documents reopen rather than re-derive. The rule is stated
as such (spec §5.9, I20): something new returns the entry to review. The one
exception is amounts derived from other rows, which follow their records or
their partner without reopening, because they are consequences, not proposals.
A user's own edits to a confirmed entry keep it confirmed.

## D73 Whether an account reports a balance is observed — *partly superseded by D83*

"Reports a balance" could have meant what the importer declares or what the
account has received. Observed is used throughout (spec §3.10): a bank that
silently omits balances for one account type leaves that account able to take
a manual anchor, and an account that starts receiving balances becomes asserted
on its own, with no declaration to keep in sync with reality.

## D75 Instances without a credential are shared

"Who may authenticate" means nothing for a CSV profile or a public rate source.
Such instances are always shared, so either user can upload the statement of a
shared card, and those needing no input run in the background whenever either
user syncs (spec §5.11). Rejected: owners on CSV profiles purely to filter the
UI, which would be a second meaning for the same column.

## D77 What "verifiably read-only" requires

Without a test, the credential rule ends either with no token ever stored or
with one stored on a hunch. A token may be stored only where the importer
documents the granted scopes with a citation of the provider's documentation,
and checks them by introspection where the provider allows (spec §7). Nothing
in v1 stores a token; the rule is decidable before the first importer that
wants to.

## D78 Savings include unclassified flows — *partly superseded by D126*

The savings rate is the yardstick the separation of flows, valuations and FX is
argued against, so it is defined (spec §8): savings are all flows including
the Unclassified line, so the figure is true to the money before review
finishes; the rate divides by income and is marked while unclassified flows
exist. Rejected: dropping the savings rate from reporting.

## D79 Resolution runs on every new entry — *partly superseded by D100 and D106*

Resolution ran only on imports. It now runs on every new entry, filling only
NULL fields, never overwriting and never re-run by a change or reopening (spec
§5.9, I18): on a complete entry it does nothing, and a rejected or changed value
cannot be brought back by it. This is what lets reconciling flows be
categorised like imports. History learns from confirmed values on every origin
except manual — whose entries have no source signals to match a future import —
and gains a key of the account for derived flows.

## D80 The model sees name, booking text and purpose

Supersedes D25. The model's payload is the counterparty name, booking text and
purpose, plus a confirmed document's merchant and lines (spec §5.9). Purpose
often carries exactly the hint needed — an invoice naming the service, a
merchant buried in a card descriptor — at the cost of more personal data, which
the disclosure statement covers; an on-premise model remains the expected
configuration, and restricting by channel stays rejected for D25's reasons.
Never sent: the counterparty IBAN, which identifies a person's bank account and
tells a model nothing, the BIC, end-to-end and other references, amounts,
dates, accounts and balances.

## D83 Every balance record reconciles — *partly superseded by D105*

Supersedes D34, D74 and the treatment-by-kind part of D54; D54's model of
deriving the opening and reconciling entries from records stands. Asserting
reported records and reconciling manual ones gave the account two treatments,
a third record kind for the switch-over, rules on which records a synced
account may take (I16) and an "out of balance" state that could only be
cleared by fixing rows. Now every record reconciles: each record after the
anchor owns a derived entry explaining its interval, whatever its kind
(spec §3.10, §5.10). I14 and I16 are retired, and manual records are allowed
on every account — a wrong one shows as a reconciliation and is deleted or
corrected (D101).

Detection survives. A dropped or duplicated row used to leave the balance
wrong and flagged; now the balance is right and the reconciling entry carries
the difference, shown as an *unexplained difference* on the account and in
the run summary (spec §3.11, §5.10). Because derived entries are recomputed on
every change, voiding the duplicate or importing the missing row makes the
entry disappear by itself. The notice does not block, except at a switch-over
(D86), and reconciling entries get no special review handling: the status and
the run summary are the signal.

A record is the balance at the end of its date, counting every entry dated on
it (spec §3.10). That is what the reconciliation formula already implied; it
is stated so that a count entered at noon is understood to include the
afternoon.

Rejected: keeping assertion as the stricter guard, which costs the record
kinds and write rules above for a signal reconciliation gives as well; and
materialising only the persistent mismatch as one rolling entry per synced
account, a new rule where closed-day dating (D85) and deletion (D101) remove
the cause instead.

## D84 Synced means linked, and gates only manual entries — *partly superseded by D104 and D156*

Supersedes D72. "Synced" (has an `account_source` row) and "imported into"
(I15 as it was) disagreed for an account linked but not yet fetched, and
unlinking was undefined. Now linking is the only gate: a synced account takes
no new manual entries, and the matcher waits for real legs instead of
creating mirrors (spec §3.3, §3.9, I15). Balance records no longer depend on
it (D83). Unlinking the last source simply makes the account unsynced again;
no rule is needed, and relinking later is a switch-over like any other (D86).
A revert no longer reopens an account to manual entries while it stays
linked.

## D85 The reported balance is the last closed day's — *partly superseded by D124*

Supersedes D45. Under reconciliation every record carries weight (D83): a
record dated on the fetch day misses that day's later bookings, and when they
arrive the record's interval and the next one gain a pair of offsetting
reconciling entries that never go away. The same open day made an anchor from
a midday first fetch absorb a late same-day booking into the opening. The
importer therefore reports the booked balance at the end of the last day
before the fetch (spec §5.1); a statement that includes forward-dated lines is
dated on the latest of them, as before.

What remains is a booking the bank dates back past a day it has already
closed, which leaves an offsetting pair; it is rare, and deleting the earlier
record cancels it (D101).

Rejected:

- **A watermark on each record** — the highest source-transaction id it saw,
  excluding later rows from its interval. It cannot tell "not yet booked" from
  "not yet imported": a gap filled from a file, or a backfill inside an
  existing interval, would never be credited to the record that should have
  had it, which disables the main remedy for a missing row. Sequence ids are
  also not in commit order under concurrent syncs.
- **Counting a row towards the record of the run that delivered it.** It
  fixes backdating and the open day, but does not compose with the opening:
  an overlapping backfill reporting its own balance leaves the opening wrong
  and an offsetting flow in spend. Restricting it to records written at or
  after the row's run turns it back into the watermark.

The data cannot tell a newly booked old row from one that existed all along;
counting by booking date assumes the latter, which is right for backfills,
gap fills, repairs and the opening.

## D88 Tags stay editable on unreviewed entries — *partly superseded by D137*

Partly supersedes D57. The read-only rule protects the fields review settles;
tags are not among them, and the date that puts an entry in a tagged range
cannot change during review. Range tagging applies to every entry in the
range (spec §3.7, I21). D57's objection — a bulk action doing different things
to different rows — falls away, because it now does the same to all of them.
Trips are when unreviewed entries cluster, which made the refusal bite
exactly when tagging matters.

## D89 FX translation is unvalued where any of its terms is

FX translation is the residual of an account's base values (D42), so a
missing rate would surface as a confident figure. Where any term is unvalued,
the account's FX translation is shown as unvalued and the bridge carries the
existing unvalued line (spec §3.8). Rounding stays absorbed by the residual by
design.

## D90 A source transaction has at most one transfer entry

The instructed amount describes what arrived on the other account, so the one
transfer leg of a source transaction can always use it; anything extra on this
account is split off as a flow. Two transfer children of one source would
each read the full instructed amount and double a counter-leg. A split therefore
produces only flows, and converting an entry to a transfer is refused while
another entry of the same source is one (spec §5.9, I31). Stated per source
rather than "children are flows" so the user may make a child, not the
residual, the transfer. Rejected: storing an instructed amount per entry,
which adds a column and an editing rule for a case the invariant removes.

I3 was extended at the same time: the entries of a source transaction carry
its account, currency and dates and sum to its amount, and amounts change only
by splitting. The copied-field rule had lived only in a table.

## D91 Cross-currency mirror amounts are set once and editable — *partly superseded by D112*

Partly supersedes D71's exception for mirror legs. A cross-currency mirror
whose partner has no instructed amount has no row to follow, and I13 made a
user's figure uneditable. Now I13 covers only entries derived from balance
records. A same-currency mirror follows its partner, which I10 requires
anyway; a cross-currency mirror takes its amount at creation — the instructed
amount, else the conversion function at the leg's date, else the user's figure
— and is then an ordinary editable value (spec §5.7). A structural change to
the partner recreates the mirror. Computing it from a rate goes through the
one conversion function, so §8 says "nothing else converts" rather than
"nothing else multiplies an amount by a rate".

## D92 Deleting a manual entry runs the removal routine — *partly superseded by D167 and D168*

A paired manual leg deleted without the routine left a mirror pointing at
nothing or an imported leg with a dangling counterpart. Deleting a
user-authored transaction is a trigger of the routine like marking a
duplicate, revert and breaking a pair (spec §5.6). It may be deleted even
while unreviewed (I21): everything on it is the user's own.

## D95 The purpose only breaks ties

Partly supersedes D56: the counter-account and end-to-end id filters stand.
Banks often rewrite the purpose on the receiving side — a card payoff reads
differently on Giro and card — so as a filter it kept common transfers out of
automatic pairing, on an assumption the first-week checks had not confirmed.
It now narrows candidates only where several remain (spec §5.7, I24).

§5.7 also claimed the pairing was the same in any import order. It is not:
pairs are never revisited, so arrival order can change who pairs with whom.
D56's point holds — indistinguishable candidates leave balances and reports
unchanged — and the spec now says that instead. Rejected: re-pairing the
matcher's own unconfirmed pairs when a closer candidate arrives, which changes
pairs under the user's eyes for no visible gain.

## D97 Document importers have a start date — *partly superseded by D108 and D230*

Each document importer instance has a start date below which nothing is imported (spec §5.5); it bounds what is read, and a clearance account's start bounds what is booked (D230).

## D98 Derived entries are recomputed under a per-account lock — *partly superseded by D114*

Unique indexes already make a racing double insert of a mirror leg or derived
entry fail loudly. What remained was quieter: two users editing one unsynced
account at once each recomputed its reconciling entries from a snapshot
without the other's change, leaving them wrong until the next recomputation.
Every operation that recomputes derived entries or creates mirror legs takes
an advisory lock per affected account, in id order (architecture §5.2).
Rejected: the global post-import lock for every edit, which queues edits
behind a running phase; and accepting the staleness as self-healing.

## D99 There is no batch confirmation — *partly superseded by D129 and D133*

Supersedes D67 and D57's batch provisions. A batch makes sense only for
entries with the same proposed values from the same evidence, and confirming
such a group either means looking at each — per-entry review in another
layout — or not looking, which defeats review. At a household's volume,
entries ordered by shape and confirmed with one keystroke each take minutes a
month with every entry seen (spec §6). With nothing gated on it,
`low_confidence` was dropped; each key's confidence is shown instead, and one
proposal threshold remains (spec §5.9). Auto-confirmation (spec §9) stays the
lever if volume ever needs one.

## D101 Any balance record can be deleted — *partly superseded by D124*

Reported records included; manual ones can also be edited (spec §3.10).
Deleting a record merges its interval into the next, which removes the
offsetting pair a backdated booking leaves (D85) without anyone typing a
number, and doubles as a diagnostic: a difference that disappears was timing,
one that only moves is real and needs a void or an import. Rejected: editing
reported records, which invents a figure and rewrites what the source said;
and patching earlier records automatically when an old row arrives, which
cannot tell backdating from a duplicate or a repair and would absorb
duplicates for good.

## D102 No "void run" operation

Considered for undoing a mis-mapped import below the top of the revert stack:
void every row of the run, which leaves a corrected re-import free wherever the
error changed a hashed field. Rejected: where the error was in an unhashed
field, the corrected rows would be skipped as already seen, silently; and
mis-mapped imports are mostly a setup-phase problem the revert stack (D55) and
boundary decisions already cover.

## D103 Duplicates are found by identity, then by amount; the first one in wins — *partly superseded by D117 and D146*

Supersedes D20, D47, D49 and D86, and with D86 the rest of D59; partly
supersedes D29 and D19.

The boundary decision of D20, D49 and D86 put a blocking, row-level prompt
into the sync and the CSV upload, held an account's rows unwritten until the
user decided, and needed a taxonomy of its own — overlaps, touching batches,
format changes, switch-overs — plus a blocking reconciliation at the
switch-over and the advice to unlink a source to finish hand-kept history.
All of that suggested a deterministic answer the user was asked to approve,
and abandoning a decision left `synced_through` able to advance past rows
never written.

**The core does not rank sources.** A CSV may have been edited and another
tool's export entered by hand, so an importer is not inherently more
trustworthy than a person; how trustworthy a source is depends on the source,
and building that into the core would mean brittle rules and endless
argument. One rule replaces the taxonomy (spec §5.2, I32): per account and
booking day, incoming rows are matched first by identity, then one to one by
amount against the *remaining* existing movements — those this delivery's
identity matches did not use up. A matched incoming row is stored void, and
existing rows and entries always stay. "Remaining" is what makes the amount
step safe: within one source and rendering, identity is complete and every
existing row on a covered day is used up, so two genuine €5 purchases are
never merged; rows from another source, an older rendering or a person are
never matched by identity, so they remain.

Manual and mirror entries count as existing movements; derived entries do
not, because they are computed from the movements and would otherwise void
the very row that explains them.

Accepted, with reconciliation as the guard (spec §5.3): different booking
dates for the same movement duplicate; two different movements sharing a day
and an amount can void the second; gaps between files go undetected. **Unvoid**
is added as the inverse of void (spec §5.6) — the correction for a row voided
wrongly, and the way the bank's rows complete a hand-kept history found
incomplete.

**One identity per row.** The reject outcome — same `source_id`, different
hash, "the source changed a booked event" — was a judgement about how a source
should behave; under the principle above it is a duplicate, and the existing
row wins. Rows with a `source_id` therefore need nothing but the id, and the
content hash identifies only rows without one. The second identity of D29
mattered only for supersede (spec §9), which would bring it back. With one
identity per row there is no second index to disagree with the first, so the
hash collision D47 made visible can no longer be told apart from a duplicate;
at this volume and with a cryptographic hash it is accepted. The source regime
concept leaves ingest; `source_format` stays as provenance.

A side effect: the shared-account question (both logins producing the same
hash) stops being load-bearing. Where the hashes differ, the second delivery
pairs by amount and is stored void once, after which its identity blocks it.

Rejected:

- **A third level, by date span, for hand-made history** — not an identity at
  all, because it voids every row in its window whether or not it duplicates
  anything.
- **A cutoff at the end of hand-kept history**, the old switch-over *T* made
  automatic — a precedence rule that ranks people above importers before that
  date and voids a later backfill of older history wholesale.
- **Prefilling the first fetch to avoid any overlap** — it helps a fetch but
  not a file, and leaves the rest to manual voiding.

## D105 Derived entries are never reviewed; reconciliation is its own type — *partly superseded by D163 and D168*

Partly supersedes D54 (the treatment of later records) and D83 (reconciling
entries as reviewed flows). D54's model of deriving the opening and the
entries after it from balance records stands.

A reconciling entry on a non-investment account was a flow: resolved through a
history key of its own, reviewed, categorised, counted as spend, and changed
silently after confirmation whenever its amount was recomputed — the one
exception to I20. A bank discrepancy thus became spending in whatever category
the user picked to clear the queue, and a wallet count made the user
categorise a number they had caused themselves.

The existing principle already answers it: a derived entry follows
mechanically from a record, so it is never resolved and never reviewed (spec
§3.9). Three types carry the meaning (spec §3.4):
`opening` for the anchor's entry, `valuation` for later records on investment
accounts, `reconciliation` for later records on any other. All three are
computed by one formula (spec §3.10), are excluded from income, expense and
savings, and have their own report lines (spec §8). The reconciliation line
also tells the reader how much of a report rests on movement the ledger does
not explain — an accuracy signal, kept apart from valuation, which is not an
error.

The type is stored rather than derived when read: the reference an entry
sets — a source transaction or a balance record — says how it came to exist
and `type` what it means, so a single `adjustment` type would merely
duplicate `balance_record_id IS NOT NULL` and push the meaning into a
classification every report would repeat. Storing it costs nothing extra,
since the derived entry is recomputed on every change to its records anyway.
For the same reason that a category's kind is fixed (D41), whether an account
is an investment account is fixed at creation (spec §3.3, I38).

Accepted: unrecorded cash spending is one uncategorised line per account
rather than a category; individual cash spending is entered by hand anyway.
History key 6, I8's exception for derived flows and pass 3's empty-payload
case go. The opening's date is now the day before the earlier of the first
other entry and the anchor date, which fixes the case of an anchor older than
every entry.

Rejected: one `adjustment` type with meaning derived from the anchor and the
account type (above); and counting reconciliations on non-investment accounts
in savings, which would bring back a rule by account type.

## D106 Resolution is a pure function; unconfirmed entries are rederived — *partly superseded by D118, D129 and D131*

Partly supersedes D79 ("never re-run") and D68. Resolution ran once, at
insert, filling NULL fields. On the first import, with history empty, nearly
everything arrived unclassified, and confirming the first of thirty REWE
entries taught the other twenty-nine nothing.

Now resolution is a pure function of an entry's inputs, the review draft,
rules and history (spec §5.9), called alike by ingest, settling and the
review preview. Ownership is per entry: an unconfirmed entry's values are
machine output and always reflect current inputs, rules and history, so a
confirmation, a rule change or a confirmed document link updates every
unconfirmed entry it bears on; a reviewed entry is never touched (I18, I20).
Structural consequences — a changed type or counter-account breaking a
machine-made pairing — go through the existing removal routine and matcher.
One human input outlives this: a pending destination (D28 stands), which
outranks every pass. When to recompute is the architecture's choice.

The proposal threshold must let one unanimous precedent propose; otherwise
the twenty-nine update only after the second or third confirmation. A low
threshold is safe, because every proposal is reviewed. The model, pass 3, is
asked at most once per entry and its answer reused, because asking a slow and
possibly paid endpoint on every recompute is not.

Rejected: filling only NULL fields of unconfirmed entries, which keeps a
stale guess when better evidence arrives; and computing proposals at read
time, which would make every report run resolution.

## D107 Review is atomic and per unit, in one panel — *partly superseded by D156, D163, D165 and D172*

Partly supersedes D57, D69 and D71; with D108, supersedes D100.

**Per unit.** Reviewing per entry let one leg of a pair be confirmed while
the other was pending — and under D106 a recompute of the pending leg would
then break a confirmed pair. A unit is now the entries of a source
transaction or a transfer pair, joined transitively, and is reviewed when it
meets every requirement of confirming and carries only standing keys (spec §6,
I21). Mixed states cannot
exist. I22 becomes "a transfer is confirmed only as a pair", which also
reviews the match itself when a manual leg's partner arrives.

**Atomic.** Nothing in review persists before the commit: everything is a
**draft** — document, partner or destination, split, field values — laid
over the stored state; the panel
previews it with the same pure functions the core uses, and one commit writes
the full state the user saw. It is refused only where the unit's structure
changed, so a proposal recomputed meanwhile never invalidates a review. The
one way to finish is a commit; settling then derives whether the unit is
confirmed (D165).

**One panel.** Creating a manual entry, reviewing and editing a confirmed unit
are the same commit; a confirmed unit stays confirmed. Converting, splitting,
re-pairing and picking a document stop being separate server operations that
each persist a step, and become previews. With split, reallocation and a
re-resolve preview in the panel, no reset operation is needed.

Rejected:

- **A reset operation** — replacing a confirmed unit by one fresh entry and
  sending it back to review. Destructive, and everything it was for is a
  preview in the panel.
- **Two write paths**, preview-and-commit in review but immediate operations
  after confirmation, which would keep both sets of operations alive.

## D109 Runs are per account and record their coverage; `synced_through` is derived — *partly superseded by D116 and D177*

Partly supersedes D22, D30, D50, D55 and D76.

`synced_through` was a stored column with three meanings — "known complete"
in the spec, "end of the last successful fetch" in D22, and a fetch day the
balance rule treated as still open — that only ever advanced, so a reverted
run that had advanced it left a gap no fetch would fill.

Coverage is now a fact recorded per run: *from* and *through*, reported by
the importer and never overstated (spec §5.1). A fetch covers through the day
before the fetch, the same last closed day as its reported balance (D85). An
account's `synced_through` is the latest coverage among its non-reverted runs.
Revert, concurrent syncs and unlinking need no rule of their own.

That required a relation between runs and accounts, because a run per
instance covers several accounts and the links can change later. Rather than
a coverage table, **a transaction run now belongs to one account**: the
orchestrator asks the importer for one account at a time, since deciding
which accounts a run covers is not the importer's business, and FinTS fetches
statements per account anyway. Coverage becomes a column on the run, a run
has at most one reported balance record, a failing account leaves one failed
run, and the revert stack of D55 is simply the account's own runs (I30).
Document runs record the provider's coverage the same way, so instance state
keeps only what belongs to the credential.

A reported balance record is never dated after its run's coverage (I36);
where a statement's forward-dated lines would require that, the run reports
no balance.

Rejected: a run-coverage table beside per-instance runs, which models a
relation the run itself should express; and resetting the column on revert to
the latest remaining booking date, which understates quiet accounts past the
history a bank delivers without a TAN.

## D110 Mirror legs are created when a leg is confirmed — *partly superseded by D117, D134, D144, D156 and D168*

Supersedes D33; partly supersedes D60.

D33 created mirror legs automatically, because a leg only suggested might
never be created, leaving drift. Under D107 that cannot happen: a transfer is
confirmed only as a pair, so the mirror leg comes into existence at the
moment of confirmation, and drift lasts only from import to review. Creating
it at commit removes unconfirmed mirror legs altogether, and with them the
setup trap where importing the Giro before linking the savings account filled
savings with mirror legs that its own import then had to deduplicate against.

A pair now completes by whoever can supply the partner (spec §5.7, I34): an
import, where the counter-account is synced and the leg falls within or after
its coverage; otherwise the user's confirmation. The second case includes legs
dated **before the counter-account's coverage begins** — a backfilled Giro
year against a savings account fetched since April — which used to become
unmatched legs that could never be confirmed. Their mirror legs are absorbed
by the savings account's opening, and *history before the first balance is
derived* applies to every account. The matcher is reduced to pairing existing
legs, and origin `matcher` is renamed `mirror`.

Accepted: until review, hand-kept accounts do not show unreviewed withdrawals,
the state a waiting card payoff is already in; a wallet count taken before
review yields a reconciliation that disappears once the withdrawals are
confirmed.

Rejected: confirming such legs unpaired, an exception to I22 that would also
clash with I20 once a backfill delivered the partner; and treating
unconfirmed mirror legs as machine output excluded from deduplication, which
needs a special case in D103 that creating them at commit avoids.

## D111 An automatic pair needs a known counter-account

Partly supersedes D56 and D95. Where neither leg knew its counter-account, a
leg could pair with an equal opposite leg on any account; the claim that
surviving candidates are indistinguishable did not hold there. Such legs are
now offered in review, never paired automatically (spec §5.7, I33). No flow
depended on the case: legs from pass 0, history with paired evidence and
counter-legs all know their counter-account.

## D112 Rates are used by reporting only

Supersedes D81; partly supersedes D91. Matching used rates twice: for a
cross-currency counter-leg without an instructed amount, and for tolerance
candidates that stayed inert until a rate source existed, so such transfers
could not be paired in v1. A cross-currency destination without an instructed
amount only arises from a user's choice — machine proposals obey the currency
rule — so the user is present and enters the amount received, possibly shown
an estimate; and cross-currency candidates without an instructed amount are
offered by account, window and sign, whatever their amount (spec §5.7). The
tolerance setting goes, and only reporting calls the conversion function
(I27).

## D113 Data age replaces "overdue" — *partly superseded by D122*

Partly supersedes D36: syncing regularly stays an assumption made visible, but
not through a threshold. One ledger-wide threshold could not fit a weekly
Giro, a monthly card file and a quarterly depot valuation, and D36 had already
rejected per-account thresholds. Every account now shows its data age — the
later of its coverage and its latest balance record — and the dashboard sorts
by it (spec §3.11). *Overdue*, *never synced*, the cash exemption and the
staleness setting go. Currencies show their rate age in the same way; the
maximum rate age stays, because it decides when a value is unvalued.

Rejected: per-account thresholds (D36); and inferring an expected cadence
from each account's runs, which is a presentation feature left open (spec §9).

## D114 Derived state is settled after every write

Partly supersedes D44 and D98. The post-import phase ran at the end of a sync
or upload, covered every run since the last completed phase, and missed
writes that change pairing or waiting without importing anything — linking,
unlinking, a changed setting. After D106, D108 and D110 everything it held is
derived state of one kind: pairings and proposals of unconfirmed entries,
document matches, derived entries and flags. One rule replaces its triggers:
derived state reflects current data after every write (spec §5, I37), and
bringing it up to date — settling — is idempotent and serialised. How it is
done is the architecture's; D98's rejection of a global lock for every edit
holds only if settling is fast or scoped, which at this scale it is.

## D115 Closing hides an account and stops fetching it — *partly superseded by D121 and D136*

Supersedes D87; partly supersedes D40, whose zero balance at closing stands.
D87 accepted imported rows after `closed_on` while refusing manual entries,
which ranked sources (D103). Closing now hides the account from pickers and
discovery and stops fetching it; whatever arrives later is accepted, from any
source, and the balance shows it (spec §3.3). No status is added for a closed
account with a non-zero balance: the balance is the signal.

## D116 Coverage is read only through its end

Partly supersedes D109 and D50. Coverage's start decided whether a transfer
leg waited for an import or was completed by a mirror leg (D110). It could not
carry that. An account's coverage was the hull of its runs, so a file for
January to March added after fetches since June claimed April and May too;
and a fetch that returned no statement — a quiet savings account — had no
start at all, so `synced_through` stalled and legs pointing at the account
waited for good. The start now decides nothing: an unmatched leg is completed
in review whatever the reason (D117), the domain reads only `synced_through`,
and a successful fetch covers through the day before the fetch whether or not
it returned rows (spec §5.1, §5.4). A run still records where its data starts,
for the import log.

Rejected: coverage as a union of run intervals, correct but machinery for a
decision that no longer needs it; and an empty fetch covering nothing, which
reads a quiet account as a stalled one.

## D117 Unmatched legs are completed from one list of offers; mirror legs yield to the real partner — *partly superseded by D147, D149, D156 and D168*

Partly supersedes D110 and D103; supersedes D82; subsumes D61.

Four rules decided how a leg without a partner was completed: by an import or
by a confirmation depending on coverage (D110), untyped entries offered
(D61), cross-currency legs of any amount offered, smaller amounts deferred
(D82). And a confirmed mirror leg met its account's later history only
through deduplication, which needs the same booking date: usually the rows
differed by a day and both stayed; where they matched, the bank's row was
voided and the stand-in kept.

A leg without a partner now either waits, because an import may still
deliver the partner, or is unmatched, because none will. An unmatched leg has
one list of offers: opposite-sign legs and entries on its counter-account
within the window, of any amount, including untyped entries and legs whose
partner is a mirror leg, and a counter-leg (spec §5.7). Picking a mirror-paired leg replaces the mirror; picking a
same-currency offer of a different amount splits the difference off the
larger leg. Mirror legs are not movements for deduplication (spec §5.2).

Accepted: an account's history arriving after its counter-legs counts each
such movement twice until the pick, shown by its unexplained difference where
it reports balances; and the distinction between a partner never expected and
one that failed to arrive is gone, with reconciliation the guard for the
second. Rejected: replacing mirror legs automatically, which changes a
reviewed pair (I20); and a separate offer rule per case, as before.

## D119 Partners are not swapped

Partly supersedes D58. Swapping the partners of two pairs was the one
operation whose commit spanned two units, against I21. Re-pairing one leg
already breaks the other pair and returns the leg left behind to review,
where it is re-paired (spec §5.9); nothing else needed the swap.

## D121 A closed account is unsynced

Partly supersedes D115. Closing stopped fetching but kept the links, so
`synced_through` froze and transfer legs pointing at the account waited for a
partner nothing would fetch. An account is now synced only while it is open
(spec §3.3): closing stops fetching by that definition, legs complete without
waiting, and reopening restores the account as it was. Rejected: unlinking on
close, which loses the links for reopening; and a closed-account case in the
waiting rule.

## D122 Data age follows how an account is fed

Partly supersedes D113. The later of coverage and the latest balance record
let a manual "set balance" on a synced Giro reset its data age while its
importer had stopped — exactly the lapse data age exists to show. A synced
account's data age is now its `synced_through`, an unsynced account's its
latest balance record (spec §3.11).

## D123 There is no verification level

Supersedes D48. It drove nothing, was undefined for an account fed by sources
of different kinds, and its one useful signal — whether the ledger is checked
against the bank — is what the unexplained difference shows where balances
are reported.

## D125 One status for a balance without a stated starting point — *partly superseded by D134*

Partly supersedes D60. An account with entries and no balance record summed
from zero and showed nothing, while one with entries before its first record
showed *history before the first balance is derived*. Both are now *balance
not anchored*, with the same offer of a starting balance (spec §3.11, §5.10).

## D126 Savings include reconciliations

Partly supersedes D78. A reconciliation on a cash account is spending nobody
entered; on a loan kept by hand it is interest the statement absorbed.
Excluded from savings, both overstated it by exactly that amount. Savings now
include reconciliations, which stay off income and expense on their own line,
and the savings rate is marked where they exist (spec §8). Openings and
valuations stay out: neither is money arriving or leaving.

## D127 Derived entries carry no tags or notes

A derived entry is deleted when its result reaches zero and created again
when it does not, so a tag or a note on it would vanish silently. Derived
entries are read-only throughout (spec §3.7, §3.9, I13).

## D128 Review changes what is missing, not what is counted

I26 also said confirming changes no existing amount. A commit that splits
changes the residual's amount, and confirming a counter-leg recomputes the
counter-account's derived entries. I26 now states only that review never
excludes an entry, and the spec says what review does change: until a leg is
paired, its counter-account lacks the movement, which is the transfers (net)
line (spec §6, §8). D110 had accepted the effect; this makes it visible where
readers look.

## D129 History proposes by majority and shows its evidence as counts

Partly supersedes D99 and D106 (the proposal threshold). Confidence was a
number from count, agreement and recency whose formula was never fixed, yet
the spec required its behaviour: one unanimous precedent proposes, 3 of 7 does
not. History now proposes the value a strict majority of its matches within a
lookback period share, and the basis records the counts — "3 of 4 since March"
— which is what review shows (spec §5.9). The proposal threshold setting goes;
the lookback period is a tuning parameter of the history pass.

Key 3, the payee, applies to the category only, because the type and the
counter-account are resolved before the payee (D65 stands).

Rejected: defining the confidence formula, which keeps a number nobody reads
as easily as a count.

## D130 Ingest is serialised per account

Settling was serialised and the identity index stopped identical inserts, but
deduplication's amount step reads what an account holds before writing: two
users syncing a shared account whose rows they render differently could both
insert. The architecture's per-account lock (D98, D114) already prevented it;
the rule is now stated where rules belong (spec §5, I39). Rejected: a global
write lock, for the latency D98 rejected it for.

## D131 Document matching is a subsystem of its own; links store decisions only — *partly superseded by D138, D152, D169 and D230*

Partly supersedes D108 and D106 (the model asked once per entry). Document
matching is out of v1, yet ran through the spec: matcher, enrichment,
auto-split, a waiting rule, a review flag. Its mechanics now live in a feature document (since D230, booking documents); the spec keeps the domain and what the core
requires of it (spec §5.5, §5.8).

## D132 Housekeeping: review UI out of the spec, retired invariants out of the table, examples as tests

The review queue's UI principles — ordering by shape, the buckets, the
keyboard — need no migration to change, so by the spec's own placement test
they moved to the review-queue view; the spec keeps the rules they rest on.
Retired invariants leave the table: their numbers stay unused and their
history is here (D54, D83, D104, D168 and D169). Every worked example of spec §4 is an
acceptance test (architecture §8), and three were added: a shared account
through two logins, a loan payment with an interest split, and an account's
own history replacing counter-legs.

## D133 Pass 0 and rules confirm what they decide — *partly superseded by D145 and D159*

Partly supersedes D64 and D99; settles the open question of spec §9 on rules
as standing confirmations. Every value carried a key until a human confirmed
it, so a rent payment matched by two rules, or an internal transfer matched by
IBAN on both sides, waited in the queue like a guess. With no batch
confirmation (D99) and history learning only from confirmed entries (I19),
that made onboarding the real cost: a first fetch or a year of backfill meant
thousands of keystrokes before history helped, and nothing written by the user
could shorten it.

A rule and an own-account match are not guesses. Their keys are now
**standing** (spec §5.9, §6): they keep recording where a value came from, but
a unit whose keys are all standing is confirmed as soon as it meets every
requirement of confirming — complete, a transfer paired, no open document
suggestions. History learns from such units, because the rule is a human's
declaration (I19 reworded). Changing or deleting a rule reopens nothing it
confirmed (I20 stands); re-resolving a unit shows what the rules say now.
Because a rule now confirms, the entries it would match are shown before it is
saved (architecture §4.1) — the guard against a broad rule such as `PAYPAL *`
also catching top-ups of a PayPal account. Rules change role, from
deliberately rare overrides to the way a recurring entry leaves the queue;
D31 stands, so nothing writes them automatically.

Rejected:

- **Writing no key at all** for pass 0 and rules, as §9 first proposed. An
  unconfirmed unit is rederived (D106), and a document link changes the input
  a rule matched (D108); a value without a key could not be told apart from a
  human's and would outlive both. Standing keys keep it machine output until
  the unit is confirmed.
- **Batch confirmation** for backfilled history: D99's objection stands. The
  rule is what a human looks at, once, with its matches in view.
- **Migrating another tool's categorisation**: an importer knows nothing about
  the ledger (spec §5), and a handful of rules covers the bulk.

## D134 *Balance not anchored* means no balance record at all

Partly supersedes D110 and D125. D110 extended the status to every account
with an entry dated before its earliest record, and D125 merged it with the
no-record case. On a synced account that is every account: a first fetch
delivers weeks of history and a closing balance dated after it, so the status
never cleared, and its remedy — a starting balance — created a permanent
unexplained difference unless the user knew the historical balance exactly.
The history before a reported anchor is already checked by the importer,
which verifies each statement's opening balance plus its lines against its
closing balance (spec §5.1).

The status now applies only to an account with entries and no record (spec
§3.11, §5.10). A backfill that leaves the history before a hand-kept anchor
implausible, such as a negative wallet, shows it in that history, and a
starting balance fixes it as before (spec §4).

Rejected: reporting the statement's opening balance as a second record per
run, which needs schema support for a fact the parse already checks; and
limiting the status to accounts with a manual anchor, a condition kept only
to warn about a case the history already shows.

## D135 Coverage is best-known, and balances are booked or absent

Partly supersedes D50. "Never overstated" was not true of a fetch covering
through the day before it: a bank may still book into a day it has closed,
which spec §3.10 already relies on. Coverage is now described as what the run
believes complete and never past what it asked for (spec §5.1, §5.4); the
overlap catches late bookings and reconciliation the rest. Nothing reads it
differently.

A source reporting only a current balance no longer has it adjusted by the
fetch day's bookings. A current balance may include pending items the ledger
never sees, which left the unexplained difference showing whatever was
pending at the latest sync. Such a run reports no balance, and the account
reconciles against balances entered by hand.

A statement failing its opening-plus-lines check still fails the run: a
mismatch more likely means a parser fault than a bank fault, and importing
rows from a parser that is wrong is worse than importing none. The run fails
alone, and a CSV export of the period is the fallback.

## D136 Closing only stops fetching

Partly supersedes D40 and D115. Closing required a zero balance and hid the
account from every picker, yet entries after `closed_on` were accepted. The
common close contradicted both: the final payout, interest included, arrives
after the closing date on the other account, and its transfer could neither
point at the hidden account nor leave it at zero. Closing now makes the
account unsynced (D121 stands) and removes it from discovery, and nothing
else; pickers list closed accounts after open ones, as dormant categories sink
(D41). A remaining balance is settled like any balance (spec §3.3).

Rejected: a grace period after `closed_on` during which the account stays
pickable, a rule with a number in it for what sorting already gives.

## D137 Tags apply to what a filter selects

Partly supersedes D88. Range tagging applied to every entry in a date range on
every account, so a trip's tag took in rent and salary and the cost of the
trip was wrong until someone removed them. Tagging now applies to the entries
the ledger list's current filter selects, of which a date range is the usual
case (spec §3.7, architecture §4.1). The filter bar exists anyway; tagging
reuses it instead of keeping a selection of its own. D88's point stands: tags
stay editable on unreviewed entries.

## D140 Housekeeping after the review of the draft — *partly superseded by D147 and D156*

Wording that had drifted from decisions it restated, and gaps in operations,
fixed without changing behaviour:

- Leftovers of the confidence model (D129): history proposes the type and the
  counter-account a strict majority share, not the modal value, and pass 3
  runs where earlier passes produce no value (spec §5.9).
- History learns from confirmed imported entries; no other origin carries the
  signals it keys on (spec §5.9).
- The `waiting` review flag joins the closed set, so the queue reads waiting
  from the flags like every other state; `unconfirmed` covers a pending
  destination (spec §6).
- Background runs during a sync are among the instances the current user may
  run (spec §5.11).
- A payee no entry references can be deleted, with its rules (spec §3.6). A
  manual entry is a unit of its own, and its account, date and amount are
  authored (spec §3.9, §5.9, I21). Category rules keyed on the payee run
  before text matches (spec §5.9).
- The base currency is fixed by a trigger, because rates are stored against
  it; the schema refuses a payee on an untyped entry and a category deletion
  that would drop rules referencing it, and loses the `amount_exact` match
  kind the spec never defined.
- Pass 3's stored answer is an input to resolution, and settling never waits
  for the model (spec §5.9, architecture §5.4).
- An account's own history replacing counter-legs shows the duplicate as an
  unmatched leg, not as an unexplained difference: the opening absorbs both
  rows (spec §4, §5.7). A waiting leg whose counter-account's source has
  stopped becomes unmatched when that source is unlinked (spec §5.7).
- `architecture.md` no longer names view or plugin documents, which depend on
  it (README rule 2a).

## D141 A leg left behind keeps its values — *partly superseded by D161 and D178*

The removal routine returned a partner left behind to review by writing a
`counterpart` key whose basis said the pair was broken. That made the leg an
unconfirmed entry, and unconfirmed entries are rederived (D106), so read
literally the type and counter-account a human had confirmed on it were up
for recomputation, while spec §5.9 assumed they survived.

The key is gone. Since D133, a unit is reviewed only when it meets every
requirement of confirming, and an unpaired transfer does not, so the leg
returns to review by that alone (spec §5.6, §6). Its values stay — except a
counter-account its pair set, which leaves with the pair (D178): a value
without a key was confirmed by a human, and resolution takes it as decided,
as it does a field fixed by the draft (spec §5.9, I18). Pairing remains the
matcher's, so the leg can find a new partner, steered by its confirmed
counter-account. This is not the "fill only NULL fields" rule D106 rejected:
keyed values, standing ones included, are still recomputed.

The user unpaired for a reason, and the leg left behind may be wrong too. It
is in the queue whatever happens to its values, and re-resolving it in the
panel shows fresh proposals on demand. Lost: a stored explanation of why the
leg came back. The user who acted sees it highlighted from the operation's
result; the other finds an unmatched or waiting leg.

Rejected: rederiving the leg fully. Evidence that produced its values has not
changed, so it would mostly reproduce them; and review is per unit, so its
split siblings — a fee split off, say — would be recomputed too, discarding
work the broken pair has nothing to do with.

## D142 Housekeeping after the second review — *partly superseded by D150, D163, D225 and D230*

Consistency fixes after D133–D141, without new mechanisms:

- Pairs between unconfirmed legs remain independent of arrival order. A pair
  of two standing legs is confirmed when made and then stays, as a pair a
  human confirmed would (spec §5.7). Rejected: confirming such a pair only
  where each leg is the other's only candidate, as automatic document linking
  requires (D96). The alternatives share both accounts and the exact amount
  and are not told apart by an end-to-end id, so a later, closer-dated
  candidate changes only which dates sit together, and re-pairing covers it.
- History's counter-account evidence excludes accounts closed on or before the
  booking date, as pass 0 does — a hard constraint filtering evidence (D27).
  Closed accounts became pickable with D136.
- Wording: reviewed and confirmed are synonyms and a property of the unit
  (spec §6); coverage is set by the rules of spec §5.1 and nothing else,
  replacing "never overstated" and "never past what the run asked for",
  which did not fit files (D135); a manual entry is a unit of its own unless
  paired; a rule confirms the units it decides completely, and one with both a
  payee and a text match counts as keyed on the payee.
- Accepted: changing a manual entry's account to one in another currency
  keeps the number and changes its meaning. The panel shows the account's
  currency in the preview before the commit, which is enough.

## D143 Housekeeping after the third review — *partly superseded by D144, D152 and D168*

Wording only, no change in behaviour. Matching is order-independent while
unconfirmed (D142); `synced_through` is believed complete, not known (D135); a
pass-0 leg to an unsynced account *needs* its counter-leg's commit rather than
*waiting*, a state defined in spec §5.7; an automatic split becomes the user's
once its unit is confirmed, which standing confirmation can do without a
commit (D133); the review state is keys, completeness and pairing (D141), so
only keys that are not standing hold up a partner. Spec §6 states the precise
condition for confirming without review — every key standing — rather than
the common case of a unit decided by pass 0 and rules. Spec §5.10 says that an
estimated starting balance is for hand-kept accounts: on an account whose
sources report balances it would leave a lasting unexplained difference
(D134).

## D144 Rules may declare a counter-account — *partly superseded by D172 and D179*

Partly supersedes D64, D110 and D143; settles what remained of spec §9's
question on confirming without review. D133 made rules the way a recurring
entry leaves the queue, but "rules declare no transfers" (D64) kept the most
repetitive units in it for good: cash withdrawals, card payoffs and transfers
to an IBAN that is not the household's. History proposed them, and history
never confirms.

A rule may now set a counter-account, which types the entry a transfer (spec
§5.9). It obeys the currency rule like every machine proposal: a rule for the
euro wallet does not match a withdrawal abroad. Its keys are standing. Where
the counter-account is synced, the leg waits and the pair is confirmed when
made (D142); where it is unsynced and it has no offer (D179), the unit is
confirmed by its standing keys and its mirror leg is created with it (I34
reworded). A leg whose synced counter-account passed the window without a
partner still needs a commit: there, a missing partner more likely means
missing data.

**Conditions combine.** Every rule table carries the same conditions —
`counterparty_ref`, `mandate_ref`, the name exact or by prefix, a purpose
regex, the booking text, and the payee for category rules — all of which must
hold; rules with a reference condition run first. The need is concrete: both
of the household's cards are charged from one collection account of the
issuer, and only the mandate reference tells them apart. `mandate_ref`
therefore becomes a normalised column (camt `MndtId`, MT940 `MREF+`), outside
the hash like `end_to_end_id`, and `purpose` is the remittance text only, so
formats do not differ by whether they joined the mandate into it. History key
1 is refined by the mandate where there is one, so one creditor collecting
several contracts keeps their evidence apart.

Rejected:

- **Account aliases**, extra IBANs per account for pass 0. One collection
  account charges both cards, so an alias would map one IBAN to two accounts;
  the mandate reference is what distinguishes them, and a rule matches on it.
- **Text rules that propose rather than confirm**, so that only rules keyed on
  references would be standing: two classes of rule for one risk, which the
  preview before saving and applying a changed rule to existing entries (D145)
  already cover.
- **Confirming on strong history.** A rule is the answer, written once with its
  matches in view (D133).

## D145 A rule can be applied to existing entries; categories merge — *partly superseded by D159*

Partly supersedes D41 and D133. With confirmation per unit and no batch
operation (D99), confirmed history could only be changed one unit at a time.
A category's fixed kind (D41) told the user to recategorise its entries, and a
broad rule that had confirmed the wrong value for months ("changing or deleting
a rule reopens nothing", D133) left those values standing, still marked as the
rule's.

Two existing mechanisms now do bulk work, and nothing else does (spec §3.5,
§5.9):

- **Categories merge like payees**, within their kind: entries and rules
  repointed, children moved under the target, the category deleted. Moving
  spending to the other side stays a recategorisation, which applying a rule
  can now do in bulk.
- **Saving, changing or deleting a rule** previews two sets of confirmed
  entries: those it matches that hold a different value, and those carrying its
  standing key that it no longer matches. By default nothing changes but the
  stale keys, which are dropped because they no longer say where a value came
  from. On request the rule is applied: the first set takes its values, and in
  the second the fields the rule had set are re-resolved without it and return
  to review where resolution proposes. Re-resolved entries do not vote in
  history, or a bad rule's output would propose itself again. Only unsplit
  flows take part, and their type stays `flow`: counter-account rules are not
  applied to existing entries, and no rule turns a confirmed transfer into a
  flow, because changing a confirmed transfer changes its pair, which stays a
  per-unit edit.

This is not batch confirmation: nothing is confirmed that a rule would not
confirm anyway, and a human chose the change with its effect in view.
"Confirmed is truth" is a rule about automation (I20); a human replacing a
human's decision is the system working as intended.

Rejected: a general bulk edit of the ledger list's selection, a second
mechanism for what rules already express; and merging across kinds, which a
category's children could not follow, since a child has its parent's kind.

## D146 Deduplication is between source rows only, and a duplicate names its original — *partly superseded by D156, D167 and D177*

Supersedes D139; partly supersedes D19, D103 and D104.

**Manual entries leave deduplication.** D103 counted a manual entry as an
existing movement, and D139 kept it there. That let an interpretation decide
the state of a fact: a bank row was voided because a person had typed something
first. The matching is unreliable — amount and date are the only evidence, a
description shares nothing with the bank's purpose, and a person may round the
amount or misremember the day — and the case is rare: manual entries on an
account that is imported are for correcting an importer or filling a gap. It
also had a defect no rule fixed: deleting the manual entry, allowed at any
time, left the bank row void and the movement gone. Now an import and a manual
entry for the same movement both stay; reconciliation shows the difference
where balances are reported, and the manual entry is deleted (spec §3.9,
§5.2).

**`duplicate_of` replaces `voided_at`.** A duplicate names the row on the same
account that reports the same movement — a composite foreign key — and never
another duplicate; a deferred trigger checks that, and that a duplicate has no
entries. Ingest sets it only on rows it is inserting; otherwise it is set by
the user's *mark as duplicate of* and cleared by *not a duplicate*, or when a
revert deletes the original. The word "void" is retired: every void row was a
duplicate, so the state is named for what it means. Naming the original fixes
the shared account with two renderings: an identity hit on a duplicate also
uses up its original, so the second credential's deliveries no longer leave
the first credential's rows "remaining" on every sync, where a genuine
same-amount booking arriving late could pair with one and be marked wrongly.

**I32 restated.** Rows of one delivery are never compared with each other;
pairing is one to one, against rows no incoming identity accounted for; only
ingest marks automatically, and only rows it inserts, so deduplication never
changes or removes anything that exists. The amount step relies on a later
delivery containing every row an earlier one delivered for the same days. A
fetch made during the day has an incomplete last day, which the next delivery
contains, so it is no exception; a bank that removes booked rows, or filters
its window by entry date, would be one, and `plan.md` checks for it.

**The first fetch of an account without coverage starts after its latest entry,
derived entries included** (spec §5.4), so hand-kept history and the import
meet without overlapping. D103 and D139 rejected this because it left out the
bank rows that unvoid used to complete a hand-kept history; with manual entries
outside deduplication, that use is gone. Derived entries count so that a
hand-kept depot's import starts after its last valuation, which keeps the rule
free of a list of origins; a record whose derived result is zero has no entry,
and an import reaching back over it only reconciles against it.

Rejected:

- **`duplicate_of_entry`**, a reference from a source row to a manual entry:
  it would write the layer violation into the schema.
- **Adopting a manual entry** as the interpretation of the import that matches
  it, with *detach* as its correction: brittle matching for a case that almost
  never occurs, and a new operation to undo it.
- **Limiting the amount step to rows of different importer instances.** A
  format change and an unstable `AcctSvcrRef` both happen within one instance,
  and within one instance and rendering identity already accounts for every
  row.

## D147 Mirror legs are never replaced by an imported partner — *partly superseded by D168*

Partly supersedes D117 and D140. D117 let an account's later history replace
counter-legs confirmed before it arrived: the imported partner was offered
"legs whose partner is a mirror leg", and picking one deleted the mirror. That
is a switch-over mechanism, and it worked only for an exact amount in one
currency with dates close enough: a fee, or a conversion without an instructed
amount, left the double count. The case behind it — an account kept for months
with counter-legs and nothing else, then fed by an importer — is unlikely.

The offer category and its pick are gone, as is the worked example (spec §4,
§5.7). A mirror leg lasts as long as its pair, and deduplication never compares
against it. The first-fetch prefill of D146 counts mirror legs among an
account's entries, so the import starts after them. The general re-pair from
the other leg remains for the rare case.

Rejected: excluding mirror legs from the prefill so that the first fetch reaches
further back, which only works with the mechanism removed here.

## D148 The unexplained difference spans every record from the first reported one

Supersedes D124. Summing only the reported records' reconciliations broke the
telescoping that makes derived entries meaningful: a manual record between two
reported ones, wrong by *e*, left +*e* on itself and −*e* on the next reported
record, so the account showed a bank discrepancy that did not exist and
localised it to the wrong interval. "Set balance" defaulting to today, before
today's bookings arrive, made that frequent. The sum now runs over every record
from the first reported one through the latest, in record order, manual records
included (spec §3.11, §5.10). Interleaved manual records cancel whatever their
error; a back-dated booking's pair still cancels; a manual anchor meeting its
first reported balance still shows.

Rejected: refusing manual records on accounts with reported ones again, as D34
did before D83.

## D149 Every unpaired leg shows its offers — *partly superseded by D156, D157, D158 and D165*

Partly supersedes D117. Offers belonged to unmatched legs only, so a waiting leg
whose partner was already there but did not match exactly — a fee charged in
the same booking, a savings statement without the sender's IBAN — could not be
picked until the counter-account had synced past the window. Waiting protects
one thing: no mirror leg on an account whose import may still deliver the real
partner. Offering existing rows creates nothing, so every unpaired leg now shows
them, and only an unmatched leg also offers a counter-leg (spec §5.7). Every
offer is unconfirmed, so a pick only ever joins unconfirmed entries to a unit.

Rejected: merging *set destination and wait* into commit, so that a commit
could save the draft of a leg still missing its partner. A fee split saved
ahead of its partner leaves a unit half decided by a human and half proposed,
and the general version — saving any draft — needs a second action beside
commit and a way back to the proposals. The fee split falls out of picking the
partner once it has arrived (spec §5.7), so nothing else in a draft outlives
the panel.

## D150 Pass 0 ignores closing; an account is open through its closing date

Partly supersedes D64 and D142. Pass 0 excluded accounts closed on or before the
booking date, so the payout of a closed account's remaining balance — which
spec §3.3 accepts after `closed_on` — was not recognised on the receiving
account. An IBAN match is a fact, so pass 0 is no longer filtered by closing.
History keeps its filter, where it does real work: a replaced wallet stops being
proposed. One definition serves it: an account is open on dates up to and
including `closed_on` (spec §3.3, §5.9).

## D151 No resume cursor — *partly superseded by D172*

A fetch starts from the account's derived `synced_through` minus the overlap,
or, without coverage, after its latest entry or at the importer's default
(spec §5.4), and neither the CSV nor the FinTS importer needs anything else.
`account_source.cursor` is dropped; an importer that needs a credential-scoped
cursor can bring it back. D11 is corrected accordingly.

## D152 A document's lines are a split the preview proposes; only a commit splits — *partly superseded by D166 and D230*

Partly supersedes D108, D131 and D143. Auto-split made settling split unconfirmed
transactions along their documents' lines, and collapse the split when the link
went. It was the only automatic process that created and deleted ledger entries,
and it brought rules of its own: rederived splits, draft choices on regenerated
rows, a commit refused when "the document a split came from changed", tags
vanishing with the entries a machine had made. A booking is the exception: made split as its document says (D230).

Rejected: moving documents and pass 3 out of the core spec and the v1 schema.
The core is meant to be complete, with plugins added later: with no document
source, matching finds nothing, and pass 3 without configuration does not run,
which is its stub. Their hooks — an input to resolution, a draft choice, a
requirement of confirming — stay where an extension can use them.

## D153 Nothing automatic changes a confirmed entry; user operations show their cost first — *partly superseded by D158 and D159*

With D144 to D152, I20 loses its exceptions. Ingest marks only rows it inserts
(D146); every offer is unconfirmed (D149), so a commit on one unit never
dissolves another confirmed pair (D147); a same-currency mirror leg follows its
partner, whose amount changes only by a split, a commit of the same unit. Only
derived entries are recomputed, and they are never reviewed. I20 now says that
and nothing more (spec §2.1, §5.9).

What a user does is another matter. Reverting a run, marking a duplicate,
merging a category or payee and applying a rule may reach many units; these are
not exceptions to I20 but the user's decisions. One rule replaces revert's own
confirmation sentence: every user operation that removes confirmed entries or
returns entries to review shows them before it runs (spec §6). Marking a
duplicate shows both directions, so the user can mark whichever row loses less.

## D154 Housekeeping after the fourth review

- History still falls through to the next key when a key has matches but no
  majority (spec §5.9). Considered: stopping at the first key with matches. A
  descriptor split one to one would then hide a payee pooling forty entries of
  one category, and a fall-through proposal shows its key and its counts and,
  when wrong, costs the same single correction as no proposal.
- Wording: every write ends by settling, and a model answer arrives later as a
  write of its own (I37); income and expense are categorised flows, so savings
  no longer reads as counting uncategorised flows twice (spec §3.8, §8); a unit
  returning to review returns whole and is confirmed together again (spec §6);
  a backfill changes earlier reports (spec §8).
- The dashboard shows a period's reconciliations beside its spend, where
  unrecorded cash spending ends up (`plan.md`).
- `plan.md` gains two first-week questions: whether a later fetch contains every
  row an earlier one delivered, and whether the bank delivers the mandate
  reference.
- This document keeps the decisions in force; wholly superseded entries move to
  `decisions-archive.md`.
- The schema's split trigger fired only when entries changed, so a source row
  could become void with its entries left in place; `trg_duplicate_state` now
  checks every change of `duplicate_of` itself.

## D155 Housekeeping after the final review pass — *partly superseded by D159*

- Interpretation changes outside a unit's commit are named: merging a payee,
  merging a category and applying a rule to existing entries, each previewed
  and one transaction (spec §5.9, §6; architecture I21). Payee merge already
  was one before this review.
- History key 1's mandate refinement leaves out past entries with a different
  mandate and keeps those without one, so history from a format without
  mandates is not lost (spec §5.9).
- Rules of equal rank are ordered by id, so resolution stays deterministic, and
  a rule's preview shows where it conflicts with another (spec §5.9).
- The lists of writes that settle (spec §5) and of changes that recompute
  derived entries (spec §5.10) are examples, not exhaustive lists.
- The `unmatched_transfer` flag is described by what sets it apart: its offers
  include a counter-leg (spec §6, D149).

## D156 Entries made by hand live only on unsynced accounts; waiting is a hint — *partly superseded by D165, D167 and D178*

Supersedes D93 and D104; partly supersedes D28, D84, D110, D117, D140, D146
and D149.

Three rules decided where hand-made data could go: manual entries anywhere
(D104), manual transfers pointing at synced accounts (D93), and counter-legs
for any unmatched leg, whether its counter-account was unsynced or had synced
past the window without a partner (D110, D117). Each made sense on its own;
together they produced the special cases this review kept running into — a
counter-leg created while the real partner was still on its way, a second
mirror leg for a partner booked late, a pending destination with its own pass
and its own precedence, and a manual entry an import later duplicated, which
only reconciliation could reveal.

**One rule replaces them (I40): manual entries and mirror legs are created only
on unsynced accounts.** A synced account holds what its imports deliver, so
reconciliation against its reported balances measures the imports alone.
What an import got wrong or missed is fixed through imports — a CSV for a gap,
usually the bank's own export, and marking duplicates — which is always
possible. A leg whose synced counter-account passed the window without a
partner stays unmatched until the partner is imported, or is converted; the
special case of D110, a one-sided backfill against an account fetched only
since a later date, now needs that account's history too. Entries made by hand
before an account was linked, mirror legs included, stay as its history, and
the first fetch starts after them (D146). Closing or unlinking makes an account
unsynced, so a closed account's payout can still be given its counter-leg in
the panel; settling creates none on a closed account (D178). A
trigger enforces the rule on creation and on a change of account.

This partly restores D84's gating, without its reasons: it is not trust in
importers over people (D104), but where hand-made data can live without
colliding with imported data.

**The pending destination is gone.** Its last writers were *set destination
and wait* and manual transfers to synced accounts. Neither exists any more: a
destination a user picks is kept only by a commit, and a commit needs the pair;
manual transfers run between unsynced accounts, and money between an unsynced
and a synced account is recorded from the synced side, where the imported row
is typed a transfer and the unsynced account receives the counter-leg. The pass
`user`, its precedence over every pass, and its share of the `unconfirmed` flag
go with it.

**Waiting is a hint, not a rule.** With counter-legs never offered on synced
accounts, waiting blocks nothing: it tells the user that a partner has probably
not been imported yet, and the unit stays editable, as D149 already allowed for
picking an arrived partner. *Set destination and wait* is dropped, so a commit
is the only way to finish and always confirms.

Accepted: a user can work on a waiting unit and lose the work, because its
draft outlives the panel only through a commit. With rules and history
supplying most destinations, and the hint shown, this should be rare; `plan.md`
lists it among the first month's observations.

Rejected:

- **Committing a waiting unit's full draft** — every decision the user can make,
  with only the partner outstanding — so that no work is lost. The state it
  needs already exists (D141), but a commit would no longer always confirm, and
  the case is expected to be rare; experience decides whether it is worth it.
- **Allowing hand-made entries and counter-legs on every account, at any
  time**, equally free of special cases. Its errors — a counter-leg before the
  real partner, a manual entry an import duplicates — are silent wherever no
  balance is reported, where the rule adopted here turns them into visible
  friction in rare cases.
- **Counter-legs on a synced account for legs dated before its coverage
  starts**, which kept one-sided backfills working at the price of reading
  coverage starts and an edge near them.

## D157 Every transfer leg has offers; every unit can be re-resolved — *partly superseded by D158*

Offers were defined for unpaired legs only, so a paired leg had nothing to
re-pair with, although re-pairing is a panel operation (spec §5.9) and D147
relies on it. Every transfer leg now has offers, its own partner aside; for a
paired leg, picking one re-pairs it and sends the former partner through the
removal routine (spec §5.7). Every offer is still unconfirmed.

Re-resolving was offered only for confirmed units, while D141 relies on it for
a leg left behind by a broken pair, which is unconfirmed but holds values a
human decided. It is now available for every unit (spec §5.9, §6); for a unit
holding only proposals it shows what is already there.

`plan.md` gains a list of what to observe in the first month of use: work lost
on waiting units, booking lags beyond the matching window, unmatched legs on
synced counter-accounts, and how much of the recurring load rules carry.

## D158 Wrong pairs are corrected by picking the right one — *partly superseded by D161 and D221*

Partly supersedes D157. Offers contained only unpaired legs, so a set of wrong
pairs that blocked each other — A1 paired with B2, A2 with B3, A3 with B1 —
could not be corrected: every right partner was paired elsewhere. Offers now
include legs paired elsewhere, shown with their partner (spec §5.7). Picking
one breaks that pair too, so up to two former partners go through the removal
routine, both shown in the preview. A swap takes one pick, and a cycle of *n*
wrong pairs *n* − 1. A pick can therefore reach a second confirmed unit, which
is a user's operation shown before it runs (D153).

A leg left behind keeps its confirmed counter-account (D141), and the matcher
may pair it again. That pair used to write no key, as "a pairing that follows
from the user's choice", so in a cycle the intermediate wrong pair would have
confirmed silently. The user's choice now counts only in the commit that writes
the pair, which the user saw in its preview; the matcher's pairing of a leg
whose counter-account a human confirmed earlier records a `counterpart` key and
is reviewed once (spec §5.7, §5.9). The matcher pairs without review only where
a leg's counter-account comes from pass 0 or a rule.

Rejected: a pick of "no partner", or an unpair operation. Wherever the two legs
are candidates for each other — which is how a wrong automatic pair arises —
the matcher would pair them again at the next settle, and the spec has no
operation that rejects a value without saying what is right instead (spec
§5.9). A wrong pair whose right partner has not arrived is corrected once it
has.

## D159 Standing values stand; rules apply at a point in time — *partly superseded by D163*

Partly supersedes D133, D145, D153 and D155. Standing keys kept their values
rederivable, as machine output, until the unit was confirmed (D133), and a
commit deleted them with every other key. Applying a changed rule to existing
entries (D145) then had to find the entries a rule had decided, and the review
of the final files kept finding cases where that link between a rule and its
entries broke or misled: a commit erasing the rule's key when another field had
needed review, a leg left behind whose standing keys made its re-pairing
confirm silently, a sibling entry silently re-derived from a rule changed since.
Each fix added a rule about keeping keys in step with their source. The cause
was treating a rule as a continuously applied definition of a group of entries.

**A standing value is a fact about the input it was derived from** (spec §5.9,
I18). Like a human's value, it is not rederived when rules or history change;
it holds until the entry's input changes — a document linked or unlinked, which
must let a rule keyed on `PAYPAL *` give way to one keyed on the merchant
(`documents.md` §5). Its key stays as lineage, also through a commit: a commit
deletes every key that is not standing, and the standing keys of values the
user changed, so lineage no longer depends on whether anyone opened the unit.

**A rule applies at a point in time.** It decides what it matches when an entry
is resolved, and saving, changing or deleting it changes no existing value; a
standing key may therefore name a rule that has since changed or been deleted.
The preview keeps the comfort of D145 without its risk: it lists the entries
the rule matches that hold a different value, and those carrying its key that
it no longer matches, unconfirmed ones included. Confirmed units in the lists
open in the review panel, to be corrected one at a time; unconfirmed ones are
reviewed through the queue. Nothing is changed in bulk: the unexpected
consequences of a batch, such as a transfer turned into a flow, are what the
panel's preview exists to show. The merges remain the only bulk operations.
Moving spending to a category of the other kind is per unit again, which the
fixed kind makes deliberate and rare.

Rejected: dropping a rule's key wherever the changed rule would no longer
produce the value, and dropping the keys of a leg left behind — both kept
lineage in step with rules that may change, which a rule applied at a point in
time does not need.

## D160 Housekeeping after the review of the final files — *partly superseded by D161*

- The preview never proposes a leg paired elsewhere: one keystroke must not
  break another confirmed pair. Offers are sorted unpaired first, then paired,
  exact matches leading within each and then by distance in date (spec §5.7,
  `review-queue.md`).
- The picker can widen the matching window for one pick, for a partner booked
  later than the window allows. Automatic pairing keeps the window, so the
  window need not be overestimated to make late partners pickable.
- A counter-account rule does not match where its account is not open on the
  booking date (spec §3.3, §5.9), as history's evidence is filtered (D150): a
  rule for a wallet that was closed would otherwise have confirmed every later
  withdrawal onto it, unseen.
- The matcher's re-pairing of a leg whose counter-account a human chose records
  its `counterpart` key with pass `matcher` (spec §5.7, §5.9; D158).
- Accepted: a pair the matcher forms between legs whose counter-accounts are
  standing is confirmed when made, also for legs left behind by a broken pair,
  as D142 accepted for standing legs. In a cycle of wrong pairs among such legs,
  an intermediate pair may confirm before the next pick corrects it.
- Accepted: an unmatched leg on a synced counter-account whose missing data
  cannot be imported has no clean exit; unlinking the account, which makes it
  unsynced and lets it take a counter-leg, is the workaround. `plan.md` already
  observes how often a CSV for the gap is at hand.
- `review-queue.md` says what an unmatched leg on a synced counter-account
  shows: that its partner is missing from the import, with its remedies.

## D161 Housekeeping after the last spec review; a decided counter-account completes a leg — *partly superseded by D163, D165 and D181*

Partly supersedes D141, D158 and D160.

**A leg whose counter-account is decided is completed as on ingest.** D158 and
D160 made the matcher's re-pairing of a leg left behind a proposal, with a
pass `matcher`, where a human had chosen its counter-account. The review found
the same leg could still be confirmed unseen by the other path: standing
confirmation gave it a counter-leg on an unsynced account. Rather than add the
condition there too, the separate rule is dropped. A counter-account decided by
pass 0, a rule or a human is decided alike, and pairing such a leg, or giving it
a counter-leg on an unsynced account, is the same deterministic consequence on
ingest and after a broken pair; only a pairing that follows from a guess is a
proposal (spec §5.7). D141's aim that a leg left behind stays in the queue
whatever happens to it gives way: it stays where it cannot be completed, and
where it can, the result of the operation that left it behind shows what
settling did. In a cycle of wrong pairs, that result is the cue for the next
pick. The pass `matcher` is gone.

Wording, without new behaviour:

- A **proposal** is a value whose key is not standing; a standing value, like a
  value without a key, is decided. A commit writes each value with the key its
  source gives it and deletes every key that is not standing, so a rule's value
  taken over from re-resolving keeps its rule key, and a value set by hand
  carries none (spec §5.9). This is what D159's "the standing keys of values
  the user changed" meant.
- Saving, changing or deleting a rule changes no value a human or a standing
  key decided; the proposals of unconfirmed entries follow it as they follow
  any change (spec §5.9).
- Settling recomputes the proposals of unconfirmed entries, not their every
  value; a field derived by a pass carries a key while machine-derived (spec
  §5.7, §5.9).
- Accepted and stated: changing a confirmed leg's counter-account is committed
  with its new partner, or a counter-leg where the account is unsynced. Until
  the partner has arrived the old pair stands, and a tag or a note can record
  the intended destination (spec §5.9).
- Accepted: creating an account does not re-derive standing values, since the
  accounts are not the input of a value. In the case that matters — a rule
  declared a flow to what turns out to be an own IBAN — the unit is confirmed
  and would not be rederived anyway.

## D162 Wording after D161 — *partly superseded by D163 and D181*

Wording only. Since D161, settling creates a counter-leg wherever a leg's
counter-account is decided, a human's choice included, not only by standing
keys: I34, its enforcement row, the schema comment on `mirror`, spec §5.10 and
`plan.md` say so. A pair whose legs carry only standing keys, or none, is
confirmed when made (spec §5.7). And the definition of a proposal (D161) gets
its one exception: pairing between unconfirmed legs is the matcher's,
recomputed whether or not it carries a key, which is what keeps matching
independent of arrival order; a pair is decided once it is confirmed (spec
§5.9).

## D163 Every derived value carries a key; pairs stand once made — *partly superseded by D166, D167, D172, D177 and D181*

Supersedes D118; partly supersedes D142, D159, D161 and D162.

The key system had three states for a derived value — a proposal, a standing
key, no key at all — and every review round found an edge between them: a
keyless value counted as decided but could not be told from a value nobody had
derived; pairing needed an exception to the meaning of "no key"; a pair was
keyed one way when its counter-account was decided and another when it was
guessed; and whether an entry had been confirmed by rules alone could not be
read from it. One rule replaces the three states (spec §5.9):

- **Every derived value carries a key.** Passes `history` and `llm` write
  proposals. Passes `own_account` and `rule` write standing keys, and so do two
  new ones: `matcher_decision`, for a pair or counter-leg that settling made
  (D172), and `user`, for what a user decided in a commit.
- **A commit keeps unchanged standing keys.** A proposal accepted unchanged
  becomes `user`, with the proposal's key as its basis — a snapshot of what it
  was accepted on, for display and for later analysis of how often history and
  the model are right. A value set or picked by hand becomes `user` without a
  basis, and a `user` key never wraps another. An entry without a `user` key had
  no derived value decided by a human.
- **A pair is a standing value of its maker** (spec §5.7): it carries a
  `counterpart` key of pass `matcher_decision` or `user` on both legs. Whether it needs
  review is decided by the legs' other keys: a guessed counter-account keeps
  the unit in review, a decided one does not.

**What reopens a standing value** (I18) is stated once, for every kind. An
entry's input is its source row and its linked document; when it changes, the
entry is resolved afresh — a user's values included, since new input is
exactly when a decision deserves a second look. Automatically this happens
only to an entry not yet reviewed; a reviewed one gets new input only when a
user edits its user-authored source (D167). And when
a value changes, every standing value after it in field order is derived
again, the pairing last. That needs no record of which fields a pass actually
read: passes read only earlier fields, so the field order bounds every
dependency, and it closes a gap D159 left open — a category rule keyed on a
payee that history later proposed differently. Over-approximating is
harmless: a pass re-derived without a change to what it read gives the same
result, unless the rule itself changed, in which case it is applied again at
that moment, consistent with a rule applying at a point in time.

**Matching is no longer order-independent while unconfirmed.** It never was
for pairs confirmed when made (D142), and with rules for recurring transfers
most pairs are; the candidates that compete share both accounts and the exact
amount, so arrival order changes only which dates sit together, and re-pairing
corrects it. A pair now stands once made and falls only when a leg's type or
counter-account changes, or a user re-pairs it.

Accepted: an entry resolved afresh discards a user's values on a unit that was
returned to review and then had a document linked, which is rare.

## D164 The derivation index follows D163

`ix_le_derivation` was a GIN index restricted to entries with keys. Since every
derived value carries a key (D163), the restriction excluded almost nothing,
and the nested bases of `user` keys made a default GIN index large. It is now
a `jsonb_path_ops` GIN index without a partial clause, which serves the
containment lookups it exists for — the entries carrying a rule's key, those
without a `user` key — at a fraction of the size. Review state itself is read
from `review_flags` through its partial index, not from the keys.

## D165 A commit does not confirm; the panel opens for any unit, anywhere

Partly supersedes D149, D156 and D161.

D156 kept "a commit always confirms": a unit that could not be confirmed yet —
a transfer whose partner had not arrived — could not be committed, so work on it
was lost, and changing a confirmed leg's counter-account had to wait for the new
partner (D161's accepted limitation). With D163, a unit's review state is derived
entirely from its keys, its completeness and its pairing, so confirming need not
be an action at all.

**A commit writes; settling confirms** (spec §6). A commit writes the full state
the user saw, every proposal shown accepted, with the keys of D163. It needs the
result to be valid — the invariants hold — but not complete: a category, a
counter-account or a partner may still be missing. Settling then confirms the
unit when it meets every requirement of confirming, and otherwise leaves it in
review with everything committed kept. The preview says which state the commit
leads to, so the one keystroke stays predictable. This makes a "touch every entry
once" workflow possible: a leg typed as a transfer, with its destination and a
fee split off, is committed before its partner arrives, and the partner
completes it — a decided counter-account is paired without review (D161), while
a partner that differs in amount is offered rather than paired. It also lets one
user commit what they know and leave the rest to the other, and it removes
D161's limitation: changing a confirmed leg's counter-account breaks the old
pair at once, and the leg waits for its new partner.

**Every interpretation edit goes through the panel, wherever it is opened** —
the queue, the ledger list, a rule's preview — for any unit, confirmed or not.
"An unreviewed entry is read-only outside the panel" said the same with a
restriction it no longer needs. Inline edits without a preview stay excluded,
because the preview is what shows a pair breaking or a partner returning to
review.

**A change of input still resolves an entry afresh, a user's values included**
(D163). Standing is standing: a decision is made on the input it saw, and new
input is what invalidates it. Partial commits make the case more frequent — a
partly classified charge waiting for its document — and the waiting flag is the
signal for it: hands off, the input is likely incomplete. `plan.md` observes how
often work is redone.

Rejected: re-deriving only pass-derived standing values on an input change and
keeping a user's as proposals, which would distinguish two kinds of standing
for a case the waiting flag already signals.

## D166 The panel's anchor; documents keyed and held — *partly superseded by D168, D169, D229 and D230*

Partly supersedes D152 and D163.

**The panel is anchored** (spec §6) on the source transaction it was opened
from, a manual entry if it has none, or for a mirror leg its partner's anchor.
A unit is a closure — entries of a source transaction and the legs of a pair,
transitively — so a draft that picks a partner adds the partner's whole source
transaction, and one that breaks a pair removes it; without an anchor the spec
did not say which half the panel keeps. An entry that leaves the unit is shown
as a consequence. The draft may split any source transaction in the unit, the
partner's included — which the different-amount pick of D117 already relied on —
and a split made on the partner's side leaves with it. A commit's concurrency
check covers every entry it writes, not only the unit's, so a partner left
behind cannot be changed by the other user unnoticed.

## D167 A user is a source: manual entries get source transactions — *partly superseded by D168 and D170*

Supersedes D4; partly supersedes D146 and D156, and the founding rule of
spec §5.6 that no source transaction is authored by hand.

Manual entries were a second kind of movement with rules of their own: complete
at creation, never resolved, never split, edited in the panel's authored
fields, and unable to carry a document, because every structure that groups
entries — splits, links, units — hangs off a source transaction. A cash
purchase is a movement like any other: €50 paid is the transaction, and
splitting it across categories is interpreting it. So **a user is a source for
the accounts no importer fetches** (I1, I40): the entry form creates a source
transaction — amount and purpose visible; date, account and sign prefilled —
and its one entry, settling resolves it like an import, and the panel opens on
the unit. Rules on the purpose, history and later the model complete what was
typed; history learns from it through key 5, the only key a typed purpose feeds.

What distinguishes a user-authored row (spec §5.2, §5.6):

- **No importer, no run, no format.** `importer` NULL marks it; revert never
  touches it.
- **An identity, but no deduplication.** Its `source_id` is a random id the form
  generates before submitting, so the identity rule stays uniform and a repeated
  submission is skipped. The amount step compares imported rows only, and
  nothing may be marked a duplicate of a user row: two identical coffees are two
  purchases, and a person's account of a movement shares neither wording nor
  reliable dates with a bank's (D146).
- **Editable and deletable through the form, never in the panel.**
  Immutability comes from having an importer. An edit is an input change: the
  residual absorbs a new amount, or, where it would change sign, the split
  collapses into the original entry, and the entries are resolved afresh. The
  form shows a standing hint rather than checking first, and asks for
  confirmation. Where a draft's split no longer sums to a user-authored amount,
  the panel offers to set the amount to the sum.

**Manual transfers to synced accounts return.** A cash deposit is entered on
the cash account with the Giro as its `user` counter-account; it waits and
pairs when the Giro's import delivers its leg. Nothing hand-made lands on the
synced account, so I40 holds. Mirror legs and derived entries stay without a
source: they are consequences and derived values, not movements.

**The cost-preview rule is relaxed, not excepted** (spec §6): every user
operation that removes confirmed entries or returns entries to review says so
and runs only once the user confirms; the panel's preview shows exactly which,
other operations may warn in general terms.

Unchanged: the first-fetch prefill (the day after the latest entry, which
covers user rows and mirror legs alike), synced and unsynced, reconciliation and
balance records. The document link moves onto entries in a separate step.

## D168 Counter-legs are ordinary transactions; entries are movements or derived — *partly superseded by D170, D181 and D230*

Partly supersedes D110, D117, D143, D147, D166 and D167.

D167 gave every movement a source transaction but kept mirror legs outside it,
as entries of their own origin with a lifecycle of their own: created when a
pair was confirmed, deleted when it broke, recreated when the partner's amount
changed, their amount following the partner. Yet a counter-leg *is* a movement
— the €200 arrived in the wallet — and the only difference from a withdrawal
typed by hand on the cash account is that the system wrote it. A hand-typed
withdrawal paired with its Giro import already stays when that pair breaks;
treating the generated one differently would be the inconsistency.

**A counter-leg is a user-authored transaction** (spec §5.7): a source
transaction and its entry on the unsynced counter-account (I40), offered by the
panel or created by settling, and from then on ordinary. It is never changed or deleted automatically — except on a clearance account, where it is a booking of its charge (D230): when its pair breaks it stays, as a transfer leg without
a partner — completed by settling where a candidate matches (D161), and
otherwise in the queue, where it is deleted through the entry form if it was
only there to complete the pair. Its amount is the partner's, negated, or for a
cross-currency pair the instructed or entered amount; a later correction goes
through the entry form.

**An unequal same-currency pair is shown, not repaired behind the user's back.**
A draft that takes a fee or interest off one leg keeps showing the pair, marked
invalid with the difference, and the commit is refused until it is resolved.
Where either leg is user-authored, the panel offers to adjust its amount;
where both are imported, to split the difference off the larger leg; re-picking
is always possible. One rule covers counter-legs, hand-typed legs and imported
ones alike.

**Entries are movements or derived** (spec §3.9). With counter-legs as sources,
an entry either references a source transaction or a balance record, so the
`origin` column — `import`, `manual`, `mirror`, `balance` — is gone: which of the
two references is set says what an entry is (`ck_entry_kind`), and whether a
movement was imported is its source's `importer`. With it go I34, the mirror's
lifecycle rules, `ck_mirror_is_transfer`, the entry-level trigger for hand-made
entries, the field-table rows for mirror amounts, and the anchor rule's mirror
case.

Accepted: a counter-leg created by settling can duplicate one typed by hand that
was not a candidate — a date outside the window, a slightly different amount —
and a counter-leg left behind double-counts until it is paired or deleted. Both
are ordinary rows, visible in the queue, and the first-month observations cover
them.

Rejected: keeping the lifecycle as provenance, with counter-legs marked on their
source and deleted with their pair. It would have kept the interpretation layer
uniform, but made a generated counter-leg and a typed one behave differently. D230 adopts it for clearance accounts only.

## D170 Housekeeping after the review of the final state — *partly superseded by D172*

Partly supersedes D167 and D168.

- **Editing a user-authored row** (spec §5.6): the entry form edits its amount,
  date and purpose, never its account — moving a row means deleting it and
  entering it on the other account, and the schema keeps a user-authored row's
  account and currency fixed. A changed amount breaks a same-currency pair, and
  the partner is left behind like any other; the form's standing hint says so.
- **A form edit can reopen a confirmed unit.** It is new input on a reviewed
  entry, which D163 had said could not happen; it is a user's operation, warned
  and confirmed, so I20 is untouched, and the unit returns to review wherever
  resolving it afresh yields a proposal (spec §5.9).
- **An unequal same-currency pair is resolved by splitting off the difference,
  whatever the legs' sources** (spec §5.7). D168's offer to adjust a
  user-authored leg's amount is dropped: the split is the one remedy, and where
  the difference was a mistyped amount the user undoes the split and corrects
  the amount through the form. The different-amount pick no longer requires an
  imported larger leg, since every movement can be split (D167).
- **Only waiting for a document can make committed work be redone** (spec §6):
  a document's arrival changes the input; a partner's arrival does not.
- Wording: a commit never confirms in the text either — the panel commits, and
  settling confirms; the derivation section lists `document` among the keyed
  fields and covers every derived value; `raw` is immutable for imported rows;
  §5.6's panel exception is named; history learns from a typed purpose through
  key 5 and, once the payee is decided, key 3.

## D171 I3 enforced in full; counter-legs named as user-authored rows

Wording and one schema fix after the last review.

- **I3 is enforced in full.** The split check verified only the sum, and fired
  only when entries changed — enough while every source was immutable. With
  user-authored rows editable (D167), an edit of a row's amount or date without
  its entries would have passed. The check now also requires entries to carry
  their source's account, currency, `booked_on` and `value_on`, and fires on
  updates to those columns of `source_transaction` too, deferred so an edit
  writes the row and its entries in one transaction.
- **Counter-legs are named as a third author of user-authored rows** (I1, spec
  §5.6), beside ingest and the entry form. Their source has a random id, the
  partner's purpose — so it reads well and teaches history — and a `raw`
  recording the entry it was created for, as provenance nothing reads.
- **A form edit of the date** moves the row's entries with it (I3); a pair
  stands, its partner keeping its own date.

## D172 Counter-account column, one rule table, simpler revert, documents in v1 — *partly superseded by D181, D229 and D230*

Partly supersedes D28, D51, D55, D76, D120, D144 and D170. Settled after a
review of `spec.md` and `schema.sql` for implementability.

- **A transfer leg's counter-account is a column**, `counter_account_id`
  (spec §5.7, I10). D28 kept it in the `counter_account` derivation key, but a
  rule key's basis names only the rule, which may change or be deleted, and a
  value a user sets by hand carries no basis (D163), so a decided destination
  had nowhere to live. The column holds it for every transfer leg; once
  paired it is the partner's account, checked by the pairing trigger, so the
  redundancy D28 objected to cannot drift. Rejected: storing the account in
  each key's basis, which makes a value depend on bookkeeping about it.
- **The model's answer lives only in its key** (spec §5.9). Once a pass of
  higher authority or a user replaces the `llm` key, the answer is gone and
  the model may be asked again if the field falls to pass 3 later. Whether
  the plugin caches answers is its own concern. Rejected: a core table of
  answers, persistence for a case that barely matters.
- **The fetch start is derived when a run starts** (spec §5.4), never stored:
  from the sync position with coverage, otherwise the day after the latest
  entry, otherwise the importer's default, editable for that run. Replaces
  D51's choice at link time, which had no column to keep it in and was lost
  when the first fetch failed or happened later. Rejected: resuming from the
  `covered_from` of earlier runs, which would make a log-only column domain
  input, while a failed or reverted run leaves nothing to resume from.
- **One rule table** (spec §5.9). The three rule tables shared their
  conditions and had overlapping ids, so `{rule_id}` in a key was ambiguous,
  and the type decision needed an order across tables that was never defined.
  A rule now names what it sets. Order is by what it sets — counter-account,
  then payee, then category — then priority, then id. This removes the
  circularity of a category rule's payee condition taking part in the type
  decision before the payee existed. The fixed precedence of rules with a
  reference condition, and of category rules with a payee condition (D144),
  is dropped: priority alone orders rules of one kind, under the user's
  control. Rejected: keeping specificity tiers, more rules to explain for what
  a priority number already says.
- **Two matcher keys** (spec §5.9): `matcher_decision` is standing. A settling-made counter-leg's type,
  counter-account and pair carry `matcher_decision`, a commit-made one's
  `user`.
- **Documents carry a version**, incremented by ingest when what is read of it changes; `counter_account_id` now bumps an entry's version
  outside settling, like the other derived fields.
- **Runs succeed or fail as a whole; only the latest run reverts** (spec §5.1,
  §5.6, I30). The `partial` status is dropped: a failed run writes nothing,
  and an importer that got only part of the data reports success with a
  coverage to match, or fails. Only an account's latest successful,
  non-reverted run can be reverted, whatever later runs did; the user reverts
  later ones first. Replaces D55's "later runs that wrote rows block" and
  D120's "later runs that wrote nothing go with it", with the same safety and
  one rule. Document and rate runs upsert in place and are never reverted.
- **The pairing trigger also checks the former partner** (schema 8.3), so a
  half-broken pair fails at commit rather than only showing on `/check`.

## D174 Housekeeping after the implementability review — *partly superseded by D176*

Small fixes found in the same review as D172.

- **Category merges descend the tree** (spec §3.5). A child whose name the
  target's children already use is merged into that child, recursively, and
  the preview lists every category merged. Rejected: refusing the merge until
  the user renames, more friction for the same result.
- **The category tree has no cycles** (I9), enforced by a trigger; the CHECK
  covered only a category parented to itself.
- **Category names are unique per kind and parent**, so the two roots may
  share a top-level name such as "Other".
- **The three windows** — maximum rate age, matching window, document window
  — default to 7 days each (spec §3.8); D176 makes them deployment
  configuration.
- **Stated where the schema already enforced it:** at most one manual balance
  record per account and date, setting another edits it (spec §3.10); a
  payee's deletion takes the rules naming it as a condition too (spec §3.6).
- **Deduplication's tie-break** after purpose is the lowest id, with incoming
  rows choosing in delivery order (spec §5.2), so the amount step is
  deterministic.
- **`account.external_ref` is stored canonicalised**, so its unique index
  holds for what pass 0 compares. Rejected: a second, key column beside a
  display form, for an opaque identifier nobody reads.
- Wording: I3 names the entry form's edit as the other way entry amounts
  change; I7 covers "not a duplicate"; schema comments no longer speak of
  manual or imported entries where any movement is meant, and no longer cite
  `decisions.md`.

## D175 Review of the whole spec before implementation: run atomicity, zero amounts, housekeeping

Fixes from a consistency and implementability review, without new mechanisms.

- **Ingest writes a run in one transaction, under one lock** (spec §5, §5.1,
  I39; architecture §5.2). The architecture had one transaction per source
  row, which contradicted "a failed run writes nothing" (D172): a crash part-way
  left rows owned by a failed run, which cannot be reverted and which no
  coverage vouched for. The per-row lock also let another sync interleave
  inside a delivery, though the amount step needs the whole delivery's identity
  matches before it pairs by amount, and a row this delivery inserted must
  never be a candidate for another of its rows. Rejected: keeping per-row
  transactions and letting failed runs own rows, which would have reopened
  revert, coverage and I30.
- **A booking of amount zero is not a movement** (spec §5.1, §5.9). The entry
  already refused zero; the source row did not, so a bank's 0.00 notice would
  have failed the whole run, which has no partial success. Importers do not
  emit such rows, ingest counts them, `source_transaction.amount` is checked,
  and a split may not leave a zero residual. Rejected: allowing zero-value
  entries, which would only fill the queue with nothing to decide.
- **The derived-entry formulas sum movements** (spec §3.10). "Other entries"
  would count another record's derived entry when two records share a date,
  as two logins' reports of one closed day do.
- **Pass 0 excludes the entry's own account**, which the schema already
  required of every counter-account.
- **Lines of a document are signed like its total** (spec §5.5).
- **Today is the household's day** (spec §5.4; architecture §4.5): the fetch
  day, on which coverage and the reported balance rest, needs one. "Nothing in
  the domain depends on a time zone" stays true of every stored date.
- **`closed_on` may lie in the future** (spec §3.3): the account is unsynced at
  once; the date only decides where rules and history judge an entry's date.
- **A `session` table joins the schema**, which the architecture already
  described, and the currency table is seeded with the full ISO 4217 list, so
  no currency needs a migration.
- **Architecture**: settling's dirty set, with a full pass over unconfirmed
  units as the baseline and a budget measured on the plan's backfill fixture
  (§5.2); `core` is synchronous (§2); `preview` runs the settle's functions on an
  overlay, built before the panel (§6.3); a user, not a session, has at most one
  sync task (§4.3). The plan builds resolution and a settling skeleton before
  the panel.

## D176 Configuration is the environment; the ledger starts itself

Partly supersedes D174's setup of the three windows. The deployment is a
container, so the ledger-wide settings and the users come from environment
variables (architecture §5.7), with defaults where a default is safe: the three
windows are 7 days unless set.

- **No settings table, no settings operation.** The maximum rate age, the
  matching window and the document window are read once by `utils/config.py`,
  the only reader of the environment, and passed to the code that needs them;
  changing one is changing the variable and restarting, and the start settles,
  so the change reaches stored data like any write (I37). The API exposes them
  read-only, because the frontend needs the base currency.
- **The base currency stays recorded in the database**, one column in
  `ledger_setting`, written at the first start and checked against the
  configuration on every later one, which refuses to start on a difference.
  Rates are stored against it (D18), and an environment variable alone cannot
  notice that someone changed it. Rejected: the variable alone, which would
  silently misvalue every foreign amount after one edit.
- **The maximum rate age reaches SQL as a connection setting**,
  `ledger.max_rate_age`, so `base_value()` and the views using it stay
  parameterless, as `ledger.settling` already works.
- **Users are configured, never created through the app.** Indexed groups of
  login, name and password reconcile `app_user` at start; a changed password is
  a changed variable, so there is no password-change flow; a user removed from
  the environment is disabled, not deleted, because runs and importer instances
  reference them. Secrets also accept a `_FILE` variant for Docker secrets.
  Rejected: a setup CLI or a first-run wizard — another way in to secure, and
  state a container would have to be told about separately. When OIDC arrives it
  establishes sessions for verified identities and the ledger's data does not
  change.
- **Operations that were missing** from the architecture are added (§4.1):
  login, logout and who-am-I; read-only configuration; tag management and
  tagging a single entry; account edit, and deletion only while an account holds
  nothing; importer instance management with a CSV dry run; the active sync
  task; the dashboard, the one report and the CSV export.

## D177 Review before implementation: run order, afresh by the writer, settle order, classifier specs — *partly superseded by D178 and D230*

Partly supersedes D55 (what "latest run" means), D109 (where a run's status is
written), D146 (a revert's duplicates), D163 (who resolves afresh), D169 (who
writes a link) and D76 (waiting on a document source that has never run).

- **Runs are ordered as ingest wrote them** (spec §5.6, I30). A run's `ok`,
  `finished_at`, coverage and statistics are written in the transaction that
  writes its rows, under the account's lock; "latest" is by `finished_at`. Two
  syncs of a shared account fetch at once and ingest one after the other, so
  start order would let the run written first be reverted while the second
  had skipped its rows, leaving a hole. Runs left `running` by a crash are
  failed at start — one worker, so none can still be alive. Rejected: a
  per-account ingest sequence column, the same order with one more column.
- **A revert gives orphaned duplicates a new original** (spec §5.6): the
  lowest-id row pointing at a deleted row stops being a duplicate, the rest
  point at it. Repointing on "mark as duplicate" can leave several rows of
  other runs pointing at one row; clearing them all would count one movement
  twice. Rejected: refusing such a revert, which costs the user a manual
  clean-up for the same outcome.
- **Resolving afresh is the writer's** (spec §5.9, architecture §5.2).
  Settling keeps no record of what an entry was resolved from, so it cannot
  see an input change. The only two writers that change input — document
  ingest, an entry-form edit — resolve the entry in their own transaction;
  settling does the rest. Rejected: an input fingerprint per entry for
  settling to compare, a column for two call sites.
- **A settle has a fixed order and repeats until nothing new is confirmed**
  (architecture §5.2): resolution, documents, re-resolution after a link,
  pairing, counter-legs, derived entries, flags; then again over the units
  sharing a history key with one newly confirmed, until a round confirms
  nothing new — it terminates because settling never unconfirms a unit, and
  two rounds are the ordinary case (D178). Rejected: one round, leaving
  history's effect to the next write, which breaks idempotence. Lock order is
  stated: settle lock first, account locks ascending.
- **Classifier specs are written ahead** (`plugins/classifiers/rules.md`,
  `history.md`). Rules compare references and booking texts canonicalised,
  names case- and whitespace-normalised with punctuation kept — so
  `PAYPAL *` does not match "PayPal Europe" — and purpose regexes
  case-insensitively, unanchored. History's key 5 starts as token-set Jaccard
  ≥ 0.5 over a symmetric 365-day lookback. Classifiers get their evidence from
  core — the rules, and a read-only history source — and never query the
  database. Rejected: canonicalising names like references, which merges
  descriptors that differ only by punctuation.
- **Counter-legs on an account linked later are accepted** (spec §5.4).
  Settling completes legs pointing at an unsynced account with counter-legs;
  if that account is linked later and its own history imported, nothing
  deduplicates the two. Linking shows the user-authored rows the account holds
  and warns, and the plan links accounts before importing. Rejected for now:
  automatic counter-legs only on hand-kept account kinds, a rule by kind; and
  an explicit "kept by hand" flag, a new concept — the upgrade if the first
  month shows the case recurring.
- **Smaller decisions.** Unique indexes stay non-deferrable, writes clearing
  the old holder first (rejected: deferrable `EXCLUDE` constraints, an
  extension for an ordering rule). The locale is the deployment default,
  overridden per browser, stored nowhere (rejected: a per-user column). The
  model's answer lives only in its `llm` key with a payload fingerprint, as
  spec §5.9 says (rejected: a plugin table, which the architecture had
  described).
- **Fixes.** A source row inserted without its entry is refused by
  `trg_duplicate_state`; only `ok` runs carry coverage, and the coverage views
  read only those; `base_value()` scales before dividing; waiting ends when
  coverage *reaches* the end of the window, for transfers and documents alike;
  an entry-form edit that would leave the residual at zero collapses the
  split; changing an account's `external_ref` changes no standing value; I19
  says "standing values", which counter-legs' keys are; units decided by rules
  appear in the queue while they wait; link and unlink are operations.

## D178 Second review before implementation: counter-legs, pairs, merges, documents, settling — *partly superseded by D179, D181, D225 and D230*

Partly supersedes D141 (what a leg left behind keeps), D156 (counter-legs on a
closed account) and D177 (settling's rounds).

- **A counter-leg follows its partner in a commit** (spec §5.7). Counter-legs
  were once derived and are now ordinary user-authored rows (D168), so a split
  taking interest off the Giro leg left the pair unequal, and the written remedy
  — split the difference off the larger leg — put the interest on the loan.
  Where a draft changes the amount of a leg paired in one currency with a
  user-authored leg that is its source's only entry, on an unsynced account
  (D179), the commit sets that source's amount to match. Rejected: restricting the entry form on paired
  counter-legs, which would couple the source layer to its interpretation. The
  form stays a full re-resolution, the user's values included (spec §5.6): the
  panel is where interpretations are edited, and editing what a source says has
  those consequences.
- **Counter-legs whose partner is removed stay**, as ordinary rows, and return
  to review unpaired. Rejected: deleting them with their partner, which would
  make them less than ordinary transactions. (Settling no longer creates
  counter-legs at all, D181.)
- **A counter-account its pair set belongs to the pair** (spec §5.7, §5.9).
  Pairing fills an empty counter-account (I10); as a value before the pair in
  field order it would have derived the pair again, and after a break it would
  have left the leg "decided" by nothing anyone chose, to be paired anew.
  It is keyed with the pair as its basis, starts no cascade, and leaves with
  the pair. *Decided* is any standing key, everywhere.
- **Merges repoint with their keys** (spec §3.5, §3.6): nothing is derived
  again and nothing returns to review. Merging a category into its own
  descendant is refused: the user merges the descendants upwards and renames.
  Rejected: lifting the target first, an outcome not obvious from the action.
- **Only rules judged before the payee decide the type** (spec §5.9):
  counter-account rules, payee rules and category rules without a payee
  condition. A payee-conditioned category rule applies in its own field, on a
  payee proposed or decided; its standing value is derived again when the
  payee changes, as I18 already says. Rejected: keying the type from whichever
  value implied it, which needed a rule beside the cascade.
- **History counts every match** (`plugins/classifiers/history.md`), as spec
  §5.9 says: a flow without a payee votes for no payee.
- **Settling** resolves with the current link; it repeats rounds until none
  confirms anything new, since a new confirmation can also remove a majority
  and let another unit confirm (correcting D177). `finished_at` is read with
  `clock_timestamp()` after the account lock, because `now()` is the
  transaction's start and would order a run that waited first.
- **Contracts and fixes.** A commit carries the draft, the shown values and
  bases, temporary ids and versions, and the server derives the keys, so a
  client cannot assert a standing one; versions are checked under row locks in
  id order, and a unique violation is a named conflict. "Previewed" operations
  take a dry-run flag. PUT for categories and payees; a payee's
  `document_provider` is a write. The revert and category-merge statement
  orders are written down. In the schema: an instance's deletion may null its
  rows' link; the deferred triggers fire only on the columns they check; the
  duplicate check re-reads its row; an account's currency is fixed by trigger;
  `base_value()` rounds exactly; two integrity views were added. `external_ref` may be
  set on any account. The plan gains an order its
  steps can follow.

## D179 Re-review of D178: counter-legs only where nothing is offered — *partly superseded by D180 and D181*

Partly supersedes D144 (when settling creates a counter-leg) and D178 (where a
counter-leg follows its partner).

- **Open offers come first** (spec §5.7; defined in D180): a counter-leg edited
  through the form, one left behind by a broken pair, or a withdrawal typed by
  hand is offered before a new counter-leg. Since D181 only a commit creates
  counter-legs, so nothing duplicates them automatically.
- **A counter-leg follows its partner only on an unsynced account**, and
  following is not an input change, so its values stay. I2 and I3 name it; on
  an account since synced, the unequal-pair remedies apply instead.
- **A counter-account set by a pair** is keyed with the pair's pass and the
  basis `{"from": "counterpart"}`, also when a commit's pick fills it, and
  leaves with the pair. *Decided* means a standing key for values; for the
  document field, a link of any key or "none", so a proposed link is not
  matched again.
- **Merges** are carved out of I18: repointing is not a change of value.
- **A majority for no payee ends the field** (spec §5.9): nothing is
  proposed, and neither a later key nor the model is tried.
- **Locks:** a write takes its advisory locks before row locks; settling,
  which cannot know its accounts upfront, is rerun when PostgreSQL aborts it
  on a deadlock, and an aborted commit is retried once.
- **Fixes.** Enrichment applies to the preview of any unit, re-derivation only
  to unconfirmed ones; linking is a change of the first value, not "afresh".
  Rule changes use the dry-run convention. `plan.md` and `schema.sql` no
  longer cite documents that depend on them. An entry's source transaction is
  fixed by trigger; successful transaction and document runs must carry a
  through date; an integrity view checks that the anchor's derived entry is
  the opening. Stale "keeps its values" wording and the architecture's follow
  wording are aligned; tests cover the follow, closed accounts and the offer
  condition.

## D180 Open offers, and what the preview proposes — *partly superseded by D181*

Partly supersedes D179 (which offers block a counter-leg).

- **An open offer** (spec §5.7) is an unpaired transfer leg or an untyped
  entry on the counter-account, opposite in sign and within the window, of
  any amount — not a leg whose own known counter-account is another account.
  Read literally, "no offer" was never true: offers include legs paired
  elsewhere and the counter-leg itself; and without the sign and the
  counter-account filter, a cash expense or another wallet's leg would have
  counted. Open offers decide what the preview proposes (D181).
- **The preview proposes only an exact open offer**, or, where the leg has no
  open offer at all, the counter-leg. Open offers of another amount are listed
  first and never proposed: with any of them and none exact, nothing is
  proposed and the user picks. A leftover counter-leg of an old amount then
  surfaces as a choice rather than as a quiet split. Rejected: proposing the
  first open offer whatever its amount, which proposed pairing a €200
  withdrawal with a €50 gift and splitting €150 off a synced leg.
- **Stated limits and wording.** A withdrawal typed by hand after settling
  made its counter-leg is not compared with it, and is watched in the first
  month. Following a partner is carved out of "input" in I18 and §5.9, and
  named for any user-authored single-entry leg on an unsynced account; the
  `{"from": "counterpart"}` basis is listed among the key shapes; "no payee"
  ending the field is named where pass 3 and the field order are defined; a
  `matcher_proposal` link is a proposal for review and a decision for
  matching. Settling is named as the exception to "advisory locks before row
  locks", rerun after a deadlock abort; a commit whose retry fails answers
  "try again". Crash recovery sets `finished_at`; the unreachable
  source-change clauses left by D179's trigger are removed.

## D181 Full scan before implementation: settling creates no counter-legs; history and documents; locking — *partly superseded by D225 and D230*

Partly supersedes D161 (a decided counter-account completed by a counter-leg
settling creates), its restatements in D162, D163, D168 and D172, and D178,
D179 and D180 as far as they concern automatic counter-legs.

- **Only a commit creates a counter-leg** (spec §5.7; on a clearance account, settling books it from the charge, D230). Automatic creation by
  settling drove most findings of the last rounds — open offers as blockers,
  closed accounts, follow rules, duplicates, linking order — and it made a
  deleted counter-leg come straight back. A decided leg on an unsynced account
  now waits with its counter-leg proposed, where its counter-account holds no
  open offer, and one keystroke commits it; a rule-decided withdrawal costs
  that keystroke. Settling creates no rows and takes no account lock — bookings on clearance accounts apart (D230).
- **Settling is exclusive, writes share** (architecture §5.2): every write takes
  the settle lock shared, settling exclusively. Settling had read units
  without the lock commits use and could write stale proposals over a commit;
  document ingest raced it the same way. Rejected: re-locking and re-checking
  each unit inside settling, more code for the same guarantee.
- **The overlap never reaches into hand-kept history** (spec §5.4): a fetch
  starts no earlier than the day after the account's latest user-authored row.
  After an account kept by counter-legs was linked, the second fetch otherwise
  re-imported its last week as rows nothing deduplicates. Rejected: bounding
  by the first fetched day, which the domain does not read.
- **History keeps its strict majority**, to be watched in the first month for
  mixed payees. Rejected for now: a threshold, which only trades a systematic
  error rate for another; and unanimity, which one slip disables for a whole
  lookback.
- **Fixes.** A category is deleted only without entries, rules or children.
  The commit's set-to-sum joins I2, I3 and the copied-fields table. Entering
  and editing a user-authored transaction recompute derived entries under the
  account lock. A
  sign change through the entry form breaks any pair. The plan gains login and
  sessions, tags, and category and payee management with payee merge, and
  watches mixed payees.

## D182 UI components: shadcn-svelte on Bits UI

The stack named Svelte 5 and SvelteKit but no component layer (architecture
§2). The app's important screens are custom in any case; what a library must
supply is the accessible, keyboard-correct generic widgets — dialogs, the
searchable pickers used constantly in review, menus, tooltips, toasts, a date
picker. shadcn-svelte supplies them as components copied into the repository,
on Bits UI's headless primitives: the code is owned and adapted to the dense
look of `ux/patterns.md`, the runtime dependency is Bits UI alone, and
Tailwind runs at build time. Copied components are updated deliberately, by
copying again and reviewing the diff. `components/ui/` holds them and is the
only importer of Bits UI (architecture §6.2).

Rejected: Flowbite-Svelte (many finished components, but an opinionated look,
uneven keyboard behaviour and a large installed surface, with tables that are
not data grids); Skeleton (a design system aimed at a different look, weaker
pickers); Bits UI with hand-written CSS (the same primitives, everything styled
from scratch); no library (accessible pickers and dialogs are easy to get
subtly wrong).

## D183 One generic CSV importer; a card's payment is synthesised

Three real exports — a giro with a preamble, a pending flag and a balance in the
header; a card with a footer balance, two columns named alike and no payments;
a card with inverted signs, multi-line cells and no balance — differ in layout
and parsing, never in what they deliver. So the importer is one, configured by
a profile held as data (`plugins/importers/csv.md`), and a bank is a preset
file, not code. A model may later propose a profile from a sample, which is
judged by the dry run like any other; it is never in the import path.

- **A balance may be a labelled figure** (spec §5.1). None of the three has a
  running-balance column, and two state the balance elsewhere. A figure dated
  the export day is rolled back by the booked rows of that day to the last
  closed day, so the record obeys the rule that the balance equals the sum of
  entries up to its date. Rejected: dating the record at the export day, which
  breaks I36 and would be corrected by a reconciliation on every sync.
- **A card that lists no payments gets one synthetic movement per file**
  (spec §5.1, §5.7): the negated net sum, `counterparty_ref` set to the paying
  account so that pass 0 types it, dated coverage plus *N* days, marked
  `csv:synthetic`. A statement is one month and no other range can be exported,
  so each file is self-contained. It must be dated after the balance record,
  or every reported balance reconciles by the statement itself.
  Rejected: *a flag making the account unsynced for transfers*, with I40
  relaxed — a state on the link and a rule with an exception, for what one row
  expresses; *leaving the card unlinked* — it loses runs, coverage and
  reported balances; *accepting the reconciliation as the payment* — the
  unexplained difference becomes permanent noise and the paying account's leg
  never pairs; *deriving the payment from consecutive balances* — needs both
  statements and invents a date.
- **The amount is the net sum of the rows, not the balance.** It needs no
  balance and no earlier statement. It assumes payment in full; where the debit
  differs, the offers and the reconciliation say so (spec §5.7, §5.10).
- **Goal 1.1 has one exception**, the movement the source implies; it is
  marked, and its `raw` records what it was derived from.

## D184 The content hash: SHA-256 over named, length-prefixed fields of canonical text

Spec §5.2, I4. Every stored `content_hash` is a function of these rules, so
they are in the spec: changing one means rehashing from `raw`.

- **SHA-256 over each field written as its name and its value, both
  length-prefixed.** No value can imitate another field's text. Rejected: *a
  concatenation joined by a separator* — values containing the separator move
  the boundary between fields, and two different rows collide.
- **Text is canonicalised before hashing: NFKC, case-folded, letters and digits
  only.** Absent equals empty. Rejected: *hashing the raw text* — two exports of
  one booking differ in spacing, punctuation and line-joining, so the same
  payment would stop deduplicating against its own history.
- **The ordinal groups rows by their canonical text.** Rejected: *grouping by
  the raw values* — rows that differ only in spacing would fall into different
  groups and take the same ordinal, so identical payments would collide or
  split depending on formatting.
- **The spec states properties; the exact byte layout is fixed by the
  implementation and frozen by a known-answer test** with a few digests. The
  spec cannot cite code, and tests that assert properties alone would pass an
  accidental change of layout that silently stops deduplicating against stored
  hashes.

D46's statement that a `source_id` is also a hash input no longer holds: D103
made identity the `source_id` where there is one and the hash otherwise, and
the spec's ordinal is absent for a row with a `source_id`.

## D185 A breach of the importer's contract fails the run

Spec §5.1, §5.2, I29. The importer is told what to emit: the account's
currency, no zero bookings, one record per `source_id`, a coverage. A record
that breaks this is a fault in the importer or its profile, and one rule
handles every case: the run fails, writes nothing, and names the rule.

- **The importer drops zero bookings and reports how many**, which the run's
  statistics record, so the import log stays useful. Rejected: *showing the
  count only in the importer's dry run* — the log would lose it.
- **A new error kind, `ContractViolation`**, because a wrong currency on a
  profile is fixable by the user, unlike `ParseFailed`, which needs a code fix.
  Rejected: *reusing `ParseFailed`* — no taxonomy change, but a misleading
  label.
- Rejected: *skipping and counting each case* — the cases would be handled
  inconsistently, and a profile linked to an account in another currency would
  refuse every row yet report a successful run.

## D186 A commit's version check covers every entry it writes

Architecture §4.1. Granularity is per entity (§4.1), and an entry written as a
side effect — a transfer partner unpaired by a removal — is one. Rejected:
*checking only the entries the user acted on* — a removal could then overwrite
a partner another tab had just changed, which is the lost update the per-entity
check exists to refuse.

## D187 The CSV profile's rules, settled against real exports

`plugins/importers/csv.md` §2–§5, spec §5.1. Three real exports (a giro, two
cards) fixed what the profile must say.

- **A configured label that is not found, or a value that does not parse, fails
  the run** (`ParseFailed`). Rejected: *reporting no balance* — a wrong profile
  would pass unnoticed and the account would drift to manual reconciliation;
  the dry run is where it is fixed.
- **A label matches a whole trimmed cell first, then a cell containing it; first
  match in file order, whole file searched.** In the giro export the label also
  occurs inside another cell of its row. Rejected: *contains-first* — it picks
  that cell. The offset is a profile number (cells right, rows below) because
  the card's value sits six cells right of its label.
- **The export date is a profile setting read like a balance date**, falling
  back to the upload date passed in (a plugin never reads the clock). The giro
  figure is dated the export day, so the roll-back needs it. Rejected:
  *coverage = upload date* — it is wrong for a file saved earlier (spec §5.1).
- **Roll-back:** the record is dated at the last closed day and equals the
  figure minus the booked, unfiltered rows after it; a figure on or before that
  day is used as dated.
- **Filters read the cell before parsing**, so a pending row's text in a date
  column is filtered, not a parse error; two operators, `equals` and `matches`.
- **`invert amounts` also inverts the instructed amount**, one convention per
  profile. Rows after a stated period end are kept and coverage stays that end:
  a later fetch overlaps them and ingest deduplicates. Credit and debit is
  `credit − debit`, empty as 0. Text is trimmed and collapsed in normalised
  columns, `raw` keeps the original. Decoding is BOM, UTF-8, then `cp1252`.
- **`filtered` stays zero bookings only**; pending and filtered rows appear in
  the dry run, not in stored statistics. Rejected: *storing them* — the
  figures would vary with the profile, not with the data.

## D188 A file importer is a pure parse; counts are named; the dry run is the real path rolled back

Architecture §4.1, §5.5, spec §5.1. The fetch protocol (authenticate, discover,
fetch from a date) does not fit a file.

- **A file importer parses bytes given the profile, the account's currency,
  minor-unit exponent and today's date**, and returns rows, reported balance
  and date, coverage, data start and its counts. Its own problems raise
  `ParseFailed`; ingest's `ContractViolation` remains the backstop.
- **The importer's counts are a mapping of named integers** stored under the
  run's statistics (`filtered`, `synthetic_skipped`). Rejected: *one ingest
  parameter per counter* — each new count would change the interface.
- **The upload's dry run is the real path in a transaction that is rolled
  back**, returning the run summary and the parse report. Rejected: *a separate
  preview path* — it would drift from the real one, which the §4.1 convention
  exists to prevent.

## D189 The balance record is dated at the earliest of the figure's date, the last closed day and the coverage

Spec §5.1, I36, `plugins/importers/csv.md` §5. The old rule dated a figure at its
own date or, if dated after the last closed day, rolled it back to that day; where
that day fell after the run's coverage the run reported no balance. A quiet
account, whose last booking is earlier than the closed day, therefore lost its
balance on every sync.

- **One rule:** the record is dated at the earliest of the figure's own date, the
  last closed day and the coverage; where that is earlier than the figure's
  date, the amounts of the booked, unfiltered rows after it, up to the figure's
  date, are subtracted from the figure. I36 holds by construction and a quiet
  account reports its balance dated at its coverage.
- Rejected: *reporting no balance, falling back to manual records* — the account
  would drift to manual reconciliation for no fault of the data.
- Rejected: *dating the record after the coverage and relaxing I36* — the record
  would then claim a day the run has not seen.

## D190 `ParseFailed` covers a profile that no longer fits

Architecture §5.5, D185, D187. A missing header row or label is fixed in the
profile, not in code. The two non-retryable kinds stay separate by *cause*, not
by who fixes them: `ParseFailed` — the importer could not read the file as
configured; `ContractViolation` — the importer read it and delivered what its
contract forbids, and the error names the rule. Rejected: *merging them* — the
queue would behave the same (both are not retried), but the user would lose
which side failed and, for a breach, which rule.

## D191 Categories, accounts and payees carry an icon and a colour, presentation only

Spec §3.3, §3.5, §3.6, §3.7. Icons and colours make the ledger list, the
review queue, pickers and the report scannable, which is how they are read.

- **One rule for every curated dimension.** Categories, accounts and payees
  carry the same two attributes with the same semantics, so the spec states it
  once and the UI has one picker. Tags carry a colour only: they are short-lived
  episodes, shown as chips. Rejected: *categories only* — accounts appear in
  most lists and two of one kind need telling apart, and a second schema change
  later would cost more than the columns do now.
- **Names, not values.** Each stores an icon name and a colour name from fixed
  sets the UI defines; a tag's colour is a name from the same colour set.
  Contrast and a later dark mode are then the design system's to keep, once.
  Rejected: *free hex colours* — every user choice would need a contrast check
  and a dark variant; *the theme's colour tokens* — too few, and with meanings
  (sign, primary) a dimension's colour must not borrow.
- **Curated per dimension.** Each picker offers the icons that suit it —
  merchant kinds for payees, account kinds for accounts — not the whole
  library.
- **Unchecked in the database.** A name the UI does not know renders as its
  default, so the sets can change without a migration. Rejected: *a CHECK on
  the names* — it ties the schema to the icon library's naming.
- **Defaults are derived, not stored.** A category inherits down the tree, an
  account's default follows its kind, a payee's is its initial; a merge keeps
  the target's own. Rejected: *copying the parent's or the kind's on creation*
  — a later change would leave the copies behind.
- **The colour set is also the chart palette,** so a category's bar matches its
  icon. One set instead of two.
- **Custom icons are a later extension of the same column:** a name such as
  `custom:<id>` naming an uploaded image, which needs the storage attachments
  need. Rejected for good: *logos fetched by domain* — they send the
  household's merchants to a third party.

## D192 The ledger list pages by offset and sorts so a split stays together

Architecture §4.1, spec §8. The list answers one page of the entries a filter selects, with the count.

- **Offset and limit, with `total`** (limit 1 to 500, default 100). The count is needed anyway: "Tag all…"
  confirms a number, and the list says "N of M". Keyset paging is correct under concurrent inserts, but the
  list is a snapshot patched in place (patterns §7), so no row appears or moves under a page, and two users
  rarely write at once. A page of 100 plus the count stayed within its budget on 8,000 entries, a deep page
  included. Rejected: *keyset* — it buys an insert-stability the list does not need and cannot give `total`
  or a jump to a place cheaply.
- **Order `booked_on` descending, source transaction descending (none last), id descending.** The siblings of
  a split share a date and a source transaction, so they are adjacent without any grouping; derived entries
  have no source transaction and come first within their day, above its movements, because a balance record
  states the balance at the end of its day (spec §5); an opening, dated the day before the first movement, is
  the oldest row of its account (I13). Rejected: *derived entries last in their day* (the first build) — in
  a newest-first list it reads as if the balance were taken before the day's movements. The order is total, so pages never overlap. Rejected: *`booked_on` and id only* — siblings
  would be adjacent only when their ids happen to be, and an entry from another source could fall between
  them; *sorting by `value_on`* — the domain buckets by `booked_on` (spec §8). Changing the order later
  would change what a page holds, so it is part of the contract.
- A split that straddles a page edge is rare and acceptable (D196).

## D193 Filter semantics: OR within a dimension, descendants by default, amounts by magnitude

Spec §8, architecture §4.1. One filter serves the list, the tag operation and the report drill-downs, so
what it means is stated once.

- **Several values of one dimension are alternatives, dimensions combine.** Picking two accounts or two tags
  widens; adding a dimension narrows. Rejected: *AND within a dimension* — an entry has one account and one
  payee, so two of them would match nothing, and "either of these tags" is the useful question.
- **A category includes its descendants by default;** `category_descendants=false` asks for exactly one.
  Choosing "Groceries" and seeing only the entries filed directly under it would hide most of them.
  Rejected: *exact by default* — a parent would then be a category of its own rather than a group, which is not how a tree of categories is read (spec §3.5).
- **Amounts are compared by magnitude, in one currency named with the bounds,** with an optional direction.
  A signed range reads wrongly for spending (−50 to −10), and a range over currencies is meaningless; the
  currency is required and nothing is converted, because only reporting converts (I27). Rejected: *a signed
  range* — "between 10 and 50" would match refunds but not purchases; *converting to the base currency* —
  a rate-dependent filter would change as rates arrive.
- **Text is a case-insensitive substring match, every word required, over the entry's description and note,
  the source's counterparty, purpose, end-to-end id and mandate reference, the payee's and the category's
  name.** These are the places a user remembers a transaction by. Rejected: *description only* — the
  counterparty is often the only text; *full-text search* — an unindexed scan took under 30 ms on 8,000
  entries, so no index is needed yet (architecture §11 keeps the scale caveat).
- **`uncategorised` selects the entries that could have a category and have none: type `flow` or no type yet,
  and no category; never a transfer or a derived entry.** It is an alternative to the categories chosen beside
  it. Rejected: *flows only* (option A) — entries that an import has produced and nothing has typed yet are
  the first thing a user wants to find, and they are the "no type yet" half of the report's Unclassified
  line (§8); *every entry with no category* (option C) — transfers and derived entries have none by nature
  and would drown the result.
- **Type and review flag are dimensions too,** because the dashboard's drill-downs need them. Derived entries
  are listed unless the type excludes them (patterns §4.1 shows them).

## D194 Tagging a filter's result is previewed, guarded by a count, and never a keystroke

Spec §3.7, architecture §4.1, D137. Applying a tag to a filter can touch thousands of entries.

- **Always previewed and confirmed.** The preview reports how many entries would be tagged, how many already
  carry the tag, how many derived ones are skipped, the accounts affected and the tag's span before and
  after. Confirmation scales with cost (patterns §6).
- **`expected_count` guards what the preview counted, and a real run must carry it.** Tags move no
  `ledger_entry.version` (they are not part of review), so the version rule cannot protect the selected set.
  The confirming request carries the preview's number (422 without it), and a different one writes nothing
  and answers 409. Rejected: *an optional guard* (the first build) — a real run without it would be the one
  unguarded write over a filter, and the only client always has the number; *locking the set between
  preview and confirm* — the user may think for a minute; *no guard* — another sync or the other user could
  widen the set after the user looked; *a token for the preview* — more state for the same protection.
- **An empty filter is refused.** Otherwise a cleared filter bar and one confirmation would tag the whole
  ledger. With an empty filter the list's button is disabled ("Narrow the filter first"); a user who means
  every entry gives a date range that covers them. Rejected: *an `all` flag that overrides the refusal*
  (the first build) — the API has one client, which never sets it, so it was a parameter, a rule and an
  error path that nothing used.
- **Tagging moves no version and takes no account lock;** it takes the settle lock shared and settles after
  commit, like every write. Derived entries are skipped and counted, not an error (I13).
- **The `t` key tags the row under the cursor; "Tag all…" is a visible action of the filter bar,** with no
  count on its label (the dialog states it, D195). The dangerous action is never one keystroke. `t` opens a
  searchable list of tags for the row (`Enter` toggles through the single-entry operations, a new name is
  created in place); a derived entry refuses with a quiet notice, as the API does. Rejected: *`t` for both, the second after a confirmation* (the
  earlier patterns text) — the same key meaning two operations of very different reach.
- **Untagging by filter and merging tags are deferred.** A tag comes off one entry, or goes with the tag
  (the answer counts the memberships removed); neither was needed to try the list. Revisit after the
  prototype.

## D195 "Tag all…" states the server's numbers and leaves the rows you changed to an opt-in

Patterns §5 and §7, D194, plan C10. A tag action leaves rows in the list that an active tag filter no longer
matches: they stay, marked, until the list is fetched again (nothing moves under the cursor). The filter-based
apply works on the server's result, and that result no longer holds those rows, so the dialog has two sets to
account for.

- **The numbers are live and the filter is captured when the dialog opens.** The preview is a dry run; its
  headline ("Tag all N entries") is the server's `selected`, not the number of rows held nor the list's
  `total`, which belong to a snapshot; the button carries no number for the same reason. The confirming
  request carries the preview's `newly_tagged`; when the result has moved (409 `filter_result_changed`) the
  dialog previews again, says what the number was and is now, and asks again. Rejected: *the list's total as
  the headline* — it may be stale, and the user would confirm a number the server will not use; *a count on
  the button* — it would need a request per filter change or show a stale number; *re-running silently
  with the new number* — the user would confirm something they have not seen.
- **Marked rows are explained, and tagging them is an opt-in that is off by default.** When the list holds
  marked rows the dialog says that the filter does not include them; for those the chosen tag would still
  change (not derived, not already tagged) it offers "Also tag the N rows you changed that are still shown".
  They are tagged after the filter-based apply, through the single-entry operation, up to four at a time; a
  failure for some is reported inside the dialog (what worked, how many failed and why), the preview is
  taken again, and nothing already written is undone. Confirm is possible when the filter would tag nothing
  but the opted-in rows would be. There is no new server operation (architecture §4.1: none works on a list
  of ids). Rejected: *"Tag all" acting on the rows shown (a selection)* — the filter is the selection
  (patterns §5), "all" would then mean two things, and the rows shown depend on how many pages were loaded;
  *the explanation alone* — it leaves the user to tag those rows one by one, though they are exactly the
  rows they just handled; *reloading the list when the dialog opens* — it would drop the marks and move
  rows under the user (patterns §7) before they decided anything; *including the rows by default* — the
  action would then do more than the filter says, which is the surprise the preview exists to prevent.
- **The opt-in is the first candidate for removal.** It is the most involved part of the action (a second
  set, a bounded fan-out, partial failure reported in the dialog). If the first month shows it unused, it
  goes, and the explanation alone remains (patterns §10).

## D196 The ledger list is a list of entries; units are drawn, never rows

Spec §6, architecture §4.1, patterns §4.1, D192. A split's entries share a date and adjoin in the sort; a
transfer's legs may be days apart.

- **Every row is an entry.** Filter, order, count, page, tag and any later sum are defined on entries and
  never change; grouping is presentation. A split's entries sit next to each other, visually joined, with a
  marker on each of its rows; the unit opens in the panel.
- **A transfer leg carries a read-only summary of its partner** (account, date, amount: one join, an additive
  field). It works when an account filter hides the partner, and the partner's row is
  highlighted when visible. Sorting cannot bring the legs together without lying about a date.
- Rejected: *a parent row per unit with an expander* — a split's total is not an entry, so the row could not
  be filtered, counted or tagged like one, and an expander moves rows under the cursor; *one row per
  transfer pair* — it hides a leg from an account filter and needs a rule for which date the pair sorts by;
  *sorting a pair by one of its dates* — the other leg's date would be wrong; *paging by units* — it breaks
  the count and offsets. Where a page edge cuts a split badly, the server may extend a page to the end of the
  unit; the paging stays by entry.

## D197 The OpenAPI document is generated, committed and exposed only in development

Architecture §4.4, §5.7, §6.7. The frontend's types should come from the API, not from a second hand-written
copy.

- **`EXPOSE_OPENAPI` (default off) serves `/api/openapi.json`; `/docs` and `/redoc` never exist.** They load
  scripts from a third-party host, and the app loads nothing from one (§6.7). Rejected: *always on* — an
  unauthenticated description of the API in a deployment for no need.
- **`scripts/dump_openapi.py` writes `frontend/openapi.json` from the application object,** with no database
  and no server, deterministically (sorted keys), and `--check` fails when it is stale. Rejected: *dumping from
  a running server* — it would need a database and a started process just to refresh a file.
- **The generated schema and `frontend/src/lib/types/api.d.ts` are committed.** A change to the API then shows
  as a diff, and an agent or a CI job without network access can check them. Rejected: *generating on every
  build* — it hides contract changes and needs the Python environment in the frontend build.
- **The document says what the server does:** operation ids are the handlers' names, and the error envelope
  (§4.4) replaces FastAPI's default validation error on every operation, so the generated error types are
  right. Rejected: *FastAPI's default 422 schema* — it describes a body the API never sends.
- **`openapi-typescript` generates the types, and the client stays a thin hand-written `request()`** that
  routes on the error `code`. The generator's own TypeScript dependency is overridden by npm to the
  project's (TypeScript 6). Rejected: *a generated client with a runtime* — one more dependency between the
  views and `fetch`, which only `lib/api` may call (§6.2).

## D198 A rule has a name; it has no enabled flag and no version

Spec §5.9, schema `rule`, patterns §4.3. Evidence has to explain why a value was decided, and a rule's conditions
are a poor explanation.

- **`name` is required, trimmed, not blank and unique case-insensitively,** like a tag's or a payee's. Evidence
  renders as "rule: its name", linking to the rule, whose own page shows the conditions. A key whose rule was
  deleted renders as "rule deleted": the basis holds only `rule_id`. Rejected: *no name, the rule rendered as its
  conditions* — a regex and three conditions do not say what the user meant; *an optional name* — evidence would
  then fall back to something else half the time.
- **There is no enabled flag and no version.** Deleting a rule is the off switch, and the last write wins: a rule
  write changes no entry (I20), so there is nothing a stale editor could overwrite that matters. Rejected: *an
  enabled flag* — a second way to turn a rule off, and a state every list and preview would have to explain.

## D199 A rule's `sets` is fixed at creation

Spec §5.9, D198. Like a category's kind (spec §3.5): a key's `{rule_id}` keeps its meaning, and the groups of the
rule list do not change under the user. The target value, conditions, priority and name can be edited.
Rejected: *changing what a rule sets* — a rule for a payee becoming a rule for a category is a different rule;
delete and create it, with a preview each way.

## D200 A merge bumps the versions of the entries it repoints, and a stale id is a `stale_reference` conflict

Spec §3.5, §3.6, architecture §4.1, I18. A merge changes an entry's category or payee, which is a user-meaningful
change: `trg_le_version` bumps the entry, an open panel showing the old value is refused and reloads (patterns §8).
Settling does not bump because its rederiving is constant and would conflict every panel all the time; a merge is
rare and explicit, so the conflicts it causes are cheap. A merge still decides nothing anew (I18): keys kept,
nothing derived again, nothing returned to review.

- **A stale id is a separate case the version does not cover.** A stale lookup list or a picker in another tab can
  name a category, payee or account that no longer exists. Any write doing so is refused as 409 with the code
  `stale_reference`, details naming the field, never as a generic validation error; the client reloads its lookups
  on that code, with the refresh-in-place of other conflicts (patterns §8).
- **A merged-away id is simply an id that no longer exists.** No redirect, no `merged_into`: it would be a second
  mechanism for a case the one refusal covers.
- Rejected: *merging under the settling flag so versions do not move*: it hides from an open panel that the value
  it shows is gone, needs a special case in the trigger rules, and rests on a rationale (settling's) that does not
  apply to a rare explicit operation.

## D201 Merge details: into an ancestor, the target's attributes, payee delete

Spec §3.5, §3.6. Settled where the spec was silent.

- **A category may merge into its own ancestor.** Its children move under the ancestor; the source is left out
  of the ancestor's children when same-named ones are matched, or it would collide with itself. Merging into a
  descendant stays refused (I9).
- **On a payee merge the target's attributes win** (name, note, icon, colour, `document_provider`); the preview
  warns when the source's `document_provider` would be lost. Rejected: *merging attributes* — a rule for which
  one wins per field is more than the occasion needs.
- **Deleting a payee deletes the rules that set it or name it as a condition, and the preview lists them.**
  Entry keys naming a deleted rule stay and render "rule deleted" (D198).

## D202 Merges and rule writes are previewed and guarded by a count

Architecture §4.1, D194. The tag convention is reused rather than a second one.

- **Previewed:** category merge, payee merge, rule create, update and delete, payee delete and category delete.
  The other dimension writes go directly. The real run of a merge or rule write carries `expected_count` from its
  dry run; a moved number is 409 `conflict`, reason `filter_result_changed`, and nothing is written. Rejected:
  *versions on rules* (D198) — the count is what the user confirmed.
- **Rule writes return the rule, the preview's lists and the settle result,** so the client patches what changed
  (architecture §4.1). `GET /payees` returns `document_provider`, which `PUT` and the editor need.

## D203 Keys are typed, the rederive walk is stated, and names are compared per plugin

Spec §5.9, rules and history plugin documents.

- **The type carries its own key:** the pass that decided it, with the same basis as the value it came with;
  a pass that proposes a payee or category thereby proposes `flow`, a counter-account `transfer`. Pass 0's basis
  is `{"account_id": n}`, the account matched.
- **Rederiving an unconfirmed entry** walks the fields in order: a standing field is kept and joins the fixed
  set, a proposal or keyless field is resolved afresh, a changed value derives the later standing fields again,
  and only differences are written. It is I18 made operational, so a second settle writes nothing.
- **Names are compared per plugin:** rules by their normalisation (NFKC, casefold, collapse whitespace, trim,
  punctuation kept), history key 2 by canonical text. Rejected: *one normalisation for both* — canonical text
  drops punctuation and would make `PAYPAL *` match `PayPal Europe`, which the rules documentation relies on
  telling apart.

## D204 A rule's preview shows matches, confirmable units and the two lists; a regex is bounded

Spec §5.9, D31. A rule confirms units without review, so what it would do is shown before it is written.

- **The preview shows** (a) the entries the rule matches, each with the earlier rule that takes precedence, if
  any; (b) the units it would confirm, computed per entry now (value complete, every key standing) and refined by
  unit closure when units exist; (c) the two lists of "matches with a different value" and "carries its key, no
  longer matches", as before.
- **A rule starts from an example entry in the editor (D208);** nothing is written automatically (D31). The client
  does no matching (architecture §6.3).
- **A regex is at most 200 characters and must compile,** case-insensitive, `search`; it is refused on save
  otherwise. Python's `re` has no timeout, and a bound keeps the obvious pathologies out; no sandbox. Rejected:
  *no bound* — one pasted pattern could stall settling.

## D205 Management lives under settings

Architecture §6.2, patterns §5, §10. The ledger is where entries are worked; categories, payees and rules are
configuration.

- **Routes:** `/settings/categories`, `/settings/payees`, `/settings/rules`, `/settings/rules/new` (optionally
  `?from=<entry id>`) and `/settings/rules/{id}`. The rule editor is a page, not a sheet over the list: its
  preview needs the width, and `/settings/rules/{id}` is the stable link evidence points to (D198). Rejected:
  *top-level navigation items* — three more entries for screens used rarely.
- **The ledger links in:** a "Manage…" link on category and payee chips; it does not start rules (D208). Inline
  classification and bulk classification stay out (spec §5.9: nothing is changed in bulk).
- **Open and to be tried on real data:** the rule editor's layout and how conditions are built, rule ordering,
  category reordering buttons, the starter categories (the author's tree) — patterns §10.

## D206 Entries carry their source

Architecture §4.1, spec §5.9. A rule's conditions read source fields, and the client cannot show or choose them
from an entry that carries only a name and a purpose.

- **Every entry read carries `source`:** the source transaction as one nested object, `null` only for derived
  entries (every movement has a source transaction, imported or entered by hand: a hand-entered one has its amount
  and purpose and no counterparty, reference, booking text or format), holding counterparty name, reference and BIC, purpose, booking text, end-to-end id,
  mandate reference, instructed amount and currency and source format; never the raw record or the content hash.
  It serves the list, a new `GET /api/ledger/entries/{id}` (200, 404 when missing, behind login) and a rule
  preview's rows.
- **The flat `counterparty_name` and `purpose` leave the entry;** the client reads them from `source`.
  `display_text` stays, being derived. No id filter is added: the detail endpoint answers the one-entry case.

## D207 Rule conditions are one uniform list

Spec §5.9, rules plugin §2–3, schema `rule`. Supersedes the column-per-condition shape that D197–D205 and the
earlier decision on combining conditions describe.

- **A rule holds a list of conditions, all of which must hold,** plus, for category rules, the payee condition.
  A condition is `{field, op, value}`: fields `counterparty_name`, `counterparty_ref`, `purpose`, `booking_text`,
  `mandate_ref`; operators `equals`, `starts_with`, `contains`, `regex`, the same on every field. Codes (`counterparty_ref`,
  `mandate_ref`) compare as canonical text (spec §5.2), names, purpose and booking text by the rules plugin's name
  normalisation, a regex case-insensitively on the raw value. The same field may recur. The regex bound of
  D204 applies on any field.
- **Stored as `conditions jsonb`;** `condition_payee_id` stays a column, its foreign key carrying the
  payee-delete cascade. Field and operator validity is the plugin's, not the database's. The list is an implicit
  AND, and the format leaves room for grouping and negation without a schema change; neither is specified.
- Rejected: *regex only, on every field* — an IBAN prefix or a plain name start would need regex escaping;
  *a `name_contains` column* — one more column per wish, where a uniform list adds none.

## D208 A rule starts from an example picked in the editor

Architecture §6.2, patterns §5, spec §5.9. Supersedes the ledger key `r` and "Create rule from this entry".

- **The editor starts from an example:** an entry picked in the editor with a find box (text search over
  entries, rows showing date, amount and the source fields), or one it is opened with,
  `/settings/rules/new?from=<entry id>`, which the review panel opens too. The example's source fields stand
  beside the conditions as a read-only table; nothing is ticked or prefilled, because an example is enough and a
  condition rarely wants a whole field.
- **The ledger no longer starts rules:** it does not show the source fields a condition reads, so a rule begun
  there would be written blind. Key `r` and the row action are removed; the "Manage…" links stay.

## D209 Interaction standards: five surfaces, one decision rule, no inline forms

Patterns §11 (new), §5, §10; design §2, §5, §7; architecture §6.2.

- **Every interaction has one surface:** in place, popover, dialog, work panel or page, chosen by an ordered rule
  (patterns §11.1). The work panel is the unit panel as a large overlay, addressable by URL, list dimmed behind
  it; its geometry is left to design.md.
- **Inline forms are retired.** Adding, and editing more than one field, are form dialogs (up to three fields) or
  pages; only the rename of one text value stays in place, and blur commits it. Dialogs split into form dialogs
  (Enter submits) and decision dialogs (Enter never confirms). A popover never makes a write that needs a
  decision.
- **Row actions:** at most two inline icon actions, the rest in one `⋯` menu with delete last; category order
  (Move up, Move down) is menu items. The ledger and queue rows carry none.
- **Wording is fixed:** *Add*, never "Create" or "New"; no "OK", "Yes" or "Confirm" (confirm is a unit's review
  state); "…" only on verbs that open a decision; no icons on text buttons. One 32px button scale, Cancel is
  `outline`.
- **Validation messages under a field are red,** which amends design §2 (red for amounts, destructive
  confirmations and field validation messages).
- **The shared components are listed in architecture §6.2;** the key `r` and "Create rule from this entry" are
  removed as D208 states.
- Rejected: *inline add and multi-field edit* (inserts rows into lists, three behaviours today); *every create
  as a page* (a page loses the origin's snapshot and draft); *a narrow side panel for units* (a unit with
  splits, evidence, draft and preview needs width); *a component-library document* (the §6.2 list suffices).

## D210 Flags are judged over the unit; the queue is the units not confirmed

Spec §6 (flags rules), architecture §4.1 (rows), review-queue view.

- **The flags of a unit apply to every entry of an unconfirmed unit,** so `unconfirmed` marks all of them, a
  complete sibling of an unclassified split entry included. The queue is the units not confirmed.
- **Entries carry what a unit needs to be drawn:** `derivation`, `unit_key` (the same for every entry of a unit),
  `authored` (a user-authored entry has no `source`, so `source` cannot tell it was entered by hand) and the
  partner summary.
- **The entry form is allowed on a closed account,** like importing: entries after `closed_on` are accepted.
- Rejected: *per-entry flags with the unit state computed only in the queue* (two definitions of "in review").

## D211 The unit preview is an overlay; temporary ids, full-row write responses, one lock order

Architecture §4.1, §6.3.

- **`preview` is an in-memory overlay** over the functions settling uses and writes nothing; the entry form's
  `PUT` and `DELETE` use `dry_run`. Both statements of the architecture hold, each for its own operations.
- **Rows a draft creates carry client-issued negative integer ids,** echoed by the preview and mapped to real ids
  in the commit response.
- **Write responses carry full rows** for the unit, its consequences and the partners whose flags changed, ids
  with a `truncated` flag for the rest, the removed ids and the unit states.
- **A commit locks in one order:** settle shared, accounts ascending, entry rows ascending. It reads the unit
  before the locks and checks again after: a changed closure is 409 `unit_moved`.
- Rejected: *a dry-run commit in a rolled-back transaction* (settling opens its own); *server-issued ids for
  draft rows* (the preview would have to persist the draft).

## D212 A commit derives its keys from the values it is sent — *partly superseded by D230*

Spec §5.9, architecture §4.1.

- **A standing value keeps its key** (pass 0, a rule, a matcher decision, a booking or a user's, with its basis): a commit
  does not rewrite what already stands. **A proposal becomes `user`** with the proposal's key nested as its
  basis: a value equal to a shown proposal, or one decided by `history` or `llm`. What the
  user typed is `user` without a basis. Empty fields carry no key. A commit does not confirm.
- **The client may name a basis only for the passes `history` and `llm`;** it is stored
  wrapped under `user` and never trusted as evidence. A client can never assert `rule` or `own_account`.
- Rejected: *trusting the key the client sends* (a client could mint a standing key and confirm a unit).

## D213 The queue has three sections, each by date; grouping by shape is open

Review-queue view, architecture §4.1, §6.5, patterns §10. Supersedes the "order by shape" of D99 and D132.

- **Sections:** pending review, needs an account, waiting; each ordered by `booked_on`, then anchor entry id.
  The queue is a snapshot (architecture §6.5).
- **"Shape" is not defined.** Whether units are grouped by what they share, and by what, stays open until the
  author has seen real units in the first month.
- Rejected: *defining shape now* (type, counter-account or payee, category, key passes; groups by size) — a
  guess that is cheaper to make after seeing the units.

## D214 The work panel: keys, address, advancing, marks

Patterns §5, §6, §7, §10, §11.1, design §5.

- **Keys** when focus is not in a field, panel-local: `[` `]` step units, `c` category, `y` payee, `s` split,
  `x` flow ↔ transfer, `r` re-resolve; the ledger's `r` stays removed (D208). **URL** `?unit=<anchor entry id>`
  on any page, opened with a new history entry and stepped with a replaced one; the queue is `/review`, with a
  Review nav item.
- **After `Ctrl/⌘ + Enter` the panel stays open and advances** to the next unopened unit; at the end it closes
  with a notice and the cursor on the last row. "One keystroke" means that chord with the panel open.
- **Created split entries are inserted next to the anchor,** the one exception to snapshots never adding rows.
  Refreshed proposals are patched silently; only state changes and returns to review are marked, and a mark
  fades when the cursor visits.
- **Dirty drafts:** Esc or stepping asks in a nested decision dialog, Cancel focused; "Edit entry" is disabled
  while dirty; opening a consequence row asks first. (The tags clause is superseded by D218.) Re-resolve is a draft edit of the whole unit, with "Reset to proposal" per
  field. Enter on a derived entry gives a quiet notice with a link to the record.
- **The entry-edit confirmation is the static §5.6 warning above Save;** the entry form offers "Add and add
  another" beside "Add". **Form dialogs hold up to five fields** (amends D209's three).
- Rejected: *a queue-row key that commits without opening* (defeats the preview; §11.3 forbids row buttons);
  *a confirmation dialog on entry edit* (the warning is always shown); *a modal panel per step without
  advancing* (a boring unit would cost three keystrokes).

## D215 The payee condition is a normal condition

Spec §3.6, §5.9, rules plugin §2–3, architecture §4.1, schema `rule`. Supersedes the payee-condition parts of D201
("or name it as a condition"; payee delete takes such rules), D207 ("plus, for category rules, the payee condition";
"`condition_payee_id` stays a column, its foreign key carrying the payee-delete cascade") and the line in D174
"a payee's deletion takes the rules naming it as a condition too". D172 (a category rule's payee condition in the
type decision) stays as history. D199 does not mention the column.

- **The payee condition is one more kind of condition in the list:** `{"field":"payee","op":"is","value":"<payee id
  as a digit string>"}`. Several may appear; the list stays an implicit AND. Only a category rule carries them, `is`
  is the only operator, the value is a positive integer id; the rules plugin validates that, core checks at write
  time that the payee exists. It is judged on the payee resolved so far in the same resolution, a proposed one
  included (spec §5.9), and a category rule that has one never decides the type.
- **No foreign key, so:** deleting a payee deletes only the rules that set it; a rule whose condition names it stays,
  shows "Payee deleted" in the editor and never matches (ids are never reused). A merge rewrites such conditions to
  the target. The delete's preview lists the rules it deletes and the rules left with a dangling condition.
  The `condition_payee_id` column, `ck_rule_payee_condition` and its clause in `ck_rule_condition` are removed.
- Rejected: *keeping the column* — a second shape for one idea, one condition at most, a special case in editor,
  plugin and schema; *a payee delete that cascades to such rules* — it silently deletes rules the user wrote for
  another purpose.

## D216 The list's description column shows the entry's own description

Patterns §4.1, §10; architecture §4.1. Supersedes the fallback in the row spec ("the entry's description, else the
source's counterparty name or purpose") and the derived `display_text` as the column's text.

- **The column shows `description` only;** nothing is borrowed from the source transaction, whose fields are shown
  where they belong: the work panel and the rule preview's source columns. An entry without a description shows an
  empty cell. The API keeps `display_text` (description, else counterparty name, else purpose) for other uses such as
  the panel title and search results; the column does not use it.
- **Open:** whether imports get a description at creation (patterns §10).
- Rejected: *the fallback chain in the column* — it hides that an entry has no description of its own and
  duplicates what the source columns show.

## D217 The payee has three states

Spec §5.9 (field order), architecture §4.1, history.md, patterns §4.3. Supersedes the "empty fields carry no key" part of D212, and the "ends the field" wording of the no-payee majority in D178, D179 and D180.

- **A flow's payee is a payee, undecided, or no payee by the user's decision.** Undecided is empty with no key: the
  passes may propose, and history's majority for *no payee* ends the search there, storing nothing. The user's
  "no payee" is empty with the key `user`, no basis (`{"pass": "user"}`, `payee_id` NULL): standing, kept by
  rederiving, never proposed over by any pass or payee rule (I18, I20), and not a reason for review. Clearing the
  payee in the panel chooses it; picking a payee or re-resolving replaces it; converting to a transfer drops it (I9).
- **Qualifies D212:** empty fields carry no key, except the payee a user decided to leave empty.
- **The other fields have no empty decision.** Clearing a decided type, category or counter-account withdraws the
  decision and the passes propose again; a flow without a category is unclassified. The commit treats a `fixed`
  draft of those without a value as re-resolve.
- **UX:** the clear control is offered only on values the user decided; "Reset to proposal" only when the shown value
  differs from the stored one.
- Rejected: *a stored "no payee" proposal from history* (it holds back units whose category a rule already decided);
  *an explicit empty decision for every field* (a flow needs a category, so there is nothing to decide);
  *the clear control as "make it empty"* (the passes re-propose it: it misled).

## D218 Tags are part of the draft

Spec §3.7, §6, authorship table; architecture §4.1; patterns §5. Supersedes the tags clause of D214.

- **The draft carries a tag change per entry:** the tag ids added and removed, relative to the tags the entry had
  when loaded, not the full set. A tag written elsewhere meanwhile is never overwritten and no version is
  involved. A draft that does not touch tags carries nothing; re-resolve never touches tags; Reset drops them.
- **A new split entry starts with the original's tags,** editable in the draft like any row's.
- **Preview rows carry `tag_ids` with the draft applied;** tag changes are not consequences and affect no state,
  flag or proposal.
- **The commit applies them in its transaction after the entries exist,** idempotently, under its existing locks.
  A commit that changes only tags is valid and bumps no version. A tag deleted meanwhile is refused as
  409 `stale_reference` naming the tag. An entry the draft removes takes its tags with it.
- **UX:** tag edits make the panel dirty. Each entry block has a Tags row without clear control or proposals; `t`
  edits the focused entry's draft tags. A new tag is created at once through the tag endpoint and added to the
  draft; cancelling leaves it (deletable in the tag settings). Elsewhere tags stay direct writes (ledger `t`, tag
  all, settings).
- Rejected: *the full tag set in the draft* (overwrites a concurrent change); *creating new tags only at commit*
  (names in the draft, more validation); *tags outside the draft* (the author's UX tests found it restrictive).

## D219 Transfer matching: offers without a counter-account, tie-breaks, placeholders, no estimate

Spec §5.7, §5.9; architecture §4.1, §5.2.

- **A leg without a counter-account is offered every opposite-sign candidate** in the window on every account the
  currency rule allows; a pick sets the counter-account as the pair's, with pass `user`. This makes I33's "offered in
  review" concrete.
- **Equal date distance:** the earlier `booked_on`, then the lower entry id; pairing is deterministic.
- **The pair key `counterpart` has an empty basis `{}`** on both legs; the counter-account a pair sets keeps
  `{"from": "counterpart"}`. Nothing reads the pair key's basis.
- **Placeholder end-to-end ids** `NOTPROVIDED`, `NONREF` and empty, case-insensitively, count as absent.
- **Needs an account:** an unpaired transfer leg with no counter-account, an instructed currency and no open
  non-own account in that currency, by the one currency-rule function. A leg without an instructed currency and
  without a counter-account stays in pending review. The test is one function in core (the preview's), restated in
  SQL for the queue's sections and covered by the section tests.
- **No preselection of the one fitting account:** a counter-account is proposed only from evidence (history, a rule,
  later the LLM pass), the same for every currency. The account just added is the user's choice for the unit it
  was added from and is offered first on the others.
- **A cross-currency counter-leg carries no estimate:** conversion happens only in reporting (I27); the user types
  the amount received.
- **Widening the window for one pick** is a request parameter of at most 90 days, checked by the server.
- **A paired leg of an unconfirmed unit is re-derived by settling;** when its type or its own counter-account
  changes, the pair is released on both legs and may be made again in the same round (I18). Settling's first step
  no longer skips paired legs.
- Rejected: *offers only on a known counter-account* (a leg with none could never be paired by hand); *a random
  or first-seen tie-break* (order-dependent); *a reference-rate estimate on the counter-leg* (conversion outside
  reporting); *an unbounded window for a pick* (offers without limit); *a stored proposal for the one fitting
  account* (it would hold the unit unconfirmed with nothing to review).

## D220 Transfer pairing in the panel and the queue

Spec §5.7; patterns §4.2, §4.3, §11.1; review-queue; architecture §4.1. Qualifies D213: the per-currency grouping
inside Needs an account is the one defined grouping.

- **Offers are always in a popover,** never inline: the transfer block shows the partner summary (for an unpaired
  leg the proposed offer, preselected, or "no partner yet") with a "Choose partner…" trigger, for a paired leg
  "Pick another partner…". The popover scrolls with many offers; a pick is a draft edit. The offers and the amount
  received are fields of the draft editor.
- **No "Unpair" control:** the remedies are another partner, converting to a flow, or changing the counter-account.
- **The queue says "N transfers need an account in USD"** with one "Add account" action per currency group (a card
  payoff abroad is also a transfer); a waiting unit gives "Waiting for <account>, synced through <date>"; counts
  are per section.
- **"Add account" is a form dialog** (currency locked to the one needed); the full accounts page comes later.
- **The badge is `unlink`** with the tooltip "Transfer leg without a partner"; the `waiting` tooltip names the
  partner's account for an unpaired transfer leg. Evidence reads "paired with <account>" with "matched
  automatically" or "set by you"; the counter-account a pair set reads "from its partner", with no clear control.
- **The architecture carries it** as the draft's `pairing` field, offers per transfer leg in the preview, the unit
  state distinguishing waiting from unmatched, a commit closure and lock set extended to the partner and the
  counter-leg's account, and counter-legs created by a commit only.
- Rejected: *an inline offers list for an unpaired leg and a popover for a paired one* (two surfaces for one
  choice); *an "Unpair" control* (the spec has no "no partner" pick); *"withdrawals" in the queue wording* (not all
  are); *an inline Add account form* (patterns: no inline forms); *a stored Add-account follow-up that moves queue
  rows* (the snapshot holds).

## D221 A swap takes one pick only where the freed legs keep their own counter-account

Narrows the claim in D158 ("a swap takes one pick"). A counter-account a pair set is not an independent
decision: it was inferred from a partner that a pick now rejects, so it leaves with the pair (§5.7) and a leg left
behind keeps only what it had before. Keeping it would pin the leg to a wrong account, so the matcher's counter-account
filter (I33) could never offer the right partner, and a re-pair would clash with I10.

- **A swap** frees two legs. A freed leg that had its own counter-account (pass 0, a rule, history or the user) is
  re-paired by settling; one whose counter-account its pair set has none and needs a pick of its own.
- Rejected: *keeping the pair-set counter-account as a non-standing key after release* (a new kind of key to save one
  pick in a rare case).

## D222 The entry form takes one signed amount

Spec §3.9, patterns §2. The form had an unsigned amount and an Income/Expense control. A leg of a transfer, such as
cash paid into the bank, is neither, and the control also hid the sign that every other view shows (patterns §2:
the sign is shown, not hidden). §3.9 only says the sign is prefilled — an expense — and can be changed, so the control
was a patterns choice.

- **One signed amount field,** prefilled with a minus (the expense default of §3.9), with the hint
  "− money out, + money in". A typed `+`, `−` or `-` sets the sign.
- **An amount without a sign is refused,** like any ambiguous input (architecture §6.6): the minus is prefilled, so
  clearing it is the only way to omit it.
- Rejected: *a neutral "Money out | Money in" control* (a mouse or extra key for a choice the sign already states,
  and more space than the field).

## D223 Step 9: documents with a test importer — *partly superseded by D230*

Spec `features/documents.md`, spec §5.5, §5.8, §6, architecture §4.1. The decisions that shape how documents
meet the existing machinery; D1 to D9 of the step's plan.

- **D6 A lean documents view** (`ux/views/documents.md`) and a panel section, reusing the ledger table patterns.

## D224 Step 9: the document decision is enforced; providers are registered — *partly superseded by D229 and D230*

Spec §3.6, §5.8, §6, `features/documents.md` §7, architecture §4.1, §5.2, patterns §6. D223 left "commit without a
document" as something the panel asks for; the server did not check it, so a client could skip a wait unnoticed.

- **Documents join the lock order:** settle shared, documents ascending, accounts, rows. Ingest takes documents,
  accounts, rows in the same order, so the two never deadlock.
- **`ENABLE_TEST_IMPORTERS`** (default off) registers the deterministic test importer `testdocs` in the composition root.

## D225 Documents are inputs to rules, not a rewrite — *partly superseded by D230*

Spec §5.8, §5.9, §6, §9, `features/documents.md` §1, §4 to §6, §8, `plugins/classifiers/rules.md`,
`plugins/classifiers/history.md`, schema (`ledger_entry.document_line_id`). Partly supersedes D178 (enrichment in
resolution's input) and D181 (history closed to documented transactions; per-line input only in the draft), and replaces
the enrichment section of `features/documents.md` (§5, as step 9 built it, D223). Enriching the input made resolution
intransparent: a rule on `PAYPAL *` silently stopped matching once a document linked, "create rule from this
transaction" showed an example the rule no longer saw, history was switched off, a panel-wide re-resolve on a confirmed
entry wiped its values with nothing to propose them again, a document could sit on a transfer, and a split entry resolved
with its own line in the preview but with all lines after the commit.

- **A document is an input rules can read; the source is never rewritten.** `counterparty_name`, `purpose` and the
  other source fields are the bank's, with or without a document. Rejected: *enriching the counterparty text and the
  purpose* (what was built).
- **A rule field on the entry's source text (D230, `source_text`, formerly `document_line`), entry-level:** `document_line`, failing without a document or, for the
  line, without a line. The rule editor's example shows them with `payee`, in two groups (source transaction, entry).
- **`document_line` is singular, the entry's own line, or none.** Rejected: *`document_lines`, matching any line*,
  which on an unsplit order of several items matches one item for all of them.
- **A booking entry is a `flow`, under a standing key; converting it is refused (D230):** formerly, a document implied `flow`, a field-order constraint like "a category implies a flow". A transfer is not a
  candidate and a pick on it is refused (`document_not_for_transfer`); converting a linked transaction to a transfer
  drops its document, as it drops the payee (I9); the document decides `flow` first, the type taking the link's key (§5.9, field order);
  the schema refuses a document on a transfer (`ck_document_not_on_transfer`). Entries cut before this change are
  dropped: there is no real data yet.
- **The model as the reviewer of weak history** is recorded as an open question (spec §9), to be decided with pass 3.

## D226 OIDC sign-in, and users it creates

Architecture §2, §4.1, §4.5, §5.6, §5.7, the start sequence; schema `app_user`.

- **An OIDC sign-in may create a user.** The login claim is the login; an unknown one is created without a
  password, gated by `OIDC_ALLOWED_GROUP` when it is set. Configured users and OIDC users coexist; the start
  reconciles only the configured ones (`app_user.source`). Supersedes "users are configured, never created through
  the app" (D176) for OIDC. Rejected: *matching the provider's `sub`* (the login
  attribute is what the household configures and reads, and the provider is the household's own).
- **A user is the configuration's or the provider's, never both.** A configured user's first OIDC sign-in hands
  them to the provider and drops their password, so no password outlives the configuration's control; the start
  then ignores their configured login and logs it. Accepted cost: no password fallback when the provider is down.
  Rejected: *a flag per field* (`named_by_oidc`) and *handing over but keeping the password* (both a rule per
  field).
- **The group is checked at every OIDC sign-in, not per request.** Revoking at once is deleting sessions.
  Rejected: *re-asking the provider per request* (a network call per request, and the provider must be up).
- **The name claim wins over the configured name**: a handed-over user is no longer the configuration's.
- **A claim missing from the ID token is taken from userinfo**, one generic fallback; `OIDC_CLAIMS_SOURCE` is
  not a setting.
- **Sign-out is local.** The provider's session is the provider's.

## D227 The model is asked in the background, for the category

Spec §5.9 pass 3; architecture §4.1, §4.2, §5.4; `ux/views/review-queue.md`.

- **Category only.** Payees are left to rules and history. Rejected: *both fields at once* (a payee list in every
  prompt, and context per payee, for little gain).
- **A worker with an in-memory list, not a review flag.** Review flags stay derived from stored data; whether the
  model has answered yet depends on whether it is reachable, which only the running process knows. Rejected: *a
  `waiting` reason for the model* (entries would wait for days behind an unreachable model, and the flag would need
  re-settling whenever it came back).
- **Shown where its results land**: the Review item and the queue, not `/sync`. Rejected: *on `/sync`* (bank tasks
  and guesses are different things, and the guesses are reviewed in Review).
- **The change poll carries the remaining count, every 5 s while there is work.** Rejected: *a stream* (as for the
  change values, §4.2).
- **One short rationale.** It costs generation time, in the background, and is what makes a guess for an unfamiliar
  name checkable.
- **Structured output and a stable prompt prefix.** Few tokens generated, no invented id, the category list
  processed once by a server that caches it.

## D228 Empty is a value

Spec §5.9 (field order, keys), §6; architecture §4.1; history.md; patterns §4.3. Supersedes D217's three payee
states.

- **A standing key fixes a value, empty included.** Whether a field may be empty is the field's own rule: the payee
  may, a type, a flow's category and a transfer's counter-account may not. There are no payee states, only values,
  keys and that rule.
- **An empty result ends the search and stores no key.** On a field that may be empty, a pass's empty result wins
  like a value and needs no review; history's majority for *no payee* is that, not a special case.
- **A commit decides what the user saw, empty included where the field may be empty,** whether cleared or left
  empty. A confirmed unit is never resolved again, so this only matters for a unit still incomplete after the
  commit — and there it keeps the user's value from being proposed over, whichever way it became empty.
- **On a field that may be empty, the clear control works on any value, a proposal included;** the empty value reads
  muted ("No payee"); the payee picker's separate "No payee" item goes.
- Rejected: *dropping the user's empty payee key* (an incomplete unit could be pulled back into review by a payee
  the user had removed); *keeping a key only for a cleared payee* (two empty states the user cannot tell apart).

## D230 Clearance accounts replace document matching — *partly superseded by D235*

Spec I1, I2, I3, I7, I20, I21, I35, I41, §2, §3.3, §3.6, §3.8, §3.9, §4, §5 to §5.9, §6, §8, §9;
`features/documents.md`; `rules.md`; `history.md`; schema; architecture §4.1, §5.1, §5.2, §5.4, §5.5, §5.7, §6.3,
§6.5, §8. Supersedes D62, D76, D96, D108, D169, D173 and D229;
partly supersedes D63, D97, D131, D142, D152, D166, D168, D172, D177, D178, D181, D212, D223, D224 and D225.

- **Bookkeeping instead of matching.** Document matching linked each charge to the order it paid and split it along
  the order's lines. Real Amazon data broke it again and again — orders charged in parts with no visible logic,
  discounts not itemised, VAT shown apart, two orders in one charge — and each case added a rule: line allocation,
  unitemised shares, document-joined units, waiting for the rest of an order, split proposals, line answers for the
  model. A **clearance account** replaces all of it with bookkeeping the ledger already does: every charge from the
  provider is a transfer to the account, every order a purchase booked on it, split into its items. When everything
  is there the account settles at 0; when something is missing or wrong, its balance says so. No charge needs to know
  which order it paid. Rejected: *document matching itself*, with or without the unitemised amount (a growing rule
  set that still left cases for a person).
- **A kind, fixed at creation; no source; providers on the account.** A clearance account cannot be linked to an
  importer, so it is unsynced and the entry form works on it — the remedy for a cancelled item, a gift card or a
  misread order. It lists the providers it takes; a provider maps to at most one account per currency, compared
  without regard to case, so a list absorbs name variants. A booking never converts: a converted amount would never
  balance against a charge made at the bank's rate. Rejected: *auto-created accounts per provider* (clutter from
  one-off shops and model-made name variants); *a provider-mapping settings area* (a second place for what the
  account is for).
- **A booking is a source transaction of a third origin.** The author was inferred from three NULLs (no importer, no
  run, no format); `source_format` names a format, not an author, so it cannot carry "booking". An explicit `origin`
  — `import`, `user`, `booking` — states it as one fact, under one CHECK. This is a column of the source, not D168's
  retired entry `origin`. The booking's source kind stays in its `source_id` (`document:<id>`, `transfer:<entry>`),
  an identity.
- **A booking follows its source, confirmed or not** — the stated exception to I20. A changed document re-derives its
  booking; unchanged lines keep their entries and the user's decisions, and only what the document changed returns
  to review. How often that happens is the importer's declared re-delivery mode: `replace` (re-reads the same record)
  or `keep` (the email importer: a later mail never changes an order). Rejected: *immutable snapshot bookings* (a
  misread or replaced document would leave a booking only a hand entry can correct, while I20 would protect nothing
  the user decided on the lines that stayed); *importer-side memory of delivered orders* (work an importer should not
  carry).
- **Settling maintains all bookings, in one step**: it books what its sources call for, re-derives what changed and
  removes what no source calls for, idempotently by `source_id`, locking only the clearance accounts it touches. The
  contained exception to D181's "settling creates no rows and takes no account lock": only clearance accounts, only
  bookings. Rejected: *ingest and the provider-list write as the writers* (two more writers of the same rows, and a
  counter-leg would still need a third).
- **Counter-legs on a clearance account are bookings of the charge.** A charge decided as a transfer to the account
  books its counter-leg (`transfer:<entry id>`), which follows the charge: re-typed or re-pointed, it goes; split, it
  re-derives. So a rule-decided charge is complete, and confirmed, at once (I22 holds as a pair). D181 and D168 stay on
  every other account, which keeps imported or hand-made rows apart from machine-made ones; a clearance account has
  no such rows to protect. D168 rejected exactly this lifecycle for counter-legs in general; it is adopted here only.
  Rejected: *commit-made counter-legs for clearance accounts* (a keystroke per charge, and a deleted or lingering
  counter-leg would drift the balance unseen).
- **Made split, spread in proportion.** A booking has one entry per line — an exception to I7 that D152's reasons do
  not reach: the split is made and re-derived only as its document says, never against a split of the user's, who
  does not split a booking. What the lines leave of the total is spread over the lines of the total's sign, in
  proportion; coupons stay as listed; a total of 0 books nothing (`features/documents.md`). This closes spec §9's
  question on splitting during settling.
- **Each entry has its own source text** (`ledger_entry.source_text`): the text the entry's source gives it, set by
  whatever creates the entry and never editable. A booking writes each line's text there; classification reads it
  without knowing bookings — a rule condition and the model's payload. Booking entries take no part in history:
  their source fields are shared by every entry, item titles rarely repeat, and a transfer booking's vote would
  count its leg's twice. Rejected: *a history key on the source text* (exact titles rarely recur; tokens over them
  are noise ahead of the model). Re-derivation matches a
  booking's entries to the lines by position, inside the booking layer. A booking entry is a flow under a standing
  key and is never a transfer offer or candidate. Rejected: *a line reference on the entry* (`source_line`:
  classification would depend on the booking layer); *the description as input* (editable inputs would reset
  standing keys, and a rule could fire on the user's own text); *a `metadata` jsonb column* (untyped and unchecked,
  for one field); *the document's merchant as an input* (the account names the platform; the merchant stays as
  provenance); *a seller field on lines* (noise in real data; addable later).
- **A booking writes its own source fields; lists render only data** (user, 2026-10-26). A document booking's
  counterparty name is the document's provider and its purpose "Order *reference*" ("Refund *reference*" for a
  refund), the word alone where there is none; a counter-leg booking carries its charge's date and purpose, like
  any counter-leg. Its row therefore reads like any row: the ledger list and an account's statement hold nothing
  specific to an account kind or an author, and every statement row with a source shows its origin as a small tag —
  "Imported", "Entered", "Booked" — in place of "entered by hand". Accepted consequences: the
  model's payload sees these fields (harmless), and a rule on the counterparty "Amazon" matches booking entries
  too — their type is fixed to `flow`, so no transfer rule applies. Only navigation reads the format of a
  `source_id`: the panel's "Booked from *provider* order *reference*" and a row's "Open document", like "Open
  review". Rejected: *the statement assembling "order … from …" or "charge on …" for a booking* (a rendering rule
  per kind of row, in every list). Creating a clearance account asks for a start date and writes "0 at the end of"
  it; documents dated after it are booked. Without a start, booking a past year of orders would count each
  purchase twice: as the old categorised charge and as the booked order. Rejected: *a start date setting on the
  account* (a second anchor beside the balance records).
- **Documents stay**, one per order or refund, each dated on its own day — an order on the day it was placed: what the user checks, and where the original mail
  is shown later. One not booked says why.
- **No balance signal yet.** A clearance account is shown like any unsynced account (user, 2026-10-26); a balance
  that is not 0 is normal while charges lag behind orders.
- Deferred: editing documents by hand (the booking follows; the document `version` detects conflicts); "create a
  clearance account" from a document not booked; the email importer mapping sender domains to providers; refunds as
  documents of their own; a status or signal for clearance accounts.

## D231 Content on cards, structure on the background

Design §5; `ux/views/account.md`.

- **One rule for every page.** Which content got a card was decided page by page: the Overview, Sync, Importers
  and Rules used cards; the ledger, the review queue, accounts, reports and the settings of categories, payees and
  tags put their content straight on the background. Now content — figures, forms, charts, lists, tables — sits
  on a card, and structure — the header, tabs, filter bars, report controls, notices, headings — on the
  background.
- **Two kinds of card,** both already in use: *padded* for a self-contained block, its title inside if it has
  one; *flush* for a page's list or table, its heading above, one card per group (as Settings → Rules).
- **A page's facts are figure cards,** as on the Overview: an account's balance, a document's total.
- **An account's secondary actions move into the page header,** before "Add entry"; patterns §11.7 bounds only
  the primary action.
- **Row hover is a tint of the cursor,** `row-hover`: `surface-muted` on a card read as a hole in the table.
- Rejected: *the dense views on the background*, as in the mockup's ledger and review — an exception to
  remember, while a flush card keeps the compact density; *putting everything on cards as it is* — headers and
  controls on cards read heavier and blur what is content; *"Set balance" in the Balance card as well* — one
  action in two places.

## D232 The email importer

email.md; spec §5.5, §5.8, §5.9, §7; architecture §5.5, §5.7.

- **One dedicated inbox, read-only, with authenticated senders.** The household forwards receipts there, by rule or
  by hand. A message is read when its `From` or a forwarding header names a listed address and the inbox's provider
  vouches for it in the topmost `Authentication-Results` header: a forward by hand needs its listed `From` to pass
  DMARC or an aligned DKIM signature; an automatic forward needs the shop's DKIM pass, or an ARC pass from the forwarder, and a forwarding header
  naming a listed address. Anything else is skipped, as `not_accepted` or `not_authenticated`. Headers alone can be
  written by anyone, and a forged mail would book a purchase on a clearance account (D230). What remains is a
  genuine receipt of someone else's purchase forwarded with a forged forwarding header, which needs the inbox's
  address; the planned sender-domain mapping narrows it. Rejected: *a check of the listed addresses alone* (every
  header it reads can be forged); *verifying DKIM ourselves* (run days after delivery, when keys may be rotated or
  revoked, with DNS lookups and a dependency; a later fallback for a provider that adds no
  `Authentication-Results`); *merchant allow or block lists* (settings that must be curated for every new shop);
  *reading the users' own inboxes* (every mail of theirs to the model).
- **The model extracts; code decides.** No "is this a receipt" field: a document that is not a receipt carries the
  same amounts. A document is delivered only when it states a total and lines that account for it — what they
  leave unitemised no larger than the lines themselves — which keeps mails without an order's lines out without
  asking the model what kind of mail it is. Total and lines are delivered as read: booking spreads what the lines
  leave over them (D230), and a purchase paid with a voucher, total 0, is delivered too, though not booked. Rejected: *lines that add up
  exactly* (Amazon's mails list items before a discount the total already has). The one exception is `refund`,
  a fact the document states, without which a refund would arrive as a charge.
- **A later mail never changes an order**: the importer declares the re-delivery mode `keep`, so the first complete
  mail of an order wins and a shipping notice, invoice or cancellation is kept out. Rejected: *importer-side memory
  of delivered order ids* (work the importer should not carry); *`replace`* (a partial mail would degrade a complete
  order, and its booking with it). Given up: cancellations by mail, corrected by an entry on the clearance account.
- **Refunds are not delivered yet.** Keyed by the order id, a refund would collide with its order's document. Parked:
  refunds as positive documents with a key of their own, once real refund mails are seen.
- **The position advances only with a written run.** A UID position with UIDVALIDITY, an overlap by arrival date
  and a short memory of Message-IDs; kept in `state`, but applied only when the run's documents are written, since
  `state` is otherwise written back whatever the outcome. Rejected: *re-reading from the start date every run*
  (the model asked for every mail, every time); *Message-IDs checked against stored documents* (the importer reads
  no database, and mails that yield no document would still be asked again).
- **The provider is the merchant, canonicalised in code.** Legal forms and domain suffixes stripped; no list of
  merchants; the document key keeps the provider as stored, and only a clearance account's list compares without
  regard to case. Planned: sender domains mapped to providers in the settings, so no misread decides a provider.
- **Text first, PDF as fallback.** German shops attach terms and conditions as PDFs; reading the PDF first would
  lose the order in the body. The vision model gets no schema: constrained decoding made it loop.
- **The password is typed at every sync**, like the PIN: a mailbox password is not verifiably read-only.
- **A listed sender address covers its plus addresses.** `martin+amazon@proton.me` is read for a listed
  `martin@proton.me`: the tag is the mailbox owner's own, handed out per shop, and the domain that authentication
  rests on is unchanged, so nothing the sender check guards is widened. Only `+` separates a tag; a listed address
  that carries one matches only itself. Rejected: *ignoring dots in the local part too* (Gmail's convention — dots
  are significant at most providers, so it would accept a genuinely different mailbox).
- **The title loses the forwarding client's markers.** A forward by hand quoted inline is its own inner message,
  so its subject arrives as "Fwd: Re: …". A leading `Re`, `Fw`, `Fwd`, `Aw` or `Wg`, with an optional counter, is
  stripped repeatedly before the title is cut to 200 characters. Accepted consequence: `RE:` is also the German
  abbreviation for *Rechnung*, so `RE: 12345` is read as a marker and titled `12345`; the two cannot be told
  apart, and the order number now has a column of its own.
- **The order number is the document's reference, not its key** (D233). The mail's Message-ID stays the key where
  the shop names no order number.

## D233 A document's `source_id` and its reference

spec §5.5; `schema.sql`; `ux/views/documents.md`; `plugins/importers/email.md` §6.

- **Two different ids, two names.** A document's key was `external_id`, which reads as the vendor's id, and most
  of the spec took it that way. The email importer could not honour that: a receipt naming no order number still
  needs a key, so it stored `message:` and the mail's Message-ID there. The key is renamed `source_id`, as on a
  transaction (§5.2) — the id the source assigns — and the provider's order, invoice or booking number moved to a
  new nullable `reference`. A receipt is *keyed* by the mail it arrived in and *referenced* by the number the shop
  printed; those are not the same thing.
- **`source_id` is never null**, unlike a transaction's: a document has no content hash to fall back on, so an
  importer whose source names nothing usable synthesises one.
- **The reference is what is shown.** The documents list has a Reference column, the text filter matches it, the
  detail shows it, and a booking's purpose is "Order *reference*" — "Order" alone where there is none. Nothing
  resolves on it.
- Rejected: *showing the key as the reference* (`message:CAF…@mail.gmail.com` as a column value); *marking a
  synthesised key by its prefix and hiding those in the views* (one importer's detail leaking into a core view);
  *giving the importer a generic synthetic prefix instead of renaming* (it changes the key, so every stored
  document re-keys and duplicates).

## D234 What an importer delivers decides what its instance shows

`ux/views/importers.md`; spec §5.1, §5.5; `features/documents.md` §1.

- **A documents-only importer has no linked accounts.** A document is booked onto whichever clearance account
  takes its provider (D230), never fetched for a linked account. The instance list shows "delivers documents"
  where it would list linked accounts, drops "Link account" from the row, and the instance page replaces its
  Linked accounts section with one line saying where the documents go.
- **The catalog says what an importer delivers**, not only how it is fed: "takes a file", "fetches transactions",
  "fetches documents", "fetches transactions and documents". A file importer always delivers transactions, so it
  needs no second half.
- **Hidden for documents, disabled otherwise.** "Link account" is dropped for an importer that delivers documents
  only, and stays disabled for one that delivers neither transactions nor documents, which the server refuses
  anyway.
- Rejected: *leaving the row's accounts slot empty* (the row goes quiet with nothing explaining why it has none).

## D235 The ledger list's total; lists of entries without the origin tag

patterns §4.1; architecture §4.1 (*The ledger list and tags*); design §5; D196, D230.

- **The ledger list sums its filter.** The answer carries, beside the count, the sum of the amounts of every entry the filter selects, so the total row states "Total of all *n*" whatever the page holds; the client adds nothing (patterns §1). A sum of the loaded rows would change with every "Load more" and mean nothing.
- **One sum per currency, never converted** (user, 2026-10-28). The ledger list is not reporting (I27): one currency is one figure, a mix is shown as it is. Rejected: *a base-currency `Line`, as the reports have* (conversion outside reporting, and an unvalued remainder on a list).
- **Every entry of a split carries the marker.** On the first row only, the others were unexplained wherever the cursor or a scroll landed on them.
- **Lists of entries drop the origin tag** (user, 2026-10-28), partly superseding D230. The ledger list and the review queue are read by what an entry means; who authored its source is the statement's concern, and the panel's provenance says it for any entry. The statement keeps the tag. Rejected: *keeping it in the ledger list to match the statement* (a column on every row for a fact rarely asked of an entry).

## D236 A column names its one currency in its header

patterns §2; D235.

- **The header carries the currency a column shares** (user, 2026-10-28): "Amount (EUR)", as the category report already had it, and the cells drop the code. Where a column mixes currencies, the header says "Amount" and every cell shows its code, as before. A list of one currency is then explicit without repeating the code on every row.
- **Decided by the server's answer where it has one.** The ledger list decides by its `sums` (D235), so loading more never relabels it. A list without such a figure — the documents list — decides by the rows it holds, and loading more may relabel it (accepted, user 2026-10-28).
- The rule preview and the rule example's candidate list showed no code even where currencies mixed; they follow §2 like every other list.

## D237 Account page tabs, a statement without running balances, waiting grouped by account

`ux/views/account.md`, `ux/views/review-queue.md`; design §5; architecture §4.1, §6.5; D235.

- **The account page has two tabs, Transactions and Runs** (user, 2026-10-29). Both lists grow without bound; stacked, the runs pushed the statement down, and five of them with "Show all" was neither the whole log nor out of the way. The Runs tab is the whole log. A clearance account has no runs and no tabs. Rejected: *runs below the statement* (out of reach on a long statement).
- **The statement shows no running balance** (user, 2026-10-29). A balance on every row read as if each transaction had one, and blurred the records, which are the account's only stated balances. The column stays for the records; the API drops the field, which nothing else read. The invariant it guarded is asserted on the records: Bₙ plus the movements after Dₙ is the account's balance. Rejected: *hiding it in the client only* (a computed field no client reads).
- **Waiting is grouped by the account waited for** (user, 2026-10-29), one card per group as the needs-an-account section is by currency, the reason said once in the group's heading. Rejected: *the reason under every unit* (the same line repeated); *group rows inside one table* (a second way to draw a grouped list; to be revisited if one card per group does not read well).
- **A row of figure cards is filled**: a figure keeps an Overview tile's width, the sources card takes the rest.
- **The Review count is a count chip** (user, 2026-10-29), a tag chip in `stone`: the familiar mark of something new, where a bare muted number read as part of the label.
