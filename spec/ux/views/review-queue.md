# Review queue — view sketch

Status: **thin sketch.** Written down before implementation only as far as
the principles go; the interaction model is expected to change after a month
of real use, and this document with it. The rules these principles rest on
are `spec.md` §5.7 and §6; the contracts are `architecture.md` §4.1 and §6.5.

---

**Three sections, each by date.** Pending review, needs an account and waiting
(below), and within each section units are ordered by booked date, then by
anchor entry id. Most units are recurring — the same proposed values from the
same evidence — and each is committed with one keystroke that moves to the
next. The pending section can instead be cut by counterparty (below). A unit
appears once, with all its entries. Units decided entirely by own accounts and
rules arrive confirmed once complete (`spec.md` §5.9), and appear only in the
waiting bucket while a partner is still to come: a recurring unit leaves the
queue for good once a rule decides it. A charge a rule decides as a transfer to
a clearance account is complete at once, its counter-leg booked with it
(`spec.md` §5.7), and never appears.

**The navigation counts what can be done.** The Review item shows, beside its
label, how many units are pending review or need an account — not those
waiting — as a count chip (`design.md` §5), and nothing at zero (architecture §6.5). While the model is
looking at entries, a small activity mark beside the count says so, and its
tooltip how many.

**An account filter narrows the queue.** Above the sections stands the
ledger list's filter bar with its Account chip alone, without the chip's
counter-account section; several accounts are alternatives. A unit shows when
any of its entries is on a chosen account, so a transfer between two accounts
shows under either. The filter is in the address, like the ledger list's, and
changing it fetches the queue again, as a refresh does. The sections, their
groups and their counts are those of the units the filter shows. The Review
item and the Overview's To review card count the whole queue, since the work is
the household's and not one view's. A filter that shows nothing says so and
offers "Clear filters" (`ux/patterns.md` §11.6). The ledger's other dimensions
are not offered: category, payee and tags are proposals that change under
review, and the type and flags are what the sections already show.

**Pending review is cut by date or by counterparty.** Beside the Account
chip, a segmented control, "By date" or "By counterparty", chooses how the
pending section is cut. It is in the address with the filter, "By date" where
the address says nothing, and changing it fetches the queue again.

By date, the section is cut by month and day (`patterns.md` §4.1). By
counterparty, it is cut once: a band row per counterparty (`design.md` §5),
with its number of units. The counterparty is the counterparty name of the
anchor entry's source, compared ignoring case and repeated spaces, and
labelled as its first unit spells it. A counterparty with one unit in the
section, and a unit whose source names none, go to one last band, "Other".

Bands are ordered by their count, largest first, then by name. Within a band,
units are in booked date order, then by anchor entry id, and the date column
is shown. The cut is the server's, so each page continues the last band or
starts the next, and Load more only appends. The other two sections keep
their cuts.

**What the model has not yet answered says so.** A unit the model is still
looking at is marked on each row the model has not yet answered, one quiet
line above the list says how many there are, and the panel says the model's
guess is still coming; a unit can be decided meanwhile, and the guess then
gives way. Its answers arrive as new data.

**Evidence is shown, not confidence.** Each derived value shows its basis as
the pass recorded it: "1 of 1 since March" for history, the rule for a rule,
the rationale for the model. A thin proposal stands out without a number to
interpret.

**Proposals are current when a unit is opened; the order is not.** The panel
previews each unit fresh, so confirming the first of thirty entries from a new
merchant gives the other twenty-nine a proposal by the time the cursor reaches
them. The queue itself stays as it was fetched for the session (architecture
§6.5).

**Units can be committed as seen, several at once.** In the pending section each
unit has a checkbox, on its first row, in a narrow first column without a
header. It is enabled where a commit would confirm what the row shows: a
complete interpretation (a flow with its category, a transfer with its pair)
and no answer of the model still to come. Elsewhere it is disabled, with the
reason as tooltip. The other two sections have none. `x` ticks or clears the
unit under the cursor. A counterparty band's checkbox ticks or clears its
enabled units, and shows as mixed when some are ticked.

While units are ticked, a footer sticks to the bottom of the section: "5 units
selected", Commit and Clear. `Ctrl/⌘ + Enter` with the panel closed commits
them. They are committed one after the other, each on its own, as the panel
would: each is previewed afresh and committed only if its values (type,
category, counter-account, payee, description) are those its row showed. A
changed basis ("2 of 2" where it said "1 of 1") is not a change.

