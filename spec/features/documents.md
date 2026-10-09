# Household ledger — document matching

Status: **written ahead, in v1** — exercised with a test document importer;
real document importers come later. The internals of linking external
documents (an Amazon order, a PayPal payment passed through to a card) to the
source transactions they describe. `spec.md` owns the domain this relies on —
documents and what a document importer delivers (§5.5), the link as a
derived field and its invariant (§5.8, I35), resolution (§5.9) and review
(§6) — and states
what the core requires of matching. This document covers only how matching
meets those requirements.

---

## 1. Which transactions are matched

A source transaction is considered when all of the following hold:

- it is not a duplicate;
- its unit is unconfirmed (`spec.md` I20);
- its entries have a payee with a `document_provider` (`spec.md` §3.6);
- its original entry has no decided `document`: neither a link nor a user's
  "none".

Eligibility is judged on the transaction as resolved without a document. The
link comes first in field order (`spec.md` §5.9), so a payee that the enriched
input resolves differently — the real merchant instead of PayPal — does not
undo it: a linked transaction is no longer considered at all.

While a transaction waits for its document (§7), settling does not confirm
its unit, however standing its values (`spec.md` §6), so rules on a provider
payee do not keep its document from being matched.

An entry whose payee is not yet resolved gets no automatic match; it can
still be linked by hand in the review panel.

## 2. Candidates

```
candidates(t), for a transaction t considered by §1:
  = documents of t's payee's document_provider
      carried by no entry,
      whose signed amount matches t exactly (§3),
      and whose occurred_on is within the document window of booked_on
          (spec.md §5.8): [booked_on − w, booked_on + w]
```

The window is symmetric and a single ledger-wide setting, like the matching
window of transfers.

## 3. Amounts match exactly, with their sign, in the document's currency

Where the document's currency is the transaction's, its total equals the
transaction's amount; where it is the transaction's instructed currency, its
total equals the instructed amount (`spec.md` §3.8); otherwise there is no
candidate. The tolerance is zero, no rate is ever involved, and a refund can
only match a refund document.

## 4. What settling writes

```
for each considered transaction t with at least one candidate:
    if t has exactly one candidate d,
       and d is a candidate of no other transaction
                       → set document_id = d on t's original entry, keyed
                         document with pass matcher_decision for a document
                         of one line, matcher_proposal for one of several
    otherwise          → write nothing; the candidates are t's
                         suggestions, computed when read
```

**Automatic linking needs uniqueness both ways.** Two identical charges
from one provider within the window may see the same single document;
neither gets it automatically, because which charge it describes is exactly
what the data cannot tell. Both are offered it as a suggestion. The unique
indexes on `document_id` (`spec.md` I35) make a racing second link fail
rather than double it.

**A link to a document of several lines is reviewed once** (`spec.md` §5.9):
its key is `matcher_proposal`, so the panel shows the split along the lines,
and the commit makes the key `user`, with or without the split. A link to a
document of one line has nothing to split and is keyed `matcher_decision`,
which is standing.

**Suggestions are never stored**, and carry no key. They are computed only
while the original entry has no decided `document`, so a decision — a pick,
or "none of these" — keeps the other candidates from being proposed again for
as long as it stands. One that stops being a candidate — the document changed,
another transaction took it — simply disappears, and the `document_suggested`
flag (`spec.md` §6) follows.

**The link has two writers**, like any derived field: settling, writing a
matcher link as above, and a commit, writing the user's pick or "none" as
`user` (`spec.md` §6). Beyond them, only a change of input touches it: a
changed document's ingest resolves its unconfirmed transaction afresh, dropping
the link for settling to make again (`spec.md` §5.5, §5.9); an
entry that is removed — its transaction marked as a duplicate or reverted, a
user-authored transaction deleted — frees its document (`spec.md` §5.6).

## 5. Enrichment

