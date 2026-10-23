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
- its amount is not zero: a zero-amount booking explains nothing;
- its unit is unconfirmed (`spec.md` I20);
- its original entry has a payee with a `document_provider` (`spec.md` §3.6);
  the original entry's payee alone decides, since it carries the link, whatever
  the payee of the other entries of a split;
- its original entry has no decided `document`: neither a link nor a user's
  "none";
- none of its entries is a transfer (`spec.md` §5.8): a document explains a flow.

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
      for which a line allocation exists over the document's carriers and t
          (§3),
      and whose occurred_on is within the document window of booked_on
          (spec.md §5.8): [booked_on − back, booked_on + ahead]
```

The window is asymmetric: `back` and `ahead` are two ledger-wide settings, by
default 60 and 7 days. A document carried by a confirmed transaction is a
candidate too; it is only suggested (§4).

## 3. Amounts match exactly, with their sign, in the document's currency

A **line allocation** of a document over a set of transactions assigns each of
its lines to at most one of them, so that the lines assigned to a transaction
sum exactly to its amount — except that a single transaction whose amount
equals the document's total takes every line, however they sum (a
whole-document match). Lines assigned to none are not yet charged. A line
allocation **keeps** the committed references when it assigns every line that
an entry references (`spec.md` I35) to that entry's transaction. Where the
document's currency is the transaction's, the transaction's amount is the one
compared; where it is the transaction's instructed currency, the instructed
amount (`spec.md` §3.8); otherwise there is no candidate. The tolerance is
zero, no rate is ever involved, and a refund can only match a refund document.
The amounts of a document's carriers **reach** its total when their sum equals
it, and **fall short** of it when their sum is smaller in magnitude.

- A **whole-document match** is possible for any document, including one whose
  lines do not sum to its total; the original entry then takes the difference
  (§6).
- A **partial match** — a transaction taking some of the lines — is possible
  only for a document whose lines sum exactly to its total and has at most 20
  lines, a fixed limit that bounds the search.

## 4. What settling writes

```
for each document d that is a candidate of a considered transaction:
    let S be the considered transactions of which d is a candidate
    if d is the only candidate of every t in S,
       a line allocation keeping the committed references exists over d's
           carriers and S together,
       and no carrier of d is confirmed
                       → for each t in S, set document_id = d on t's original
                         entry, keyed document with pass matcher_decision for
                         a document of one line, matcher_proposal for one of
                         several; for a document of one line, in the same
                         write set the entry's document_line_id to that line
    otherwise          → write nothing; d is a suggestion to each t in S,
                         computed when read
