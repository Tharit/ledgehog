# Household ledger — archived design decisions

Status: closed record. Decisions from `decisions.md` that a later decision
superseded entirely, kept with their identifiers so that references to them
still resolve; and, after them, the passages of decisions superseded only in
part, removed from the entries that stay. Nothing here is in force; each entry names the decision that
replaced it. See `decisions.md` for its conventions.

---

## D4 Manual entries have no source transaction — *superseded by D167*

Considered: synthesising a source transaction for manual entries so the
invariant is universal. Rejected as redundant, because manual entries are never
split — splitting something typed by hand is just typing two entries. The
invariant is therefore conditional on `source_transaction_id IS NOT NULL`, which
covers every entry that *can* split. The split action is hidden, not disabled,
on manual entries.

## D20 Overlap trimming at import, not duplicate detection afterwards — *superseded by D103*

Rejected: a near-duplicate detector scanning for same-amount pairs after
import. Repeat purchases through one regime — two coffees on consecutive days —
would generate an endless stream of pairs to dismiss, and it finds the problem
after the fact. Rejected: a coverage range on the account–source link, because
CSV and FinTS alternate on one account. Rejected: automatic discarding of
near-duplicates, because dropping a row for resembling another is false
sameness, silent on accounts without a reported balance. Rejected: trimming in
the importer, because importers know nothing of the ledger and each would get
it slightly wrong. Trimming in ingest, decided by the user at the boundary and
recorded as void, handles the real case — one booking reaching an account by
two regimes — where it arises (spec §5.3). The same decision now also settles
a format change within one regime (D49) and a switch-over from manual to
imported (D59).

Existing rows take precedence at a boundary. Considered: letting the user pick
which side wins. Rejected: an overlap between imported regimes covers days,
because a fetch starts shortly before the account's sync position; the rows
on the losing side survive as void with their raw payload; and history carries
over through the IBAN and the canonicalised name. A per-boundary choice would
need classification carried across from the losing side, which has edge cases
with splits, to solve a problem confined to a week of rows.

## D25 Pass 3's payload is not restricted by channel — *superseded by D80*

Considered: sending only payments identifiably made to a business — card
payments and direct debits, via a normalised channel column — so that private
persons' names never reach the model. Rejected for simplicity: an on-premise
model is the expected configuration, and the disclosure travels with the
endpoint setting instead (spec §5.9). The column would be backfillable from
`raw` if this is revisited.

## D26 Proposed transfer pairs are not stored — *superseded by D56*

Rejected: pairing the best candidate automatically and flagging it — a wrong
pair blocks the true partner and can cascade. Rejected: a suggestion table like
document links — new storage and a new state machine for something derivable.
Ambiguous legs stay unmatched and their candidates are computed when read
(spec §5.7).

## D33 Mirror legs are created, not suggested — *superseded by D110*

A counter-account inferred by history or a model is a guess, and a wrong
transfer is worse than a miscategorised expense, because it moves money
between accounts. Rejected anyway: only suggesting the leg. Leaving it
uncreated means cash drift the user reconciles by hand later; creating it,
with its basis and confidence recorded for review, means correcting one entry
instead of silent divergence (spec §5.7).

The two ways a counter-account becomes known are treated differently. An exact
match on one of the household's own IBANs is not a guess (D64): the pairing
that follows writes no key, and the leg itself is reviewed once anyway. An
inferred counter-account records its confidence on the pairing, written to
both legs.

## D34 Manual "set balance" is refused where a balance is reported — *superseded by D83*

The refusal is the point, not a restriction. Two mechanisms writing the same
residual would fight: a hand-entered balance makes the next assertion fail,
and "correcting" it by hand again turns the assertion into something the user
routinely overrides. Once that happens the assertion no longer detects
anything, which costs far more than the convenience gained (spec §3.10,
§5.10, I16).

Under balance records (D54) the rule reads: a synced account takes a manual
record only as its anchor, while it holds no record at all; once it holds a
reported record, no manual record can be created. Whether a balance is
reported is observed from the records, not declared (D73).

## D38 Where entries come from is a core concept — *superseded by D168*

`origin` was introduced in passing under the hand-authoring invariant, yet the
rules for splitting, review, deletion and editing all differ by origin. It
moved to the core concepts with one table of what each origin may be and what
it is subject to (spec §3.9), and the shape of the system now shows entries
without a source (spec §2).

## D45 The importer makes its balance date consistent with the core rule — *superseded by D85*

Some banks date weekend payments on the next business day while already
including them in the balance, or the reverse; the assertion would then fail
spuriously, and a spurious failure teaches the user to ignore it (D34). The
core rule stays one line — the balance equals the entries booked up to its
date — and the importer reports a date consistent with it: the last
statement's closing balance, dated the later of its own date and the latest
booking delivered (spec §5.1). Statement formats also guarantee that opening
balance plus lines equals closing balance, which the importer checks, so a
parsing bug surfaces as one and not as a ledger problem.

Rejected: a tolerant core rule summing up to the latest booking delivered,
which builds a guess about bank behaviour into the core and is wrong for banks
that deliver future-dated rows outside the balance.

## D47 A hash collision is visible — *superseded by D103*

After D46, a conflict on `content_hash` alone at insert can only be a genuine
collision. It is recorded on the run like a reject, and the row is not written
(spec §5.2). A conflict on both indexes is the concurrent shared-account case
and stays a silent skip. The hash encoding tags each field so that no
combination of values in one field reproduces another's input.

## D48 Accounts show how much the system can verify — *superseded by D123*

Reject fires only where sources assign ids; the assertion runs only where
they report balances. An account with neither has no duplicate detection at
all. Rather than leave that implicit, each account shows a derived
verification level — id + balance, balance only, none (spec §3.11) — telling
the user which numbers deserve more trust.

## D49 Format changes are detected at import — *superseded by D103*

A bank changing its description format re-delivers its overlap window under
new hashes. Previously that surfaced as a failed assertion days later and a
manual hunt, and not at all on accounts without a balance. The signal at
ingest is clean: in normal operation every existing row in the window is
re-delivered under its old hash, so an existing row that was *not*
re-delivered, paired by amount and date with an incoming row that has no hash
hit, marks a format change. It goes through the same boundary decision as an
overlap between regimes (spec §5.3). Rejected: a duplicate finder shown only
on accounts with a failing assertion, which avoids D20's noise but cannot help
accounts without a balance.

## D51 The first fetch is chosen when an account is linked — *superseded by D172*

An account linked but never fetched has no sync position, so "from the sync
position" gives no start date. The start is chosen once at link time,
prefilled with the importer's default, because that is the one moment the user
thinks about history depth and the importer knows what its bank delivers
(spec §5.4). Legs pointing at such an account keep waiting, which is correct,
and the account shows *never synced*, so the wait always has a visible cause.
Rejected: treating the link date as the sync position, which never fetches any
history.

## D52 A value derived from a document lives only while its link is confirmed — *superseded by D108*

A changed document downgrades its automatic links, and a suggestion can be
rejected; either way the values it re-derived would otherwise stay, citing a
basis no longer true. They revert to what they held before, which the
document's basis records (spec §5.8). This keeps the invariant that every
key's basis is currently true. Rejected: keeping the values with a "basis no
longer confirmed" marker. A rejected link stays rejected even if the document
changes later: rejection is a deliberate decision, and a manual link remains
possible.

