"""Settle steps 2 and 3, document matching and the resolution after a link (architecture §5.2, spec §5.8,
§5.9, documents.md §1-§5, I20, I35, I37).

Step 2, `match_documents`, loads ONLY what it needs: the transactions §1 considers (payee with a
`document_provider`, no `document` key, not a duplicate, no transfer entry; the unit is unconfirmed by
construction, see `load_gated`) and the documents of their providers with their lines and carriers
(`core/resolution/doc_load.py`; none at all: it returns at once). Their payee is the one step 1 resolved
WITHOUT a document, which is what eligibility is judged on. The pure matcher (`core/matching/documents.py`)
finds the automatic links: for each document d that is a candidate of considered transactions, all of those
at once, when d is the only candidate of every one of them, a line allocation keeping the committed line
references exists over d's carriers and them together, and no carrier of d is confirmed. ONE statement
writes them on the original entries: `document_id` and the key `document`, `matcher_decision` for a document
of one line, `matcher_proposal` for one of several (the unit is reviewed once and a commit makes it `user`);
for a document of exactly one line the same statement writes the entry's `document_line_id` (spec §5.8: the
line is applied with the link; a document of several lines gives none, the split along the lines is a
commit's business). Settling never creates an entry and links into no document with a confirmed carrier. The
`trg_le_version` bumps the version on a `document_id` or `document_line_id` change, as the schema says: a link
is structural. Writing nothing for a transaction that has no automatic link is what makes a second settle
write nothing (I37). A linked entry leaves the considered set, so rounds terminate. A later round runs the
step only if step 1 wrote something since (`SettleRun.documents_dirty`): a payee is all matching reads of an
entry.

Step 3, `resolve_after_link`, derives again every standing value after the link for the transactions step 2
linked in this settle and the other carriers of their documents (spec §5.9: the link is a change of the first
value in field order), a targeted resolution of just those entries (all entries of the transaction: a split's
other entries read the same document). The link itself stays: it is not a field of `rederive`'s walk but its
input, read through the fields `document_merchant` and `document_line` the loader fills
(`core/resolution/load.py`); history asks a documented entry the merchant key only, for the category.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Connection, text

from app.core.matching.documents import automatic_links
from app.core.resolution.doc_load import document_window, load_documents, load_gated
from app.core.resolution.load import UnconfirmedEntry, load_accounts, load_rules, load_units_of
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import load_snapshot
from app.core.settle.resolution import settle_rewrites, write_rewrites
from app.core.settle.run import ResolutionContext, StepOutcome, current_run

_ANY_DOCUMENT = text("SELECT EXISTS (SELECT 1 FROM external_document)")

# per document: how many lines it has and, for what matters of a document of one, that line's id
_LINE_COUNTS = text(
    "SELECT document_id, count(*) AS n, min(id) AS line_id FROM external_document_line"
    " WHERE document_id = ANY(:ids) GROUP BY document_id"
)

_LINK = text(
    """
    UPDATE ledger_entry AS e
       SET document_id = v.doc, document_line_id = v.line,
           derivation = e.derivation || jsonb_build_object(
               'document', jsonb_build_object('pass', v.pass, 'basis', '{}'::jsonb))
      FROM unnest(CAST(:ids AS bigint[]), CAST(:docs AS bigint[]), CAST(:passes AS text[]),
                  CAST(:lines AS bigint[]))
           AS v(id, doc, pass, line)
     WHERE e.id = v.id
    RETURNING e.id
    """
)

_SOURCE_ENTRIES = text(
    """
    SELECT e.id FROM ledger_entry AS e
     WHERE e.source_transaction_id IN (SELECT x.source_transaction_id FROM ledger_entry AS x
                                        WHERE x.id = ANY(:ids)
                                       UNION
                                       SELECT c.source_transaction_id
                                         FROM ledger_entry AS x
                                         JOIN ledger_entry AS c ON c.document_id = x.document_id
                                        WHERE x.id = ANY(:ids))
    """
)


def match_documents_step(conn: Connection) -> StepOutcome:
    """Step 2: link the considered transactions a document divides among, as the matcher finds them."""
    run = current_run()
    if not run.documents_dirty:
        return StepOutcome()  # step 1 changed no payee since the last look: nothing new to match
    run.documents_dirty = False
    if not conn.execute(_ANY_DOCUMENT).scalar_one():
        return StepOutcome()  # no document: nothing to load, the cheap path
    transactions = load_gated(conn)
    if not transactions:
        return StepOutcome()
    window = document_window(conn)
    documents = load_documents(conn, transactions, window)
    if not documents:
        return StepOutcome()
    links = automatic_links(transactions, documents, window)
    if not links:
        return StepOutcome()
    ids = sorted(links)
    docs = [links[i] for i in ids]
    counts = {
        int(r.document_id): (int(r.n), int(r.line_id)) for r in conn.execute(_LINE_COUNTS, {"ids": docs})
    }
    passes = ["matcher_proposal" if counts.get(d, (0, 0))[0] > 1 else "matcher_decision" for d in docs]
    # a document of exactly one line gives the original entry that line, in the same write as the link; one of
    # none or of several gives none (the split along the lines is a commit's business, spec §5.8)
    only = [counts[d][1] if d in counts and counts[d][0] == 1 else None for d in docs]
    written = [
        int(i)
        for i in conn.execute(_LINK, {"ids": ids, "docs": docs, "passes": passes, "lines": only}).scalars()
    ]
    run.linked.extend(written)
    run.document_linked = run.document_linked or bool(written)
    return StepOutcome(touched=written)


def _context(conn: Connection) -> ResolutionContext:
    run = current_run()
    if run.resolution is not None:
        return run.resolution
    # outside a settle (a step called alone): loaded for this call only, nothing of it kept
    return ResolutionContext(load_accounts(conn), classifiers_for(load_rules(conn)), load_snapshot(conn))


def resolve_after_link_step(conn: Connection) -> StepOutcome:
    """Step 3: derive every value of the transactions linked since step 3 last ran again (the link stays)."""
    run = current_run()
    linked, run.linked = list(run.linked), []
    if not linked:
        return StepOutcome()
    wanted = {int(i) for i in conn.execute(_SOURCE_ENTRIES, {"ids": linked}).scalars()}
    rows: Sequence[UnconfirmedEntry] = load_units_of(conn, sorted(wanted))
    ctx = _context(conn)
    rewrites = settle_rewrites(
        rows,
        reach=lambda row: row.input.entry_id in wanted,
        accounts=ctx.accounts,
        classifiers=ctx.classifiers,
        history=ctx.snapshot,
        reopen=True,
    )
    return write_rewrites(conn, rewrites)
