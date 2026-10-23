# Documents — view sketch

Status: **thin sketch.** Written before implementation, lean on purpose; it
changes with use. The rules are `spec.md` §5.5 and §5.8 and
`features/documents.md`; the contracts are `architecture.md` §4.1.

---

**A list of documents, in the shape of the ledger table** (`ux/patterns.md`
§4, §7). Columns: provider, date, merchant or title, amount, and carried by —
the number of transactions carrying it ("2 transactions"), empty where none
does. Documents are browsed here; they are never created or
edited. The list is a snapshot like the ledger list, with new data as the
passive notice "New data — Refresh" (`ux/patterns.md` §7).

**Filters** are in the address, like the ledger list's: provider (several
allowed), date range, amount (with its currency), text, *not linked*
(documents carried by no entry) and *not fully charged* (documents whose
carriers' amounts fall short of their total, those carried by none included).
The list is newest first and paged.

**A detail** opens from a row and shows the document's merchant, total and
currency, and its lines, each with its category and rationale, read-only. For
a linked document it lists the carrying transactions, each with its own date,
amount and currency, and each opening the review panel. While the document is
not fully charged it lists the transactions it would match
(`features/documents.md` §9), confirmed ones included, each marked with its
unit's state. Opening one of these opens the review panel on that transaction
with the document already picked in the draft; the link is written only by
that commit (`spec.md` §5.8).

**The panel's document section** (`ux/views/review-queue.md`) holds the
document part of the draft:

- the lines of the linked document, the unit's carriers of it, and *look for
  a document* — a document-only re-resolve — offered also for a unit whose
  document is decided "none" by the matcher; an entry with a line shows its
  description on its row, each row of a split along the lines and the one
  entry of a document of one line;
- the suggestions, each a row with its provider, date, merchant and amount;
- *pick by hand* — the same list as above, filtered to the payee's provider and
  to documents not fully charged, in the panel's popover (`ux/patterns.md`
  §11);
- *none of these*, a decision that stops the suggestions and, for a carrier,
  takes its transaction out of that document's unit;
- *split along the lines*, offered once every link of the document is the
  user's (until then it is proposed); where it would replace an existing
  split, the tags it deletes are listed in the preview;
- *commit without a document*, an explicit choice where documents are suggested
  or awaited, never the default key (`ux/patterns.md` §6): the server refuses a
  commit without a pick or this choice there (`decision_required` in the
  preview), so the commit key is disabled with that reason until the user
  decides.

A document that changed since it was picked is shown as a consequence: each
unconfirmed carrier is resolved afresh and its pick is gone (`spec.md` §5.9).
