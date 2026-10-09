# Review queue — view sketch

Status: **thin sketch.** Written down before implementation only as far as
the principles go; the interaction model is expected to change after a month
of real use, and this document with it. The rules these principles rest on
are `spec.md` §5.7 and §6; the contracts are `architecture.md` §4.1 and §6.5.

---

**Order by shape, not date.** Most units are recurring — the same proposed
values from the same evidence — and sit next to each other, each confirmed
with one keystroke that moves to the next. A flat chronological list demands
full attention on the boring ones, which is why people abandon these queues.
A unit appears once, with all its entries. Units decided entirely by own
accounts and rules arrive confirmed once complete (`spec.md` §5.9), and appear
only in the waiting bucket while a partner or a document is still to come: a
recurring unit leaves the queue for good once a rule decides it.

**Evidence is shown, not confidence.** Each derived value shows its basis as
the pass recorded it: "1 of 1 since March" for history, the rule for a rule,
the rationale for the model. A thin proposal stands out without a number to
interpret.

**Proposals are current when a unit is opened; the order is not.** The panel
previews each unit fresh, so confirming the first of thirty entries from a new
merchant gives the other twenty-nine a proposal by the time the cursor reaches
them. The queue itself stays as it was fetched for the session (architecture
§6.5).

**Buckets.**

- **Waiting** — entries expecting information that has not had its chance to
  arrive (`spec.md` §6): a partner leg, which cannot be confirmed until
  paired, and a document, which can. Waiting is a hint; the unit stays
  editable.
- **Needs an account** — unmatched legs whose counter-account does not exist,
  grouped by the currency they need, with one create action per group:

  ```
  3 withdrawals need an account in USD          [ create account … ]
  ```

  The new account is then offered first on each, and each is confirmed on
  its own (`spec.md` §5.7).

**Unpaired legs show their offers** (`spec.md` §5.7) — unpaired legs and
entries on the counter-account first, exact matches leading, then legs paired
elsewhere, then, where the counter-account is unsynced, the counter-leg — with
an exact open offer preselected, or the counter-leg where there is no open
offer, so the common case stays one keystroke. Where only open offers of
another amount exist, nothing is preselected and the user picks. A leg paired
elsewhere is never preselected, and a "load more candidates"
action widens the window for one pick. An unmatched leg whose counter-account
is synced says so: its partner is missing from the import, so the remedy is to
import what is missing, or to convert the leg if it is not a transfer.

**Keyboard-first.** The bindings are a cross-view convention and belong in
`ux/patterns.md`.
