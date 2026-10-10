"""The ingest run (spec §5.1-§5.4, architecture §5.2 'run transaction').

A delivery is written in ONE transaction, under the settle lock (shared) and the
account's lock. Identity is checked for every row first, then the remaining rows
are paired by amount with rows the account already holds (spec §5.2); everything
else is inserted with exactly one entry. The run is set `ok` in the same
transaction. Settling runs afterwards, in its own transaction: a settling failure
is reported, never raised into the committed write.

Pure `core`: no framework imports; the engine is handed in.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.domain.errors import ContractViolation, IngestError
from app.core.ingest.entries import insert_entry
from app.core.ingest.identity import ContentHash, SourceId, assign_ordinals, canonical_text, identity_of
from app.core.plugins.importer import IncomingRow
from app.core.settle.settle import SettleResult, settle
from app.utils.db.locks import lock_accounts, lock_settle_shared, retry_on_deadlock


@dataclass(frozen=True)
class RunResult:
    run_id: int
    inserted: int  # rows written with an entry
    # (new source_transaction id, id of the existing row it duplicates), delivery order
    duplicates: tuple[tuple[int, int], ...]
    skipped_by_identity: int
    filtered: int  # rows the importer dropped before delivery (e.g. zero bookings), as reported
    settle: SettleResult


@dataclass(frozen=True)
class _Counts:
    inserted: int
    duplicates: tuple[tuple[int, int], ...]
    skipped_by_identity: int


def start_run(
    engine: Engine,
    account_id: int,
    kind: str,
    *,
    importer: str,
    importer_instance_id: int | None = None,
    started_by: int | None = None,
) -> int:
    """Commit a `running` run before anything else, in its own transaction (spec §5.1)."""
    if kind != "transactions":
        raise ValueError(f"ingest_delivery writes transaction runs only, not {kind!r}")
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO import_run (importer, importer_instance_id, emits, account_id,"
                    " status, started_by) VALUES (:importer, :inst, :emits, :account, 'running', :by)"
                    " RETURNING id"
                ),
                {
                    "importer": importer,
                    "inst": importer_instance_id,
                    "emits": kind,
                    "account": account_id,
                    "by": started_by,
                },
            ).scalar_one()
        )


def fail_run(engine: Engine, run_id: int, error: str) -> None:
    """End a run `failed`, in its own transaction. A run no longer `running` is left alone."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE import_run SET status = 'failed', finished_at = clock_timestamp(),"
                " error_text = :err WHERE id = :id AND status = 'running'"
            ),
            {"id": run_id, "err": error},
        )


def recompute_derived(conn: Connection, account_id: int) -> None:
    """Step 4 hook: derived entries and balance records of the account are recomputed here."""


