"""Loading what document matching reads (documents.md §1-§4), as the pure matcher takes it
(`core/matching/documents.py`): the transactions §1 gates, the documents of their providers with their lines
and carriers, and from them the candidacy the unit CTE reads (`core/resolution/confirmed.py`).

A carrier is a transaction whose original entry links the document; it is confirmed when its unit is: every
entry of every carrier of the document is complete and carries only standing keys (a carrier has a decided
document, so the document test of the unit adds nothing). A line allocation cannot be done in SQL, so the
candidates and suggestions are found here and bound into the unit CTE.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Row, text

from app.core.matching.documents import DocInput, DocTxn, DocWindow, match
from app.core.matching.lines import MAX_PARTIAL_LINES, Line
from app.core.plugins.classifier import STANDING_PASSES
from app.core.resolution.entry_state import COMPLETE, STANDING


def document_window(conn: Connection) -> DocWindow:
    """The configured document window (spec §5.8) as (back, ahead) days: a transaction matches a document
    dated within [booked_on - back, booked_on + ahead], and waits for one until booked_on + ahead. Set like
    the matching window (`core/settle/window.py`); an unset setting is an error, never a default."""
    back, ahead = conn.execute(
        text(
            "SELECT current_setting('ledger.document_window_back_days'),"
            " current_setting('ledger.document_window_ahead_days')"
        )
    ).one()
    return DocWindow(int(back), int(ahead))


# documents.md §1 without the unit test: the original entry (I31) of a non-duplicate transaction, none of
# whose entries is a transfer, whose payee has a provider and which has no decided document. Amounts and the
# booking date are the transaction's, as the unit CTE's candidate test reads them.
_GATED = text(
    """
    SELECT e.id, e.account_id, st.booked_on, st.amount, st.currency, st.instructed_amount,
           st.instructed_currency, p.document_provider AS provider
      FROM ledger_entry AS e
      JOIN source_transaction AS st ON st.id = e.source_transaction_id
      JOIN payee AS p ON p.id = e.payee_id
     WHERE p.document_provider IS NOT NULL
       AND st.duplicate_of IS NULL
       AND e.id <> ALL(CAST(:exclude AS bigint[]))
       AND NOT jsonb_exists(e.derivation, 'document')
       AND NOT EXISTS (SELECT 1 FROM ledger_entry AS lo
                        WHERE lo.source_transaction_id = e.source_transaction_id AND lo.id < e.id)
       AND NOT EXISTS (SELECT 1 FROM ledger_entry AS t
                        WHERE t.source_transaction_id = e.source_transaction_id AND t.type = 'transfer')
    """
)

# a document without its lines: what `_possible` needs to say whether any gated transaction could match it
# (`n` lines summing to `s`), so the lines and carriers are read only for those that could
_DOCUMENT_SELECT = """
    SELECT d.id, d.provider, d.occurred_on, d.total, d.currency, COALESCE(l.n, 0) AS n, COALESCE(l.s, 0) AS s
      FROM external_document AS d
      LEFT JOIN (SELECT document_id, count(*) AS n, sum(amount) AS s
                   FROM external_document_line GROUP BY document_id) AS l ON l.document_id = d.id
"""
_HEADERS = text(_DOCUMENT_SELECT + " WHERE lower(d.provider) = ANY(CAST(:providers AS text[]))")
_HEADER = text(_DOCUMENT_SELECT + " WHERE d.id = :id")

_LINES = text(
    "SELECT document_id, line_no, amount FROM external_document_line"
    " WHERE document_id = ANY(CAST(:ids AS bigint[])) ORDER BY document_id, line_no"
)

# the carriers of documents: the original entry (it holds the link), the transaction's amounts and the
# lines of the document that any entry of the transaction references
_CARRIERS = text(
    """
    SELECT o.document_id, o.id, o.account_id, o.source_transaction_id AS src, st.booked_on, st.amount,
           st.currency, st.instructed_amount, st.instructed_currency,
           COALESCE((SELECT array_agg(l.line_no ORDER BY l.line_no)
                       FROM ledger_entry AS x
                       JOIN external_document_line AS l
                         ON l.id = x.document_line_id AND l.document_id = o.document_id
                      WHERE x.source_transaction_id = o.source_transaction_id), '{}') AS refs
      FROM ledger_entry AS o
      JOIN source_transaction AS st ON st.id = o.source_transaction_id
     WHERE o.document_id = ANY(CAST(:ids AS bigint[]))
    """
)

# the transactions among these with an entry that is not complete and standing (so the carrier is not
# confirmed): a plain query on `ix_le_source`, the planner reads the same test inside the carriers' as a scan
_OPEN_SOURCES = text(
    f"""
    SELECT DISTINCT le.source_transaction_id
      FROM ledger_entry AS le
     WHERE le.source_transaction_id = ANY(CAST(:srcs AS bigint[]))
       AND NOT ({COMPLETE} AND {STANDING})
    """  # noqa: S608
)


def load_gated(conn: Connection, exclude: Collection[int] = ()) -> list[DocTxn]:
    """The transactions documents.md §1 considers, as the matcher reads them, bar `exclude` (original entry
    ids).

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
        for r in conn.execute(_GATED, {"exclude": sorted(exclude)})
    ]


