# Review queue — view sketch

Status: **thin sketch.** Written down before implementation only as far as
the principles go; the interaction model is expected to change after a month
of real use, and this document with it. The rules these principles rest on
are `spec.md` §5.7 and §6; the contracts are `architecture.md` §4.1 and §6.5.

---

**Three sections, each by date.** Pending review, needs an account and
waiting (below), and within each section units are ordered by booked date,
then by anchor entry id. Most units are recurring — the same proposed values
from the same evidence — and each is committed with one keystroke that moves
to the next. Whether the queue should also group such units, and what makes
two units alike, is open until the first month of real units has been seen;
nothing here defines a shape. A unit appears once, with all its entries. Units decided entirely by own
accounts and rules arrive confirmed once complete (`spec.md` §5.9), and appear
only in the waiting bucket while a partner or a document is still to come: a
recurring unit leaves the queue for good once a rule decides it.

**The navigation counts what can be done.** The Review item shows, beside its
label, how many units are pending review or need an account — not those
waiting — muted, and nothing at zero (architecture §6.5). While the model is
looking at entries, a small activity mark beside the count says so, and its
tooltip how many.

**What the model has not yet answered says so.** A unit the model is still
looking at is marked in its row, one quiet line above the list says how many
there are, and the panel says the model's guess is still coming; a unit can
be decided meanwhile, and the guess then gives way. Its answers arrive as new
data.

**Evidence is shown, not confidence.** Each derived value shows its basis as
the pass recorded it: "1 of 1 since March" for history, the rule for a rule,
the rationale for the model. A thin proposal stands out without a number to
interpret.

**Proposals are current when a unit is opened; the order is not.** The panel
previews each unit fresh, so confirming the first of thirty entries from a new
merchant gives the other twenty-nine a proposal by the time the cursor reaches
them. The queue itself stays as it was fetched for the session (architecture
§6.5).

**Sections.** The queue is the units not confirmed (`spec.md` §6), each in one
section, with the count per section.

- **Pending review** — the units that have what they need and await a
  decision.
- **Needs an account** — unmatched legs whose counter-account does not exist
  (`spec.md` §5.7), grouped by the currency they need, with one add action
  per currency group; this per-currency grouping is the one defined grouping
  in the queue:

  ```
  3 transfers need an account in USD          [ Add account ]
  ```

  One unit reads "A transfer needs an account in USD". The new account is then
  offered first on each, and each is confirmed on its own (`spec.md` §5.7). The
  queue stays a snapshot: after an account is added, the group shows a quiet
  notice, "3 units can now be completed: Refresh", and refetches only on
  request.
- **Waiting** — entries expecting information that has not had its chance to
  arrive (`spec.md` §6): a partner leg, which cannot be confirmed until
  paired, and a document, which can be committed once the user explicitly
decides to commit without it. Waiting is a hint; the unit stays
  editable. A unit waiting for a partner gives its reason in one line:
  "Waiting for <account>, synced through <date>", or "…, not synced yet" for
  an account never fetched; one waiting for a document reads "Waiting for a
  document from <provider>, covered through <date>", or "…, not synced yet".
  The waiting flag wins: a unit in this section stays here even while it has
  document suggestions.

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
import what is missing, or to convert the leg if it is not a transfer.

**Open for the first month.** Whether and how to group units by what they
share (type, counter-account or payee, category, the evidence behind them),
whether grouping is wanted beyond the three sections, and how it would be
drawn: decided only after the queue has been used on real units.

**The panel offers a rule where a rule's value is changed.** Where the draft
changes a value a rule set — a payee, say, from the provider's to the
merchant's — the panel offers "Create rule from this transaction", with the
document fields available in the editor (`spec.md` §5.9). A split row shows the
description of its line. Converting a linked transaction to a transfer shows
its document dropped (`spec.md` §5.8). The document section is in
`ux/views/documents.md`.

**Keyboard-first.** The bindings are a cross-view convention and belong in
`ux/patterns.md`.
