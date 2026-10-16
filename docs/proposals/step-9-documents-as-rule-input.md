# Documents as an input to rules, not a rewrite of the source

Status: for review, second revision. Nothing in `spec/` is changed by this document; part 3 drafts the
text. References are by section and content; line numbers would drift.

## 1. Behaviour we want

### 1.1 The problem this solves

Step 9 as built lets a linked document **replace** the counterparty text and append its line
descriptions to the purpose, so that resolution reads "enriched" text. In use it is intransparent:

- a rule on the card descriptor (`PAYPAL *`) silently stops matching once a document links, and
  "Create rule from this transaction" shows an example the rule no longer sees;
- history had to be switched off for documented transactions, because the text it compares is no
  longer the bank's;
- a panel-wide "Re-resolve" on a confirmed entry with a candidate document wipes type, category and
  payee, with nothing to propose them again;
- nothing stops a document from being attached to a transfer;
- a split entry resolves with its own line in the preview but with all lines after the commit, so the
  same rule gives different answers before and after.

### 1.2 The model

**A document is an input that rules can read. It never rewrites what the source says.**

1. **Resolution always reads the source fields as stored.** The counterparty name, purpose and
   booking text are the bank's, with or without a document.
2. **Rules get two new readable fields**, entry-level, not on the source transaction:
   - `document_merchant`: the linked document's merchant name;
   - `document_lines`: the linked document's line descriptions.

   A condition on a document field fails when the entry has no linked document. The rule editor's
   example also shows `payee`, which category rules already read.
3. **Both stages stay visible.** Before a link, the rule on the bank text fires (payee PayPal); the
   payee has a document provider, so the entry waits for its document. The link is new input, so
   every value after it is derived again (§5.9), and a rule on the merchant, ordered before the
   descriptor rule, sets the payee CloudNotes. The panel shows the linked document; the rule editor's
   example shows the same fields the rule reads.
4. **`document_lines` matches any line.** A condition holds if any line description satisfies it, with
   the usual operators: `contains "lamp"` holds for a line "Desk lamp"; `equals "Shipping"` for a line
   "Shipping".
5. **An entry sees only its own line, once it has one.** When a transaction is split along a
   document's lines, each entry references the line it was cut from (`document_line_id`). Its
   `document_lines` is that one line. An entry with no line (unsplit, or made by hand) sees all
   lines. The original entry takes the first line it carries, plus the remainder. A reference to a
   line of another document than the transaction's is ignored, and the entry sees all lines; a
   changed document's lines are replaced, which clears the references to them. The same line is what
   the model of pass 3 is sent for that entry.
6. **A link is new input and re-derives standing values after it, a user's included** (§5.9: "new
   input is exactly when a decision deserves a second look"). Nothing in this proposal changes that;
   it only removes the contradicting sentence "never replaces a value a user confirmed" (spec §5.8).
7. **A document implies `flow`.** It is a constraint of field order, like "a category implies a flow":
   a type pass never proposes `transfer` for a transaction with a linked or picked document.
   - A transaction typed as a transfer is not a candidate, and a hand pick on it is refused.
   - Converting a linked transaction to a transfer in the draft drops its document, as it drops the
     payee (I9); the preview shows it.
   - A pick on an untyped transaction sets its type to `flow` as a user decision, as a drafted payee
     already does.

### 1.3 The payee of a documented charge

**The payee is the provider, unless a rule on the document says otherwise.** A payee is a curated
reporting dimension (§3.6); most merchants reached through PayPal will never be one.

- The descriptor rule (`PAYPAL *` → PayPal) is standing and fires again after the link. Every merchant
  the user has not made a payee therefore stays under PayPal, which is the payee that was paid.
- A merchant becomes the payee through a rule on `document_merchant`, ordered before the descriptor
  rule. That rule is the explicit act of curating the merchant.
- History cannot do this: pass 1 outranks pass 2, so a rule's payee always wins over history's. Letting
  a provider payee be "applied, yet replaceable by history" would add a third state between proposal
  and decided value, touching review state, confirmation and the commit. Rejected.
- Two UX aids close the friction, both reusing the existing editor:
  - **The panel nudges.** Where the user changes a value a rule set (PayPal → CloudNotes), the panel
    offers "Create rule from this transaction", with the document fields available.
  - **The editor orders it.** A new payee rule with a document condition is given a priority before
    every payee rule without one; the preview already shows where another rule takes precedence.

