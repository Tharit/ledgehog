# Classifier: history (pass 2)

Status: **written ahead, in v1; expected to churn.** A tuning document: the
starting definitions below are guesses to be adjusted against a month of real
data. `spec.md` §5.9 owns what history learns from (I19), its keys and their
order, the strict-majority rule and the hard filters on counter-account
evidence; `architecture.md` §5.4 the protocol and the read-only history source
core provides. This document covers what counts as a match for each key, what
is counted, and the parameters.

---

## 1. Votes

A **vote** is a confirmed entry with a source transaction that is not a booking
(`spec.md` I19; a booking follows its source, whose own decision is the vote,
§5.8), booked within the **lookback** of the entry being resolved, and not in the unit
being re-resolved (`spec.md` §5.9). An entry with a source text votes only
for keys 3 and 5 (§2), and only an entry with one votes for key 5. Each
entry is one vote; the entries of a split vote separately. The plugin asks core's history source for the votes
matching a key value and never reads the database itself.

The lookback is symmetric — confirmed entries booked within it on either side
of the entry's `booked_on` — so a backfilled year learns from the
confirmations that came after it, not only before.

## 2. What matches, per key

Text is canonicalised as in `spec.md` §5.2 (NFKC, casefolded, alphanumerics
only) unless said otherwise.

1. **`counterparty_ref`** — equal. Where the entry has a `mandate_ref`, votes
   with a different one are left out; votes without one still count.
2. **`counterparty_name` + `booking_text`** — names equal. Where the entry has
   a booking text, votes with a different one are left out; votes without one
   still count.
3. **`payee_id`** — equal; for the category only (`spec.md` §5.9).
4. **tokens** — the tokens of `counterparty_name` and `purpose` together: NFKC,
   casefolded, split on anything not alphanumeric, keeping tokens of at least
   **3 characters with no digit**. A vote matches when the Jaccard similarity of
   the two token sets is at least **0.5**. An entry without tokens skips the
   key.
5. **`source_text`** — canonical equality of the entry's source text
   (`spec.md` §5.9): an order's item, say, booked as an entry of its own; for
   the payee and the category (such an entry's type is fixed). For an entry
   that has a source text it is asked first, then key 3; such an entry is
   neither asked nor counted on keys 1, 2 and 4. An entry without a source
   text never sees it.

A key whose input the entry lacks — no `counterparty_ref`, no name — is
skipped. Keys 1, 2 and 4 read the raw source fields on both sides and never
see an entry with a source text; key 5 reads the source text only.

## 3. What is counted, per field

For each field, keys are tried in order; the first key whose votes produce a
strict majority wins (`spec.md` §5.9).

- **Type** — every matching vote counts, by its type.
- **Counter-account** — only for a transfer; only paired votes count, and only
  those whose counter-account passes the currency rule and is open on the
  entry's `booked_on` (`spec.md` §5.7, §3.3). The filters remove votes; they
  never change the result.
- **Payee**, then **category** — only for a flow; every matching vote that is a
  flow counts. A vote without a payee votes for *no payee*, which can win: an empty result,
  which ends the search and stores nothing (`spec.md` §5.9) — payees are optional (`spec.md` §3.6), so most matches carrying
  none is evidence. Confirmed flows always carry a category.
  Key 3 applies to the category only, and only once the payee is resolved;
  for an entry with a source text it is tried after key 5.

*Of how many* is the number of votes counted for that field under that key,
after the filters above — the matches of `spec.md` §5.9.

## 4. Basis

```json
{"matched_on": "counterparty_name+booking_text",
 "agree": 3, "of": 4, "since": "2026-03-02"}
```

`matched_on` is one of `counterparty_ref`, `counterparty_name+booking_text`,
`payee`, `tokens`, `source_text`; `since` is the earliest booking date among
the votes counted. A counter-account basis adds the proposed `account_id`, as
in `spec.md` §4.

## 5. Tuning parameters

| Parameter | Start | Watch for |
|---|---|---|
| lookback | 365 days, both sides | merchants whose category drifts; seasonal counterparties |
| key 4 similarity | Jaccard ≥ 0.5 | PayPal and card descriptors matching too broadly or not at all |
| key 4 token length | ≥ 3, no digits | reference numbers and dates leaking into tokens |
| strict majority | fixed for now | mixed payees and counterparties (Amazon, a supermarket selling household goods) proposing one category systematically |

A stop list for key 4 (`gmbh`, `sagt`, `danke`, city names) is the expected
first refinement once real purpose lines are seen.

**Key 5 is exact on purpose.** It captures reorders (the same capsules, the
same filter) with certainty and misses a reworded title safely. Similarity
over source text stays out: titles rarely repeat, and shared filler words
would propose on weak evidence ahead of the model. Whether key 3 after it
proposes a mixed payee's majority category for every new item (an Amazon
payee on a clearance account) is to be watched in the first month.