## D59 A switch-over keeps the user's history — *superseded by D86 and D103*

When an account kept by hand receives its first import, the overlap is
settled like any boundary, with existing entries taking precedence: what the
user accepted as good stays good, and an importer arriving does not invalidate
it (spec §5.3). A switch-over balance record derived from the reported balance
lets the hand-kept history converge on the importer's truth through its
reconciling entry, and the residual is shown before submitting so the user can
cancel and complete the history first.

This replaced replacing auto-created legs one by one when an account gained a
source, together with the orphaned-auto-leg flag and its operation. That
mechanism started only from imported legs already typed as transfers, so an
untyped card payoff produced a silent double count.

Rejected: anchoring the switch-over at the last manual balance record, which
assumes users regularly record balances for accounts they track by hand; and
letting the import win the overlap, which deletes entries the user had
reviewed, tagged and paired.

## D67 Low-confidence entries are confirmed one at a time — *superseded by D99*

History learns from every confirmed value, and a batch of twelve model guesses
confirmed at a glance would become evidence stronger than the model ever had.
Entries carrying `low_confidence` are therefore skipped by batch confirm (spec
§6). Rejected: weighting batch confirmations lower, which needs review metadata
D21 rules out.

## D72 Manual entries only until the first import — *superseded by D84*

On a synced account, a manual entry is either a duplicate of a row that will
arrive or a movement that never happened; with a reported balance it breaks
the assertion, without one it goes undetected. Manual entries can therefore be
created on an account only until a non-reverted import has written rows to it
(spec §3.9, I15). The rule needs no switch-over date: it is one condition on
what has been imported. A reverted first import makes the account take manual
entries again. Rejected: a warning only, which leaves both failure modes in
place.

## D74 Out of balance is derived when read — *superseded by D83*

A stored assertion result went stale: a void or a backfill fixing the problem
left the account "out of balance" until the next sync, and taking the latest
*run* flipped the status on every upload without a balance. The status is
computed when read from the latest reported record against current entries
(spec §5.10), and the stored result was dropped. It is a handful of sums per
account.

## D81 Cross-currency tolerance candidates stay in the core — *superseded by D112*

A transfer between two synced accounts in different currencies, instructed in
the sender's currency, carries neither side's amount on the other leg, so exact
matching cannot pair it. Candidates within a tolerance of the reference rate
are offered, never paired automatically (spec §5.7). Unlike a smaller-amount
suggestion (D82), the tolerance is bounded. The logic is core; the rate source
is an importer, so the candidates exist only once one does. Until then such a
transfer cannot be paired, even by hand. Rejected for now: letting the user
pick any partner for a cross-currency leg regardless of amount.

## D82 Smaller-amount transfer candidates are deferred — *superseded by D117*

Offering a partner that received less than the leg sent, with a split of the
remainder, would remove the manual split in the fee case. It opens matching to
arbitrary amount differences, so it waits for real data showing such splits to
be frequent (spec §9). The manual path is unaffected: split, then the residual
pairs exactly.

## D86 A switch-over is detected by overlap with hand-made entries — *superseded by D103*

Partly supersedes D59: its precedence of existing entries stands. "The first
import on an account that already has entries" missed an account linked
again after unlinking. A switch-over is now detected where incoming rows share
booking days with manual or matcher entries (spec §5.3). No switch-over record
is written: the first reported record reconciles against the previous record,
and its reconciling entry is the correction D59 wanted (D83). Its residual is
shown before submitting — the one place a reconciliation blocks — and where
the account holds no record yet, gaps in the hand-kept history fall into the
opening, which the decision step says.

Mirror legs need no rule of their own: they are existing entries in the
side-by-side table, the user sets the boundary after them, and duplicating
imported rows are trimmed. A wrongly set boundary leaves a duplicate that is
voided. Rejected: deleting mirror legs dated after the boundary automatically
and re-pairing their partners, which adds a rule for what trimming already
does.

## D87 Imports win after closing — *superseded by D115*

Partly supersedes D40: closing still requires a zero balance. "No entries
after `closed_on`" left undefined what ingest does with final interest booked
after the closing date. Imported rows dated after it are accepted — the
importer is the authority on what happened — and only manual entries and
mirror legs are refused (spec §3.3). Rejected: refusing the row, which drops
real money from the ledger; and reopening the account automatically.

## D93 Manual transfers may point at synced accounts — *superseded by D156*

An unpaired manual transfer to a synced account holds its destination as a key
and is therefore unreviewed and read-only from the moment it is typed. That is
accepted and stated (spec §3.9): it waits in the review queue like any unpaired
leg and is paired when the real leg arrives. Rejected: allowing manual
transfers only to unsynced accounts, which removes the state but forces the
movement to be recorded only from the synced side; and making manual entries
editable outside review, an exception to I21 the deletion rule (D92) makes
unnecessary.

## D94 A split pairs its residual at once — *superseded by D168*

A paired leg is unpaired before it is split, which deletes a mirror partner.
Waiting for the next post-import phase would leave the residual unpaired and
the unsynced account without its leg in between. The split applies §5.7 to the
residual in the same transaction, as conversion already did (spec §5.9).

## D100 A document reopens its transaction and re-derives — *superseded by D107 and D108*

Partly supersedes D57 and D71 ("documents reopen rather than re-derive") and
D79 ("never re-run"). A charge confirmed as PayPal whose document later names
merchant XYZ should arrive in review with XYZ proposed. Now a suggested or
confirmed link writes a `document` key, so the entry returns to review through
the same mechanism as every other reopening and "reviewed = complete and no
keys" holds without exception. When a link is confirmed, resolution re-runs
payee and category with the document-enriched input and all passes, on every
child of a split (spec §5.8, I18, I20). A changed value replaces the field,
with the previous value in its basis, and nothing is confirmed until the user
confirms the entry.

The old protection of rule-derived values is dropped: with the merchant name
in place of the card descriptor, a rule keyed on `PAYPAL *` no longer matches,
while a rule on the merchant still wins. Rejected: leaving confirmed entries in
review only as a flag, which fails the case above; holding proposals in the
key while the field keeps the old value, a second mechanism; and re-deriving
split children only where their amounts match document lines exactly, which
is too rigid — how each child's input is formed is left to the passes.

## D104 Manual entries are allowed on every account — *superseded by D156*

Partly supersedes D84; retires I15. Forbidding manual entries on synced
accounts encoded the same trust in importers over people that D103 drops.
With D103, a manual entry and its later import are simply a duplicate pair,
and the first one in wins. The switch-over and relinking as special cases
disappear with it. Synced or unsynced now decides only how a transfer leg
pointing at the account completes — by an import, or by a mirror leg created
on confirmation (D110).

A consequence worth knowing: a payment entered by hand before its import keeps
the manual entry, and history learns nothing from it, because manual entries
carry no source signals (D79).

## D118 Pairs between unconfirmed legs are rederived — *superseded by D163*

