"""The document run (spec §5.5, architecture §5.2 'run transaction'), the `documents` kind.

A delivery is upserted in ONE transaction under the settle lock (shared), keyed on `(provider,
external_id)`; documents belong to no account. A document's lines are replaced with each delivery.
`version` moves only when what resolution reads changes: total, currency, merchant name or lines
(`title`, `raw` and `occurred_on` alone do not move it). A changed document resolves its
unconfirmed carrier afresh (`reresolve_unconfirmed_carrier`); a confirmed one is left alone (I20).
The run is set `ok` with its coverage in the same transaction, then settling runs on its own. A
document run is never reverted (§5.5): it upserts in place.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.domain.errors import ContractViolation, IngestError
from app.core.ingest.run import (
    _fail_run_quietly,
    recheck_instance,
    run_error_text,
    run_retryable,
)
from app.core.plugins.importer import IncomingDocument
from app.core.resolution import Resolved, resolve_afresh
from app.core.resolution.load import load_accounts, load_rules, load_unconfirmed
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import load_snapshot
from app.core.resolution.types import is_user_no_payee
from app.core.settle.resolution import new_derivation
from app.core.settle.settle import SettleResult, settle
from app.utils.db.changes import DOCUMENTS, note_change
from app.utils.db.locks import lock_accounts, lock_settle_shared, retry_on_deadlock

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentRunResult:
    run_id: int
    inserted: int
    updated: int  # existing documents delivered again, changed or not
    changed: tuple[int, ...]  # ids of the documents whose version moved (what resolution reads changed)
    reresolved_entry_ids: tuple[int, ...]  # unconfirmed carriers resolved afresh
    settle: SettleResult


def ingest_documents(
    engine: Engine,
    run_id: int,
    documents: Sequence[IncomingDocument],
    *,
    covered_through: date | None,
    covered_from: date | None = None,
) -> DocumentRunResult:
    """Upsert one delivery of documents atomically, then settle.

    On any failure everything is rolled back, the run ends `failed` and the error is re-raised. A
    delivery that breaks the contract (a zero total, a repeated key, an unknown currency, no
    coverage) raises `ContractViolation`.
    """
    try:

        def attempt() -> _Written:
            with engine.begin() as conn:
                return _write(conn, run_id, documents, covered_through, covered_from)

        written = retry_on_deadlock(attempt)
    except BaseException as exc:  # the run must not stay `running`
        _fail_run_quietly(engine, run_id, run_error_text(exc), retryable=run_retryable(exc))
        raise
    return DocumentRunResult(
        run_id=run_id,
        inserted=written.inserted,
        updated=written.updated,
        changed=written.changed,
        reresolved_entry_ids=written.reresolved,
        settle=settle(engine),
    )


@dataclass(frozen=True)
class _Written:
    inserted: int
    updated: int
    changed: tuple[int, ...]
    reresolved: tuple[int, ...]


def _write(
    conn: Connection,
    run_id: int,
    documents: Sequence[IncomingDocument],
    covered_through: date | None,
    covered_from: date | None,
) -> _Written:
    lock_settle_shared(conn)
    run = conn.execute(
        text("SELECT id, emits, importer_instance_id FROM import_run WHERE id = :i"), {"i": run_id}
    ).one_or_none()
    if run is None:
        raise IngestError(f"no such run: {run_id}")
    if run.emits != "documents":
        raise IngestError(f"run {run_id} emits {run.emits}, not documents")
    status: str = conn.execute(
        text("SELECT status FROM import_run WHERE id = :i FOR UPDATE"), {"i": run_id}
    ).scalar_one()
    if status != "running":
        raise IngestError(f"run {run_id} is {status}, not running")
    recheck_instance(conn, run.importer_instance_id, "documents")
    if covered_through is None:
        raise ContractViolation(
            "no_coverage", "covered_through is required: a successful run says how far it covers"
        )
    if covered_from is not None and covered_from > covered_through:
        raise ContractViolation(
            "coverage_inverted", f"coverage starts {covered_from}, after its end {covered_through}"
        )
    _check_contract(conn, documents)

    inserted = updated = 0
    changed: list[int] = []
    existing = _existing(conn, documents)
    for doc in documents:
        before = existing.get((doc.provider, doc.external_id))
        if before is None:
            _insert(conn, run, doc)
            inserted += 1
        else:
            updated += 1
            if _update(conn, run, doc, before):
                changed.append(before.id)
    reresolved = _reresolve_carriers(conn, changed)
    stats = {"inserted": inserted, "updated": updated, "changed": len(changed)}
    conn.execute(
        text(
            "UPDATE import_run SET status = 'ok', finished_at = clock_timestamp(),"
            " covered_from = :from, covered_through = :through, stats = CAST(:stats AS jsonb)"
            " WHERE id = :id"
        ),
        {"id": run_id, "from": covered_from, "through": covered_through, "stats": json.dumps(stats)},
    )
    return _Written(inserted, updated, tuple(changed), tuple(reresolved))


def _check_contract(conn: Connection, documents: Sequence[IncomingDocument]) -> None:
    seen: dict[tuple[str, str], int] = {}
    for i, doc in enumerate(documents):
        if doc.total_minor == 0:
            raise ContractViolation("zero_total", f"document {i} has total 0: a zero document is not emitted")
        key = (doc.provider, doc.external_id)
        if key in seen:
            raise ContractViolation(
                "repeated_document", f"document {i} repeats the key of document {seen[key]}"
            )
        seen[key] = i
    known = set(
        conn.execute(
            text("SELECT code FROM currency WHERE code = ANY(:c)"),
            {"c": sorted({d.currency for d in documents})},
        ).scalars()
    )
    for i, doc in enumerate(documents):
        if doc.currency not in known:
            raise ContractViolation(
                "unknown_currency", f"document {i} is in {doc.currency}, which is not a known currency"
            )


@dataclass(frozen=True)
class _Stored:
    id: int
    total: int
    currency: str
    merchant_name: str | None
    lines: tuple[tuple[str, int, int | None], ...]


def _existing(conn: Connection, documents: Sequence[IncomingDocument]) -> dict[tuple[str, str], _Stored]:
    if not documents:
        return {}
    note_change(conn, DOCUMENTS)  # its own FOR UPDATE below, not `lock_rows`
    rows = conn.execute(
        text(
            "SELECT d.id, d.provider, d.external_id, d.total, d.currency, d.merchant_name"
            " FROM external_document d"
            " JOIN unnest(CAST(:p AS text[]), CAST(:e AS text[])) AS k(provider, external_id)"
            " ON k.provider = d.provider AND k.external_id = d.external_id ORDER BY d.id FOR UPDATE OF d"
        ),
        {"p": [d.provider for d in documents], "e": [d.external_id for d in documents]},
    ).all()
    lines: dict[int, list[tuple[str, int, int | None]]] = {r.id: [] for r in rows}
    for ln in conn.execute(
        text(
            "SELECT document_id, description, amount, qty FROM external_document_line"
            " WHERE document_id = ANY(:ids) ORDER BY document_id, line_no"
        ),
        {"ids": list(lines)},
    ):
        lines[ln.document_id].append((ln.description, ln.amount, ln.qty))
    return {
        (r.provider, r.external_id): _Stored(
            r.id, r.total, r.currency.strip(), r.merchant_name, tuple(lines[r.id])
        )
        for r in rows
    }


def _params(run: Any, doc: IncomingDocument) -> dict[str, Any]:
    return {
        "provider": doc.provider,
        "external_id": doc.external_id,
        "inst": run.importer_instance_id,
        "run_id": run.id,
        "occurred_on": doc.occurred_on,
        "total": doc.total_minor,
        "currency": doc.currency,
        "merchant": doc.merchant_name,
        "title": doc.title,
        "raw": json.dumps(doc.raw),
    }


def _insert(conn: Connection, run: Any, doc: IncomingDocument) -> None:
    doc_id = conn.execute(
        text(
            "INSERT INTO external_document (provider, external_id, importer_instance_id, import_run_id,"
            " occurred_on, total, currency, merchant_name, title, raw) VALUES (:provider, :external_id,"
            " :inst, :run_id, :occurred_on, :total, :currency, :merchant, :title, CAST(:raw AS jsonb))"
            " RETURNING id"
        ),
        _params(run, doc),
    ).scalar_one()
    _insert_lines(conn, int(doc_id), doc)


def _update(conn: Connection, run: Any, doc: IncomingDocument, before: _Stored) -> bool:
    """Replace the document's content and lines; True when what resolution reads of it changed."""
    after_lines = tuple((ln.description, ln.amount_minor, ln.qty) for ln in doc.lines)
    differs = (
        before.total != doc.total_minor
        or before.currency != doc.currency
        or before.merchant_name != doc.merchant_name
        or before.lines != after_lines
    )
    conn.execute(
        text(
            "UPDATE external_document SET importer_instance_id = :inst, import_run_id = :run_id,"
            " occurred_on = :occurred_on, total = :total, currency = :currency, merchant_name = :merchant,"
            " title = :title, raw = CAST(:raw AS jsonb),"
            " version = version + CASE WHEN :bump THEN 1 ELSE 0 END"
            " WHERE id = :id"
        ),
        {**_params(run, doc), "id": before.id, "bump": differs},
    )
    if before.lines != after_lines:
        conn.execute(text("DELETE FROM external_document_line WHERE document_id = :i"), {"i": before.id})
        _insert_lines(conn, before.id, doc)
    return differs