### 1.4 Who does what: rules, history, the model

| | Rules | History | The model (pass 3, not in v1) |
|---|---|---|---|
| **Type** | not needed: a document implies `flow` | not needed | not needed |
| **Payee** | the descriptor rule (provider), a merchant rule (curated merchant) | none for a documented charge | semantic fallback where no rule decides |
| **Category** | on payee, merchant or lines | the merchant key, where one merchant has one habit (a subscription) | the line semantics |
| **Lines** | keyword rules only | never | yes, one line per split entry |

**History changes in one way.** A documented transaction is still kept out of the raw-text keys (the
bank text of a documented charge names the payment processor, and a split order's entries would each
vote under it). It is instead asked on one exact key, **for the category only**:

- **`document_merchant`**: canonical equality (§5.2: alphanumerics only) of the document's merchant
  name. Votes are confirmed entries, as for every key (source transaction, within the lookback, not in
  the unit being re-resolved), whose transaction's document has the same merchant. Counted as for the
  other keys (strict majority).
- A documented transaction votes only for this key, and an undocumented one never sees it.
- Effect: the second CloudNotes charge gets its usual category from the first, with no rule. For a
  marketplace the categories differ per order, so there is no majority and history stays silent.
- Why not the payee: the descriptor rule or a merchant rule has already decided it (§1.3); a history
  proposal could only show where neither exists.
- Cost: one grouped lookup over confirmed documented entries, a small subset; to be measured against
  the settle budget.

The threshold stays as for every key (a single unanimous precedent is a majority). Raising it is part
of the model's design, recorded as an open question (§3.13).

### 1.5 Rule editor

The Example table beside the conditions shows the example entry's fields in two groups, with a
separator each:

- **From the source transaction:** counterparty name, counterparty reference, purpose, booking text,
  mandate reference.
- **From the entry:** payee (this was missing), document merchant, document lines.

A row without a value shows "—"; the document rows say "no document linked". The condition field
picker uses the same two groups. "Create rule from this transaction" offers the document fields when a
document is linked. A new payee rule with a document condition gets a priority before the payee rules
without one (§1.3). The preview of the entries a rule would match, and the two lists of a rule change,
evaluate the document fields through each entry's linked document and line.

### 1.6 Panel

- A split row shows the description of the line it was cut from.
- The document field shows the lines, and offers **"Look for a document"** (a document-only
  re-resolve) also for a unit whose document key is the matcher's "none". It was hidden for that case.
- Where the draft changes a value a rule set, the panel offers "Create rule from this transaction"
  (§1.3).
- The panel-wide "Re-resolve" keeps its meaning (resolve everything afresh, decisions included); its
  preview already shows what changes, so it gets no separate warning.
- What Re-resolve can propose for a confirmed documented entry: the descriptor rule's payee, a merchant
  rule's values, the merchant key's category where a precedent exists. With none of them, the fields
  fall to the model, or stay empty while it is not configured. That is the honest answer, not a gap.

## 2. Decisions taken in discussion

1. No rewriting of the counterparty text or the purpose; the document is read through fields.
2. New rule fields `document_merchant` and `document_lines`, plus the example's `payee` row, grouped.
3. `document_lines` matches any line; an entry cut from a line sees only that line.
4. The line is referenced from the entry (`document_line_id`), so preview and commit agree. A
   reference rather than a number: lines have ids, a changed document's lines are replaced (which
   clears the references), and a reference to another document's line is detectable when read, so no
   write path has to clear it.
5. The payee of a documented charge is the provider, unless a rule on the document sets a curated
   merchant; the panel nudges toward that rule and the editor orders it first. Rejected: a provider
   payee that history may replace (a third value state).
6. History: one new exact key (document merchant), **category only**; no lines in history; raw keys
   unchanged and still closed to documented transactions. Threshold unchanged for now.
7. "New input deserves a second look" stays: a link re-derives a user's values too.
8. A document implies `flow`, as a field-order constraint; transfers cannot carry one; converting to a
   transfer drops the document.
9. The model as the reviewer of weak history is recorded as an open question in `spec.md` §9, to be
   decided with the model (pass 3, not in v1).

