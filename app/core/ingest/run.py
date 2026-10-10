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
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.balance.derived import recompute_derived
from app.core.balance.difference import records_since_zero, unexplained_difference
from app.core.balance.records import insert_reported_record
from app.core.domain.errors import ContractViolation, IngestError
from app.core.ingest.entries import insert_entries
from app.core.ingest.identity import ContentHash, SourceId, assign_ordinals, canonical_text, identity_of
from app.core.plugins.importer import IncomingRow
from app.core.settle.settle import SettleResult, settle
from app.utils.db.locks import lock_accounts, lock_settle_shared, retry_on_deadlock

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
    run_id: int | None  # None for a preview: its run row never existed outside the rolled-back transaction
    inserted: int  # rows written with an entry
    # (new source_transaction id, id of the existing row it duplicates), delivery order
    duplicates: tuple[tuple[int, int], ...]
    skipped_by_identity: int
    importer_stats: Mapping[str, int]  # the importer's own counts (filtered, ...), as reported
    balance_record_id: int | None  # the run's reported record, when it reported a balance
    unexplained_difference_before: int | None  # the account's, before the delivery wrote anything
    unexplained_difference_after: int | None
    settle: SettleResult | None  # None for a preview: it never settles
    stats: Mapping[str, Any] = MappingProxyType({})  # the run summary as stored (spec §5.10)


@dataclass(frozen=True)
class _Counts:
    inserted: int
    duplicates: tuple[tuple[int, int], ...]
    skipped_by_identity: int
    balance_record_id: int | None
    difference_before: int | None
    difference_after: int | None
    stats: Mapping[str, Any]


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
        return _insert_running(conn, account_id, importer, importer_instance_id, started_by)


def _insert_running(
    conn: Connection, account_id: int, importer: str, importer_instance_id: int | None, started_by: int | None
) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO import_run (importer, importer_instance_id, emits, account_id,"
                " status, started_by) VALUES (:importer, :inst, 'transactions', :account, 'running', :by)"
                " RETURNING id"
            ),
            {"importer": importer, "inst": importer_instance_id, "account": account_id, "by": started_by},
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


def _fail_run_quietly(engine: Engine, run_id: int, error: str) -> None:
    """`fail_run` that never raises: the caller is about to re-raise the original error."""
    try:
        fail_run(engine, run_id, error)
    except Exception:
        log.exception("could not mark run %s failed", run_id)


def ingest_delivery(
    engine: Engine,
    run_id: int,
    rows: Sequence[IncomingRow],
    *,
    reported_balance: int | None = None,
    reported_balance_on: date | None = None,
    covered_from: date | None = None,
    covered_through: date | None = None,
    importer_stats: Mapping[str, int] | None = None,
) -> RunResult:
    """Write one delivery for the run's account, atomically, then settle.

    On any failure everything the delivery wrote is rolled back, the run ends
    `failed` and the error is re-raised. A record that breaks the importer's contract
    (wrong currency, zero amount, a repeated `source_id`, no coverage, a balance without
    its date or dated after the coverage) is never repaired, skipped or counted: it raises
    `ContractViolation` naming the rule. `importer_stats` are the importer's own counts
    (rows it dropped before delivery, ...); they are stored under `stats["importer"]` and
    returned. A reported balance is written as the run's balance record before the derived
    entries are recomputed; the run summary (`stats`) carries it, the unexplained difference
    before and after, and the records since the running sum was last zero (spec §5.10).
    """
    try:
        given = _checked_stats(importer_stats)

        def attempt() -> _Counts:
            with engine.begin() as conn:
                return _write_delivery(
                    conn,
                    run_id,
                    rows,
                    reported_balance,
                    reported_balance_on,
                    covered_from,
                    covered_through,
                    given,
                )

        counts = retry_on_deadlock(attempt)
    except BaseException as exc:  # cancellation and interrupts too: the run must not stay `running`
        _fail_run_quietly(engine, run_id, f"{type(exc).__name__}: {exc}")
        raise
    settled = settle(engine)  # never raises: a failure comes back on the result (architecture §5.2)
    return RunResult(
        run_id=run_id,
        inserted=counts.inserted,
        duplicates=counts.duplicates,
        skipped_by_identity=counts.skipped_by_identity,
        importer_stats=MappingProxyType(dict(given)),
        balance_record_id=counts.balance_record_id,
        unexplained_difference_before=counts.difference_before,
        unexplained_difference_after=counts.difference_after,
        settle=settled,
        stats=MappingProxyType(counts.stats),
    )


class _Rollback(Exception):
    """Carries a preview's counts out of the transaction, which it rolls back."""

    def __init__(self, counts: _Counts) -> None:
        super().__init__("preview")
        self.counts = counts


