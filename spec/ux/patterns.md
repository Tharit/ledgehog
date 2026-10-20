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
  never as `0.00`, and totals that omit unvalued amounts say so (spec §8): a
  sum with some unvalued entries shows its total and "+ n unvalued", one with
  none valued shows "unvalued".
- **Entering amounts.** The entry form takes one signed amount, prefilled
  with a minus as spec §3.9 prefills an expense; a hint under the field says
  "− money out, + money in", because a leg of a transfer is neither income
  nor expense. A typed `+`, `−` or `-` sets the sign; an amount without a sign
  is refused rather than guessed, as is anything ambiguous. Parsing follows
  the active locale (architecture §6.6).

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
  where ambiguity is possible ("1 Mar – 31 Mar"). A report's periods are
  calendar months, quarters or years in the household's zone; one the range
  cuts is labelled with its days ("1–20 Oct").

## 4. Entries, units and their state

### 4.1 Rows

An entry row shows, in this order: date, account (always in the ledger list; a
view of one account may leave it out), category or the transfer's destination
("→ Cash"), payee, tags, description (the entry's own `description` only; the one column that takes the remaining
width), the review badges (§4.2) and the amount. Derived entries (opening,
valuation, reconciliation) render in the same row shape with their type in
place of a category and no review affordances (spec §3.9).

The description column shows the entry's `description` and nothing borrowed
from its source transaction: the source fields are shown where they belong, in
the work panel and in the rule preview's source columns. An entry with no
description shows an empty cell. Whether imports get a description at creation
is open (§10). The API's derived `display_text` is not used by the column.

The entries of one unit (spec §6) are shown together wherever a unit is shown:
a split's entries under their source. In the work panel that is one group per
source transaction, by date; a leg's partner is a one-line pointer to the group
above or below, and a counter-leg the commit would create is a dashed,
read-only ghost group after the others.

**In the ledger list, every entry is a row, and a unit is never a row of its
own.** Filtering, counting, paging and tagging all act on entries
(architecture §4.1); anything grouped is only how rows are drawn. The entries
of a split are adjacent, because the list's order keeps them together. There
is no parent row and no expander. The whole unit opens in the panel. The entries of a split are
also visually joined, with a marker on the first row whose tooltip gives the
unit's total. A transfer leg shows its partner —
account, date and amount — from a read-only summary the row carries, so it
works when a filter hides the partner; the partner's own row is highlighted
when it is in view.

### 4.2 Review state

Review state is shown with the flags the server sends (`review_flags`,
spec §6), one consistent badge per token and nothing else:

| Token | Badge | Meaning to the user |
|---|---|---|
| `unconfirmed` | outlined dot | values are proposals |
| `unclassified` | "?" | type or category missing |
| `document_suggested` | document icon | a document may explain this |
| `waiting` | clock | partner or document still expected |
| `unmatched_transfer` | unlink | Transfer leg without a partner |

A confirmed entry shows no badge. Badges carry a tooltip with the sentence in
the third column; the `waiting` tooltip names the partner's account when the
entry is an unpaired transfer leg, and the provider when it waits for a document. Account and currency status (spec §3.11) is never shown as an
entry badge; it belongs to the account (§4.4).

### 4.3 Derivation and evidence

Every derived value can show its basis, rendered from the derivation key
(spec §5.9) in one vocabulary:

| Key | Rendered as |
|---|---|
| `own_account` | "own account" |
| `rule` | "rule: *its name*", linking to the rule; "rule deleted" where the rule is gone |
| `history` | "history: 3 of 4 since Mar 2026" |
| `llm` | "suggested by the model", rationale on demand |
| `matcher_decision` | "matched automatically" |
| `matcher_proposal` | "document matched — check the split" |
| `user` with a basis | "confirmed by you, proposed by *…*" |
| `user` without one | "set by you" |
| `user` on an empty payee | "No payee" shown muted, with "set by you" |
| `counterpart`, `matcher_decision` | "paired with *account*" / "matched automatically" |
| `counterpart`, `user` | "paired with *account*" / "set by you" |
| a partner or counter-leg picked in the draft | "picked by you" |
| a partner the preview proposes | "proposed: exact match" / "proposed: closest candidate" |
| a counter-leg the preview proposes | "proposed: no open offer" |
| the counter-account a pair set (basis `{"from": "counterpart"}`) | "from its partner", with no clear control |

