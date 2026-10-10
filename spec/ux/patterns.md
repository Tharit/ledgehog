# Household ledger — UX patterns

Status: **draft, written before the first screen.** Conventions that apply
across every view, decided once so that no view re-decides them. Individual
screens are `ux/views/*.md`. This document depends on `spec.md` (what the
system does) and `architecture.md` (the contracts, especially §4 and §6); it
adds no domain concepts of its own.

Where a choice here is a starting point rather than a settled convention, it
says so; those are revisited after the first month of use, not per view.

---

## 1. Principles

- **The server decides, the client shows.** No view computes a balance, a
  review state, a proposal or a consequence (architecture §6.3). Everything a
  screen shows about the domain comes from an API response; the client only
  formats it.
- **Evidence, not confidence.** A derived value always shows where it came
  from, in the terms the pass recorded (spec §5.9). There are no confidence
  percentages and no colour-coded certainty.
- **Nothing moves under the cursor.** Lists are patched in place from the
  affected set an operation returns (architecture §4.1, §6.5); rows are never
  reordered or removed while the user works in them.
- **Consequences before commitment.** Every operation that removes, breaks,
  returns to review or creates something elsewhere shows it before it runs
  (spec §6), using one consequence pattern (§6 below).
- **Keyboard first, mouse complete.** Everything is reachable by keyboard;
  nothing is keyboard-only.

## 2. Money

- **Integers in, formatted out.** Amounts arrive as signed integers in minor
  units with a currency code (architecture §4.5, §6.6) and are formatted only
  in `lib/format`. The number of decimals comes from the currency, never from
  an assumption of two.
- **The sign is shown, not hidden.** Amounts render with their sign as stored —
  ledger convention, positive increases the account's balance (spec §3.3). A
  card's purchase is `−84.31`, a refund `+80.00`. No view flips signs to make
  spending "look positive", and no view shows income and expense as unsigned
  columns.
- **Colour supports the sign, never replaces it.** Negative amounts may use a
  muted red, positive a neutral or muted green; the minus sign is always there,
  so the reading survives colour blindness and printing.
- **Currency.** An amount in the account's currency shows its code only where
  accounts of several currencies appear together. An amount in another
  currency — the instructed amount (spec §3.8), a base-currency value — always
  shows its code. Base-currency values in reports are labelled as such.
- **Alignment.** Amount columns are right-aligned with tabular numerals.
- **Unvalued is not zero.** A value with no usable rate renders as "unvalued"
  (a dash with a tooltip naming the currency and its rate age, spec §3.11),
  never as `0.00`, and totals that omit unvalued amounts say so (spec §8).
- **Entering amounts.** The entry form takes an unsigned amount plus a sign
  control prefilled as in spec §3.9; parsing follows the active locale and
  rejects ambiguous input rather than guessing (architecture §6.6).

## 3. Dates and time

- **Domain dates are calendar dates** (`booked_on`, `value_on`, balance
  dates): rendered in the locale's short date format, never shifted by a time
  zone (spec §5.4).
- **Relative dates** ("3 days ago", data age) are computed from *today* as the
  server defines it — the household's day (architecture §4.5) — and always
  have the absolute date in a tooltip.