def preview_delivery(
    engine: Engine,
    *,
    account_id: int,
    instance_id: int | None,
    importer: str,
    rows: Sequence[IncomingRow],
    reported_balance: int | None = None,
    reported_balance_on: date | None = None,
    covered_from: date | None = None,
    covered_through: date | None = None,
    importer_stats: Mapping[str, int] | None = None,
) -> RunResult:
    """What `ingest_delivery` would write, by running the same write path in one transaction
    that is rolled back (architecture §4.1 'Previewed'): a temporary run row, the shared
    `_write_delivery`, then a rollback. Nothing persists and nothing settles. Failures are the
    real ones: `ContractViolation` and the rest are raised, for the caller to present.
    """
    given = _checked_stats(importer_stats)

    def attempt() -> _Counts:
        try:
            with engine.begin() as conn:
                lock_settle_shared(conn)  # first, as for every write (the body takes it again: it stacks)
                run_id = _insert_running(conn, account_id, importer, instance_id, None)
                counts = _write_delivery(
                    conn,
                    run_id,
                    rows,
                    reported_balance,
                    reported_balance_on,
                    covered_from,
                    covered_through,
                    given,
                )
                raise _Rollback(counts)
        except _Rollback as done:
            return done.counts

    counts = retry_on_deadlock(attempt)
    return RunResult(
        run_id=None,
        inserted=counts.inserted,
        duplicates=counts.duplicates,
        skipped_by_identity=counts.skipped_by_identity,
        importer_stats=MappingProxyType(dict(given)),
        balance_record_id=counts.balance_record_id,
        unexplained_difference_before=counts.difference_before,
        unexplained_difference_after=counts.difference_after,
        settle=None,
        stats=MappingProxyType(counts.stats),
    )


def _checked_stats(importer_stats: Mapping[str, int] | None) -> dict[str, int]:
    """A copy of the importer's counts; each must be a non-negative int."""
    out = dict(importer_stats or {})
    for key, value in out.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"importer_stats[{key!r}] must be a non-negative int, got {value!r}")
    return out


def _write_delivery(
    conn: Connection,
    run_id: int,
    rows: Sequence[IncomingRow],
    reported_balance: int | None,
    reported_balance_on: date | None,
    covered_from: date | None,
    covered_through: date | None,
    importer_stats: dict[str, int],
) -> _Counts:
    """The one write body, run by `ingest_delivery` (committed) and `preview_delivery` (rolled
    back) inside the caller's transaction."""
    lock_settle_shared(conn)
    run = conn.execute(
        text("SELECT id, account_id, importer, importer_instance_id, status FROM import_run WHERE id = :i"),
        {"i": run_id},
    ).one_or_none()
    if run is None:
        raise IngestError(f"no such run: {run_id}")
    account_id: int = run.account_id
    lock_accounts(conn, [account_id])
    # The first look was before the lock wait: judge the status as it is now, row-locked.
    status: str = conn.execute(
        text("SELECT status FROM import_run WHERE id = :i FOR UPDATE"), {"i": run_id}
    ).scalar_one()
    if status != "running":
        raise IngestError(f"run {run_id} is {status}, not running")
    if covered_through is None:
        raise ContractViolation(
            "no_coverage", "covered_through is required: a successful run says how far it covers"
        )
    if (reported_balance is None) != (reported_balance_on is None):
        missing = "reported_balance_on" if reported_balance_on is None else "reported_balance"
        raise ContractViolation(
            "balance_without_date", f"{missing} is missing: a reported balance comes with its date"
        )
    if reported_balance_on is not None and reported_balance_on > covered_through:
        raise ContractViolation(
            "balance_after_coverage",
            f"the balance is dated {reported_balance_on}, after the coverage end {covered_through}",
        )
    currency: str = conn.execute(
        text("SELECT currency FROM account WHERE id = :i"), {"i": account_id}
    ).scalar_one()

    _check_contract(rows, currency)
    difference_before = unexplained_difference(conn, account_id)

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
    for start in range(0, len(remaining), _CHUNK):
        chunk = remaining[start : start + _CHUNK]
        ids = _insert_sources(conn, run, account_id, chunk, pairing[start : start + _CHUNK])
        to_entry: list[int] = []
        for (_, col, value), original in zip(chunk, pairing[start : start + _CHUNK], strict=True):
            new_id = ids.get((col, value))
            if new_id is None:  # identity taken by a concurrent insert: skipped (I4)
                skipped += 1
            elif original is not None:
                duplicates.append((new_id, original))
            else:
                to_entry.append(new_id)
        insert_entries(conn, to_entry)
        inserted += len(to_entry)

    record_id: int | None = None
    if reported_balance is not None and reported_balance_on is not None:
        record_id = insert_reported_record(
            conn,
            account_id=account_id,
            import_run_id=run_id,
            balance_on=reported_balance_on,
            balance=reported_balance,
        )
    recompute_derived(conn, account_id)
    difference_after = unexplained_difference(conn, account_id)
    stats: dict[str, Any] = {
        "inserted": inserted,
        "skipped_by_identity": skipped,
        "inserted_as_duplicates": [{"id": n, "duplicate_of": o} for n, o in duplicates],
        "importer": importer_stats,
        "unexplained_difference": {"before": difference_before, "after": difference_after},
        "since_zero": records_since_zero(conn, account_id),
    }
    if reported_balance is not None and reported_balance_on is not None:
        stats["balance"] = {"balance_on": reported_balance_on.isoformat(), "balance": reported_balance}
    conn.execute(
        text(
            "UPDATE import_run SET status = 'ok', finished_at = clock_timestamp(),"
            " covered_from = :from, covered_through = :through, stats = CAST(:stats AS jsonb)"
            " WHERE id = :id"
        ),
        {"id": run_id, "from": covered_from, "through": covered_through, "stats": json.dumps(stats)},
    )
    return _Counts(
        inserted,
        tuple(duplicates),
        skipped,
        record_id,
        difference_before,
        difference_after,
        json.loads(json.dumps(stats)),
    )


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
_CHUNK = 1_000  # source rows per INSERT statement


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


