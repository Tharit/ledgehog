"""Settle steps 2 and 3, document matching and the resolution after a link (architecture §5.2, spec §5.8,
§5.9, documents.md §1-§5, I20, I35, I37).

Step 2, `match_documents`, loads ONLY what it needs: the unlinked documents (none: it returns at once) and
the original entries of the transactions §1 considers (payee with a `document_provider`, no `document` key,
not a duplicate; the unit is unconfirmed by construction, see `_considered`). Their payee is the one step 1
resolved WITHOUT a document, which is what eligibility is judged on. The pure matcher
(`core/matching/documents.py`) finds the automatic links (exactly one candidate, a candidate of no other
transaction) and ONE statement writes them on the original entry: `document_id` and the key `document`,
`matcher_decision` for a document of one line, `matcher_proposal` for one of several (the unit is reviewed
once and a commit makes it `user`); for a document of exactly one line the same statement writes the entry's
`document_line_id` (spec §5.8: the line is applied with the link; a document of several lines gives none, the
split along the lines is a commit's business). The `trg_le_version` bumps the version on a `document_id` or
`document_line_id` change, as the schema says: a link is structural. Writing nothing for a transaction that
has no automatic link is what makes a second settle write nothing (I37). A linked entry leaves the
considered set, so rounds terminate. A later round runs the step only if step 1 wrote something since
(`SettleRun.documents_dirty`): a payee is all matching reads of an entry.

Step 3, `resolve_after_link`, derives again every standing value after the link for the transactions step 2
linked in this settle (spec §5.9: the link is a change of the first value in field order), a targeted
resolution of just those entries (all entries of the transaction: a split's other entries read the same
document). The link itself stays: it is not a field of `rederive`'s walk but its input, read through the
fields `document_merchant` and `document_line` the loader fills (`core/resolution/load.py`); history asks a
documented entry the merchant key only, for the category.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Connection, text

from app.core.matching.documents import DocInput, DocTxn, automatic_links
from app.core.resolution.load import UnconfirmedEntry, load_accounts, load_rules, load_units_of
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import load_snapshot
from app.core.settle.resolution import settle_rewrites, write_rewrites
from app.core.settle.run import ResolutionContext, StepOutcome, current_run
from app.core.settle.window import document_window

_ANY_UNLINKED = text(
    "SELECT EXISTS (SELECT 1 FROM external_document AS d"
    " WHERE NOT EXISTS (SELECT 1 FROM ledger_entry AS c WHERE c.document_id = d.id))"
)

_UNLINKED = text(
    """
    SELECT d.id, d.provider, d.occurred_on, d.total, d.currency
      FROM external_document AS d
     WHERE NOT EXISTS (SELECT 1 FROM ledger_entry AS c WHERE c.document_id = d.id)
    """
)

# documents.md §1 without the unit test: the original entry (I31) of a non-duplicate transaction, whose payee
# has a provider and which has no decided document. Amounts and the booking date are the transaction's, as the
# unit CTE's candidate test reads them.
_GATED = text(
    """
    SELECT e.id, e.account_id, st.booked_on, st.amount, st.currency, st.instructed_amount,
           st.instructed_currency, p.document_provider AS provider
      FROM ledger_entry AS e
      JOIN source_transaction AS st ON st.id = e.source_transaction_id
      JOIN payee AS p ON p.id = e.payee_id
     WHERE p.document_provider IS NOT NULL
       AND e.type IS DISTINCT FROM 'transfer'
       AND st.duplicate_of IS NULL
       AND NOT jsonb_exists(e.derivation, 'document')
       AND NOT EXISTS (SELECT 1 FROM ledger_entry AS lo
                        WHERE lo.source_transaction_id = e.source_transaction_id AND lo.id < e.id)
    """
)

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
                                        WHERE x.id = ANY(:ids))
    """
)


def _considered(conn: Connection) -> list[DocTxn]:
    """The transactions documents.md §1 considers, as the matcher reads them.

    That the unit is unconfirmed (I20) is not asked of the unit CTE: a transaction with a candidate is never
    in a confirmed unit, because `doc_candidate` keeps that unit open (`core/resolution/confirmed.py`), and
    one without a candidate has nothing to link. So every gated transaction is `confirmed=False` here."""
    return [
        DocTxn(
            entry_id=int(r.id),
            account_id=int(r.account_id),
            booked_on=r.booked_on,
            amount=int(r.amount),
            currency=str(r.currency).strip(),
            instructed_amount=r.instructed_amount,
            instructed_currency=r.instructed_currency.strip() if r.instructed_currency else None,
            payee_provider=r.provider,
        )
        for r in conn.execute(_GATED)
    ]


def _documents(conn: Connection, providers: set[str]) -> list[DocInput]:
    return [
        DocInput(
            document_id=int(r.id),
            provider=r.provider,
            occurred_on=r.occurred_on,
            total=int(r.total),
            currency=str(r.currency).strip(),
        )
        for r in conn.execute(_UNLINKED)
        if r.provider in providers
    ]


def match_documents_step(conn: Connection) -> StepOutcome:
    """Step 2: link each considered transaction that has exactly one candidate no other transaction has."""
    run = current_run()
    if not run.documents_dirty:
        return StepOutcome()  # step 1 changed no payee since the last look: nothing new to match
    run.documents_dirty = False
    if not conn.execute(_ANY_UNLINKED).scalar_one():
        return StepOutcome()  # no document waits for a transaction: nothing to load, the cheap path
    transactions = _considered(conn)
    if not transactions:
        return StepOutcome()
    documents = _documents(conn, {t.payee_provider for t in transactions if t.payee_provider})
    if not documents:
        return StepOutcome()
    links = automatic_links(transactions, documents, document_window(conn))
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