Proposals (history, model, matcher proposal) are visually distinct from
decided values — e.g. italic or a lighter weight — and the distinction is the
same in every view. Thin evidence is shown as such ("1 of 1"), never rounded
into a percentage.

The clear control on a type, category or counter-account is offered only on a
value the user decided; it means "remove my choice", and the passes propose
again. On a payee it means "no payee" (spec §5.9, state 3). "Reset to
proposal" is offered only when the value shown differs from the value stored.

### 4.4 Account facts

Data age, unexplained difference and "balance not anchored" (spec §3.11) render
on the account wherever the account is shown with its balance: a quiet line
under the balance, with the unexplained difference as an amount and the
records that localise it on demand. They are notices, never prompts or review
items (spec §5.10).

### 4.5 Provenance widget

Every entry with a source transaction can open its **provenance**, and so can
every row of an account's statement, a duplicate included
(`ux/views/account.md`): what the
source said, rendered from `source_transaction.raw` by an importer-specific
widget (spec §3.1), with the normalised columns above it — counterparty and
reference, purpose, booking text, end-to-end id, mandate reference, instructed
amount — and the run it arrived in (importer, account, time). A user-authored
row shows "entered by hand" instead, a stored counter-leg too. "Created for
*partner*" appears only in the ghost block of a counter-leg not yet committed. A
duplicate shows the row it duplicates. Provenance is read-only everywhere.

## 5. Keyboard model

Bindings are global conventions; a view may add its own, never redefine these.
A starting set, to be revisited after real use:

| Key | Action |
|---|---|
| `↑` / `↓` (also `k` / `j`) | move the cursor in a list; `↓` in the filter bar's text box moves it to the first row |
| `Enter` | open the row: the unit panel for an entry; on a derived entry a quiet notice, "Derived from a balance record — correct the record", with a link to the record |
| `Enter` in a form | submits a form dialog or an in-place edit; never submits a draft editor or confirms a decision dialog (§11.2) |
| `Esc` | closes the innermost open surface (popover, dialog, panel), discarding its draft; a panel whose draft has changes asks first |
| `Ctrl/⌘ + Enter` | commit the panel as previewed |
| `Tab` / `Shift + Tab` | move between fields of the panel |
| `/` | focus the filter bar's text box |
| `t` | tag the row under the cursor |
| `p` | open provenance |
| `?` | show or hide the bindings (a panel fixed to the corner of the view, not a dialog) |

`t` opens a searchable list of tags: `Enter` toggles the one under the
highlight, and a name no tag has can be created in place; on a derived entry
it refuses with a quiet notice. In the work panel `t` edits the focused entry's
draft tags instead (below).