Partly supersedes D56 and D106. The matcher never revisited a pair it made, so
pairings depended on arrival order and were persisted decisions, while the
spec called matching order-independent and derived state a function of
current data (I37). A pair between unconfirmed legs is now a proposal like
any other value of an unconfirmed entry and is recomputed when settling
(spec §5.7, I18); reviewed pairs are never touched (I20). A commit is still
refused where the chosen partner moved (spec §6), so a recomputed pair cannot
slip under an open panel.

This also removes a contradiction: §5.7 dropped a pending destination when the
matcher paired the leg, §5.9 kept it until the pair was confirmed. It now stays
until confirmation, which a recomputed pair needs. Rejected: keeping sticky
pairs and correcting the wording, which leaves full and incremental settling
able to disagree.

## D120 Revert takes later runs that wrote nothing with it — *superseded by D172*

Partly supersedes D55. A later run that only skipped rows did not block a
revert, but its coverage and reported balance kept counting: uploading the
same file twice by mistake, then reverting the first upload, left the account
covered and with a balance, but with no rows behind either. Later runs that
wrote nothing are now reverted with the run (spec §5.6, I30); runs that wrote
rows still block. Taking a skip-only run that skipped other rows is harmless:
its coverage stops counting, `synced_through` may fall back, and the next
fetch overlaps more, which deduplication makes free. Rejected: reverting every
later run, which can delete history a bank will not redeliver without a TAN.

## D124 The unexplained difference is the sum of reported reconciliations — *superseded by D148*

Partly supersedes D101 and D85. Every booking the bank dates back into a
closed day left a pair of opposite reconciliations on consecutive records,
shown as two unexplained differences until someone deleted a record: manual
work that destroyed a data point, and that a same-day re-sync could undo. The
account's unexplained difference is now the sum of its reported records'
reconciliations (spec §3.11, §5.10): the pair cancels, a missing or duplicated
row persists. The per-record entries stay, so balances still match the bank on
every record date, and the records since the sum was last zero localise a
persisting difference. Deleting records remains a correction, no longer a
diagnostic.

Rejected: deriving no entries from reported records (the retired I14), which
would end "every record reconciles" (D83).

## D138 Document links are `linked` or `rejected` — *superseded by D169*

Partly supersedes D131. A link's status was `confirmed`, also set
automatically, so a transaction could be unconfirmed with a confirmed link
that nobody had seen. The status is now `linked`; `method` still says who
made it. A commit that picks another document records the automatic link it
replaces as `rejected`, like the other suggestions (spec §5.8). Renamed before
v1 because the table ships with it, where a later rename is a migration.

## D139 Manual entries stay in the amount step — *superseded by D146*

Considered and rejected: removing manual entries from deduplication, so that
an import always enters and a manual duplicate shows as an unexplained
difference. The goal was provenance — the surviving entry of a pair is the
manual one, and the bank's row is void. But nothing is lost: the void row
keeps its raw payload, is listed in its run's summary and can be unvoided. On
the same booking date the current rule settles the pair with no work; the
alternative turned every such pair into a difference to notice, investigate
and delete. Where the dates differ, both rules leave a duplicate. Users are
not expected to enter movements by hand on a synced account; where it
happens anyway — a switch-over, a back-dated booking — the amount step is
what keeps it from mattering. The goal is reworded to what the design
guarantees: every imported movement is kept, as an entry or as a void row
(spec §1.1, §3.9).

Also rejected again, as in D103: prefilling the first fetch of a hand-kept
account after its last manual entry. It would leave out exactly the bank rows
that unvoid uses to complete hand-kept history.

## D62 Document importers deliver one document per charge — *superseded by D230*

Automatic document matching is exact. Amazon charges an order in parts, often
weeks after the order date, so an order-level document matches its charges
only through the line allocation of D229. Granularity is still the importer's
first choice — one document per charge where the provider exposes charges,
dated on the charge (spec §5.5) — and the core rule stays exact. Rejected:
provider-specific windows in the core, which are fuzzy and put provider
knowledge where it does not belong.

## D76 Document waiting follows the document source's coverage — *superseded by D230*

Comparing a run's start time with a booking date needs a time zone, which D22
says the domain does not use. Document importers report the date up to which
their documents are complete, and an entry waits until that coverage passes its
booking date plus the matcher's window (spec §5.5, §6). Both waiting rules are
now the same rule: wait until the source that would deliver the missing piece
has moved past where it should have. Rejected: using the household's display
zone, which would have made document waiting the one domain rule depending on
a time zone.

## D96 Document auto-confirmation needs uniqueness both ways — *superseded by D230*

Two identical charges with one document each saw a single candidate, and the
first processed took it. Unlike indistinguishable transfer legs (D56), the
choice matters: the document re-derives payee and category, and the other
charge may be a different purchase. A link is confirmed automatically only
when the transaction has exactly one candidate and that document is a
candidate of no other transaction; otherwise every link is suggested (spec
§5.8).

## D108 Documents: one per transaction, unconfirmed transactions only, split by line — *superseded by D230*

Supersedes D52; with D107, D100; partly supersedes D96 and D97; strengthens
D62.

**Reviewed entries are left alone.** A document arriving for a confirmed
charge returned it to review and re-derived its values, replacing a human's
choice with a pass's proposal, then reverting it if the link was downgraded
(D52). Almost every document arrives while its charge is still unreviewed —
that is what the waiting bucket is for — so the late case did not justify the
machinery. The matcher now considers only unconfirmed transactions (spec
§5.8); a late document is linked by hand in the panel, where a re-resolve
preview shows what it would change. Waiting stays advisory, and confirming
early gives up automatic attachment.

**A confirmed link is an input to resolution**, as D63 had it, and D106 does
the rest: proposals follow the link while the transaction is unconfirmed, and
disappear with it. No previous values are kept and nothing is reverted.

**One document per transaction** (I35), enforced by a partial unique index.
D229 lets one document explain several transactions.

**Auto-split by document lines** on unconfirmed transactions: one entry per
line, converted proportionally where the document is in the instructed
currency, the residual taking shipping, discounts and rounding; no split
unless the total matches exactly and the residual keeps its sign. Each line's
entry takes its own line as input, which settles how a split's entries are
resolved. A suggested document is picked in the draft, and the preview shows
the split before the commit.

The document importer's start date is prefilled with the oldest unreviewed
entry's date, so enabling a source does not produce a pile of unmatched
documents for reviewed history.

Rejected: suggesting documents on confirmed transactions without a `document`
key, accepted by resetting the entries — a special case plus a destructive
reset (D107).

## D169 The document link is a field of the original entry — *superseded by D230*

Supersedes D138; partly supersedes D8, D11, D108, D131 and D166.

Documents kept a decision system of their own beside the keys: link rows,
`linked` or `rejected`, `auto` or `manual`, in a join table on the source layer;
a rejection memory (I25); a special writer in ingest deleting automatic links
when a document changed; and, since D166, a `document` key recording on the
entry who decided what a link row already recorded. The rows were workflow
decisions made in review, stored against the facts.

**The link is a derived field like any other** (spec §5.8, §5.9):
`ledger_entry.document_id`, on the transaction's original entry, keyed
`document` — `matcher_decision` or `matcher_proposal` for an automatic link
(D172), `user` for a pick or for "none",
a key without a value. The source layer stays facts; the link becomes
interpretation pointing at enrichment data, as `category_id` points at a
category. Since D167 every movement has a source transaction, imported or
user-authored, so this covers a cash receipt as well as an Amazon order: one
source, split if need be, one document.

