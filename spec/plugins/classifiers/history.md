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

A **vote** is a confirmed entry with a source transaction (`spec.md` I19),
booked within the **lookback** of the entry being resolved, and not in the unit
being re-resolved (`spec.md` §5.9), whose transaction carries no document.
Each entry is one vote; the entries of a
split vote separately. The plugin asks core's history source for the votes
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
4. **`booking_text`** — equal, and on the same account.
5. **tokens** — the tokens of `counterparty_name` and `purpose` together: NFKC,
   casefolded, split on anything not alphanumeric, keeping tokens of at least
   **3 characters with no digit**. A vote matches when the Jaccard similarity of
   the two token sets is at least **0.5**. An entry without tokens skips the
   key.

A key whose input the entry lacks — no `counterparty_ref`, no name — is
skipped. History never sees a document: it is not asked for a transaction
with a linked or picked document, and such a transaction never votes
(`spec.md` §5.9), so both sides are always the raw source fields.

## 3. What is counted, per field

For each field, keys are tried in order; the first key whose votes produce a
strict majority wins (`spec.md` §5.9).

- **Type** — every matching vote counts, by its type.
- **Counter-account** — only for a transfer; only paired votes count, and only
  those whose counter-account passes the currency rule and is open on the
  entry's `booked_on` (`spec.md` §5.7, §3.3). The filters remove votes; they
  never change the result.
- **Payee**, then **category** — only for a flow; every matching vote that is a
  flow counts. A vote without a payee votes for *no payee*, which can win; it then
  ends the field — nothing is proposed, and neither a later key nor the model
  is tried (`spec.md` §5.9) — payees are optional (`spec.md` §3.6), so most
  matches carrying none is evidence. Confirmed flows always carry a category.
  Key 3 applies to the category only, and only once the payee is resolved.

*Of how many* is the number of votes counted for that field under that key,
after the filters above — the matches of `spec.md` §5.9.

## 4. Basis

```json
{"matched_on": "counterparty_name+booking_text",
 "agree": 3, "of": 4, "since": "2026-03-02"}
```

`matched_on` is one of `counterparty_ref`, `counterparty_name+booking_text`,
`payee`, `booking_text`, `tokens`; `since` is the earliest booking date among
the votes counted. A counter-account basis adds the proposed `account_id`, as
in `spec.md` §4.

## 5. Tuning parameters

| Parameter | Start | Watch for |
|---|---|---|
| lookback | 365 days, both sides | merchants whose category drifts; seasonal counterparties |
| key 5 similarity | Jaccard ≥ 0.5 | PayPal and card descriptors matching too broadly or not at all |
| key 5 token length | ≥ 3, no digits | reference numbers and dates leaking into tokens |
| strict majority | fixed for now | mixed payees and counterparties (Amazon, a supermarket selling household goods) proposing one category systematically |

A stop list for key 5 (`gmbh`, `sagt`, `danke`, city names) is the expected
first refinement once real purpose lines are seen.
