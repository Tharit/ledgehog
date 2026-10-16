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
- its original entry has a payee with a `document_provider` (`spec.md` §3.6);
  the original entry's payee alone decides, since it carries the link, whatever
  the payee of the other entries of a split;
- its original entry has no decided `document`: neither a link nor a user's
  "none";
- it is not typed as a transfer (`spec.md` §5.8): a document explains a flow.

Eligibility is judged on the transaction as resolved without a document. The
link comes first in field order (`spec.md` §5.9), so a payee that a rule on
the document resolves differently — the real merchant instead of PayPal — does
not undo it: a linked transaction is no longer considered at all.

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
                         of one line, matcher_proposal for one of several;
                         for a document of one line, in the same write set
                         the entry's document_line_id to that line
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
and the commit makes the key `user`, with or without the split. The draft
knows only the stored link: a link settling has yet to make is shown in the
preview but written by settling after the commit, and only a stored
`matcher_proposal` becomes `user` on a commit. A link to a
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

## 5. The document as an input

A linked or picked document adds two fields to its transaction's entries, which
rules read (`spec.md` §5.9): `document_merchant`, the merchant name, and
`document_line`, the description of the entry's own line. The source row is not
rewritten: `counterparty_name`, `purpose` and the other source fields are the
bank's. A rule keyed on a card descriptor such as `PAYPAL *` therefore matches
before and after the link. Its payee, the provider, stays the payee of every
merchant the user has not curated; to make a merchant the payee, the user
writes a rule on `document_merchant`, ordered before the descriptor rule.

An entry's line is the line it references (`document_line_id`). Applying a
document's lines is one operation, whatever their number: for a document of one
line, the original entry takes it in the same write as the link, by settling
(§4) or a commit (§8), and nothing is split; for a document of several, the
split along the lines (§6) gives each entry it makes its line, the original the
first. Every other entry — an unsplit transaction of a document of several
lines, a split made by hand — has no line, and a condition on `document_line`
fails: a line matched there would be any one of the order's items, for all of
them. The write that changes the link sets or clears the original entry's
reference with it; a reference is read only while its line belongs to the
transaction's document, and a changed document's lines are replaced, which
clears it.

Linking is a change of the first value in field order, so every standing value
after it is derived again (`spec.md` §5.9), the link itself staying. A change
to the linked document's total, currency, merchant or lines resolves the
transaction afresh in the same way. Rules and the model run on these inputs;
history asks one key, the merchant, for the category only (`history.md`).

## 6. Splitting along the lines

The review panel proposes splitting a linked transaction along the
document's lines, whether its unit is confirmed or not, (`spec.md` §5.8). The split is draft state until the commit
writes it; only a commit splits (`spec.md` I7). The proposal is:

- one entry per line, with the line's amount — converted proportionally to the
  transaction's amount where the document is in the instructed currency,
  rounded half-even;
- the original entry takes the first line and the remainder — shipping,
  discounts, rounding — so it is never zero when the lines add up exactly;
  the commit writes `document_line_id` on each entry it creates, the original's
  being the first line it carries; the panel shows the description of an
  entry's line on its row;
- no split for a document of one line, where the document's total does not
  match the transaction exactly by §3, or where the original entry's share
  would be zero or change sign; the link stands, unsplit.

The proposal is made only for a transaction that is not split, and only
from a stored link or a pick. An existing
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

With no active document source, nothing waits. Which instance provides a
provider is learned from a registry the composition root configures, never by
core importing a plugin; the instance's start date is its setting `start_date`
(`spec.md` §5.5). **The waiting flag wins:** a waiting unit is in the queue's
waiting section even while it has suggestions, since what it waits for may
change the user's other decisions. The queue's line reads "Waiting for a
document from <provider>, covered through <date>", or "…, not synced yet" where
no instance has run. Waiting holds automatic
confirmation: settling does not confirm a waiting transaction's unit
(`spec.md` §6). For a person it is advisory: a commit with no document picked
decides "no document", keyed `document: user` without a link; the server
refuses a commit that leaves this unsaid while documents are suggested or one is
awaited (422 `document_decision_required`), so skipping the wait is a conscious
choice, and the panel offers it as "Commit without a document". That lets the unit be confirmed and gives up
automatic attachment. A data migration records the same "none" on every unit
confirmed before documents existed, so a source added later cannot reopen them
(`spec.md` I20). When the coverage reaches the end of the window, the waiting ends.

## 8. Picking a document in review

Part of the review draft (`spec.md` §6): the user picks one of the suggestions,
or a document found by hand, or "none of these". The preview shows the values
resolved with the document and the split; the commit writes the pick, or
"none", as the original entry's `document`, keyed `user`, replacing an
automatic link; the pick of a document of one line writes the line with it. A
suggestion is no decision: where documents are suggested or one is awaited, a
commit with neither a pick nor "none" is refused by the server. A
document arriving after
its charge was confirmed is linked this way, if at all; re-resolving the unit
shows what it would change.

## 9. Transactions a document would match

The reverse of §2, for a document carried by no entry (`spec.md` §5.8):
the non-duplicate transactions on any account, not typed as a transfer, whose
amount matches the document by §3 and whose `booked_on` is within the document window of its
`occurred_on`, confirmed or not, and whatever their payee. Computed when
read, never stored, and never used by settling: confirmed transactions are
only ever linked by a person. A transaction that already carries a document
is listed with it, since picking replaces that link.
