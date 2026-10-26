# Importers — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §5.1–§5.4, §5.6 and §5.11; the CSV
profile is `plugins/importers/csv.md`; the contracts are `architecture.md`
§4.1 and §6.4. The account page, where an upload starts, is
`ux/views/account.md`.

---

**Settings → Importers**, `/settings/importers`, is where importer instances
are managed: a tab of Settings beside categories, payees, rules and tags.
Fetching and syncing are not here but in `ux/views/sync.md`; the discovery of an
instance's accounts is *Refresh accounts*, below. The FinTS importer's setup is
*The FinTS form*, below.

## The instance list

Titled "Importers", with the primary action "Add importer". A row shows the
instance's label, its importer, the accounts it is linked to — each a link to
the account's page — when it last ran ("never run" for none, relative with the
absolute instant in a tooltip, `ux/patterns.md` §3) and "disabled" when it is.
For an instance that holds a login, whose it is is shown too — "your login",
"*Name*'s login", or "shared" where either user may run it (`spec.md` §5.11);
a file importer holds none and is always shared. A row opens its page (below). It follows the settings-row
rule (`ux/patterns.md` §11.3): two icon actions, "Edit" and "Link account" —
for an instance of an importer that fetches and emits transactions, "Refresh
accounts" instead (below) — and
one `⋯` menu holding "Disable" or "Enable", "Reset…" and, last in the
destructive style, "Delete…".

- **Add importer** opens a pick dialog over the importer catalog
  (`architecture.md` §4.1): each importer by name with whether it takes a file
  or fetches. Choosing one opens the add page for it.
- **Reset…** is offered only for an importer that keeps state, a login; a file
  importer has none. The decision dialog says it clears the state and keeps the
  settings.
- **Delete…** is refused while the instance has runs (`spec.md` §5.6), the
  runs staying as history. The action is disabled on a row that has run, with
  the reason as its tooltip — "has runs; disable it instead" — and "Disable" is
  right beside it. Should the server still refuse, because a run began meanwhile
  (`instance_has_runs`), the decision dialog shows the refusal as an error
  with the same pointer. An instance without runs is deleted after the decision
  dialog; its links go with it, and the notice says so.
- **The other user's login** is read-only: its row shows no actions and opens
  its page read-only (below).
- An empty list says what is missing and offers "Add importer" (§9).

## The instance page

`/settings/importers/new?importer=` adds, `/settings/importers/[id]` edits: a
page, because a profile has more than five fields (`ux/patterns.md` §11.1).
The title is "Add importer" or the instance's label; the editor is a draft
editor with "Save importer" and Cancel (`ux/patterns.md` §11.2). It holds:

- **The label**, the instance's one name — a CSV profile has none of its own;
  its rows' `source_format` is read from this label (`plugins/importers/csv.md`
  §3) — and the importer's own settings below it: one form component
  per importer, chosen by its name, like the provenance widget
  (`ux/patterns.md` §4.5). The server validates the settings; a refusal names
  the setting (`invalid_profile`) and stands under that field (`ux/patterns.md`
  §11.5). Saving changes later uploads only: rows already imported keep saying
  what the file said.
- **Linked accounts**, listing each with "Unlink…" and the action "Link
  account", for an instance already saved; for an importer that fetches and
  emits transactions the action is "Refresh accounts" (below).

For the other user's login the page is read-only: everything it shows — the
label, the settings, whose login it is, the linked accounts, when it last ran —
with no editor and none of the actions above. Nothing of an instance is hidden
from the other user: no credential is ever stored, and the rest is not secret.

**Link account** is a form dialog: an account picker (open accounts which the
instance does not link yet, clearance accounts never) and, for a file
importer, nothing else — it is never
asked for a reference. For an importer that fetches, the account at the login
comes from discovery (*Refresh accounts*, below), which opens this dialog with
the account fixed and the discovered reference sent. Once an account is chosen
the dialog shows the link's dry run (`architecture.md` §4.1), the warning of `spec.md` §5.4:

```
This account holds 14 rows entered by hand, 3 Jan – 29 Mar.
Imports overlapping them are not deduplicated against them.
Once linked, the account is synced: rows can no longer be entered by hand.
```

The first sentence appears only where the account holds user-authored rows —
their count and the inclusive date range come from the preview; the second goes
with it; the third is the consequence of every link that makes the account
synced. The verb is "Link". **Unlink…** is a decision dialog that says the
account's coverage stays as history and that rows it holds stay.

## The CSV profile form

The CSV importer's settings are a profile (`plugins/importers/csv.md` §1): the
form is the add and edit page above, in groups that follow the profile
(`plugins/importers/csv.md` §2–§6) —
*Reading the file* (encoding, delimiter, quote, the header marker), *Columns*
(booking date and its format, value date, the amount as one signed column or a
credit and a debit column, the separators, the counterparty fields, purpose as
a list of columns, instructed amount, currency), *Rows* (placeholders, filters),
*Balance and coverage* (none, a running-balance column or a labelled figure with
its label, offsets and date; the export date), *Statement payment* (off unless
enabled: counter-account reference, purpose, date offset) and the two inversion
settings. A column is named by its header, by `Name#2` for the second of that
name, or by a position counted from 1; the helper text under each field says
so, since no field carries an example value as a placeholder.

**Presets** (`plugins/importers/csv.md` §8) are chosen from a select at the top
of the add page, "Start from a preset", which comes from the catalog's entry for
the importer. Choosing one fills the form as a draft edit: nothing is saved
until "Save importer", and Cancel discards it. It is offered on add only.

