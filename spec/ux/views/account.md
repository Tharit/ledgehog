# Accounts — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §3.3, §3.10–§3.11, §5.4, §5.6 and
§5.10; the contracts are `architecture.md` §4.1 (*The account statement*).
Importer instances and the CSV upload flow are in `ux/views/importers.md`.

---

**Accounts is a top-level item of the navigation.** `/accounts` lists the
accounts, `/accounts/[id]` is one account. The importer instances that feed
accounts are managed in Settings (`ux/views/importers.md`), not here.

## The list

`/accounts`, titled "Accounts", with the primary action "Add account", a form
dialog (`ux/patterns.md` §11.1); once added, the account's page opens. One row
per account, open accounts first by their sort order, then closed ones,
muted. A row shows the account's name, kind, balance — with the currency code,
since accounts of several currencies stand together (`ux/patterns.md` §2) — and
its facts as the quiet line of `ux/patterns.md` §4.4: data age, "balance not
anchored", the unexplained difference. A row opens the account. An empty list
says how accounts come about: added here, then fed by a file, a sync or by hand
(§9). The list is not the dashboard: sorting accounts by data age and the
reports are step 11's.

## The account page

**A bank-layer view.** Its data is the account, its source transactions —
duplicates included — and its balance records: what the sources said and what
was reported or counted. Nothing of the entry layer appears on it: no category,
payee, tag, split mark or derived entry. "View entries" in the header opens the
ledger list filtered by the account (`/ledger?account_id=`), where the
interpretation is.

**Header.** The page header carries the account's name and, as its description,
kind, currency and, for a closed account, "closed on <date>". Below it, in
this order:

- the balance and the quiet facts line (`ux/patterns.md` §4.4): data age,
  "balance not anchored" with "Set balance" beside it, the unexplained
  difference as an amount. The reported records that localise a difference
  (`spec.md` §5.10) are marked on the statement as "since the difference began"
  rather than listed twice;
- the **linked sources**, one line each: the instance's label and importer, and
  its action — "Upload" for a file importer (`ux/views/importers.md`), "Fetch"
  for one that fetches (with the sync, a later wave). An account with none says
  how it is fed: "Not linked to an importer — link one in Settings → Importers",
  a link, and that it can be kept by hand;
- the actions: "Set balance", a form dialog (the date, defaulting to today, and
  the balance, with the help text that the record counts everything dated on
  that day, `spec.md` §5.10), and "View entries". The page has no primary action
  (`ux/patterns.md` §11.7: it has no "Add"). A `⋯` menu holds "Edit", a form
  dialog (name, external reference, note, icon, colour), "Close…" or "Reopen",
  and "Delete…", last and destructive; the server refuses to delete an account
  that holds anything, and the decision dialog then says what it holds and points
  to "Close…" (`architecture.md` §4.1).

**The statement** is the account's rows, newest first, one list in two kinds of
row. It pages like the ledger list (`ux/patterns.md` §7).

- *A source transaction*: booked date, counterparty, purpose, amount and the
  running balance after it, in the shape of `ux/patterns.md` §4.1 without the
  entry's columns. A row a user entered carries the label "entered by hand" in
  place of a counterparty. A **duplicate** is dimmed, shows "duplicate of #N",
  which opens the row it duplicates, has no running balance, and counts toward
  none (`spec.md` §5.6, I3).
- *A balance record*, a marker row standing above the day's rows, because a
  record is the state at the end of its day: its kind (reported or manual), its
  date and its balance. Where the rows since the previous record do not add up
  to it, the marker says so: "rows sum to Y · difference Z" — the part of the
  change the rows do not explain, which is what the record's derived entry
  would be (`spec.md` §3.10), so the account page and the ledger tell one story
  without this page reading the entry layer. No difference shows no second half.
  The first record, the anchor, shows its balance and no difference: everything
  before it is absorbed by the opening, and reconciliation starts with the next
  record (`spec.md` §5.10). A marker's actions are "Edit", for a manual record,
  a form dialog (date and balance), and "Delete…", a decision dialog: the
  record's interval merges into the next one and derived entries are
  recomputed.

**The running balance re-anchors at each record.** It is the server's: the
client formats it (`ux/patterns.md` §1). Below the oldest record it is counted
back from the anchor, between two records it starts from the earlier record's
balance, above the newest it continues from it, and an account with no record
starts from zero and says "balance not anchored" in the header. The newest
row's balance is therefore the ledger balance in the header, whatever the
duplicates and the differences in between; the precise rule and its edge cases
(records sharing a date, investment accounts, reverted runs) are
`architecture.md` §4.1. On an investment account (`spec.md` §3.3) the markers
carry the valuations, and a hand-kept one may be markers alone.

**The statement is a snapshot, with one exception.** New data from another
sync appears as a passive count (`ux/patterns.md` §7). An action taken on this
page — marking or clearing a duplicate, a revert, an upload, a record written —
refetches the pages the statement holds, because it moves the running balance
of every row after it; the cursor stays on the row it acted on, by id.

**A row opens its source detail**, by click, `Enter` or `p` (`ux/patterns.md`
§5), in a dialog addressed by `?source=<source transaction id>`, so a link from
a run summary lands on it whatever page of the statement the row is on. The
detail is the provenance widget (`ux/patterns.md` §4.5) — what the source said,
the run it arrived in, "entered by hand" for a user's row, the original for a
duplicate — and one plain navigation link, "Open in review" (`?unit=` on the
review page), absent on a duplicate, which has no unit.

**Duplicates are marked and cleared from here** (`spec.md` §5.6). A row has one
icon action, revealed on hover and focus (`ux/patterns.md` §11.3), repeated in
its detail: on a source transaction, "Mark as duplicate of…"; on a duplicate,
"Not a duplicate".

- *Mark as duplicate of…* opens a decision dialog with a picker over the
  account's other rows of the same amount (the statement's `amount` filter),
  duplicates excluded. Once one is chosen the dialog previews both directions —
  what marking this row would remove, and what marking the other would remove
  — each as the consequence list of `ux/patterns.md` §6, with the newer row
  marked by default, so the user keeps the row that loses less. Stating the
  entries removed and the partners unpaired is a consequence statement; the page
  itself shows no entry. The verb is "Mark as duplicate".
- *Not a duplicate* acts at once and reports in a notice that the row has an
  entry again and is waiting in review, with the link "Open in review". It
  creates only what ingest would have created, and the notice is its
  consequence.

**Runs** are the account's import log (`spec.md` §5.6): a section of the page
under the header, the latest five with "Show all". A row shows the instance,
the start as an instant, the status, "covered through <date>" and a one-line
summary — inserted, inserted as duplicates, skipped — and opens the run summary
component (`ux/views/importers.md`). A reverted run is marked; a failed one
shows its error, with whether trying again can help (`ux/patterns.md` §8).
"Revert…" is offered on the one run the server marks revertible: the account's
latest successful, non-reverted run (`spec.md` I30). Earlier runs have none;
a short line says the later ones are reverted first. Its decision dialog is the
revert's preview (`ux/patterns.md` §6): the source transactions, the entries
removed and the partners left unpaired, confirmed entries named by count, and
the verb "Revert run".

**Open for the first month.** Whether the runs sit better below the statement
or on a tab of their own; whether the records that localise a difference want a
list of their own rather than a mark; whether an account page filters its
statement by date.
