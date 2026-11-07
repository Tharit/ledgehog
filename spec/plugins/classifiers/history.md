# Classifier: history (pass 2)

Status: **written ahead, in v1; expected to churn.** A tuning document: the
starting definitions below are guesses to be adjusted against a month of real
data. `spec.md` §5.9 owns what history learns from (I19), its keys and their
order, the purpose refinement, the strict-majority rule and when history
gives way to the model, and the hard filters on counter-account evidence; `architecture.md` §5.4 the protocol and the read-only history source
core provides. This document covers what counts as a match for each key, what
is counted, and the parameters.

---

## 1. Votes

A **vote** is a confirmed entry with a source transaction (`spec.md` I19)
that is not a booking, booked within the **lookback** of the entry being
resolved, and not in the unit being re-resolved (`spec.md` §5.9). **Booking
entries take no part in history** (`spec.md` §5.8): they neither vote nor are
asked. Each entry is one vote; the entries of a split vote separately. The
plugin asks core's history source for the votes matching a key value and
never reads the database itself.

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

A key whose input the entry lacks — no `counterparty_ref`, no name — is
skipped. All keys read the raw source fields on both sides.

**Similar purpose.** A key's matches are first narrowed to those whose purpose
resembles the entry's: the tokens of each purpose — NFKC, casefolded, split on
anything not alphanumeric, keeping tokens of at least **3 characters with no
digit** — have a Jaccard similarity of at least **0.5**. An entry whose purpose
has no tokens skips the narrowing; a vote whose purpose has none is not
similar. The counterparty name is left out: the key has already matched the
counterparty, and its words would make every match look similar.

## 3. What is counted, per field

For each field, keys are tried in order, each first on its similar-purpose
matches and then on all its matches; the first set of matches that produces a
strict majority wins (`spec.md` §5.9). On the category, the proposal is
history's only when that set is unanimous; otherwise it gives way to the model
(`spec.md` §5.9, pass 3).

- **Type** — every matching vote counts, by its type.
- **Counter-account** — only for a transfer; only paired votes count, and only
  those whose counter-account passes the currency rule and is open on the
  entry's `booked_on` (`spec.md` §5.7, §3.3). The filters remove votes; they
  never change the result.
- **Payee**, then **category** — only for a flow; every matching vote that is a
  flow counts. A vote without a payee votes for *no payee*, which can win: an empty result,
  which ends the search and stores nothing (`spec.md` §5.9) — payees are optional (`spec.md` §3.6), so most matches carrying
  none is evidence. Confirmed flows always carry a category.
  Key 3 applies to the category only, and only once the payee is resolved.

*Of how many* is the number of votes counted for that field in that set,
after the filters above — the matches of `spec.md` §5.9.

**What the model is told.** Where history counted votes for the category, the
model's payload carries their categories: all the matches of the first key that
has any, not only the similar ones; the three most frequent, ties broken by
path, sent in path order. Neither counts nor the text of past entries are sent:
counts change with each confirmation, and every change would ask the model
again for each unconfirmed entry of the counterparty.

## 4. Basis

```json
{"matched_on": "counterparty_name+booking_text",
 "agree": 3, "of": 4, "since": "2026-03-02"}
```

`matched_on` is one of `counterparty_ref`, `counterparty_name+booking_text`,
`payee`, each with `+purpose` appended where the similar-purpose matches
decided; `since` is the earliest booking date among
the votes counted. A counter-account basis adds the proposed `account_id`, as
in `spec.md` §4.

## 5. Tuning parameters

| Parameter | Start | Watch for |
|---|---|---|
| lookback | 365 days, both sides | merchants whose category drifts; seasonal counterparties |
| purpose similarity | Jaccard ≥ 0.5 | one counterparty's purposes told apart too finely, or not at all (an intermediary's boilerplate) |
| purpose token length | ≥ 3, no digits | reference numbers and dates leaking into tokens; stable numbers (customer, contract) lost where they are the only thing telling a counterparty's purposes apart |
| strict majority; unanimity on the category | fixed for now | model calls for counterparties mixed only by one old outlier |

**No key on item texts.** Booking entries — an order's items — stay out of
history (§1): item titles rarely repeat exactly, and tokens over them are
mostly noise that would propose on weak evidence ahead of the model. Rules on
the source text and the model classify them.
