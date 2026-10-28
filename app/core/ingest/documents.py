"""The document run (spec §5.5, architecture §5.2 'run transaction'), the `documents` kind.

A delivery is upserted in ONE transaction under the settle lock (shared), keyed on `(provider,
source_id)`; documents belong to no account. A document's lines are replaced with each delivery.
`version` moves when the content changes: date, total, currency, merchant, title or lines (`raw` alone
does not move it). Document ingest writes documents only: it resolves no entry and links
nothing. What a document means for the ledger, its booking on a clearance account, is settling's
(`core/settle/bookings.py`, the booking step), which reads the stored documents. How a document already
stored is taken is the importer's declared re-delivery mode (spec §5.5): replaced in place, or kept. The run
is set `ok` with its coverage in the same transaction, then settling runs on its own. A document run is
never reverted (§5.5): it upserts in place.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import Connection, Engine, text

from app.core.domain.errors import ContractViolation, IngestError
from app.core.ingest.run import (
    _checked_stats,
    _fail_run_quietly,
    recheck_instance,
    run_error_text,
    run_retryable,
)
from app.core.plugins.importer import IncomingDocument
from app.core.settle.settle import SettleResult, settle
from app.utils.db.changes import DOCUMENTS, note_change
from app.utils.db.locks import lock_settle_shared, retry_on_deadlock

log = logging.getLogger(__name__)

Redelivery = Literal["replace", "keep"]


@dataclass(frozen=True)
class DocumentRunResult:
    run_id: int
    inserted: int
    updated: int  # existing documents delivered again and replaced (`replace`), changed or not
    kept: int  # existing documents delivered again and left as stored (`keep`)
    changed: tuple[int, ...]  # ids of the documents whose version moved (their content changed)
    settle: SettleResult


def ingest_documents(
    engine: Engine,
    run_id: int,
    documents: Sequence[IncomingDocument],
    *,
    covered_through: date | None,
    covered_from: date | None = None,
    importer_stats: Mapping[str, int] | None = None,
    redelivery: Redelivery = "replace",
) -> DocumentRunResult:
    """Upsert one delivery of documents atomically, then settle.

    `redelivery` is the importer's declared mode (spec §5.5): `replace` updates a stored document in place,
    `keep` leaves it as stored and counts it as kept.

    On any failure everything is rolled back, the run ends `failed` and the error is re-raised. A
    delivery that breaks the contract (a repeated key, an unknown currency, no
    coverage) raises `ContractViolation`. `importer_stats` are the importer's own counts, stored
    under `stats["importer"]`.
    """
    try:
        given = _checked_stats(importer_stats)

        def attempt() -> _Written:
            with engine.begin() as conn:
                return _write(conn, run_id, documents, covered_through, covered_from, given, redelivery)

        written = retry_on_deadlock(attempt)
    except BaseException as exc:  # the run must not stay `running`
        _fail_run_quietly(engine, run_id, run_error_text(exc), retryable=run_retryable(exc))
        raise
    return DocumentRunResult(
        run_id=run_id,
        inserted=written.inserted,
        updated=written.updated,
        kept=written.kept,
        changed=written.changed,
        settle=settle(engine),
    )


@dataclass(frozen=True)
class _Written:
    inserted: int
    updated: int
    kept: int
    changed: tuple[int, ...]


def _write(
    conn: Connection,
    run_id: int,
    documents: Sequence[IncomingDocument],
    covered_through: date | None,
    covered_from: date | None,
    importer_stats: dict[str, int],
    redelivery: Redelivery,
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

    inserted = updated = kept = 0
    changed: list[int] = []
    existing = _existing(conn, documents)
    for doc in documents:
        before = existing.get((doc.provider, doc.source_id))
        if before is None:
            _insert(conn, run, doc)
            inserted += 1
        elif redelivery == "keep":
            kept += 1
        else:
            updated += 1
            if _update(conn, run, doc, before):
                changed.append(before.id)
    stats: dict[str, Any] = {
        "inserted": inserted,
        "updated": updated,
        "kept": kept,
        "changed": len(changed),
        "importer": importer_stats,
    }
    conn.execute(
        text(
            "UPDATE import_run SET status = 'ok', finished_at = clock_timestamp(),"
            " covered_from = :from, covered_through = :through, stats = CAST(:stats AS jsonb)"
            " WHERE id = :id"
        ),
        {"id": run_id, "from": covered_from, "through": covered_through, "stats": json.dumps(stats)},
    )
    return _Written(inserted, updated, kept, tuple(changed))


def _check_contract(conn: Connection, documents: Sequence[IncomingDocument]) -> None:
    seen: dict[tuple[str, str], int] = {}
    for i, doc in enumerate(documents):
        key = (doc.provider, doc.source_id)
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
    occurred_on: date
    total: int
    currency: str
    merchant_name: str | None
    title: str | None
    reference: str | None
    lines: tuple[tuple[str, int, int | None], ...]


def _existing(conn: Connection, documents: Sequence[IncomingDocument]) -> dict[tuple[str, str], _Stored]:
    if not documents:
        return {}
    note_change(conn, DOCUMENTS)  # its own FOR UPDATE below, not `lock_rows`
    rows = conn.execute(
        text(
            "SELECT d.id, d.provider, d.source_id, d.occurred_on, d.total, d.currency,"
            " d.merchant_name, d.title, d.reference"
            " FROM external_document d"
            " JOIN unnest(CAST(:p AS text[]), CAST(:e AS text[])) AS k(provider, source_id)"
            " ON k.provider = d.provider AND k.source_id = d.source_id ORDER BY d.id FOR UPDATE OF d"
        ),
        {"p": [d.provider for d in documents], "e": [d.source_id for d in documents]},
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
        (r.provider, r.source_id): _Stored(
            r.id,
            r.occurred_on,
            r.total,
            r.currency.strip(),
            r.merchant_name,
            r.title,
            r.reference,
            tuple(lines[r.id]),
        )
        for r in rows
    }


def _params(run: Any, doc: IncomingDocument) -> dict[str, Any]:
    return {
        "provider": doc.provider,
        "source_id": doc.source_id,
        "inst": run.importer_instance_id,
        "run_id": run.id,
        "occurred_on": doc.occurred_on,
        "total": doc.total_minor,
        "currency": doc.currency,
        "merchant": doc.merchant_name,
        "title": doc.title,
        "reference": doc.reference,
        "raw": json.dumps(doc.raw),
    }


def _insert(conn: Connection, run: Any, doc: IncomingDocument) -> None:
    doc_id = conn.execute(
        text(
            "INSERT INTO external_document (provider, source_id, importer_instance_id, import_run_id,"
            " occurred_on, total, currency, merchant_name, title, reference, raw)"
            " VALUES (:provider, :source_id,"
            " :inst, :run_id, :occurred_on, :total, :currency, :merchant, :title, :reference,"
            " CAST(:raw AS jsonb))"
            " RETURNING id"
        ),
        _params(run, doc),
    ).scalar_one()
    _insert_lines(conn, int(doc_id), doc)


def _update(conn: Connection, run: Any, doc: IncomingDocument, before: _Stored) -> bool:
    """Replace the document's content and lines; True when its content changed."""
    after_lines = tuple((ln.description, ln.amount_minor, ln.qty) for ln in doc.lines)
    differs = (
        before.occurred_on != doc.occurred_on
        or before.total != doc.total_minor
        or before.currency != doc.currency
        or before.merchant_name != doc.merchant_name
        or before.title != doc.title
        or before.reference != doc.reference
        or before.lines != after_lines
    )
    conn.execute(
        text(
            "UPDATE external_document SET importer_instance_id = :inst, import_run_id = :run_id,"
            " occurred_on = :occurred_on, total = :total, currency = :currency, merchant_name = :merchant,"
            " title = :title, reference = :reference, raw = CAST(:raw AS jsonb),"
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
    rows = [
        {"d": doc_id, "n": n, "description": ln.description, "amount": ln.amount_minor, "qty": ln.qty}
        for n, ln in enumerate(doc.lines, start=1)
    ]
    conn.execute(
        text(
            "INSERT INTO external_document_line (document_id, line_no, description, amount, qty)"
            " VALUES (:d, :n, :description, :amount, :qty)"
        ),
        rows,
    )