def _insert_lines(conn: Connection, doc_id: int, doc: IncomingDocument) -> None:
    if not doc.lines:
        return
    conn.execute(
        text(
            "INSERT INTO external_document_line (document_id, line_no, description, amount, qty)"
            " VALUES (:d, :n, :description, :amount, :qty)"
        ),
        [
            {"d": doc_id, "n": n, "description": ln.description, "amount": ln.amount_minor, "qty": ln.qty}
            for n, ln in enumerate(doc.lines, start=1)
        ],
    )


def _reresolve_carriers(conn: Connection, changed: Sequence[int]) -> list[int]:
    """The entries carrying a changed document, resolved afresh when their unit is unconfirmed (I20)."""
    if not changed:
        return []
    rows = conn.execute(
        text("SELECT id, account_id FROM ledger_entry WHERE document_id = ANY(:d) ORDER BY id"),
        {"d": list(changed)},
    ).all()
    lock_accounts(conn, [r.account_id for r in rows])
    return reresolve_unconfirmed_carrier(conn, [r.id for r in rows])


def reresolve_unconfirmed_carrier(conn: Connection, entry_ids: Sequence[int]) -> list[int]:
    """Resolve the unconfirmed ones among `entry_ids` afresh: the link, its `document` key and the entry's
    line of the document are dropped in the one statement (settling makes the link again, and the line with it
    for a document of one line), and every value, a user's included, is derived again (spec §5.5, §5.9).
    A confirmed entry is left alone (I20). Returns the entries rewritten.

    The afresh resolution (`resolve_afresh`, as the entry form uses it) runs on the entry's input WITHOUT
    the document: the link is dropped, so the input has no document merchant and no line (neither the old
    link's nor the old content of the document's), and history asks its raw keys again. The loader is asked
    for exactly that (`with_document=False`). Settling then links again where the changed document still
    matches uniquely, and its step 3 derives the values once more from the document as it now is
    (documents.md §4, §5).
    """
    wanted = set(entry_ids)
    rows = [r for r in load_unconfirmed(conn, with_document=False) if r.input.entry_id in wanted]
    if not rows:
        return []
    accounts = load_accounts(conn)
    classifiers = classifiers_for(load_rules(conn))
    snapshot = load_snapshot(conn)
    written: list[int] = []
    for row in rows:
        entry_id = row.input.entry_id
        resolved = resolve_afresh(
            row.input,
            accounts=accounts,
            classifiers=classifiers,
            history=snapshot,
            exclude_entry_ids=frozenset({entry_id}),
        )
        kind = resolved.get("type")
        if kind is not None and kind.value == "transfer" and not row.original:
            kind = None  # I31: only the original may be a transfer
            resolved = Resolved()
        derivation = {k: v for k, v in new_derivation(row.derivation, resolved).items() if k != "document"}
        conn.execute(
            text(
                "UPDATE ledger_entry SET document_id = NULL, document_line_id = NULL, type = :type,"
                " payee_id = :payee,"
                " category_id = :category, counter_account_id = :counter,"
                " derivation = CAST(:d AS jsonb) WHERE id = :id"
            ),
            {
                "type": str(kind.value) if kind is not None else None,
                "payee": _id(resolved.get("payee")),
                "category": _id(resolved.get("category")),
                "counter": _id(resolved.get("counter_account")),
                "d": json.dumps(derivation),
                "id": entry_id,
            },
        )
        written.append(entry_id)
    return written


def _id(decided: Any) -> int | None:
    if decided is None or is_user_no_payee(decided):
        return None
    return int(decided.value)