- **Instants** (a run's start, a session) render in the household's zone with
  date and time.
- **Ranges** are inclusive on both ends, as the domain's dates are, and say so
  where ambiguity is possible ("1 Mar – 31 Mar").

## 4. Entries, units and their state

### 4.1 Rows

An entry row shows, in this order: date, account (where several are listed),
description (the entry's `description`, else the source's counterparty name or
purpose), payee, category or the transfer's destination ("→ Cash"), tags,
amount. Derived entries (opening, valuation, reconciliation) render in the same
row shape with their type in place of a category and no review affordances
(spec §3.9).

The entries of one unit (spec §6) are shown together wherever a unit is shown:
a split's entries under their source, a pair's two legs side by side. In the
ledger list, a split shows as one row that expands.

### 4.2 Review state

Review state is shown with the flags the server sends (`review_flags`,
spec §6), one consistent badge per token and nothing else:

| Token | Badge | Meaning to the user |
|---|---|---|
| `unconfirmed` | outlined dot | values are proposals |
| `unclassified` | "?" | type or category missing |
| `document_suggested` | document icon | a document may explain this |
| `waiting` | clock | partner or document still expected |
| `unmatched_transfer` | broken link | transfer leg without a partner |

A confirmed entry shows no badge. Badges carry a tooltip with the sentence in
the third column. Account and currency status (spec §3.11) is never shown as an
entry badge; it belongs to the account (§4.4).

### 4.3 Derivation and evidence

Every derived value can show its basis, rendered from the derivation key
(spec §5.9) in one vocabulary:

| Key | Rendered as |
|---|---|
| `own_account` | "own account (IBAN match)" |
| `rule` | "rule: *rule name or conditions*", linking to the rule |
| `history` | "history: 3 of 4 since Mar 2026" |
| `llm` | "suggested by the model", rationale on demand |
| `matcher_decision` | "matched automatically" |
| `matcher_proposal` | "document matched — check the split" |
| `user` with a basis | "confirmed by you, proposed by *…*" |
| `user` without one | "set by you" |

Proposals (history, model, matcher proposal) are visually distinct from
decided values — e.g. italic or a lighter weight — and the distinction is the
same in every view. Thin evidence is shown as such ("1 of 1"), never rounded
into a percentage.

### 4.4 Account facts

Data age, unexplained difference and "balance not anchored" (spec §3.11) render
on the account wherever the account is shown with its balance: a quiet line
under the balance, with the unexplained difference as an amount and the
records that localise it on demand. They are notices, never prompts or review
items (spec §5.10).

### 4.5 Provenance widget

Every entry with a source transaction can open its **provenance**: what the
source said, rendered from `source_transaction.raw` by an importer-specific
widget (spec §3.1), with the normalised columns above it — counterparty and
reference, purpose, booking text, end-to-end id, mandate reference, instructed
amount — and the run it arrived in (importer, account, time). A user-authored
row shows "entered by hand" instead, a counter-leg "created for *partner*". A
duplicate shows the row it duplicates. Provenance is read-only everywhere.

## 5. Keyboard model

Bindings are global conventions; a view may add its own, never redefine these.
A starting set, to be revisited after real use:

| Key | Action |
|---|---|
| `↑` / `↓` (also `k` / `j`) | move the cursor in a list |
| `Enter` | open the row: the unit panel for an entry |
| `Esc` | close the panel or dialog, discarding its draft (asking first if the draft has changes) |
| `Ctrl/⌘ + Enter` | commit the panel as previewed |
| `Tab` / `Shift + Tab` | move between fields of the panel |
| `/` | focus the filter bar |
| `t` | tag the row (or the filter's result, after a confirmation, spec §3.7) |
| `p` | open provenance |
| `?` | show the bindings |

The cursor is the selection; there is no multi-select for interpretation,
because there is no batch confirmation (spec §6). After a commit the cursor
moves to the next row; a resolved row stays in place, marked (§7).

## 6. Previews, consequences and confirmation

- **One preview pattern.** The panel and every operation marked *previewed*
  (architecture §4.1) render the dry-run response the same way: the resulting
  state first ("confirmed", "waits for its partner", "stays unclassified" —
  spec §6), then a consequence list grouped by effect: *created*, *changed*,
  *returns to review*, *deleted*, *left behind*. Each item is a row in the
  shape of §4.1 and can be opened.
- **Confirmation scales with cost.** An operation that only writes what the
  user sees in the panel commits with one key. An operation that removes
  confirmed entries or returns entries to review asks explicitly, naming how
  many (spec §6). An entry-form edit of a user-authored row always shows the
  general warning the spec requires (spec §5.6).
- **Skipping a document wait is explicit.** Where documents are suggested or
  awaited, committing without one is a deliberate choice ("commit without a
  document"), not the default key (spec §5.8, §6).
- **Invalid is shown, not blocked.** A draft that would be invalid — an unequal
  same-currency pair, a residual of zero — stays editable and shows why it
  cannot be committed, with the remedies the spec offers (spec §5.7, §5.9);
  the commit key is disabled with that reason as its tooltip.

## 7. Lists, patching and freshness

- **Patch, don't refetch.** After an operation the client patches every entity
  in its affected set (architecture §4.1). Rows resolved by the user's action
  are marked resolved; rows changed as a *consequence* are marked differently
  ("changed by your last action"), so nothing changes silently.
- **Snapshots stay snapshots.** A list fetched for a session (the review queue,
  architecture §6.5) does not add or reorder rows; new data from another sync
  appears as a passive count ("12 new — refresh") that refetches only on
  request.
- **Optimistic echo only.** A view may show the expected result of an
  operation it has sent, and rolls it back on error; it never shows a domain
  outcome it computed itself (architecture §6.3).

## 8. Errors and conflicts

- **Routed by code, never by message** (architecture §4.4). Each code maps to
  one presentation:
  - *validation* — inline at the field or the draft, as in §6;
  - *conflict* (someone changed this) — a non-blocking notice naming what
    moved, the affected rows refetched in place, the draft kept where it can
    be previewed again; never an automatic overwrite;
  - *try again* (a write aborted twice, architecture §5.2) — a notice with a
    retry action, the draft kept;
  - *importer errors* (architecture §5.5) — on the run, in the sync view, with
    the retryability the taxonomy states: "wrong PIN" invites correction,
    "bank unreachable" a retry, "format changed" neither.
- **Run summaries are reports, not alarms.** Duplicates inserted, rows skipped
  and an unexplained difference caused by a run are listed in its summary with
  links to the rows (spec §5.3, §5.10); none of them opens a dialog.
- **A settle that failed** after a write (architecture §5.2) shows a quiet
  notice that derived state may be stale until the next action.

## 9. Empty and absent values

- **Absent is not zero, and not blank.** An unset category renders as
  "Unclassified", a missing counter-account as "→ ?" with "needs an account in
  *currency*" where the spec derives it (spec §5.7), a balance without records
  as "not anchored" (spec §3.11), a value without a rate as "unvalued" (§2).
- **Empty states explain the next step**: an empty review queue says so and
  links to the ledger; an account with no data says how it is fed (sync, file,
  by hand).

## 10. Open for the first month

- the badge glyphs and the proposal styling of §4.2–§4.3;
- the key bindings of §5, especially commit and tag;
- whether resolved rows in a snapshot collapse after a while (architecture
  §6.5 leaves it to the view).
