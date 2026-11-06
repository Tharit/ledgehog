# Household ledger — bookings from documents

Status: **written ahead, in v1** — exercised with a test document importer
and the email importer. How a document — an order, a receipt — is booked onto
a clearance account: which documents are booked, on which account, the
entries a booking is made of and their amounts, how a booking follows its
document, and why a document is not booked. `spec.md` owns the domain this
relies on — documents and what a document importer delivers (§5.5), the
clearance account and its providers (§3.3), the booking as the third author
of source transactions (§5.6), what settling maintains and when (§5.8), the
entry's source text and resolution (§5.9) and review (§6) — and states what
the core requires of bookings. This document covers only how documents meet
those requirements.

---

## 1. Where a document is booked

A document is booked onto **the clearance account that takes its provider in
its currency** (`spec.md` §3.3): the account whose list of providers holds the
document's provider, compared without regard to case, and whose currency is
the document's. A provider is taken by at most one account per currency, so
at most one account qualifies. A booking never converts: a document in
another currency than the account that takes its provider is not booked
there.

A document not yet booked is booked when such an account exists, its total
is not 0, and it is dated after the account's **start** — the date of the
account's earliest balance record, the opening its create form writes
(`spec.md` §3.3, §3.10). Otherwise it is **not booked**, for the first of
these reasons that applies:

| Reason | When |
|---|---|
| total 0 | its total is 0 — an order paid entirely with vouchers or store credit, or a refund made entirely to store credit: nothing to clear, and an entry of 0 cannot exist |
| no account | no clearance account takes its provider in its currency: none takes the provider, or only in another currency |
| no start | the account that takes it has no balance record |
| before the start | it is dated on or before the account's start |

Each reason names what it needs — the provider and the currency, or the
account and its start — so that the reason says what to do ("no account
takes Amazon in USD").

**A document stays booked where it was booked**, as long as its total is not
0 and its currency is its account's. The provider lists and the start decide only where a document not yet
booked goes: adding a provider to an account books its documents dated after
the start; removing a provider, or moving it to another account, leaves
existing bookings where they are, and documents not yet booked follow the new
lists; an earlier start books the documents it now covers, a later one
removes none. A booked document whose total becomes 0, or whose currency
changes, loses its booking (§4).

## 2. The entries of a booking

The booking itself — a source transaction of origin `booking` on the
account, `source_id` `document:<id>`, dated on the document's `occurred_on`,
for its total, with the provider as its counterparty name and "Order
*reference*" ("Refund *reference*" for a positive total), or the word alone
where the document has no reference, as its purpose —
is `spec.md` §5.6 and §5.8's. It is made with **one entry per
line**, each carrying the line's description as its source text
(`spec.md` §5.9), and amounts that sum to the total:

```
entries(d), for a document d of total T ≠ 0, in minor units:
  lines   = d's lines in line order, lines of amount 0 dropped
  S       = the lines of T's sign; O = the lines of the opposite sign
  if S is empty:
      one entry of amount T, with no source text
  else:
      each line of O: one entry of its own amount, as listed
      T_S   = T − (sum of O)
      each line i of S: one entry of round_half_even(a_i × T_S / sum of S)
      the remainder, T_S − (sum of those entries), is added to the
          largest entry of S — by the line's magnitude, the earlier line
          on a tie
      repeatedly, until none is left: an entry of 0, or of the sign
          opposite to T, among those of S merges into the largest other
          entry of S (as above) — its amount is added there, and its line
          gets no entry
```

The unitemised amount — what the lines leave of the total: a discount the
receipt does not itemise, shipping, a fee or tax left out — is therefore
spread over the lines of the total's sign, in proportion. Lines of the
opposite sign, a listed coupon or credit, stay as listed. T_S has T's sign
and is at least as large as T, so every share keeps its line's sign before
rounding; the merge step only absorbs rounding, and ends because the entries
of S sum to T_S. A line of 0 and a line merged away have no entry: a booking
has as many entries as it has **entry lines**, the lines that got one, in
line order.

The **original entry** of a booking (`spec.md` §3.1) is its first, the entry
of its first entry line. With no line of the total's sign there is one entry
and no source text: its inputs are its account alone.

**A booking entry is a flow**, under a standing key; converting it to a
transfer is refused, and it is never a transfer offer or candidate
(`spec.md` §5.7, §5.8). Its other values are resolved like any entry's, from
its account and its source text (`spec.md` §5.9), and reviewed as usual. Its
`description` stays empty, the user's to fill; the row shows the source text.
**Its split is the document's**: the user does not split, merge or
reallocate a booking's entries. A share the spread got wrong is corrected
by an entry on the account, entered by hand (`spec.md` §3.3).

## 3. A booking follows its document

A booking follows its document (`spec.md` §5.8, I20): when what it is made
from changes — the document's total, date or lines — the next settling
re-derives it, confirmed or not. Re-derivation computes the entries afresh
(§2) and matches them to the stored ones **by position**: the k-th stored
entry, in the booking's order, takes the k-th entry line of the new
computation.

- An entry that keeps its position keeps its id, its values, its keys and
  its tags. It takes the new amount, and the new source text; where the
  source text changed, that is a change of input, and the entry resolves
  afresh (`spec.md` §5.9).
- A position the new computation no longer has deletes its entry, a
  consequence with its tags (`spec.md` §5.6). The original entry, the first,
  is never deleted while the booking exists.
- A new position gets a new entry, resolved like any new entry.
- The booking's date, amount and purpose follow the document's.

An amount is not an input (`spec.md` §5.9): an entry whose source text stays
keeps its values and its review state, whatever its new amount. The user's
decisions on unchanged lines therefore stay, and only what the document
changed returns to review, as new data.

**Matching by position has a cost.** A line removed or inserted before the
last shifts every later entry onto another line: those entries take another
source text, resolve afresh, and their decisions return to review. Matching
by text instead would need a rule for repeated and reworded items; positions
are exact, and the shift is the price of that.

How often a document changes is its importer's re-delivery mode
(`spec.md` §5.5): only an importer that declares `replace` changes a stored
document, and with it a booking — so only there does the cost above arise;
one that declares `keep` never does. A document whose total becomes 0, or
whose currency is no longer its account's, loses its booking: the source
transaction and its entries are removed, as consequences (`spec.md` §5.6).

## 4. What settling does

The booking step of settling (`spec.md` §5.8) books every document §1 says
is to be booked and is not, re-derives every booking whose document changed
(§3), and removes every booking whose document now has a total of 0 or
another currency than its account. It
writes only bookings, on clearance accounts, and is idempotent: a document
has at most one booking, by its `source_id`. Nothing else books a document —
neither its ingest nor a change of an account's providers or start, which
mark it for settling.

The charges that pay a clearance account are transfers to it; their
counter-legs are bookings too, made from the charge (`spec.md` §5.7), and
nothing here applies to them.