def load_carriers(conn: Connection, document_ids: Sequence[int]) -> dict[int, tuple[DocTxn, ...]]:
    """The carriers of each of the documents, by document id (a document with none has no key)."""
    if not document_ids:
        return {}
    rows = conn.execute(_CARRIERS, {"ids": sorted(document_ids)}).all()
    open_sources = {
        int(i)
        for i in conn.execute(
            _OPEN_SOURCES, {"srcs": sorted({int(r.src) for r in rows}), "standing": sorted(STANDING_PASSES)}
        ).scalars()
    }
    open_docs = {int(r.document_id) for r in rows if int(r.src) in open_sources}
    out: dict[int, list[DocTxn]] = defaultdict(list)
    for r in rows:
        out[int(r.document_id)].append(
            DocTxn(
                entry_id=int(r.id),
                account_id=int(r.account_id),
                booked_on=r.booked_on,
                amount=int(r.amount),
                currency=str(r.currency).strip(),
                instructed_amount=r.instructed_amount,
                instructed_currency=r.instructed_currency.strip() if r.instructed_currency else None,
                confirmed=int(r.document_id) not in open_docs,
                document_decided=True,
                document_id=int(r.document_id),
                line_numbers=frozenset(int(n) for n in r.refs),
            )
        )
    return {d: tuple(sorted(c, key=lambda t: t.entry_id)) for d, c in out.items()}


def _inputs(conn: Connection, rows: Sequence[Row[Any]]) -> list[DocInput]:
    """The documents of these header rows, with their lines and carriers."""
    ids = [int(r.id) for r in rows]
    lines: dict[int, list[Line]] = defaultdict(list)
    for r in conn.execute(_LINES, {"ids": ids}):
        lines[int(r.document_id)].append(Line(int(r.line_no), int(r.amount)))
    carriers = load_carriers(conn, ids)
    return [
        DocInput(
            document_id=int(r.id),
            provider=r.provider,
            occurred_on=r.occurred_on,
            total=int(r.total),
            currency=str(r.currency).strip(),
            lines=tuple(lines.get(int(r.id), ())),
            carriers=carriers.get(int(r.id), ()),
        )
        for r in rows
    ]


def _possible(gated: Sequence[DocTxn], rows: Sequence[Row[Any]], window: DocWindow) -> list[Row[Any]]:
    """The documents some gated transaction could match, at most: of its payee's provider, within the window,
    whose total is its amount in the document's currency (a whole match) or whose lines sum to the total, of
    two or more and at most `MAX_PARTIAL_LINES` (a partial one; one line is the whole). The matcher decides;
    this only keeps the lines and carriers of every other document from being read."""
    whole: dict[tuple[str, str, int], list[Row[Any]]] = defaultdict(list)
    partial: dict[tuple[str, str], list[Row[Any]]] = defaultdict(list)
    for r in rows:
        provider, currency = str(r.provider).lower(), str(r.currency).strip()
        whole[(provider, currency, int(r.total))].append(r)
        if 2 <= int(r.n) <= MAX_PARTIAL_LINES and int(r.s) == int(r.total):
            partial[(provider, currency)].append(r)
    for found in partial.values():
        found.sort(key=lambda r: r.occurred_on)
    dates = {key: [r.occurred_on for r in found] for key, found in partial.items()}
    keep: dict[int, Row[Any]] = {}
    for t in gated:
        assert t.payee_provider is not None
        provider = t.payee_provider.lower()
        asked = [(t.currency, t.amount)]
        if t.instructed_currency is not None and t.instructed_amount is not None:
            asked.append((t.instructed_currency, t.instructed_amount))
        lo, hi = t.booked_on - timedelta(days=window.back), t.booked_on + timedelta(days=window.ahead)
        for currency, amount in asked:
            for r in whole.get((provider, currency, amount), ()):
                if lo <= r.occurred_on <= hi:
                    keep[int(r.id)] = r
            near = partial.get((provider, currency))
            if near:
                span = dates[(provider, currency)]
                for r in near[bisect_left(span, lo) : bisect_right(span, hi)]:
                    keep[int(r.id)] = r
    return [keep[i] for i in sorted(keep)]


def load_documents(conn: Connection, gated: Sequence[DocTxn], window: DocWindow) -> list[DocInput]:
    """The documents the gated transactions could match (documents.md §2), with their lines and carriers."""
    wanted = sorted({t.payee_provider.lower() for t in gated if t.payee_provider})
    if not wanted:
        return []
    rows = conn.execute(_HEADERS, {"providers": wanted}).all()
    return _inputs(conn, _possible(gated, rows, window))


def load_document(conn: Connection, document_id: int) -> DocInput | None:
    """One document with its lines and carriers; None when there is no such document."""
    found = _inputs(conn, conn.execute(_HEADER, {"id": document_id}).all())
    return found[0] if found else None


# One settle reads the candidacy a few times a round (every flags, votes and units read binds it), while
# only a step that wrote can change it: `settle` opens a memo for its rounds and forgets it after each step
# that touched an entry. Outside a settle nothing is kept.
_MEMO: ContextVar[dict[str, dict[int, bool]] | None] = ContextVar("candidacy_memo", default=None)


@contextmanager
def candidacy_memo() -> Iterator[None]:
    token = _MEMO.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)


def forget_candidacy() -> None:
    """The ledger changed: the next `candidacy` reads it afresh."""
    memo = _MEMO.get()
    if memo is not None:
        memo.clear()


def candidacy(conn: Connection) -> dict[int, bool]:
    """{original entry id: suggested} for every gated transaction that has a candidate (documents.md §2, §4):
    suggested when it has no automatic link. What the unit CTE reads as `doc_candidate`, `doc_suggested`."""
    memo = _MEMO.get()
    if memo is not None and "found" in memo:
        return memo["found"]
    found = _candidacy(conn)
    if memo is not None:
        memo["found"] = found
    return found


def _candidacy(conn: Connection) -> dict[int, bool]:
    gated = load_gated(conn)
    if not gated:
        return {}
    window = document_window(conn)
    documents = load_documents(conn, gated, window)
    if not documents:
        return {}
    found = match(gated, documents, window)
    return {i: i not in found.links for i in found.candidates}