```

**Automatic linking needs uniqueness both ways.** Two identical charges from
one provider within the window may see the same single document; no line
allocation exists over both, so neither gets it automatically. Both are
offered it as a suggestion. For a single transaction taking every line, this
is the one-to-one rule: t has exactly one candidate d, and d is a candidate of
no other transaction. The unique index on a line's reference (`spec.md` I35)
makes a racing second claim of one line fail rather than double it.

**A document with a confirmed carrier is only suggested.** Settling links into
no document one of whose carriers is confirmed (`spec.md` I20). A pick (§8)
links it.

**The line allocation is derived, never stored.** It is computed when read,
from the links, the amounts and the line references that committed splits
wrote. The proposal is built line by line, in line order, each line going to
the earliest carrier — by `booked_on`, then id — that still leaves a line
allocation keeping the committed references; where none keeps them, the same
without that condition. It is shown as a proposal and reviewed. Settling
links only on a line allocation that keeps the committed references;
candidates (§2), suggestions and the reverse list (§9) need only some line
allocation, whether it keeps them or not. Where the proposal moves lines a
committed split references, the draft proposes that split's replacement (§6).
A line folded into a remainder (§6) or a carrier committed without a split
needs no reference, because the derivation assigns it. Where a document's
carriers admit no line allocation — a pick by hand, a changed document whose
confirmed carriers keep their links — every link stands and no split is
proposed.

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
other charges left no line allocation — simply disappears, and the
`document_suggested` flag (`spec.md` §6) follows.

**The link has two writers**, like any derived field: settling, writing a
matcher link as above, and a commit, writing the user's pick or "none" as
`user` (`spec.md` §6). Beyond them, only a change of input touches it: a
changed document's ingest resolves each of its unconfirmed carriers afresh,
dropping the link for settling to make again (`spec.md` §5.5, §5.9); an
entry that is removed — its transaction marked as a duplicate or reverted, a
user-authored transaction deleted — ends its transaction's carrying of the
document and frees its lines (`spec.md` §5.6).

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
split along the lines (§6) gives each entry it makes one of the lines of the
document's sign that the line allocation gives its transaction, the original
the first. Every other entry — an unsplit carrier of a document of several
lines, until a commit gives it one, a split made by hand — has no line, and a
condition on `document_line` fails: a line matched there would be any one of
the order's items, for all of them. The write that changes the link sets or
clears the original entry's reference with it; a reference is read only while
its line belongs to the transaction's document, and a changed document's lines
are replaced, which clears it.

Linking is a change of the first value in field order, so every standing value
after it is derived again (`spec.md` §5.9), the link itself staying. A change
to the linked document's total, currency, merchant or lines resolves each of its
unconfirmed carriers afresh in the same way. Rules and the model run on these
inputs; history asks one key, the merchant, for the category only, and not for
an entry with a line (`history.md`).

**An entry with a line is classified from its line.** Its model input is the
document's merchant and the line's description, without the charge's own text,
and the answer belongs to the line, not to the entry; every other entry is
asked about itself (`spec.md` §5.9). Ingest asks for every line of a new or
changed document, and the answer is stored on the line, with the payload's
fingerprint, which keeps it across a re-fetch that leaves the line's payload
unchanged (`spec.md` §5.5). Resolution reads it at pass 3's place: for an
entry with a line, where passes 0 and 1 produce no category (history asks it
no key), pass 3 takes the line's stored answer instead of asking; where the
line has no answer for its payload yet, the line is asked, not the entry. It
is a proposal shown with its rationale, never confirming (`spec.md` §5.9).
"Ask again" in the panel asks the line anew.

## 6. Splitting along the lines

The review panel proposes splitting each carrier of a linked document along the
document's lines while any of the document's links is not yet the user's — a
matcher link, or a pick in the draft (`spec.md` §5.8); once every link is the
user's, nothing is proposed, and re-resolving shows what would change. The
split is draft state until the commit writes it; only a commit splits
(`spec.md` I7). The proposal for a carrier is:

- one entry per line of the document's sign that the line allocation (§4)
  gives the transaction, with the line's amount — converted proportionally to
  the transaction's amount where the document is in the instructed currency,
  rounded half-even;
- the original entry takes the first of those lines and the remainder —
  shipping, discounts, rounding, and every line of the opposite sign that the
  line allocation gives it, a coupon or a credit — so it is never zero when
  the lines add up exactly; the commit writes `document_line_id` on each entry
  it creates, the original's being the first line it carries; the panel shows
  the description of an entry's line on its row;
- no split for a document of one line, where the document's carriers admit no
  line allocation (§4), or where the original entry's share would be zero or
  change sign; the link stands, unsplit.

The proposal replaces whatever split a carrier has, a split made by hand or
one the line allocation moves included; the entries it replaces and their
tags are listed as consequences. The user accepts it by committing, or changes
it like any split, removing its rows included. A replaced split and the split
of the charge that takes its lines are written by one commit. Once every link
is the user's, *split along the lines* stays available as an explicit choice
(`spec.md` §6). Picking another document in the draft regenerates the
proposals. Once committed, the split is the user's like any other. Settling
never creates or removes an entry for a document.

## 7. Waiting for a document

A transaction waits for its document (`spec.md` §6) while:

- its unit is unconfirmed (`spec.md` I20), as in §1;
- its payee has a `document_provider`;
- its original entry has no decided `document`;
- and some instance that is not disabled, provides that provider's documents
  and has a start date (`spec.md` §5.5) not after `booked_on`, has a
  document coverage that has not yet reached `booked_on` plus `ahead`, the
  upper end of the window in §2. An instance that has never run has no
  coverage and holds the transaction too. With several such instances there
  is no knowing which one would deliver the document, so the transaction
  waits until all of them have reached it.

With no active document source, nothing waits for a document. Whether an
instance provides a provider is asked of its importer through a registry the
composition root configures, never by core importing a plugin — an importer
built for fixed providers answers for those, one that reads receipts of any
provider from the instance's settings; the instance's start date is its
setting `start_date` (`spec.md` §5.5). **The waiting flag wins:** a waiting
unit is in the queue's waiting section even while it has suggestions, since
what it waits for may change the user's other decisions. The queue's line
reads "Waiting for a document from <provider>, covered through <date>", or
"…, not synced yet" where no instance has run. Waiting for a document holds
automatic confirmation: settling does not confirm a waiting transaction's unit
(`spec.md` §6). For a person it is advisory: a commit with no document picked
decides "no document", keyed `document: user` without a link; the server
refuses a commit that leaves this unsaid while documents are suggested or one is
awaited (422 `document_decision_required`), so skipping the wait is a conscious
choice, and the panel offers it as "Commit without a document". That lets the unit be confirmed and gives up
automatic attachment. A data migration records the same "none" on every unit
confirmed before documents existed, so a source added later cannot reopen them
(`spec.md` I20). When the coverage reaches the end of the window, the waiting ends.

**A transaction waits for the rest of its order** while its original entry
carries a document with a matcher key and the amounts of the document's
carriers (in the document's currency, §3) fall short of its total, until the
`synced_through` of every synced account (`spec.md` §5.4) has reached the
document's `occurred_on` plus `back`; a synced account never fetched holds it
too. The queue's line reads "Waiting for the rest of order <external id> from
<provider>: <amount> of <total> not yet charged". The wait holds no automatic
confirmation of its own, and skipping it needs no confirmation: a commit makes
the link `user`, which ends the wait and keeps the link. The server adds no
refusal.

## 8. Picking a document in review

Part of the review draft (`spec.md` §6): the user picks one of the suggestions,
or a document found by hand, or "none of these". Picking a document for a
transaction brings the document's other carriers into the draft's unit
(`spec.md` I21), a confirmed carrier included, its split proposed with the
others (§6); deciding "none" for a carrier takes it out of the unit, and the
document's other carriers stay. The preview shows the values resolved with
the document and the split of each carrier; the commit writes each carrier's
link — a pick, or the matcher link it accepts — or "none", as its original
entry's `document`, keyed `user`, replacing an automatic link; the pick of a
document of one line writes the line with it. A suggestion is no decision:
where documents are suggested or one is awaited, a commit with neither a pick
nor "none" is refused by the server. A document arriving after its charge was
confirmed, or a further charge of an order, is linked this way, if at all;
re-resolving the unit shows what it would change.


## 9. Transactions a document would match

The reverse of §2, for a document not fully charged — carried by no entry, or
by transactions whose amounts fall short of its total (§3, `spec.md` §5.8):
the non-duplicate transactions on any account, with no transfer entry, other
than its carriers, for which a line allocation exists over the document's
carriers and the transaction (§3) and whose `booked_on` is within the document
window of its `occurred_on`: [`occurred_on − ahead`, `occurred_on + back`],
confirmed or not, and whatever their payee. Computed when read, never stored,
and never used by settling: confirmed transactions are only ever linked by a
person. A transaction that already carries a document is listed with it,
since picking replaces that link.
