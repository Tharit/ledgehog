# Classifier: rules (pass 1)

Status: **written ahead, in v1.** How a rule's conditions are compared with an
entry. `spec.md` §5.9 owns what a rule is, what it sets, the order rules are
evaluated in and what their keys mean; `architecture.md` §5.4 the classifier
protocol and how rules reach the plugin. This document covers only matching.

---

## 1. Input

The entry's input as resolution sees it (`spec.md` §5.9): its source
transaction and, where one is linked or picked, its document — the merchant
name standing in for the counterparty name, the line descriptions added to the
purpose (`spec.md` §5.8). That input is built when resolving and never
stored; the source row is not changed. Plus the payee already resolved for the
entry, for category rules. The rules arrive from core, whole; the plugin never
reads the database.

**Which rules decide the type** (`spec.md` §5.9): counter-account rules,
payee rules, and category rules without a payee condition — the rules that can
be judged before the payee is. A category rule with a payee condition never
decides the type; it applies in the category field, on whatever payee was
resolved, a proposed one included. Its value is then standing, and is derived
again if that payee changes (`spec.md` I18).

A user-authored row carries only a purpose (`spec.md` §5.9), so only purpose
and payee conditions can hold for it.

## 2. Conditions

All of a rule's conditions must hold; a condition on a field the entry lacks
does not hold. Each is compared as follows.

| Condition | Compared with | How |
|---|---|---|
| `counterparty_ref` | `counterparty_ref` | equal after the canonicalisation of `spec.md` §5.2 (NFKC, casefolded, alphanumerics only), both sides |
| `mandate_ref` | `mandate_ref` | likewise |
| `booking_text` | `booking_text` | likewise |
| `name_exact` | counterparty name, or the linked document's merchant name | equal after **name normalisation** (below) |
| `name_prefix` | the same | the normalised name starts with the normalised prefix |
| `purpose_regex` | purpose, with a linked document's line descriptions appended, one per line | Python `re`, case-insensitive, `search` — unanchored unless the pattern anchors itself |
| `condition_payee_id` | the payee resolved earlier in the same resolution | equal (category rules only) |

**Name normalisation** is NFKC, casefolded, runs of whitespace collapsed to
one space, trimmed. Punctuation is kept, so the typical card-descriptor rule
`name_prefix 'PAYPAL *'` matches `PAYPAL *SEEEDDEVELO` but not
`PayPal Europe S.a.r.l.` — canonicalising names to alphanumerics, as references
are, would merge the two.

References and booking texts are canonicalised fully because they are codes:
an IBAN with or without spaces is one IBAN.

## 3. Validation on save

A rule is refused when its regex does not compile, or when every condition is
empty (also a schema CHECK). Conditions are stored as the user typed them;
normalisation happens when comparing, so changing it is a code change, not a
migration.

## 4. Basis

`{"rule_id": <id>}`, as in `spec.md` §4. Nothing else is recorded: the rule
row says what it matched on.

## 5. Tuning parameters

None. Rules are declarations; if one matches too much, the user narrows it,
seeing in its preview what it would match (`spec.md` §5.9).