**A profile is judged by a dry run, not by the form.** The dry run needs a
file and an account — the account's currency, coverage and rows decide what a
run would do — so it lives on the upload page (*Uploading a file*, below), and
setting up a new format is: add the profile, link the account, upload with the
dry run, adjust the profile and check again until the report is right. After
saving a new instance, its page offers "Link account" at once, so the
sequence reads as one path. No second dry-run mechanism is added for unsaved
settings.

## The FinTS form

The FinTS importer's settings (`plugins/importers/fints.md` §1) are four fields
on the instance page, each with a visible label and helper text and no
placeholder: *Bank address* ("The address your bank publishes for online access
by software (FinTS). Your bank's help pages or the FinTS bank list give it. It
must start with https."), *Bank code* ("The eight-digit Bankleitzahl of your
bank."), *Login name* ("The name you sign in to online banking with.") and,
optional, *Customer ID* ("Only if your bank gave you a customer ID that differs
from the login name. Leave empty otherwise."). Below them one line: "The PIN is
not stored. You will be asked for it whenever this login is used." There is no
connection test: *Refresh accounts* is one, and every extra login spends an
attempt. The page's CSV-specific parts — the preset select, the hints about the
file and about `source_format` — are shown for a CSV profile only.

## Uploading a file

Started from the account page, with "Upload file" on a linked source: the page
`/accounts/[id]/upload?instance=`, a page because it holds a preview and a table
(`ux/patterns.md` §11.1). Titled "Upload a file", described as the account and
the instance. One page, three steps:

1. **Choose the file.** A file field, with the helper text that the file is for
   this account only and may be up to 10 MiB. Choosing it starts the dry run at
   once, "Checking the file…" (`ux/patterns.md` §11.6): the real path in a
   transaction that is rolled back (`architecture.md` §4.1).
2. **The report.** What the dry run carries, so that the profile can be judged
   before the file is used (`plugins/importers/csv.md` §7):
   - the file as read: encoding, delimiter, the header row and the columns
     mapped, field to column; the first rows as parsed;
   - counts: rows read, imported, skipped as not transactions, filtered by a
     row filter, dropped as zero bookings, each with examples by line number
     and reason, never cell content;
   - the export date used and where it came from; the coverage and where it
     came from;
   - the balance record that would be written, its date, the figure in the file
     and any roll-back applied; the synthetic statement payment, with its
     amount, date and the sum it is made of;
   - the importer's warnings;
   - the run summary as it would stand: rows inserted, skipped by identity and
     inserted as duplicates — each naming the existing row it duplicates, a
     link to that row; the new duplicate itself is not linked, since a dry run
     rolled it back — and the unexplained difference before and after.

   A failure the real run would end in — an unreadable file, a header or label
   not found, a currency that differs from the account's — takes the place of
   the counts and says which setting to look at. The commit is disabled with
   that as its reason (`ux/patterns.md` §6).

   "Edit profile" opens the instance's page in a new tab, and "Check again"
   reruns the dry run on the same file with the profile as now saved: the
   page keeps the file, so adjusting a profile never means choosing it
   again.
3. **Commit.** "Upload" runs the real operation with the same file. The page
   becomes the run summary (below) with "Back to the account".

A refusal of the request itself — a file over the limit, the account closed or
no longer linked — stands above the buttons as an error (`ux/patterns.md`
§11.5).

## Refresh accounts

For an instance of an importer that fetches and emits transactions, "Refresh
accounts" is the action of the instance page's linked accounts, instead of
"Link account", and the second icon action of its row in the list. It starts a
discovery (`spec.md` §5.4) and opens the page `/settings/importers/[id]/accounts`,
titled "Refresh accounts", described "What *label* can reach at the bank, and what
each is here." A discovery is a task like a sync (`ux/views/sync.md`): it prompts
in the same dialogs, on this page, and its failure is shown as a sync's.

One row per account the login reaches — a pocket of another currency is its own
row — with its name, currency, kind, and its reference as the bank reports it.
Each is one of: *linked* ("Linked to *Account*", a link); *nothing to fetch*
("The bank offers neither bookings nor a balance for this account."); *matches a
closed account*, which is not offered; *matches* an open account, with "Link…";
or *not in the ledger yet*, with "Add and link". "Link…" is the link dialog of
the instance page with the account fixed, showing the dry run of `spec.md` §5.4.
"Add and link" is the add-account dialog prefilled with the name, the kind, the
currency and the reference, ending "Add and link": it adds the account and links
it, with no second dialog, because a new account holds no rows to warn about. A
row changes state in place after either. Once an account has been linked, a
notice offers "Fetch", which opens the sync page narrowed to this login, where
each new account's start is prefilled and editable.

## The run summary

One component, shown after an upload here, on a run in the account page's run
list, and in the report of a sync (`ux/views/sync.md`, `architecture.md`
§6.4), where a row opens it from the statistics of the run's event. It is a
report, not an alarm (`ux/patterns.md` §8): it opens no dialog and colours nothing red.
Per account it says how many rows were inserted; how many were inserted as
duplicates, each "of #N" with a link to the row it duplicates on the account's
statement (`?source=`, `ux/views/account.md`), and a link to the duplicate
itself; how many were skipped by identity;
what the importer left out (zero bookings it dropped, a statement payment it
did not emit); the balance record the run wrote, with its date and balance; the
coverage; and the unexplained difference before and after, which where it is
non-zero names the reported records that localise it, linking to the statement.
A failed run shows its error and whether trying again can help. The component
takes a run's stored statistics; for a dry run the same shape, with the links
to rolled-back rows left out; in a sync's report, where the event carries
statistics and not the run's dates, without the coverage line, which is in the
account's run log.

**Open for the first month.** Whether the profile form wants a live sample
beside it; how a file importer's
instance with several linked accounts is best chosen on the account page.