## 3. Resulting spec changes, drafted

### 3.1 `spec/schema.sql` and migration

Add to `ledger_entry`, next to `document_id`:

```sql
    -- the document line this entry was cut from by a split along the lines
    -- (spec §5.8); null for an unsplit entry or one made by hand. Read only
    -- while the line belongs to the document its transaction carries; a
    -- reference to another document's line is ignored. A changed document's
    -- lines are replaced (spec §5.5), which clears it.
    document_line_id     bigint REFERENCES external_document_line(id) ON DELETE SET NULL,
```

a constraint and an index:

```sql
    -- a transfer is not explained by a document (spec §5.8)
    CONSTRAINT ck_document_not_on_transfer
        CHECK (document_id IS NULL OR type IS DISTINCT FROM 'transfer'),

-- a line is cut into at most one entry
CREATE UNIQUE INDEX ux_le_document_line
    ON ledger_entry (document_line_id) WHERE document_line_id IS NOT NULL;
```

A migration `0007_document_line` adds the column, the constraint and the index (additive; no existing
row violates them: confirmed units carry no link on a transfer). The schema equivalence test covers it.

### 3.2 `spec/spec.md` §5.8: replace the "A link is an input to resolution" bullet

Current:
> **A link is an input to resolution** (§5.9). While its transaction is unconfirmed, the document's
> merchant name and line descriptions enrich its entries' input … so a rule keyed on a card descriptor
> such as `PAYPAL *` no longer matches and one keyed on the merchant does. …

Replace by:
> **A link is an input to resolution** (§5.9). The source row is read as stored; the document adds
> fields that rules read: its merchant name (`document_merchant`) and its line descriptions
> (`document_lines`). A rule on the card descriptor keeps matching, so the entry first resolves as the
> descriptor says and waits for its document; once linked, a rule on the merchant ordered before it
> wins. The resolved values appear when a link is made and disappear with it. **The payee of a
> documented charge is the provider unless such a rule names the merchant** (§3.6: a payee is
> curated).

### 3.3 `spec/spec.md` §5.8: the closing sentence

Current:
> Nothing else follows from a document: it never reopens a reviewed entry and never replaces a value a
> user confirmed.

Replace by:
> Nothing else follows from a document: it never reopens a reviewed entry. For an unreviewed
> transaction a link is new input, and re-derives the values after it as any new input does (§5.9).

### 3.4 `spec/spec.md` §5.8 and §5.9 field order: transfers and the implied type

§5.8, add after the eligibility text:
> **A document explains a flow.** A transaction typed as a transfer is not a candidate, a pick on it is
> refused, and the schema refuses a link on a transfer. Converting a linked transaction to a transfer
> drops its document, as it drops the payee (I9). Picking a document for an untyped transaction types
> it `flow`, as a user decision, like a drafted payee.