- **I35 is enforced on the entries** by two partial unique indexes: a document
  is carried by at most one entry, and a transaction has at most one entry
  carrying a document. The original entry keeps its id through splits, so the
  link survives a re-split; `v_entry_document` resolves any entry's document
  through its transaction's carrier, one join instead of a copy per entry.
- **Suggestions are computed only while no document is decided**, so a pick or
  "none" keeps the other candidates from returning for as long as it stands.
  I25's permanent rejection memory is retired: a rejected candidate can come
  back only if the decision itself is reopened, which takes a change of input.
- **A changed document is a change of input.** Its total, currency, merchant
  or lines — what resolution reads — changing resolves an unconfirmed
  transaction afresh, its link included; a change elsewhere in the payload
  does nothing, so a provider updating an order's status does not discard a
  user's work. This replaces ingest's special writer.
- **The document comes first in field order.** Matching judges a transaction
  as resolved without one, and a link then changes every field after it, as
  the cascade of D163 already prescribes; a payee that a rule on the document
  resolves differently cannot undo the link it came from.
- **A removed entry frees its document**, so marking a duplicate, a revert or
  deleting a user-authored transaction needs no rule of its own for links.

Rejected:

- **The link only in the key**, which would make it the one derived value
  without a column, and leave I35 unenforceable.
- **The link on every entry of a transaction**, which needs an exclusion
  constraint, a trigger for mixed NULLs and sync on every split, for reads the
  view gives anyway.
- **Entries linked to document lines instead**, which cannot represent an
  unsplit transaction explained by a whole document, or a residual; a line
  reference remains a possible addition for split entries (spec §9).

## D173 Documents can be browsed; a late link splits like an early one — *superseded by D230*

Follows from D172: a commit now decides "no document", and the matcher only
considers unconfirmed transactions, so a document that arrives after its
charge was committed is linked only by a person. Two gaps made that hard.

- **Documents are browsable** (spec §5.8), each with the transactions carrying
  it, filterable to those not fully charged. For such a document, the
  transactions it would match by amount and date are offered, confirmed ones
  included, and picking one opens the panel with the document in the draft.
  The reverse match is read-time only, like suggestions; settling still never
  links a confirmed transaction (I20). Rejected: a notice on the transaction
  when a late document arrives, which is review state on a reviewed unit.
- **A late link is split like an early one**: a pick in the panel is a link not
  yet the user's, so the draft proposes the split along the lines, confirmed
  unit or not (D229).

## D229 Order documents: one document, several charges — *superseded by D230*

Spec I21, I35, §3.6, §3.8, §5.1, §5.5, §5.8, §5.9 (pass 2, pass 3), §6; documents.md; history.md; architecture §4.1,
§5.4, §5.5. Partly supersedes D62 (sum-matching rejected), D108 (one document per transaction and per document), D166
and D173 (an existing split stays), D172 (a symmetric document window) and D224 (registered providers).

- **A document may explain several charges; each of its lines explains at most one.** An email importer sees
  orders, and Amazon charges an order in parts without saying which items each part paid. So I35 moves from the
  document to its lines, and D108's "one document per transaction, and per document" keeps only its first half.
  A document of one charge behaves as before. D62 rejected sum-matching as fuzzy; a line allocation is exact —
  each charge equals the sum of the lines it takes — and bounded to documents of at most 20 lines.