**The panel's keys** act when focus is not in a field, and only in the panel
(the ledger's `r` stays removed, D208):

| Key | Action |
|---|---|
| `[` / `]` | step to the previous or next unit |
| `c` / `y` | category / payee |
| `s` | split |
| `x` | flow ↔ transfer |
| `r` | re-resolve |
| `t` | edit the focused entry's draft tags |

**The panel is addressed by `?unit=<anchor entry id>`** on any page: opening it
adds a history entry, stepping replaces one, so reload and a shared link
work. The queue is the page `/review`, with a Review item in the navigation.
After `Ctrl/⌘ + Enter` the panel stays open and advances to the next unopened
unit, skipping resolved ones; at the end it closes with a notice and the
cursor on the last row. "One keystroke" means that chord with the panel open:
the panel must be open to show the preview. `Esc`, or stepping, with a dirty
draft asks in a decision dialog nested over the panel, Cancel focused. "Edit
entry" is disabled while the draft is dirty, with the reason as tooltip, and
opening a consequence row from a dirty panel asks first. Tags are part of
the draft: each entry block has a Tags row like its other fields, without a
clear control and without proposals, and a tag edit makes the draft dirty. The
`t` picker lists the tags; a name no tag has is created at once through the tag
endpoint (creating a tag is not an entry write) and added to the draft, and
cancelling the draft leaves the tag, which can be deleted in the tag settings.
Re-resolve (`r`) applies to the whole unit as a draft edit that
Cancel undoes, with "Reset to proposal" on each field.

The cursor is the selection; there is no multi-select, for interpretation
because there is no batch confirmation (spec §6), and for tagging because a
filter's result is tagged through the filter. That is a visible action of the
filter bar, "Tag all…", never a key: it is unavailable, with its reason as
tooltip, while the list loads, when the filter restricts nothing and when
there is nothing to tag. It opens a dialog that shows the preview of
architecture §4.1 (how many would be tagged, how many already carry the tag,
how many are skipped, the accounts affected, the tag's span before and after)
and asks before it writes (§6). After a commit the cursor moves to the next
row; a resolved row stays in place, marked (§7).

## 6. Previews, consequences and confirmation

- **One preview pattern.** The panel and every operation marked *previewed*
  (architecture §4.1) render the dry-run response the same way: the resulting
  state first ("confirmed", "waits for its partner", "stays unclassified", "stays without a
  partner", "proposals to check" — spec §6), then a consequence list grouped by effect: *created*, *changed*,
  *returns to review*, *deleted*, *unpaired*, *left behind*. Each item is a row in the
  shape of §4.1 and can be opened. A preview lists its consequences as rows
  when the operation acts on one thing the user picked — a unit, a row, a
  record — and states them as counts when it acts on a set the user named as a
  whole — a run, a filter's result, a category or payee merged into another:
  that set is already known by what names it, and listing it would not help the
  decision. Counts are given per group, with the confirmed entries among each
  counted, since those are what confirmation names (below). A rule's preview is
  the exception: listing what it matches is the purpose of its page.
- **A rule's preview rows carry their source.** Each row is an entry with its
  `source` (architecture §4.1); beside the entry's own fields the row shows the
  source fields that the rule's conditions read, always the counterparty, under
  their own headers. Rows open the review panel once units exist.
- **Confirmation scales with cost.** An operation that only writes what the
  user sees in the panel commits with one key. An operation that removes
  confirmed entries or returns entries to review asks explicitly, naming how
  many (spec §6). An entry-form edit of a user-authored row always shows the
  general warning the spec requires (spec §5.6), static above Save; that
  warning is its confirmation.
- **Skipping a document wait is explicit.** Where documents are suggested or
  awaited, committing without one is a deliberate choice ("commit without a
  document"), not the default key; the server enforces it and refuses a
  commit that lacks it (spec §5.8, §6). A payee's document provider is
  selected from the registered providers, never typed.
- **Invalid is shown, not blocked.** A draft that would be invalid — an unequal
  same-currency pair, a residual of zero — stays editable and shows why it
  cannot be committed, with the remedies the spec offers (spec §5.7, §5.9);
  the commit key is disabled with that reason as its tooltip.

## 7. Lists, patching and freshness

- **Patch, don't refetch.** After an operation the client patches every entity
  in its affected set (architecture §4.1). Rows the user has committed
  are muted, and a committed unit that is confirmed also carries a check; a
  committed unit that stays in review keeps its review badge. Rows changed as a
  *consequence* are marked differently ("changed by your last action"), so
  nothing changes silently. A commit can refresh dozens of proposals: those are
  patched silently, and only state changes and returns to review are marked.
  The consequence mark fades when the cursor visits the row; the muting and the
  check stay until the list is refreshed.
- **Snapshots stay snapshots.** A list fetched for a session (the review queue,
  architecture §6.5; the ledger list, whose filter is in its address) does not
  add or reorder rows; new data, whatever wrote it, appears as a passive notice
  ("New data — Refresh") that refetches only on request (architecture §4.2). An
  action patches the rows it touched in place and
  never removes or moves one: a row that the action takes out of the list's
  filter (a tag removed under a tag filter) stays, marked, until the list is
  fetched again. The one exception to never adding a row: the entries a split
  creates are inserted next to their anchor.
- **Computed views refetch.** A view of aggregates (the Overview, the reports)
  has no cursor to protect and nothing in it is removed under the user's hand:
  it keeps its figures on screen and replaces them when the ledger's change
  value moves (architecture §4.2). A change of its controls is a new request,
  the previous figures dimmed until the answer arrives. The ledger lists it
  links to are snapshots in their own right.
- **A filter's result is the server's, not the list's.** An action on a
  filter's result (spec §3.7) states how many entries it will touch from the
  server's count for the filter as it stands, not from the rows the list holds,
  which may be a snapshot, and it captures the filter when it opens. If the
  result has moved when the user confirms, nothing is written and the action
  shows the new number and asks again. Rows the user changed that the filter no
  longer matches are not in the result: the action says so, and offers to
  include those that are still shown as a choice that is off by default.
- **Optimistic echo only.** A view may show the expected result of an
  operation it has sent, and rolls it back on error; it never shows a domain
  outcome it computed itself (architecture §6.3).

## 8. Errors and conflicts

- **Routed by code, never by message** (architecture §4.4). Each code maps to
  one presentation:
  - *validation* — inline at the field or the draft, as in §6;
  - *conflict* (someone changed this) — a non-blocking notice naming what
    moved, the affected rows refetched in place, the draft kept where it can
    be previewed again; never an automatic overwrite. A `stale_reference`
    (the write named a category, payee or account that no longer exists, for
    instance after a merge) is such a conflict whose notice names the field,
    and the category, payee and account lists are reloaded in place;
  - *try again* (a write aborted twice, architecture §5.2) — a notice with a
    retry action, the draft kept;
  - *importer errors* (architecture §5.5) — on the run, in the sync view, with
    the retryability the taxonomy states: a run that trying again can help — a
    rejected PIN, an expired TAN, an unreachable bank; every run asks for its
    PIN afresh — offers to run it again; one that cannot — a changed format, a
    missing registration — says what to fix instead.
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
- the key bindings of §5, especially commit and tag, and the panel's;
- whether and how the review queue groups units by what they share, beyond its
  three sections (`ux/views/review-queue.md`); open until real units have
  been seen;
- whether resolved rows in a snapshot collapse after a while (architecture
  §6.5 leaves it to the view);
- the ledger list's columns: their order (in particular whether the amount
  comes before the description) and which columns give way first at a narrow
  width (the prototype's table simply overflows);
- whether the ledger list shows the account's facts (§4.4) when one account is
  filtered; the prototype leaves them to the account view;
- where a quiet notice appears (the prototype reserves one line under the
  filter bar, so that it never moves a row; the alternative is a floating
  notice) and how a partly failed action is worded and styled (the prototype
  reports it inside the dialog in plain text);
- whether the filter-bar action "Tag all…", its dialog and the opt-in to tag
  the marked rows suit real use;
- the rule editor: its layout, the find box that picks its example entry and
  the example's table beside the conditions, in two groups (from the source
  transaction; from the entry: payee, document merchant, document line), with
  the condition picker grouped the same way, and the priority a new payee rule
  with a document condition is given, before every payee rule without one
  (which conditions one reaches for on real descriptors);
- how rules are ordered by priority, and whether the editor needs to show
  that at all;
- whether imports get a description at creation (the list shows an entry's own
  `description` only, §4.1), and if so how it is filled and reviewed;
- the starter categories offered on an empty tree (the author's tree);

all of them to be tried on real data.

## 11. Interaction standards

A view picks one of these patterns for each situation; it does not invent a
variant. The components that realise them are listed in `architecture.md`
§6.2; how they look is `design.md` §5 and §7.

### 11.1 Surfaces

An interaction has one surface. A **dialog** is modal and centred; a
**popover** is anchored to its trigger and does not block the page; the **work
panel** is the unit panel (§4.1, §5): a large overlay (roughly half to four
fifths of the viewport), addressable by URL, the list dimmed behind it,
stepping to the next and previous unit by key, and asking on Esc when its
draft has changes; a **page** has its own route. Take the first rule that
applies:

1. Choosing among known options, or toggling: a **popover** from a visible
   trigger; a **dialog** when it starts from a menu item.
2. Editing one text value of a thing that is shown right there: **in place**.
   Nothing else is inline.
3. Working one item of a list the user steps through, with draft, preview and
   commit, the list kept in view: the **work panel**.
4. More than five fields, a preview, a table, fields that depend on others,
   or a thing other screens link to: a **page**.
5. Otherwise, up to five single-line fields or a decision about
   consequences: a **dialog**.

An interaction that needs the page it started from (its snapshot, its cursor,
an unsaved draft) is a dialog, a popover or a new tab, never a page. A task
that must outlive navigation lives on a page and in a store that outlives it.
A popover never makes a write that needs a decision; choosing or toggling is
its only write. **There is no inline form**: adding, and editing more than one
field, are dialogs or pages. The entry form is a form dialog; once it has created the transaction the work panel opens on it. It offers a secondary "Add and add another" beside "Add", which clears the form for the next transaction instead.

In the work panel, a transfer leg's partner offers and the amount received of a
counter-leg are fields of the draft editor, not inline forms. The transfer block shows the
partner summary — for an unpaired leg the proposed offer, preselected, or "no
partner yet" — with a "Choose partner…" trigger (for a paired leg "Pick another
partner…") that opens the **offers popover**; offers are never listed inline.
The popover groups the offers as the server orders them (open, paired
elsewhere, new), has a search box that filters them, and scrolls where there
are many; "Load more candidates" widens the window for one pick, and a pick is
a draft edit. A picked partner shows "Reset to proposal". Picking an offer of
another amount splits the difference off the larger leg automatically, a fee
shown in the preview, never a separate step. There is no "Unpair" control: the remedies are another partner, converting the
leg to a flow, or changing its counter-account. "Add account" is a form dialog.

### 11.2 Forms and keys

| Kind | Buttons | Enter | Esc | Ctrl/⌘ + Enter |
|---|---|---|---|---|
| In place | none | commits a changed, non-empty value; otherwise cancels | cancels | as Enter |
| Popover choice | none | chooses the highlighted item | closes | — |
| Popover form (view settings) | Clear, Apply | applies | closes, discarding | — |
| Form dialog | the verb, Cancel | submits | cancels | — |
| Decision dialog | the verb, Cancel | never confirms | cancels | not bound |
| Pick dialog | Cancel | chooses the highlighted item | cancels | — |
| Draft editor (page, panel) | Save *thing* or Commit, Cancel | never submits | page: not bound; panel: closes, asking if the draft has changes | saves or commits |
| Standalone form (login) | one primary | submits | — | — |

Blur commits an in-place edit; a refusal keeps the field open with the error.
A decision dialog about a destructive action starts with focus on Cancel.
Leaving a draft editor with changes asks first. Esc acts on the innermost open
surface. A surface cannot be dismissed while its write runs. When a surface
closes, focus returns to what opened it.

### 11.3 Row actions

A row has one primary action, what a click means, and secondary actions. A row
of the ledger or the queue has no action buttons: its actions are keys (§5)
and the panel, and each key action also has a mouse path. A row of a settings
list or a tree shows at most two icon actions, the edit action and the
add-in-context action, and puts the rest in one `⋯` menu: reorder (Move up,
Move down), move, merge, then delete, last and in the destructive style. Where
a row has two actions or fewer they are all shown and there is no menu.
Actions are revealed on hover and keyboard focus and are always focusable. An
icon action's accessible name is "*Verb* *name*" and its tooltip "*Verb*", the
same words as the menu item.

### 11.4 Wording

Buttons are verbs in sentence case without a full stop. Things are *added*,
never "created" or "new": "Add category", "Add rule", "Add tag “x”"; a page
that adds is titled "Add rule". An add dialog ends with "Add", an edit with
"Save", a page editor with "Save *thing*", a popover that only changes the view
with "Apply", a decision dialog with the verb of the action, with the count
where there is one ("Delete", "Merge", "Tag 214 entries"). "OK", "Yes" and
"Confirm" are not used: *confirm* is a unit's review state. Cancelling is
"Cancel". A verb that acts on existing data and opens a decision first ends
with "…" ("Delete…", "Merge…", "Move to…", "Tag all…"); "Add …", "Edit" and
navigation do not. While a write runs the button names it ("Saving…") and is
disabled; a disabled action stays visible and gives its reason (§5, §6). Text
buttons carry no icon. A placeholder is allowed only in a find or filter box
and is an imperative ("Find a category…"), never an example value; every other
field has a visible label.

### 11.5 Feedback

A field's validation message stands under the field. A failure of a write
started in a dialog stands in the dialog, above its buttons, as an *error*
(nothing was written), a *conflict* (the world moved; the new numbers are shown
and the user asks again, §8) or a *report* (partly done). A direct write that
fails, and every structural success (delete, merge, tag all, saving a page), is
one notice on the reserved line under the page header; a plain direct write
(add, rename, a look) says nothing, because the list shows it. A failure to
load shows the error with "Try again" (§8): the page's own state for a page or
list, a notice for a part.

### 11.6 Empty, loading and error states

An empty list says what is missing and what to do (§9): "No categories yet",
one sentence, the page's add action; an empty filter result says so and offers
"Clear filters". A list loads as skeleton rows, a part as one muted line, a
preview as "Checking what would change…". A picker's empty state is one line
inside it.

### 11.7 Page header

Every page has a title, a one-sentence description and at most one primary
action, at the right of the title row. A page's primary action is its "Add"; a
page that has no add has no primary action.