def ingest_delivery(
    engine: Engine,
    run_id: int,
    rows: Sequence[IncomingRow],
    *,
    reported_balance: int | None = None,
    covered_through: date | None = None,
    filtered: int = 0,
) -> RunResult:
    """Write one delivery for the run's account, atomically, then settle.

    On any failure everything the delivery wrote is rolled back, the run ends
    `failed` and the error is re-raised. A record that breaks the importer's contract
    (wrong currency, zero amount, a repeated `source_id`, no coverage) is never repaired,
    skipped or counted: it raises `ContractViolation` naming the rule. `filtered` is the
    importer's own count of rows it dropped before delivery; it is stored in the run's
    statistics and returned. `reported_balance` is step 4 and ignored.
    """
    del reported_balance  # balance records and reconciliation are step 4
    try:
        if filtered < 0:
            raise ValueError(f"filtered must not be negative, got {filtered}")
        counts = retry_on_deadlock(lambda: _write_delivery(engine, run_id, rows, covered_through, filtered))
    except Exception as exc:
        fail_run(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise
    try:
        settled = settle(engine)
    except Exception as exc:  # the write stands (architecture §5.2)
        settled = SettleResult(error=f"{type(exc).__name__}: {exc}")
    return RunResult(
        run_id=run_id,
        inserted=counts.inserted,
        duplicates=counts.duplicates,
        skipped_by_identity=counts.skipped_by_identity,
        filtered=filtered,
        settle=settled,
    )


def _write_delivery(
    engine: Engine, run_id: int, rows: Sequence[IncomingRow], covered_through: date | None, filtered: int
) -> _Counts:
    with engine.begin() as conn:
        lock_settle_shared(conn)
        run = conn.execute(
            text(
                "SELECT id, account_id, importer, importer_instance_id, status FROM import_run WHERE id = :i"
            ),
            {"i": run_id},
        ).one_or_none()
        if run is None:
            raise IngestError(f"no such run: {run_id}")
        account_id: int = run.account_id
        lock_accounts(conn, [account_id])
        if run.status != "running":
            raise IngestError(f"run {run_id} is {run.status}, not running")
        if covered_through is None:
            raise ContractViolation(
                "no_coverage", "covered_through is required: a successful run says how far it covers"
            )
        currency: str = conn.execute(
            text("SELECT currency FROM account WHERE id = :i"), {"i": account_id}
        ).scalar_one()

        _check_contract(rows, currency)

        # Ordinals over the WHOLE delivery, before any filtering (spec §5.2).
        ordinals = assign_ordinals(rows)
        # (row, identity column, identity value) of every row that takes part
        live: list[tuple[IncomingRow, str, str]] = []
        for row, ordinal in zip(rows, ordinals, strict=True):
            ident = identity_of(row, ordinal)
            if isinstance(ident, SourceId):
                live.append((row, "source_id", ident.value))
            else:
                assert isinstance(ident, ContentHash)
                live.append((row, "content_hash", ident.hex()))

        used, skipped, remaining = _identity_step(conn, account_id, live)
        pairing = _amount_step(conn, account_id, remaining, used)

        inserted = 0
        duplicates: list[tuple[int, int]] = []
        for (row, col, value), original in zip(remaining, pairing, strict=True):
            new_id = _insert_source(conn, run, account_id, row, col, value, original)
            if new_id is None:  # identity taken by a concurrent insert: skipped (I4)
                skipped += 1
            elif original is not None:
                duplicates.append((new_id, original))
            else:
                insert_entry(conn, new_id)
                inserted += 1

        recompute_derived(conn, account_id)
        stats = {
            "inserted": inserted,
            "skipped_by_identity": skipped,
            "inserted_as_duplicates": [{"id": n, "duplicate_of": o} for n, o in duplicates],
            "filtered": filtered,
        }
        conn.execute(
            text(
                "UPDATE import_run SET status = 'ok', finished_at = clock_timestamp(),"
                " covered_through = :through, stats = CAST(:stats AS jsonb) WHERE id = :id"
            ),
            {"id": run_id, "through": covered_through, "stats": json.dumps(stats)},
        )
        return _Counts(inserted, tuple(duplicates), skipped)


def _check_contract(rows: Sequence[IncomingRow], currency: str) -> None:
    """The importer's contract (spec §5.1), checked for every row before anything is written."""
    first_seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        if row.currency != currency:
            raise ContractViolation(
                "currency_mismatch", f"row {i} is in {row.currency}, the account is in {currency}"
            )
        if row.amount_minor == 0:
            raise ContractViolation("zero_amount", f"row {i} has amount 0: a zero booking is not emitted")
        if row.source_id is not None:
            if row.source_id in first_seen:
                raise ContractViolation(
                    "repeated_source_id",
                    f"row {i} repeats the source_id of row {first_seen[row.source_id]}",
                )
            first_seen[row.source_id] = i


Live = tuple[IncomingRow, str, str]


def _identity_step(conn: Connection, account_id: int, live: list[Live]) -> tuple[set[int], int, list[Live]]:
    """Step 1. Returns (existing rows used up, rows skipped, rows still to place)."""
    sids = [v for _, c, v in live if c == "source_id"]
    hashes = [v for _, c, v in live if c == "content_hash"]
    found = conn.execute(
        text(
            "SELECT id, source_id, content_hash, duplicate_of FROM source_transaction"
            " WHERE account_id = :a AND (source_id = ANY(:sids) OR content_hash = ANY(:hashes))"
        ),
        {"a": account_id, "sids": sids, "hashes": hashes},
    ).all()
    by_sid = {r.source_id: r for r in found if r.source_id is not None}
    by_hash = {r.content_hash: r for r in found if r.content_hash is not None}
    used: set[int] = set()
    skipped = 0
    remaining: list[Live] = []
    for item in live:
        _, col, value = item
        hit = (by_sid if col == "source_id" else by_hash).get(value)
        if hit is None:
            remaining.append(item)
            continue
        skipped += 1
        used.add(hit.id)
        if hit.duplicate_of is not None:  # a duplicate also accounts for its original
            used.add(hit.duplicate_of)
    return used, skipped, remaining


def _amount_step(
    conn: Connection, account_id: int, remaining: list[Live], used: set[int]
) -> list[int | None]:
    """Step 2. For each remaining row, the existing row it duplicates, or None.

    Candidates: imported (importer IS NOT NULL), not themselves duplicates, not used
    up by step 1, read BEFORE this delivery writes, so its own rows never qualify.
    """
    if not remaining:
        return []
    days = sorted({row.booked_on for row, _, _ in remaining})
    cands = conn.execute(
        text(
            "SELECT id, booked_on, amount, purpose FROM source_transaction"
            " WHERE account_id = :a AND booked_on = ANY(:days) AND importer IS NOT NULL"
            " AND duplicate_of IS NULL ORDER BY id"
        ),
        {"a": account_id, "days": days},
    ).all()
    pool: dict[tuple[date, int], list[tuple[int, str]]] = {}
    for c in cands:
        if c.id not in used:
            pool.setdefault((c.booked_on, c.amount), []).append((c.id, canonical_text(c.purpose)))
    out: list[int | None] = []
    for row, _, _ in remaining:
        options = pool.get((row.booked_on, row.amount_minor), [])
        if not options:
            out.append(None)
            continue
        want = canonical_text(row.purpose)
        pick = next((i for i, (_, p) in enumerate(options) if p == want), 0)  # options are id-ordered
        out.append(options.pop(pick)[0])
    return out


def _insert_source(
    conn: Connection,
    run: Any,
    account_id: int,
    row: IncomingRow,
    col: str,
    value: str,
    duplicate_of: int | None,
) -> int | None:
    params: dict[str, Any] = {
        "importer": run.importer,
        "inst": run.importer_instance_id,
        "run_id": run.id,
        "account": account_id,
        "source_id": value if col == "source_id" else None,
        "content_hash": value if col == "content_hash" else None,
        "source_format": row.source_format,
        "amount": row.amount_minor,
        "currency": row.currency,
        "booked_on": row.booked_on,
        "value_on": row.value_on,
        "instr_amount": row.instructed_amount_minor,
        "instr_currency": row.instructed_currency,
        "cp_ref": row.counterparty_ref,
        "cp_bic": row.counterparty_bic,
        "cp_name": row.counterparty_name,
        "purpose": row.purpose,
        "e2e": row.end_to_end_id,
        "mandate": row.mandate_ref,
        "booking_text": row.booking_text,
        "raw": json.dumps(row.raw, default=str),
        "dup": duplicate_of,
    }
    return conn.execute(
        text(
            "INSERT INTO source_transaction (importer, importer_instance_id, import_run_id,"
            " account_id, source_id, content_hash, source_format, amount, currency, booked_on,"
            " value_on, instructed_amount, instructed_currency, counterparty_ref, counterparty_bic,"
            " counterparty_name, purpose, end_to_end_id, mandate_ref, booking_text, raw, duplicate_of)"
            " VALUES (:importer, :inst, :run_id, :account, :source_id, :content_hash, :source_format,"
            " :amount, :currency, :booked_on, :value_on, :instr_amount, :instr_currency, :cp_ref,"
            " :cp_bic, :cp_name, :purpose, :e2e, :mandate, :booking_text, CAST(:raw AS jsonb), :dup)"
            " ON CONFLICT DO NOTHING RETURNING id"
        ),
        params,
    ).scalar_one_or_none()
