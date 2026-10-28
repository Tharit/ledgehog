# Documents — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §5.5 and §5.8 and
`features/documents.md`; the contracts are `architecture.md` §4.1.

---

**A list of documents, in the shape of the ledger table** (`ux/patterns.md`
§4, §7). Columns: provider, date, reference, title, amount, and booked — the
clearance account the document is booked on, a link to the account, or "Not
booked" with its reason (`features/documents.md` §1): "total 0", "no account
takes *provider* in *currency*", "*account* has no start", "before the start
of *account*". The reference is the order or invoice number the source names,
empty where it names none. The title is the document's own — for the email
importer the receipt's subject (`plugins/importers/email.md` §6) — falling back
to "*provider* document" where it has none; the merchant is not repeated, since
the provider column already carries it canonicalised (`spec.md` §3.3).
Documents are browsed here; they are never created or edited.
The list is a snapshot like the ledger list, with new data as the passive
notice "New data — Refresh" (`ux/patterns.md` §7).

**Filters** are in the address, like the ledger list's: provider (several
allowed), date range, amount (with its currency), text (the reference, the
title, the merchant and the lines' descriptions), and *not booked*. The list
is newest first and paged.

**A detail** opens from a row and shows the document's merchant, total and
currency, its date and its reference, and its lines, each with its
description, quantity and amount, read-only. A booked document says where:
"Booked on *account*", opening the booking's unit in the review panel; there
each entry shows its line's text (`ux/views/review-queue.md`). A document not
booked shows its reason; where the reason is a missing account, no action is
offered yet (a "create a clearance account" from here is a later
convenience).