A linked or picked document enriches the input of its transaction's entries
(`spec.md` §5.9) — in the preview of any unit, confirmed or not; automatic
re-derivation reaches only unconfirmed transactions (`spec.md` I20): the document's merchant name stands in for the counterparty
name, and its line descriptions are added to the purpose. Rules and the model
run on that input — history does not run for a transaction with a document,
whose bank fields describe the provider rather than the purchase (`spec.md`
§5.9) — so a rule keyed on a card descriptor such as `PAYPAL *` no longer
matches, while a rule keyed on the merchant name wins. Card lines for
pass-through providers look alike — `PAYPAL *SEEEDDEVELO` — while the document
names the real merchant, which is the point.

In the preview's draft of a split along the lines (§6), an entry made from a
line is resolved with that line — the original entry with the first line it
carries; every other entry, an unsplit one included, takes the document's
merchant name and all its lines. No line is stored with an entry (`spec.md`
§9), so once committed every entry of the transaction takes all lines when it
is resolved again. The input is built when resolving
and never stored (`spec.md` §5.9): the source row is not changed.

Linking is a change of the first value in field order, so every standing
value after it is derived again (`spec.md` §5.9), the link itself staying: a rule keyed on `PAYPAL *` gives way to one
keyed on the merchant. The enriched proposals therefore appear as soon as a
link is made and disappear when it is deleted or the transaction is linked to
another document. A change to the linked document's total, currency,
merchant or lines resolves the transaction afresh in the same way. A split
along the lines (§6)
exists only once a commit has written it; until then the transaction's entry
takes the document's merchant name and all its lines as input, as an unsplit
entry does. The model of pass 3 is asked
again only because its payload changed (`spec.md` §5.9).

## 6. Splitting along the lines

The review panel proposes splitting a linked transaction along the
document's lines, whether its unit is confirmed or not, (`spec.md` §5.8). The split is draft state until the commit
writes it; only a commit splits (`spec.md` I7). The proposal is:

- one entry per line, with the line's amount — converted proportionally to the
  transaction's amount where the document is in the instructed currency,
  rounded half-even;
- the original entry takes the first line and the remainder — shipping,
  discounts, rounding — so it is never zero when the lines add up exactly;
- no split for a document of one line, where the document's total does not
  match the transaction exactly by §3, or where the original entry's share
  would be zero or change sign; the link stands, unsplit.

The proposal is made only for a transaction that is not split. An existing
split stays, and the draft offers *split along the lines* as an explicit
choice that replaces it (`spec.md` §6). The user may change the proposal
before committing, like any split. Picking another document in the draft
regenerates it. Once committed, the
split is the user's like any other. Settling never creates or removes an entry
for a document.

## 7. Waiting for a document

A transaction waits for its document (`spec.md` §6) while:

- its unit is unconfirmed (`spec.md` I20), as in §1;
- its payee has a `document_provider`;
- its original entry has no decided `document`;
- and some instance that is not disabled, provides that provider's documents
  and has a start date (`spec.md` §5.5) not after `booked_on`, has a document
  coverage that has not yet reached `booked_on` plus the document window, the
  upper end of the window in §2. An instance that has never run has no
  coverage and holds the transaction too. With several such instances there
  is no knowing which one would deliver the document, so the transaction
  waits until all of them have reached it.

With no active document source, nothing waits. Waiting holds automatic
confirmation: settling does not confirm a waiting transaction's unit
(`spec.md` §6). For a person it is advisory: a commit with no document picked
decides "no document", keyed `document: user` without a link, once the user
has confirmed skipping the wait; that lets the unit be confirmed and gives up
automatic attachment. When the coverage reaches the end of the window, the waiting ends.

## 8. Picking a document in review

Part of the review draft (`spec.md` §6): the user picks one of the suggestions,
or a document found by hand, or "none of these". The preview shows the enriched
proposals and the split; the commit writes the pick, or "none", as the
original entry's `document`, keyed `user`, replacing an automatic link. A
document arriving after
its charge was confirmed is linked this way, if at all; re-resolving the unit
shows what it would change.

## 9. Transactions a document would match

The reverse of §2, for a document carried by no entry (`spec.md` §5.8):
the non-duplicate transactions on any account whose amount matches the
document by §3 and whose `booked_on` is within the document window of its
`occurred_on`, confirmed or not, and whatever their payee. Computed when
read, never stored, and never used by settling: confirmed transactions are
only ever linked by a person. A transaction that already carries a document
is listed with it, since picking replaces that link.