§5.9 field order, in the sentence on constraints ("a category implies a flow, a payee applies only to
flows, …"), add: "a document implies a flow".

### 3.5 `spec/spec.md` §5.9 "Resolution is a pure function"

Current: "… read together with a linked or picked document, whose merchant name stands in for the
counterparty name and whose line descriptions are read with the purpose (§5.8); the source row itself
is never changed."

Replace by:
> … the source row as stored; a linked or picked document adds the fields `document_merchant` and
> `document_lines`, which rules read (§5.8). The source row is never changed.

### 3.6 `spec/spec.md` §5.9 history (pass 2) and the model

Replace the passage that says history does not run for a transaction with a document (and the vote
exclusion) by:
> A transaction with a linked or picked document is asked on one key only, the document's merchant
> name, for the category only, and votes only for that key (`history.md`); on every other key it is
> neither asked nor counted, since its bank fields describe the provider and not the purchase. Its
> payee is the provider's or a rule's (§5.8).

In the key list, add key 6: "the document's merchant name, for a transaction with a document and for
the category only".

The model's "Limited payload" bullet: add "for an entry cut from a document line, that line only".

### 3.7 `spec/spec.md` §5.9 rule conditions and the rule editor

- The fields sentence ("The fields are `counterparty_name`, …"): add `document_merchant` and
  `document_lines`, which take the four text operators and fail without a document;
  `document_lines` holds when any line satisfies the condition.
- The comparison sentence: the two fields are compared with the name normalisation.
- Rule editor ("The editor shows the example's source fields beside the conditions"): "The editor shows
  the example's fields beside the conditions in two groups, from the source transaction and from the
  entry (payee, document merchant, document lines). A new payee rule with a document condition is
  given a priority before every payee rule without one."

### 3.8 `spec/spec.md` §6: the draft's split and the panel's nudge

- The draft's top-down resolution ("in the draft, an entry made from a line is resolved with that line,
  every other entry with all of them"): replace by "an entry made from a line references it and is
  resolved with that line, in the draft and after the commit; every other entry with all of them".
- Add to the panel's offers: "Where the draft changes a value a rule set, the panel offers to create a
  rule from the transaction (§5.9, rule editor)."

### 3.9 `spec/features/documents.md` §5 "Enrichment": replace the section

Rename to **"The document as an input"** and replace its text by:
> A linked or picked document adds two fields to its transaction's entries, which rules read
> (`spec.md` §5.9): `document_merchant`, the merchant name, and `document_lines`, the line
> descriptions. The source row is not rewritten: `counterparty_name`, `purpose` and the other source
> fields are the bank's. A rule keyed on a card descriptor such as `PAYPAL *` therefore matches before
> and after the link. Its payee, the provider, stays the payee of every merchant the user has not
> curated; to make a merchant the payee, the user writes a rule on `document_merchant`, ordered before
> the descriptor rule.
>
> `document_lines` holds a condition when any line satisfies it. An entry cut from a line by a split
> along the lines (§6) references that line, and sees only it; every other entry, an unsplit one
> included, sees all lines. A reference is read only while its line belongs to the transaction's
> document, and a changed document's lines are replaced, which clears it. The model of pass 3 is sent
> the same line.
>
> Linking is a change of the first value in field order, so every standing value after it is derived
> again (`spec.md` §5.9), the link itself staying. A change to the linked document's total, currency,
> merchant or lines resolves the transaction afresh in the same way. Rules and the model run on these
> inputs; history asks one key, the merchant, for the category only (`history.md`).

This removes the sentence "No line is stored with an entry (`spec.md` §9) …".

### 3.10 `spec/features/documents.md` §6 (split) and §1 (eligibility)

- §6: the split along the lines writes `document_line_id` on each entry it creates (the original: the
  first line it carries). The panel shows the description of that line on the row.
- §1: "a payee that the enriched input resolves differently — the real merchant instead of PayPal —
  does not undo it" becomes "a payee that a rule on the document resolves differently — …".
- Add to §1: a transaction typed as a transfer is not considered (`spec.md` §5.8).

### 3.11 `spec/plugins/classifiers/rules.md`

§1 Input: replace "its document — the merchant name standing in for the counterparty name, the line
descriptions added to the purpose" by "its document, read through the fields `document_merchant` and
`document_lines` (below); the source fields are as stored".

§2 fields table, replace the first and third rows and add:

| Field | Read from |
|---|---|
| `counterparty_name` | the counterparty name |
| `purpose` | the purpose |
| `document_merchant` | the linked document's merchant name (fails without a document) |
| `document_lines` | the linked document's line descriptions: the entry's own line if it was cut from one, else all (fails without a document) |

Add: "`document_lines` holds when any line satisfies the condition; `regex` runs on each line." The
comparison table lists both under name normalisation. The `payee` sentence (category rules only) is
unchanged.

### 3.12 `spec/plugins/classifiers/history.md` §1, §2, §4

- §1, the vote definition: keep "whose transaction carries no document" for keys 1 to 5; add: "A vote
  for the document key (§2) is a confirmed entry, otherwise as above, whose transaction's linked
  document has the same merchant name."
- §2, after the key list:
  > 6. **`document_merchant`** — canonical equality of the document's merchant name (`spec.md` §5.2),
  >    for the category only. It is the only key asked for an entry whose transaction has a linked or
  >    picked document, and such an entry is not asked on keys 1 to 5. An entry without a document
  >    never sees it.
- Replace "History never sees a document: it is not asked for a transaction with a linked or picked
  document …" by: "Keys 1 to 5 never see a document: a transaction with a document is not asked on them
  and does not vote for them; key 6 reads the merchant name only."
- §4: `matched_on` also takes `document_merchant`.

### 3.13 `spec/spec.md` §9 open questions

Remove **"History over enriched input"**: this proposal answers it (key 6).

In **"Splitting along a document's lines during settling"**, the sentences on a line reference
("Entries split along the lines … could also carry a reference to their line (`document_line_id`) …"
to the end) are now settled; remove them.

Add:
> - **The model as the reviewer of weak history.** Today history proposes on a single unanimous
>   precedent, and whatever it proposes keeps the model from being asked (§5.9, pass 3). Once the model
>   runs, that is often the wrong way round: a shop bought from once proposes the same category next
>   time, while the model, which has the purpose and a document's lines, would do better. A sketch:
>   rules decide first and are never reviewed by the model; history proposes on its own only where its
>   evidence is strong (a minimum number of votes, all agreeing); below that it proposes nothing and
>   hands its votes to the model as context — per key, the values the user chose and how often
>   ("merchant CloudNotes: Software ×3"), never the text of past entries — together with the
>   categories and payees to choose from. The model answers as a proposal, its basis naming the
>   evidence it was given. Questions to settle with the model: the threshold for history alone, and
>   whether it depends on a model being configured (without one, history must stand alone as today);
>   what of the evidence enters the payload's fingerprint, so a new confirmation does not re-ask the
>   model for every similar entry; and whether the counts are within the limited payload. Decided with
>   pass 3: it is the reason history's threshold is left as it is in v1.

### 3.14 `spec/ux/patterns.md` and `spec/ux/views/review-queue.md`

- Patterns, the rule-editor bullet: the example's two groups (source transaction, entry), the
  condition picker grouped the same way, and the priority given to a new rule with a document
  condition.
- Review queue / panel: split rows show their line description; the document field offers "Look for a
  document" also for a matcher "none"; the "Create rule from this transaction" nudge where the draft
  changes a rule's value; converting to a transfer shows the document dropped.

### 3.15 `spec/decisions.md`: new D225

"Documents are inputs to rules, not a rewrite" with the decisions of part 2, the rejected alternatives
(enriching the counterparty text; tokenizing lines in history; no stored line; a stored line number
cleared by every link write; a provider payee replaceable by history), and the supersession of the
enrichment parts of D223 and `documents.md` §5.

## 4. What changes in code (for planning, not for the spec)

- **Resolution input:** stop replacing `counterparty_name` and appending to `purpose`
  (`app/core/resolution/enrich.py` goes; `load.py`, the overlay's input builder); add the document
  fields to the entry input, from the entry's `document_line_id` where it belongs to the carrier's
  document.
- **History:** documented transactions ask only the merchant key, for the category
  (`settle/resolution.py`, the votes snapshot, `plugins/classifiers/history.py`).
- **Field order:** a document implies `flow`; a type pass proposing `transfer` with a document is
  dropped.
- **Rules:** the two fields in the plugin and its validation, the rule preview, `rule_preview.py`; the
  editor's default priority for a payee rule with a document condition.
- **Schema:** the column, constraint and index, migration `0007`. The commit's split writes the line
  references; the overlay carries them through the draft. No write path clears them: replaced lines
  clear by `ON DELETE SET NULL`, another document's line is ignored when read.
- **Draft/overlay:** a pick on a transfer is refused (`document_not_for_transfer`); converting a linked
  transaction to a transfer drops the document; a pick on an untyped entry implies `flow`; split
  entries resolve with their line.
- **API:** the entry carries a document summary (merchant, lines) and its line, for the rule editor's
  example and the panel row.
- **Frontend:** the example table groups and the payee row, the rule field picker groups, the lines on
  the document field and split rows, "Look for a document" for the matcher "none", the "Create rule"
  nudge.
- **Perf:** the merchant key's lookup in the votes snapshot; re-measure the settle budget, which is
  already at its limit.

## 5. Open points

Settled in this revision:

1. The panel-wide "Re-resolve" gets no warning; its preview shows what changes (§1.6).
2. The refusal for a pick on a transfer is `document_not_for_transfer`.
3. Entries cut before this change: dropped; there is no real data yet.

Remaining:

1. The nudge (§1.3, §1.6): offered only where the draft changes a value a *rule* set, or wherever the
   user changes a payee or category? Proposed: rule values only, since there the rule is what keeps
   coming back.
