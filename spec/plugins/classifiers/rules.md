# Classifier: rules (pass 1)

Status: **written ahead, in v1.** How a rule's conditions are compared with an
entry. `spec.md` §5.9 owns what a rule is, what it sets, the order rules are
evaluated in and what their keys mean; `architecture.md` §5.4 the classifier
protocol and how rules reach the plugin. This document covers only matching.

---

## 1. Input

The entry's input as resolution sees it (`spec.md` §5.9): its account, its
source transaction's fields as stored, and its own source text, where it has
one. That input is built when resolving and never stored. Plus the payee
already resolved for the entry, for category rules. The rules arrive from core, whole; the plugin never
reads the database.

**Which rules decide the type** (`spec.md` §5.9): counter-account rules,
payee rules, and category rules that have no payee condition — the rules that can
be judged before the payee is. A category rule that has a payee condition never
decides the type; it applies in the category field, on whatever payee was
resolved, a proposed one included. Its value is then standing, and is derived
again if that payee changes (`spec.md` I18).

A user-authored row carries only a purpose (`spec.md` §5.9), so only purpose,
account and payee conditions can hold for it. A booking carries only a
purpose and, booked from a document, a counterparty name (`spec.md` §5.8): for
its entries only counterparty-name, purpose, source-text, account and payee
conditions can hold.

## 2. Conditions

A rule holds a list of conditions, all of which must hold (an implicit AND),
including, for a category rule, payee conditions. A condition is `{field, op, value}`. The format leaves room for
grouping and negation later without a schema change; neither exists now.

A condition on a field the entry lacks fails. The same field may appear in
several conditions.

| Field | Read from |
|---|---|
| `counterparty_name` | the counterparty name |
| `counterparty_ref` | `counterparty_ref` |
| `purpose` | the purpose |
| `booking_text` | `booking_text` |
| `mandate_ref` | `mandate_ref` |
| `source_text` | the entry's own source text (`spec.md` §5.9); fails for an entry without one |
| `account` | the entry's account; the value is the account id as a digit string |
| `payee` | the payee resolved so far in the same resolution, a proposed one included; the value is the payee id as a digit string (category rules only) |

`account` and `payee` take the operator `is` only (equal ids); every other
field takes the four operators `equals`, `starts_with`, `contains` and
`regex`. A payee or account condition whose payee or account has been deleted
never matches.

| Fields | Comparison of `equals`, `starts_with`, `contains` |
|---|---|
| `counterparty_ref`, `mandate_ref` | both sides as canonical text (`spec.md` §5.2: NFKC, casefolded, alphanumerics only), so an IBAN prefix works |
| `counterparty_name`, `purpose`, `booking_text`, `source_text` | both sides by **name normalisation** (below) |

`regex` is Python `re`, case-insensitive, `search` — unanchored unless the
pattern anchors itself — on the raw value of any field.

**Name normalisation** is NFKC, casefolded, runs of whitespace collapsed to
one space, trimmed. Punctuation is kept, so the typical card-descriptor rule
`counterparty_name starts_with 'PAYPAL *'` matches `PAYPAL *SEEEDDEVELO` but not
`PayPal Europe S.a.r.l.` — canonicalising names to alphanumerics, as references
are, would merge the two.

References are canonicalised fully because they are codes: an IBAN with or
without spaces is one IBAN.

## 3. Validation on save

A rule is refused when a condition names a field or an operator the plugin
does not know, when a `regex` value is longer than 200 characters or does not
compile (on any field), when a condition's value is blank, when a `payee` condition's operator is not
`is`, its value is not a positive integer id, or its rule does not set a
category, when it has no condition (also a schema CHECK), or when its name is
blank or already used (case-insensitively; also a schema CHECK and unique
index). That a payee exists is checked at write time by core, not by the plugin. A message names the field and never quotes the value. Conditions are
stored as the user typed them; normalisation happens when comparing, so
changing it is a code change, not a migration.

## 4. Basis

`{"rule_id": <id>}`, as in `spec.md` §4. Nothing else is recorded: the rule
row says what it matched on.

## 5. Tuning parameters

None. Rules are declarations; if one matches too much, the user narrows it,
seeing in its preview what it would match (`spec.md` §5.9).