A unit that changed, or that the server refuses, is not committed: it is
cleared and marked, the reason in its tooltip, to be opened and seen anew. The
footer then says how many were and were not committed. Committed units are
marked resolved in place, as after the panel (`patterns.md` §7). A refresh, or
a change of filter or cut, clears the ticks.


**Sections.** The queue is the units not confirmed (`spec.md` §6), each in one
section, with the count per section. Each section is a card, its title the section's
name and count (`design.md` §5); an empty one is its title and a line saying
so.

- **Pending review** — the units that have what they need and await a
  decision.
- **Needs an account** — unmatched legs whose counter-account does not exist
  (`spec.md` §5.7), grouped by the currency they need, a band row per currency
  with its add action; this, the waiting section's grouping by account and
  the pending section's cut by counterparty are the queue's only defined
  groupings. Pending review is cut by month and day
  as the ledger list is (`patterns.md` §4.1), or by counterparty (above); the
  other two sections hold few rows and are cut only by their currency or
  account, their rows keeping the date column. A needs-an-account group reads:

  ```
  3 transfers need an account in USD          [ Add account ]
  ```

  One unit reads "A transfer needs an account in USD". The new account is then
  offered first on each, and each is confirmed on its own (`spec.md` §5.7). The
  counter-account picker groups the accounts by currency — "Accounts in USD"
  (the instructed currency, where the leg has one), "Accounts in EUR" (the
  leg's own), "Other accounts" — with the usual ranking within each group. No
  account is disabled for its currency: a pick the currency rule does not allow
  shows in the "After this commit" region, with the reason and no partner
  offers (`spec.md` §5.9). The queue stays a snapshot: after an account is
  added, the group shows a
  quiet notice, "3 units can now be completed: Refresh", and refetches only
  on request.
- **Waiting** — entries expecting information that has not had its chance to
  arrive (`spec.md` §6): a partner leg, which cannot be confirmed until
  paired. Waiting is a hint; the unit stays editable. The section is grouped
  by the account waited for, as the needs-an-account section is by currency:
  each band row gives the reason once — "Waiting for <account>, synced
  through <date>", or "…, not synced yet" for an account never fetched.

**Unpaired legs show their offers** (`spec.md` §5.7) — unpaired legs and
entries on the counter-account first, exact matches leading, then legs paired
elsewhere, then, where the counter-account is unsynced, the counter-leg — with
an exact open offer preselected, or the counter-leg where there is no open
offer, so the common case stays one keystroke. Where only open offers of
another amount exist, nothing is preselected and the user picks. A leg paired
elsewhere is never preselected, and a "load more candidates"
action widens the window for one pick. The offers are listed in the panel's
popover (`ux/patterns.md` §11). An unmatched leg whose counter-account
is synced says so: its partner is missing from the import, so the remedy is to
import what is missing, or to convert the leg if it is not a transfer. A leg
whose counter-account is a clearance account has no offers: its partner is
the counter-leg booked from it (`spec.md` §5.7), which the preview shows on
that account as "booked from this charge", and which goes with the leg when
the draft converts it or names another counter-account. Booking entries are
never offered as partners.

**Open for the first month.** Whether to group units by more than their
counterparty (type, counter-account, category, the evidence behind them), and
whether grouping is wanted beyond the three sections: decided only after the
queue has been used on real units.

**The panel offers a rule where a rule's value is changed.** Where the draft
changes a value a rule set — a category, say — the panel offers "Create rule
from this transaction", with the entry's account and source text available in
the editor (`spec.md` §5.9).

**A unit is titled by its source, never by one of its entries.** A single
entry by its own text (`ux/patterns.md` §4); a split by its source's
counterparty, else its purpose — "REWE Markt (split in 2)"; a booking by its
document — "rewe order 304-1 · 26 items"; a transfer pair by its accounts.

**A booking's unit is leaner** (`spec.md` §5.8). Its group says where it came
from — "Booked from *provider* order *reference*", or "Booked from *provider* order" where it has none, opening the document's
detail (`ux/views/documents.md`) — and each row shows its source text. The
panel offers no partner, no conversion to a transfer and no split: a booking's
type and split are its document's. Its values — payee, category,
description, note, tags — are reviewed and committed as for any unit. A
counter-leg booking shows its charge as its partner and nothing to edit but
its description, note and tags.

**Keyboard-first.** The bindings are a cross-view convention and belong in
`ux/patterns.md`.
