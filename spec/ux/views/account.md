# Accounts — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §3.3, §3.9–§3.11, §5.4, §5.6 and
§5.10; the contracts are `architecture.md` §4.1 (*The account statement*).
Importer instances and the file upload are `ux/views/importers.md`.

---

**Accounts is an item of the navigation**, beside Ledger, Review and
Documents: `/accounts` lists the accounts, `/accounts/[id]` is one account. The
importer instances that feed them are managed in Settings
(`ux/views/importers.md`).

**Two layers, two places.** The ledger is the interpretation: entries, their
categories, payees, tags, splits and pairs. The account page is what the
account's sources said: its source transactions, duplicates included, and its
balance records. Nothing of the entry layer is shown on it — no category,
payee, tag, split, pair or derived entry. The two meet in one number, the
balance, which both tell alike (*The statement*, below), and in two links:
"View entries" opens the ledger filtered by the account, and a row's detail
opens its unit in the review panel.

## The list

`/accounts`, titled "Accounts", with the primary action "Add account", the
existing form dialog; once added, the account's page opens. Choosing the kind
*Clearance* adds two fields: *Providers* ("The shops whose orders are booked
on this account, as the documents name them.", picked like tags,
`ux/patterns.md` §6) and *Start*, a required date ("Orders dated after this
day are booked here. Choose a day with nothing in flight: no order placed
and not yet charged."). Saving writes the account's opening balance record,
0 at the end of that day (`spec.md` §3.3, §3.10). One row per
account, open accounts first in their sort order, then the closed ones, muted.
A row shows the account's icon and name, its kind, its balance with the
currency code (accounts of several currencies stand together,
`ux/patterns.md` §2) and the facts line of `ux/patterns.md` §4.4: data age,
"balance not anchored", the unexplained difference. A row opens the account.
An empty list says that accounts are added here and then fed by a file, a
sync, or by hand (`ux/patterns.md` §9). Sorting by data age and the
net-worth figure are the Overview's (`ux/views/overview.md`), not this list's.

## The account page

**Header.** The page header's title is the account's name; its description is
the kind and currency, and "closed on *date*" for a closed account. The
primary action is "Add entry" — the entry form, its account prefilled to
this one — on an unsynced account, where rows may be entered by hand (`spec.md`
I40); a synced account's page has none (`ux/patterns.md` §11.7).

Before it in the title row sit the account's secondary actions: "Set
balance", "View entries", and a `⋯` menu with "Edit", the account's form
dialog (name, external reference, note, icon, colour, and for a clearance
account its providers, whose change books the documents a new provider brings
and moves no existing booking), "Close…" or "Reopen", and "Delete…", last and
destructive. The server refuses to delete an account that holds anything; the
decision dialog then shows what it holds and offers "Close…" instead. Under
the header:

- **the balance and the facts line** (`ux/patterns.md` §4.4): data age,
  "balance not anchored", the unexplained difference as an amount. The
  reported records that localise a difference (`spec.md` §5.10) are marked in
  the statement rather than listed a second time;
- **the sources**: each instance the account is linked to, one line each —
  its label, its importer and its action, "Upload file" for a file importer
  (`ux/views/importers.md`) and "Fetch" for one that fetches
  (`ux/views/sync.md`): a one-item sync for this account alone, started at
  once, or after choosing the start where the account has no coverage. A
  source that is the other user's login shows whose it is in place of its
  action. An unlinked account says how it is fed instead: by hand, or by
  linking it in Settings → Importers (a link). A clearance account, which is
  never linked, says instead that it is fed by the orders of its providers —
  listed, each a link to the documents list filtered by it — and by the
  charges decided as transfers to it.

**Two tabs** (`design.md` §5) follow the header and its cards, each its own
address: **Transactions**, `/accounts/[id]`, the statement; **Runs**,
`/accounts/[id]/runs`, the import log. The new-data notice stands above them. A
clearance account, which has no runs, has no tabs: its statement follows the
header.

"Set balance" is a form dialog with the date, defaulting to today, and the
balance, its help text saying that the record counts everything dated on that
day (`spec.md` §5.10). On a date that already holds a manual record it edits
that record.

## The statement

The Transactions tab: the account's rows, newest first, paged like the ledger list and drawn in its
density (`ux/patterns.md` §4.1, `design.md`). Two kinds of row:

- **A source transaction**: booked date, counterparty, purpose and amount,
  with its origin tag; its Balance cell is empty (`ux/patterns.md` §4.1). The
  counterparty and purpose cells show what the row holds — a booking's as it
  wrote them (`spec.md` §5.8) — and stay empty where a row has none, as a row
  entered by hand has no counterparty. A **duplicate** is dimmed — it counts
  toward no balance (`spec.md` I3) — and reads "duplicate of *date · amount*", which
  opens the row it duplicates.
- **A balance record**, a marker row above the rows of its own date, since a
  record is the state at the end of its day: its kind (reported or manual), its
  date and its balance. Where the rows since the previous record do not add up
  to it, the marker says by how much: "rows add up to *Y* · difference *Z*",
  and on an investment account "· valuation *Z*".
  That difference is what the record's derived entry is in the ledger — a
  reconciliation, or a valuation on an investment account (`spec.md` §3.10) —
  so the statement shows where the ledger had to explain something without
  reading the entry layer. The anchor, the earliest record, shows its balance
  alone: the opening absorbs everything before it and reconciliation starts
  with the next record (`spec.md` §5.10). The reported records that localise
  the unexplained difference carry a quiet mark.

**The Balance column holds the records' balances alone.** A balance is stated
where a record states it; a running balance on every row would read as if each
transaction had one. The header's balance is the account's (`ux/patterns.md`
§4.4); an account without a record says "balance not anchored".

**A snapshot, refetched after its own writes.** New data for this account, from
any source, arrives as a passive notice, "New data — Refresh"
(`ux/patterns.md` §7), whose refresh reloads the header, the facts and the
statement together, so the balance and the records do not disagree. A write
made from this page —
a duplicate marked or cleared, a run reverted, a record set or deleted, a row
entered, edited or deleted — refetches the pages the statement holds instead
of patching them, because it moves the gap of every record after it; the
cursor stays on the row it acted on. This is the statement's one exception to
*patch, don't refetch*.

**A row opens its detail** by click, `Enter` or `p` (`ux/patterns.md` §5): a
dialog addressed by `?source=`*id*, so a link from a run summary lands on the
row whatever page of the statement it is on. A statement row has no action
buttons of its own, like a ledger row (`ux/patterns.md` §11.3); its actions are
in the detail. The detail is the provenance widget (`ux/patterns.md` §4.5) —
the normalised fields, what the source said, the run it arrived in, "entered
by hand" — followed by the row's actions:

- **"Open in review"**, navigation to its unit in the review panel; not on a
  duplicate, which has no entry;
- on an **imported** row, **"Mark as duplicate of…"**; on a duplicate, **"Not
  a duplicate"** (`spec.md` §5.6);
- on a row **entered by hand**, **"Edit"** and **"Delete…"**, the entry form's
  own edit and delete (`spec.md` §5.6). A user-authored row is never marked as
  a duplicate: where an import now reports it, it is deleted.
- on a **booking**, **"Open document"** for one booked from a document, the
  document's detail (`ux/views/documents.md`), or the charge's row for a
  counter-leg. A booking is neither edited nor deleted here, nor marked as a
  duplicate: it follows its source (`spec.md` §5.8); a wrong one is offset by
  an entry made with "Add entry".

A balance marker opens no detail; its actions are "Edit" (a manual record, the
"Set balance" dialog) and "Delete…", shown on hover and focus as on a settings
row (`ux/patterns.md` §11.3). Deleting a record merges its interval into the
next one (`spec.md` §3.10), which the decision dialog says.

**Mark as duplicate of…** replaces the detail with a decision dialog. It lists
the account's other imported rows of the same amount that are not duplicates,
nearest date first, to pick the original from. Once one is picked it previews
both directions — what marking this row would remove, and what marking the
other would — each as the consequence list of `ux/patterns.md` §6, with the
newer row preselected as the duplicate (`spec.md` §5.6), so the user marks the
one that loses less. The verb is "Mark as duplicate". The entries and pairs
the preview names are consequences, stated as such; the page still shows none.

**Not a duplicate** acts at once: it only gives the row the entry ingest would
have given it, and nothing confirmed changes. A notice says that the row has
an entry again and is in review, with "Open in review".

## The Runs tab

The account's import log (`spec.md` §5.6), every run, newest first, paged like the statement. A run row shows the
instance, the start as an instant (`ux/patterns.md` §3), its status, "covered
through *date*" and one line of its summary — inserted, inserted as
duplicates, skipped — and opens the run summary (`ux/views/importers.md`). A
reverted run is marked; a failed one shows its error and whether trying again
can help (`ux/patterns.md` §8): for a fetch that can be, "Run again", a
one-item sync; where it cannot, the row says what to fix, as for a file
("Upload file").

"Revert…" is offered on the one run the server marks revertible, the
account's latest successful, non-reverted run (`spec.md` I30); an earlier run
says that later runs are reverted first. Its decision dialog is the revert's
preview (`ux/patterns.md` §6): the rows the run brought, the entries removed
and the partners unpaired, as counts per group with confirmed entries
counted. The verb is "Revert
run".

**Open for the first month.** Whether the records that localise a difference want a list of
their own; whether the statement wants a date filter or a search.