- **Which lines a charge paid is worked out, not stored: the line allocation.** It follows from the links and the
  amounts whenever it is needed. Where a committed split already says which lines a charge paid, that split is
  kept if the order still adds up with it. Only if it does not are those lines moved — and then the panel
  proposes the corrected split, instead of the order no longer being suggested at all. Rejected: *treating
  committed splits as fixed* (one wrongly split charge would hide its order for good); *a column on the line
  naming its charge* (the same fact stored twice, kept in step with the links); *matching each charge on its own*
  (a confirmed charge's lines would move as others arrive); *re-resolving confirmed charges as a changed input*
  (blurs I20); *a configurable line limit* (a setting nobody can tune; 20 lines bounds the search and covers
  real orders).
- **Nothing automatic undoes a user's split.** Settling links a charge only where every committed split can stay
  as it is, and only into a document none of whose charges is confirmed.
- **The charges of one document form one unit.** A transaction carrying a document has no transfer entry, so a
  unit never chains and its closure stays one step. The rule is the commit's: only a commit makes a split's
  other entries. Rejected: *reviewing each charge alone* (one order's items spread over several panels); *a
  database trigger for the transfer rule* (it would guard a write only the commit makes, already checked there).
- **The split along the lines is proposed while any of the document's links is not yet the user's**, for every
  charge of the document and over any split it has. The preview lists the entries it replaces, with their tags;
  the user commits the proposal or edits it like any split. Once every link is the user's, nothing is proposed.
  This replaces D166's and D173's "an existing split stays": the list of replaced entries is now the safeguard.
  Rejected: *a "decline" for the proposal* (one more control and one more preview state; the draft field
  `decline_split` goes — a yes or no on redoing the split belongs to a staged panel's document step).
- **A partly charged order waits for its other charges**, so it is reviewed once, when complete. The wait is
  advisory, holds no confirmation of its own and needs none to skip: a commit ends it. It ends with account
  coverage, like every other wait. Rejected: *ending it by the calendar* (elapsed time says nothing about whether
  a charge has been imported).
- **The document window is asymmetric**, 60 days back and 7 ahead, replacing D172's symmetric window: an order is
  charged when it ships, weeks later for a backorder.
- **Discount and coupon lines go into the remainder.** No line is marked and no importer filters.
- **Providers are open.** An email importer delivers whatever name a receipt carries, so the payee's
  `document_provider` is free text with suggestions — the names importers give and the providers of stored
  documents — and waiting asks each instance whether it delivers a provider. D224 rejected free text because a
  typo silently matches nothing; the suggestions make a typo unlikely, and receipts from a shop no importer names
  must still be nameable. Rejected: *a registry of providers* (no complete list exists once receipts can come
  from anywhere).
- **An entry made from a document line is classified from that line.** The model is asked about every line when
  the document arrives, and the answer is stored on the line; every other entry is asked about itself, as
  before. History's merchant key is not asked for an entry with a line: one merchant covers every kind of
  spending. Rejected: *settling creating the split* (D152's reasons, worse once lines move between charges); *a
  cache of answers by payload* (state with no owner); *asking only for stored links* (misses suggestions).
- Deferred: a staged work panel; editing a line's category by hand; the order number as a tie-breaker.

---

# Superseded passages

Passages removed from entries that stay in `decisions.md`, because the rest
of each decision is still in force. Kept verbatim under the entry's
identifier, with the decision that replaced them; the entry itself now reads
as corrected.

## D2 No general grouping abstraction, in part — *superseded by D146*

| Need | Covered by |
|---|---|
| Split | `source_transaction_id` |
| Transfer pair | `counterpart_entry_id` |
| Transfer + fee | sibling splits of one source transaction |
| Refund, reimbursement | same category, opposite sign; nets |
| Trip, project, "related" | tags |
| A booking delivered twice | void (spec §5.6) |
| Installments, recurring | a future schedule feature, not a group |

## D8 Review flags as a derived array, not a table, in part — *superseded by D163 and D169*

A table was the first draft, justified by "don't re-ask me". But that state
already lives elsewhere — a rejected document link is
`source_transaction_document.status`, a correction is an accepted value that
pass 2 reads — so flags are pure presentation of current state and can be
recomputed freely. Flags are a closed, machine-written set of tokens — five
since `orphaned_auto_leg` went with the auto-leg replacement (D59) — which is a
constrained array column, not tags. Not even "reviewed" is persisted: it is
"complete, with no derivation keys" (spec §6). The flags themselves cannot serve
as that proof, because they are the output of the function that would read it.

## D13 Derived over stored, where the read pattern allows it, in part — *superseded by D168*

`origin` is stored because it is not derivable: an auto-created leg and a leg
typed by hand look structurally identical, and a confirmed derivation no longer
says which it was.

## D21 No audit log or undo in v1; who and when only on event records, in part — *superseded by D163*

`derivation` is review state: it shrinks as review proceeds and is not made to
double as audit. Considered: keeping confirmed keys with a confirmation marker;
rejected as mixing a review mechanism with an audit function. Considered: a
small confirmation record serving only batch undo; rejected together with undo
itself. Audit and undo are coupled — a trigger-written change log would serve
both — and both are left out until they are missed (spec §9). The same test
decides attribution and timestamps: ledger entries carry no `created_by`,
`created_at`, `updated_at` or review time, because each of those is a
question only an audit log answers properly. Needing one of them is the
signal to build the log, not to add the column. A mistaken confirmation is
corrected by editing.

## D24 Payees are curated; history keys on source signals, in part — *superseded by D144*

Considered: allowing payees on transfers, so that history could learn "this
counterparty is a transfer to cash" through the payee. Rejected: it turns the
payee from a reporting dimension into a registry of every counterparty, down to
each ATM operator. History keys on the source fields of past cases instead (spec
§5.9), where the counterparty name is available anyway. Also rejected for now:
rules that declare transfers. Transfers to the household's own IBANs are
recognised by pass 0 (D64), all others by history, and a rule table is additive
later.



## D42 FX translation is computed per account, in part — *superseded by D113*

A maximum rate age was added: a rate feed that stopped would otherwise value
later years silently at old rates. A value past it is unvalued, and the
currency shows as stale. Rejected: valuing anyway with a stale marker, which
shows an unknown value as if it were known.

## D43 A split keeps the original row as its residual, in part — *superseded by D163 and D168*

The original entry stays as the residual child and keeps its id, type, keys
and tags; new children are the user's and keyless (spec §5.9). This disturbs
least — the row id survives under a keyboard cursor — and leaves unconfirmed
values unconfirmed rather than confirming them by the act of splitting.
Rejected: replacing the entry with N new keyless rows, which treats a split as
a review of everything on the entry.

A paired leg is unpaired before splitting, and the pair trigger was tightened
to require equal amounts for same-currency pairs, which the matcher already
required but the database did not (spec I10).



## D46 A source id replaces the ordinal in the hash, in part — *superseded by D103*

The cost is that identical content delivered by an id regime and by a no-id
regime no longer collides; boundary settlement handles that case anyway
(spec §5.3).

## D53 One routine removes an entry and its consequences, in part — *superseded by D169*

Unpair deleted a matcher partner and revert deleted mirror legs, but void did
not, leaving an auto-created cash leg inflating the wallet, and a void row kept
its document links, blocking the documents from matching the surviving row.
Void, revert and every operation that breaks a pair now share one routine
(spec §5.6). Document links are deleted rather than rejected, because the void
row was never a real booking. Rejected: refusing to void a paired or linked
row until the user has cleaned up by hand, which costs clicks and reaches the
same state.

## D70 Breaking a pair returns the leg left behind to review, in part — *superseded by D168*

A former partner left behind by re-pairing, converting to a flow or changing
the counter-account was said to "stay", which is not a state: often it was a
confirmed transfer without a partner. It goes through the removal routine —
deleted if it is a mirror leg, otherwise returned to review as a transfer
without a partner (spec §5.9). Rejected: requiring the user to decide both legs
in one dialog, which makes every unpair a two-entry decision.

## D92 Deleting a manual entry runs the removal routine, in part — *superseded by D167 and D168*

A paired manual leg deleted without the routine left a mirror pointing at
nothing or an imported leg with a dangling counterpart. Deleting a manual entry
is a trigger of the routine like void, revert and breaking a pair (spec §5.6).
A manual entry may be deleted even while unreviewed (I21): everything on it is
the user's own.

## D105 Derived entries are never reviewed; reconciliation is its own type, in part — *superseded by D163 and D168*

The existing principle already answers it: deterministic consequences carry
no key. A derived entry follows mechanically from a record, as a mirror leg
follows from the user's choice of destination, so it is never resolved and
never reviewed (spec §3.9). Three types carry the meaning (spec §3.4):
`opening` for the anchor's entry, `valuation` for later records on investment
accounts, `reconciliation` for later records on any other. All three are
computed by one formula (spec §3.10), are excluded from income, expense and
savings, and have their own report lines (spec §8). The reconciliation line
also tells the reader how much of a report rests on movement the ledger does
not explain — an accuracy signal, kept apart from valuation, which is not an
error.

The type is stored rather than derived when read: `origin` says how an entry
came to exist and `type` what it means, so a single `adjustment` type would
merely duplicate `origin = 'balance'` and push the meaning into a
classification every report would repeat. Storing it costs nothing extra,
since the derived entry is recomputed on every change to its records anyway.
For the same reason that a category's kind is fixed (D41), whether an account
is an investment account is fixed at creation (spec §3.3, I38).

## D107 Review is atomic and per unit, in one panel, in part — *superseded by D156, D163, D165 and D172*

**Per unit.** Reviewing per entry let one leg of a pair be confirmed while
the other was pending — and under D106 a recompute of the pending leg would
then break a confirmed pair. A unit is now the entries of a source
transaction or a transfer pair, joined transitively, and is reviewed when all
its entries are complete and keyless (spec §6, I21). Mixed states cannot
exist. I22 becomes "a transfer is confirmed only as a pair", which also
reviews the match itself when a manual leg's partner arrives.

**Atomic.** Nothing in review needs to persist before the commit except one
thing: a transfer destination whose partner has not arrived, kept as the
pending key of D28. Everything else is a **draft** — document, partner or
destination, split, field values — laid over the stored state; the panel
previews it with the same pure functions the core uses, and one commit writes
the full state the user saw. It is refused only where the unit's structure
changed, so a proposal recomputed meanwhile never invalidates a review. The
two ways to finish are commit and *set destination and wait*.

- **Confirming a waiting leg with a stored `counter_account_id`**, which
  would put a confirmed leg back into review when its partner arrived and
  reopen D28's rejected column.
- **A reset operation** — replacing a confirmed unit by one fresh entry and
  sending it back to review. Destructive, and everything it was for is a
  preview in the panel.
- **Two write paths**, preview-and-commit in review but immediate operations
  after confirmation, which would keep both sets of operations alive.

## D144 Rules may declare a counter-account, in part — *superseded by D179*

A rule may now set a counter-account, which types the entry a transfer (spec
§5.9). It obeys the currency rule like every machine proposal: a rule for the
euro wallet does not match a withdrawal abroad. Its keys are standing. Where
the counter-account is synced, the leg waits and the pair is confirmed when
made (D142); where it is unsynced and no candidate exists, the unit is
confirmed by its standing keys and its mirror leg is created with it (I34
reworded). A leg whose synced counter-account passed the window without a
partner still needs a commit: there, a missing partner more likely means
missing data.

## D151 No resume cursor, in part — *superseded by D172*

Every fetch starts from the account's derived `synced_through` minus the overlap
(spec §5.4), and neither the CSV nor the FinTS importer needs anything else.
`account_source.cursor` is dropped; an importer that needs a credential-scoped
cursor can bring it back. D11 is corrected accordingly.

## D156 Entries made by hand live only on unsynced accounts; waiting is a hint, in part — *superseded by D178*

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
unsynced, so a closed account's payout still gets its counter-leg. A
trigger enforces the rule on creation and on a change of account.

## D163 Every derived value carries a key; pairs stand once made, in part — *superseded by D166, D167 and D172*

- **Every derived value carries a key.** Passes `history` and `llm` write
  proposals. Passes `own_account` and `rule` write standing keys, and so do two
  new ones: `matcher`, for a pair or counter-leg that settling made, and
  `user`, for what a user decided in a commit.
- **A commit keeps unchanged standing keys.** A proposal accepted unchanged
  becomes `user`, with the proposal's key as its basis — a snapshot of what it
  was accepted on, for display and for later analysis of how often history and
  the model are right. A value set or picked by hand becomes `user` without a
  basis, and a `user` key never wraps another. An entry without a `user` key had
  no derived value decided by a human.
- **A pair is a standing value of its maker** (spec §5.7): it carries a
  `counterpart` key of pass `matcher` or `user` on both legs. Whether it needs
  review is decided by the legs' other keys: a guessed counter-account keeps
  the unit in review, a decided one does not.

**What reopens a standing value** (I18) is stated once, for every kind. An
entry's input is its source row and its linked document; when it changes, the
entry is resolved afresh — a user's values included, since new input is
exactly when a decision deserves a second look. This can only happen to an
entry not yet reviewed, because a reviewed one never gets new input. And when
a value changes, every standing value after it in field order is derived
again, the pairing last. That needs no record of which fields a pass actually
read: passes read only earlier fields, so the field order bounds every
dependency, and it closes a gap D159 left open — a category rule keyed on a
payee that history later proposed differently. Over-approximating is
harmless: a pass re-derived without a change to what it read gives the same
result, unless the rule itself changed, in which case it is applied again at
that moment, consistent with a rule applying at a point in time.

## D169 The document link is a field of the original entry, in part — *superseded by D172*

**The link is a derived field like any other** (spec §5.8, §5.9):
`ledger_entry.document_id`, on the transaction's original entry, keyed
`document` — `matcher` for an automatic link, `user` for a pick or for "none",
a key without a value. The source layer stays facts; the link becomes
interpretation pointing at enrichment data, as `category_id` points at a
category. Since D167 every movement has a source transaction, imported or
user-authored, so this covers a cash receipt as well as an Amazon order: one
source, split if need be, one document.

## D174 Housekeeping after the implementability review, in part — *superseded by D176*

- **Category merges descend the tree** (spec §3.5). A child whose name the
  target's children already use is merged into that child, recursively, and
  the preview lists every category merged. Rejected: refusing the merge until
  the user renames, more friction for the same result.
- **The category tree has no cycles** (I9), enforced by a trigger; the CHECK
  covered only a category parented to itself.
- **Category names are unique per kind and parent**, so the two roots may
  share a top-level name such as "Other".
- **Setup prefills the three windows** — maximum rate age, matching window,
  document window — with 7 days each, editable later (spec §3.8).
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

## D177 Review before implementation: run order, afresh by the writer, settle order, classifier specs, in part — *superseded by D178*

- **A settle has a fixed order and two rounds** (architecture §5.2):
  resolution, documents, re-resolution after a link, pairing, counter-legs,
  derived entries, flags; then once more for units sharing a history key with
  one newly confirmed. Only standing values confirm and history only
  proposes, so the second round confirms nothing new and settling is
  idempotent (I37). Rejected: one round, leaving history's effect to the next
  write, which breaks idempotence. Lock order is stated: settle lock first,
  account locks ascending.

## D178 Second review before implementation: counter-legs, pairs, merges, documents, settling, in part — *superseded by D179*

- **A counter-leg follows its partner in a commit** (spec §5.7). Counter-legs
  were once derived and are now ordinary user-authored rows (D168), so a split
  taking interest off the Giro leg left the pair unequal, and the written remedy
  — split the difference off the larger leg — put the interest on the loan.
  Where a draft changes the amount of a leg paired in one currency with a
  user-authored leg that is its source's only entry, the commit sets that
  source's amount to match. Rejected: restricting the entry form on paired
  counter-legs, which would couple the source layer to its interpretation. The
  form stays a full re-resolution, the user's values included (spec §5.6): the
  panel is where interpretations are edited, and editing what a source says has
  those consequences.

## D178 Second review before implementation: counter-legs, pairs, merges, documents, settling, in part — *superseded by D181*

- **Settling makes no counter-legs on a closed account** (spec §3.3, §5.7). An
  account whose importer stopped stays usable by hand, so open unsynced accounts
  keep getting them; a closed one would only collect precautionary rows that
  reopening could duplicate. The panel still offers them. Counter-legs whose
  partner is removed stay, as ordinary rows, and return to review unpaired.
  Rejected: deleting them with their partner, which would make them less than
  ordinary transactions.

## D179 Re-review of D178: counter-legs only where nothing is offered, in part — *superseded by D180*

- **Settling creates a counter-leg only where the leg has no offer** on its
  counter-account (spec §5.7): no unpaired transfer leg and no untyped entry
  there within the window, of any amount. A counter-leg edited through the
  form, one left behind by a broken pair, or a withdrawal typed by hand is then
  offered first instead of being duplicated by a second counter-leg with
  standing keys — which, under "no candidate", happened silently whenever the
  amounts no longer matched. One condition, no stored state; it also removes
  the plan's known case of a settling counter-leg duplicating a hand-typed
  withdrawal. Accepted: deleting a counter-leg whose partner's counter-account
  is still decided recreates it; the remedy is to change the partner. Rejected:
  skipping legs left behind by a user operation, which settling cannot tell
  without a marker.

## D179 Re-review of D178: counter-legs only where nothing is offered, in part — *superseded by D181*

- **Settling creates a counter-leg only where the leg has no open offer** on
  its counter-account (spec §5.7; defined in D180): a counter-leg edited
  through the form, one left behind by a broken pair, or a withdrawal typed by
  hand before settling ran is then offered first instead of being duplicated
  by a second counter-leg with standing keys — which, under "no candidate",
  happened silently whenever the amounts no longer matched. One condition, no
  stored state. Accepted: deleting a counter-leg whose partner's
  counter-account is still decided recreates it; the remedy is to change the
  partner. Rejected: skipping legs left behind by a user operation, which
  settling cannot tell without a marker.

## D180 Open offers, and what the preview proposes, in part — *superseded by D181*

- **An open offer** (spec §5.7) is an unpaired transfer leg or an untyped
  entry on the counter-account, opposite in sign and within the window, of
  any amount — not a leg whose own known counter-account is another account.
  Read literally, "no offer" was never true: offers include legs paired
  elsewhere and the counter-leg itself; and without the sign and the
  counter-account filter, a cash expense or another wallet's leg would have
  blocked every rule-decided withdrawal. Only open offers keep settling from
  creating a counter-leg, and a counter-leg settling just made is paired, so
  it blocks nothing later in the same settle.

## D178 Second review before implementation: counter-legs, pairs, merges, documents, settling, in part — *superseded by D225*

- **Enrichment lives only in resolution's input** (spec §5.9): the merchant
  name stands in for the counterparty name, the lines are read with the
  purpose, and the source row is never changed. Rejected: the merchant beside
  the counterparty name, which would need a rule condition of its own.

## D181 Full scan before implementation: settling creates no counter-legs; history and documents; locking, in part — *superseded by D225*

- **History does not run for a transaction with a document**, and such a
  transaction does not vote (spec §5.9). Its bank fields describe the
  provider, so a majority over them was systematically wrong — every PayPal
  charge alike — and kept the model from being asked; rules and the model
  decide on the enriched input. Rejected: history on the payee alone for such
  transactions, which keeps the systematic error for mixed payees such as
  Amazon; and enriched votes, deferred (spec §9).
- **Per-line input lives in the draft** (spec §6): the preview resolves each
  entry it made from a line with that line, every other entry with all lines.
  Nothing records the line once committed, so per-line input after the
  commit waits for `document_line_id` (spec §9).

## D142 Housekeeping after the second review, in part — *superseded by D225*

- A document provider's category comes from the enriched input.

## D169 The document link is a field of the original entry, in part — *superseded by D225*

- The document comes first in field order: a payee the enriched input resolves
  differently cannot undo the link it came from.

## D62 Document importers deliver one document per charge, in part — *superseded by D229*

Automatic document matching is exact and one-to-one. Amazon charges per
shipment, often weeks after the order date, so order-level documents rarely
match a charge.

Rejected: sum-matching and provider-specific windows in the core, which are
fuzzy and put provider knowledge where it does not belong.

## D108 Documents: one per transaction, unconfirmed transactions only, split by line, in part — *superseded by D229*

**One document per transaction, and per document** (I35), enforced by two
partial unique indexes. The only real many-to-many case is an order-level
document for an order charged in parts, which exact matching could not link
automatically anyway; it can now be linked to one charge.

## D166 The panel's anchor; documents keyed and held, in part — *superseded by D229*

**An existing split stays when a document is picked.** The draft proposes the
split along the lines only for a transaction that is not split; otherwise it
offers *split along the lines* as an explicit choice, shown with the entries
and tags it would delete. A split is a decision, and new input does not discard
it unless the user chooses so.

## D172 Counter-account column, one rule table, simpler revert, documents in v1, in part — *superseded by D229*

- **The document window is a ledger setting** (spec §5.8), symmetric like the
  matching window, replacing the matcher's fixed −7/+2 days (D76).

## D173 Documents can be browsed; a late link splits like an early one, in part — *superseded by D229*

- **Documents are browsable** (spec §5.8), each with the transaction carrying
  it, filterable to those no transaction carries.
- **The split along the lines is proposed for any linked transaction in the
  panel**, confirmed or not, so linking late gives the same draft as linking
  early. An existing split still stays unless the user chooses to replace it.

## D224 Step 9: the document decision is enforced; providers are registered, in part — *superseded by D229*

- **Providers come from the registered document importers,** listed by `GET /api/documents/providers`. A payee's
  `document_provider` is selected from that list; setting an unregistered value is 422 `unknown_document_provider`,
  an unchanged stored value stays and clearing is always allowed. Rejected: *free text* (a typo silently matches
  nothing and waits for nothing).

## D63 A document is input to resolution, not a pass of its own, in part — *superseded by D230*

Instead, re-derivation
re-runs resolution with the document's merchant name in place of the
counterparty name and its lines added to the purpose (spec §5.8).

## D97 Document importers have a start date, in part — *superseded by D230*

Enabling a document source whose first fetch reaches back years would return
hundreds of confirmed entries to review (I20). Each document importer instance
has a start date, chosen once like an account's first fetch, below which
nothing is imported (spec §5.5). Rejected: a bulk "dismiss suggestions before"
action, which cleans up afterwards what need not be imported; and a separate
matching cut-off, which keeps documents that do nothing.

## D131 Document matching is a subsystem of its own; links store decisions only, in part — *superseded by D230*

Two internals changed on the way. Suggested links were stored and never
updated, so one that stopped being a candidate stayed open forever. Links now
store decisions only — confirmed and rejected — and suggestions are computed
when read; ingest's downgrade to `suggested` goes with them, and a changed
document instead deletes the automatic links of unconfirmed transactions to
it. And the model's answer is kept per payload rather than per entry, so a
document confirmed later is put to it once more (spec §5.9).

## D142 Housekeeping after the second review, in part — *superseded by D230*

- Waiting for a document requires an unconfirmed unit, as matching does. With
  `waiting` a stored flag (D140), a charge confirmed before its document
  arrived would otherwise have sat in the queue.

a link's document is
  "linked elsewhere", not confirmed; a document provider's category comes from
  the entry's own resolution

## D152 A document's lines are a split the preview proposes; only a commit splits, in part — *superseded by D230*

The preview of a linked unit now
proposes the split along the lines, resolved line by line as before, and the
commit writes it (spec §5.8, `documents.md` §6). I7 becomes "only a commit
splits". Units that pass 0 and rules decide completely are confirmed at once
and never matched, so nothing is lost there.

## D166 The panel's anchor; documents keyed and held, in part — *superseded by D230*

**Documents are keyed and hold automatic confirmation.** Rules that decided
every value of a charge from a provider confirmed it at ingest, before its
document could arrive, so the document was never matched; `documents.md` could
only advise against category rules on such payees. And an automatic link could
confirm a unit without the split along its lines ever being seen. Now:

- the document link is a keyed field, `document`, on the transaction's original
  entry: `matcher` for an automatic link, `user` for a pick, or for "none" with
  no link. Suggestions, like transfer offers, are computed when read and carry
  no key;
- a new requirement of confirming: no document still awaited. Settling does not
  confirm a waiting unit; a commit can decide "no document" and confirm; the
  waiting ends with the coverage, never permanently;
- a `matcher` link to a document of several lines is a proposal — the one
  `matcher` key that is not standing — so the unit is reviewed once, through
  existing flags and rules, and the commit makes it `user`, with or without the
  split.

Splitting along the lines during settling stays out, and is sketched as an open
question (spec §9): the keys would make it idempotent, and what it would bring
back are the costs that led to D152.

## D172 Counter-account column, one rule table, simpler revert, documents in v1, in part — *superseded by D230*


  `matcher_proposal` is a proposal — settling's link to a document of several
  lines. Replaces the one exception inside `matcher`, so whether a key is
  standing is read from its pass alone.

- **A commit decides every value it leaves as it is, the document included**
  (spec §5.8, §6). With no document picked it writes "none"; where documents
  are suggested or one is awaited, the preview asks the user to confirm that.
  Supersedes D170's note that waiting for a document can make committed work
  be redone: committing gives up the document instead.

- **The document window is a ledger setting** (spec §5.8), replacing the matcher's
  fixed −7/+2 days (D76); D229 gives it two ends. With
  several instances for one provider, a transaction waits until all that are
  not disabled have covered it: there is no knowing which one would deliver.

so a commit made on an older document is refused (spec §5.5,
  §6). `document_id` and

- **Document matching is in v1**, exercised with a test document importer;
  only the real document importers are not.

## D177 Review before implementation: run order, afresh by the writer, settle order, classifier specs, in part — *superseded by D230*

- **Importers declare the document providers they deliver** (spec §5.5), in
  code, so waiting is known before an instance's first run. An instance that
  has never run holds its providers' transactions dated from its start date
  on, as a never-fetched account holds legs waiting on it; disabling it ends
  that. Rejected: a provider setting per instance, configuration for a fact
  the code knows; and inferring providers from delivered documents, unknown
  until the first run.

## D178 Second review before implementation: counter-legs, pairs, merges, documents, settling, in part — *superseded by D230*

- **A split along a document's lines** gives the original entry the first line
  and the remainder, so lines adding up exactly no longer leave a zero
  residual; a one-line document is not split (spec §5.8).

- **A changed `document_id` always bumps the version**, settling's links
  included, so a commit cannot silently take a document settling linked or
  overwrite a link it never showed. The commit carries the document's version
  too.

so an entry linked in an
  earlier settle keeps the document fields its rules read

The empty
  value a commit decides is only the document's "none"

The plan gains a document-matching step and an order

## D181 Full scan before implementation: settling creates no counter-legs; history and documents; locking, in part — *superseded by D230*

- **Confirmation stays put** (spec §6): settling records "none", keyed
  `matcher_decision`, for each transaction of a unit it confirms without a
  document key, and the document conditions apply only to transactions
  without one. Otherwise a document source set up later turned months of
  rule-confirmed charges into waiting, matched and re-derived ones, against
  I20. Rejected: storing review state.

- **Keys 1 to 5 of history do not run for a transaction with a document**, and
  such a transaction does not vote for them (spec §5.9). Its bank fields
  describe the provider, so a majority over them was systematically wrong —
  every PayPal charge alike — and kept the model from being asked. Rejected:
  history on the payee alone for such transactions, which keeps the
  systematic error for mixed payees such as Amazon. The document's merchant
  is asked on a key of its own, for the category (D225).

- **An entry's line is stored with it** (spec §5.8, §6; D225): the entry
  references its line of the document, so the preview and the commit resolve
  an entry alike.

Document ingest re-resolves only unconfirmed transactions.

## D223 Step 9: documents with a test importer, in part — *superseded by D230*

- **D1 Documents are part of the one confirmed predicate.** `units_sql` and its Python twin test for an open
  document, gated to originals with a provider payee and no document key, pinned by a test. Computing it only in
  settling would let a unit decided by rules count as confirmed, never be loaded, and never match.
- **D2 A registry the composition root configures** tells settling which instance provides which provider, as for the
  classifiers; core never imports plugins and the schema is unchanged. The start date is the setting `start_date`.
- **D3 A data migration records "none"** (`matcher_decision`) on every unit confirmed before documents existed, so a
  later source cannot reopen it (I20).
- **D4 Eligibility is judged on the original entry's payee only,** the entry that carries the link.
- **D5 The waiting flag wins.** A unit waiting for a document is in the waiting section even while suggestions
  exist, because what it waits for may change the user's other decisions. Rejected: *pending review while
  suggestions exist* (a decision on a suggestion could be overtaken by the document that is awaited).
- **D7 Picking by hand reuses `GET /api/documents`** with provider and unlinked filters. Rejected: *a separate
  endpoint*.
- **D8 A changed document re-resolves an unconfirmed carrier afresh,** dropping the user's pick; the panel shows it as
  a consequence. Rejected: *a guard that keeps the pick* (a document whose total changed may no longer be the one).
- **D9 Replacing an existing split along the lines is built last,** with the tags it deletes listed. Rejected: *cutting
  it from the first cut*.

## D224 Step 9: the document decision is enforced; providers are registered, in part — *superseded by D230*

- **The server enforces the explicit decision.** A commit where documents are suggested or one is awaited and the draft
  has no document decision (a pick, `none`, `split_along_lines`) is refused, 422 `document_decision_required`; the
  preview reports `decision_required` and the panel offers "Commit without a document" (draft mode `none`). With an
  importer and a waiting entry the user must consciously decide not to wait. Rejected: *a convention the panel keeps*
  (nothing a client sends then separates a decision from a default).
- **A payee's `document_provider` is suggested from `GET /api/documents/providers`;**
  D229 makes it free text, any value accepted, clearing always allowed.
- **A provider mismatch applies only where the payee has a different provider;** a payee with none takes any document
  (documents.md §9 offers a document to any payee, found by hand).

## D225 Documents are inputs to rules, not a rewrite, in part — *superseded by D230*

- **An entry's line is the line it was given, referenced from the entry** (`document_line_id`), so the preview and the
  commit agree. Applying the lines is one operation: with one line, the original entry takes it in the same write as the
  link (settling or a commit); with several, the commit's split along the lines gives each entry its line. Every other
  entry has none. A reference rather than a number: lines have ids, a changed document's lines are replaced (which
  clears the references), and another document's line is detectable when read. Rejected: *no stored line* (the preview
  and the commit then resolve differently); *a stored line number*; *deriving a one-line document's line when read* (a
  second definition of an entry's line, next to the stored one).

- **The payee of a documented charge is the provider, unless a rule on the document sets a curated merchant.** The
  descriptor rule stays standing and fires again after the link; a rule on `document_merchant`, ordered before it, is
  the explicit act of curating the merchant. Two aids, both reusing the editor: the panel offers "Create rule from this
  transaction" where the draft changes a value a *rule* set (not wherever a user changes a payee or category: only
  there is the rule what keeps coming back), and the editor gives a new payee rule with a document condition a priority
  before every payee rule without one. Rejected: *a provider payee that history may replace* (a third value state
  between proposal and decided value, touching review state, confirmation and the commit).

- **History asks one new exact key for a documented transaction: the document's merchant, for the category only.**
  Raw keys 1 to 5 stay closed to documented transactions, which vote only for the merchant key. Threshold unchanged (a
  single unanimous precedent is a majority); raising it belongs to the model's design (spec §9, the model as the
  reviewer of weak history). Rejected: *tokenizing lines in history* (product titles rarely repeat and shared words
  agree for the wrong reasons). Deferred to the tuning section of `history.md`: an exact-line key for reorders, asked
  before the merchant key and only for an entry with a line.

- **A link is new input and re-derives the standing values after it, a user's included** (§5.9: new input is when a
  decision deserves a second look). Only the sentence "never replaces a value a user confirmed" goes. The panel-wide
  "Re-resolve" keeps its meaning and gets no warning: its preview shows what changes.

`document_merchant` and