def _insert_sources(
    conn: Connection,
    run: Any,
    account_id: int,
    chunk: list[Live],
    duplicates_of: list[int | None],
) -> dict[tuple[str, str], int]:
    """Insert one chunk of source rows in ONE statement, in delivery order. Returns the new id
    by (identity column, identity value); a row whose identity a concurrent insert took is
    absent (ON CONFLICT DO NOTHING)."""
    records = [
        {
            "ord": n,
            "source_id": value if col == "source_id" else None,
            "content_hash": value if col == "content_hash" else None,
            "source_format": row.source_format,
            "amount": row.amount_minor,
            "currency": row.currency,
            "booked_on": row.booked_on,
            "value_on": row.value_on,
            "instructed_amount": row.instructed_amount_minor,
            "instructed_currency": row.instructed_currency,
            "counterparty_ref": row.counterparty_ref,
            "counterparty_bic": row.counterparty_bic,
            "counterparty_name": row.counterparty_name,
            "purpose": row.purpose,
            "end_to_end_id": row.end_to_end_id,
            "mandate_ref": row.mandate_ref,
            "booking_text": row.booking_text,
            "raw": row.raw,
            "duplicate_of": dup,
        }
        for n, ((row, col, value), dup) in enumerate(zip(chunk, duplicates_of, strict=True))
    ]
    result = conn.execute(
        text(
            "INSERT INTO source_transaction (importer, importer_instance_id, import_run_id,"
            " account_id, source_id, content_hash, source_format, amount, currency, booked_on,"
            " value_on, instructed_amount, instructed_currency, counterparty_ref, counterparty_bic,"
            " counterparty_name, purpose, end_to_end_id, mandate_ref, booking_text, raw, duplicate_of)"
            " SELECT :importer, :inst, :run_id, :account, t.source_id, t.content_hash, t.source_format,"
            " t.amount, t.currency, t.booked_on, t.value_on, t.instructed_amount, t.instructed_currency,"
            " t.counterparty_ref, t.counterparty_bic, t.counterparty_name, t.purpose, t.end_to_end_id,"
            " t.mandate_ref, t.booking_text, t.raw, t.duplicate_of"
            " FROM jsonb_to_recordset(CAST(:records AS jsonb)) AS t(ord int, source_id text,"
            " content_hash text, source_format text, amount bigint, currency text, booked_on date,"
            " value_on date, instructed_amount bigint, instructed_currency text, counterparty_ref text,"
            " counterparty_bic text, counterparty_name text, purpose text, end_to_end_id text,"
            " mandate_ref text, booking_text text, raw jsonb, duplicate_of bigint)"
            " ORDER BY t.ord ON CONFLICT DO NOTHING RETURNING id, source_id, content_hash"
        ),
        {
            "importer": run.importer,
            "inst": run.importer_instance_id,
            "run_id": run.id,
            "account": account_id,
            "records": json.dumps(records, default=str),
        },
    )
    out: dict[tuple[str, str], int] = {}
    for r in result:
        key = ("source_id", r.source_id) if r.source_id is not None else ("content_hash", r.content_hash)
        out[key] = r.id
    return out
