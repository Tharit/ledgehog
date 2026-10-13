"""`commit` (architecture §4.1, §5.2, spec §5.9, §6): the draft written, in one transaction, then settled.

The transaction takes the settle lock shared, then the account locks ascending for every account of the
unit, then the entry rows ascending (`utils.db.locks`). The unit is read BEFORE the locks to know which
accounts to take; after them the closure is read again, and a different one is `UnitMoved` (409): the
draft was made for a unit that is no longer that unit. Then the versions the client carries are checked
(`VersionConflict`, naming the entries that moved or that the client gave no version for) and the draft is
laid over the stored state AGAIN, under the locks, by the same `overlay.plan_unit` the preview used. A
result that would break an invariant is refused by code (`CommitRefused`, the preview's machine codes); the
deferred triggers are a net, not the check.

What is written: a pair the draft breaks is undone (`removal.unpair`, so a partner is left behind as
the removal routine leaves it), removed entries go through `removal.remove_entries`, created entries are
inserted with real ids and inherit the original's tags, and every entry of the draft takes the values and the
keys the plan derived (§5.9). An entry whose values already are the plan's is not written at all, so a commit
that changes nothing bumps nothing and succeeds. A commit does not confirm (D165): `settle` runs after the
commit and reports its own failure in the result, never raising into the committed write.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

import psycopg.errors
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.domain.errors import VersionConflict
from app.core.ingest.duplicates import _check_versions
from app.core.ingest.removal import remove_entries, unpair
from app.core.ledger.entries import EntryRow, entries_by_ids
from app.core.settle.settle import SettleResult, settle
from app.core.stale import StaleReference
from app.core.units.closure import UnitEntry, units_of
from app.core.units.draft import UnitDraft
from app.core.units.lookup import unit_ids_of
from app.core.units.overlay import plan_unit
from app.core.units.plan import Consequence, Plan, PlannedRow, Problem
from app.core.units.preview import UnitNotFound
from app.core.units.state import UnitState, unit_state
from app.core.units.stored import load_stored_entries, load_world
from app.utils.db.errors import constraint_name
from app.utils.db.locks import lock_accounts, lock_rows, lock_settle_shared, retry_on_deadlock

# rows of settle-touched entries beyond the unit that the response carries in full; the rest are ids
OTHER_ROWS_CAP = 200
OTHER_IDS_CAP = 5000

_ENTITY = {"category_id": "category", "payee_id": "payee", "counter_account_id": "account"}


class UnitMoved(Exception):
    """The unit's closure changed between reading it and holding its locks. Nothing was written."""

    def __init__(self, anchor_entry_id: int) -> None:
        self.anchor_entry_id = anchor_entry_id
        super().__init__(
            f"the unit of entry {anchor_entry_id} changed while it was being committed: reload it"
        )


class CommitRefused(Exception):
    """The result would break an invariant. `problems` are the preview's, with machine codes."""

    def __init__(self, problems: tuple[Problem, ...]) -> None:
        self.problems = problems
        super().__init__("the draft would break an invariant: " + ", ".join(p.code for p in problems))


@dataclass(frozen=True)
class CommittedUnit:
    anchor_entry_id: int
    entry_ids: tuple[int, ...]
    state: UnitState


@dataclass(frozen=True)
class CommitResult:
    created: Mapping[int, int]  # the draft's temporary id -> the real id
    removed_entry_ids: tuple[int, ...]
    entries: tuple[EntryRow, ...]  # the unit, its consequences, and settle-touched rows up to the cap
    other_entry_ids: tuple[int, ...]  # settle-touched entries beyond the rows carried, ascending
    truncated: bool  # `other_entry_ids` is itself cut short
    units: tuple[CommittedUnit, ...]
    consequences: tuple[Consequence, ...]  # entry ids are real ones
    versions: Mapping[int, int]  # the version of every entry of `entries` the unit holds, after the write
    settle: SettleResult


def _read_closure(conn: Connection, anchor_entry_id: int) -> tuple[int, ...] | None:
    ids = unit_ids_of(conn, anchor_entry_id)
    return None if ids is None else ids.entry_ids


def _accounts_of(conn: Connection, entry_ids: tuple[int, ...]) -> set[int]:
    return {
        int(a)
        for a in conn.execute(
            text("SELECT DISTINCT account_id FROM ledger_entry WHERE id = ANY(:ids)"),
            {"ids": list(entry_ids)},
        ).scalars()
    }


_INSERT = text(
    "INSERT INTO ledger_entry (source_transaction_id, account_id, amount, currency, booked_on, value_on,"
    " type, payee_id, category_id, counter_account_id, description, note, derivation)"
    " VALUES (:src, :account, :amount, :currency, :booked_on, :value_on, :type, :payee, :category, :counter,"
    " :description, :note, CAST(:derivation AS jsonb)) RETURNING id"
)

_UPDATE = text(
    "UPDATE ledger_entry SET type = :type, payee_id = :payee, category_id = :category,"
    " counter_account_id = :counter, amount = :amount, description = :description, note = :note,"
    " derivation = CAST(:derivation AS jsonb) WHERE id = :id"
)


def _stale(plan: Plan) -> None:
    for p in plan.problems:
        if p.code == "stale_reference":
            field = p.field or "id"
            found = p.detail.get("id")
            raise StaleReference(field, _ENTITY.get(field, "row"), int(found) if found is not None else None)


def _write(conn: Connection, plan: Plan) -> dict[int, int]:
    """The plan's writes; returns the real ids of the created entries by temporary id."""
    if plan.unpaired_entry_ids:
        unpair(conn, plan.unpaired_entry_ids)
    if plan.removed:
        remove_entries(conn, [e.id for e in plan.removed])
    created: dict[int, int] = {}
    for row in plan.rows:
        if row.stored is not None:
            continue
        w = row.written
        created[row.id] = int(
            conn.execute(
                _INSERT,
                {
                    "src": row.source_transaction_id,
                    "account": row.account_id,
                    "amount": w.amount,
                    "currency": row.currency,
                    "booked_on": row.booked_on,
                    "value_on": row.value_on,
                    "type": w.type,
                    "payee": w.payee_id,
                    "category": w.category_id,
                    "counter": w.counter_account_id,
                    "description": w.description,
                    "note": w.note,
                    "derivation": json.dumps(w.derivation),
                },
            ).scalar_one()
        )
        if row.tag_ids:
            conn.execute(
                text(
                    "INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id)"
                    " SELECT :e, unnest(CAST(:t AS bigint[]))"
                ),
                {"e": created[row.id], "t": list(row.tag_ids)},
            )
    # entries that stop being transfers first: one transfer per source is a unique index, checked per row
    changing = [r for r in plan.rows if r.stored is not None and r.written.accepted and _differs(r)]
    for row in sorted(changing, key=lambda r: (r.written.type == "transfer", r.id)):
        w = row.written
        conn.execute(
            _UPDATE,
            {
                "id": row.id,
                "type": w.type,
                "payee": w.payee_id,
                "category": w.category_id,
                "counter": w.counter_account_id,
                "amount": w.amount,
                "description": w.description,
                "note": w.note,
                "derivation": json.dumps(w.derivation),
            },
        )
    return created


def _differs(row: PlannedRow) -> bool:
    s, w = row.stored, row.written
    assert s is not None
    return (
        (s.type, s.payee_id, s.category_id, s.counter_account_id, s.amount, s.description, s.note)
        != (w.type, w.payee_id, w.category_id, w.counter_account_id, w.amount, w.description, w.note)
        or dict(s.derivation) != dict(w.derivation)
        or s.counterpart_entry_id != w.counterpart_entry_id
    )


def _commit_once(engine: Engine, draft: UnitDraft) -> tuple[Plan, dict[int, int], tuple[int, ...]]:
    closure: tuple[int, ...] = ()
    try:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            before = _read_closure(conn, draft.anchor_entry_id)
            if before is None:
                raise UnitNotFound(draft.anchor_entry_id)
            closure = before
            lock_accounts(conn, _accounts_of(conn, before))
            lock_rows(conn, "ledger_entry", before)
            after = _read_closure(conn, draft.anchor_entry_id)
            if after != before:
                raise UnitMoved(draft.anchor_entry_id)
            _check_versions(conn, draft.versions, written=before)
            stored = load_stored_entries(conn, draft.anchor_entry_id, before)
            plan = plan_unit(stored, draft, load_world(conn, stored, draft))
            _stale(plan)
            if plan.problems:
                raise CommitRefused(plan.problems)
            created = _write(conn, plan)
        return plan, created, before
    except DBAPIError as exc:
        orig = exc.orig
        if isinstance(orig, psycopg.errors.UniqueViolation):
            # a partner or a transfer slot taken between the check and the write: a named conflict
            raise VersionConflict(closure) from exc
        if isinstance(orig, psycopg.errors.CheckViolation | psycopg.errors.RaiseException):
            raise CommitRefused(
                (Problem("invariant_violated", detail={"constraint": constraint_name(exc)}),)
            ) from exc
        raise


def commit_unit(engine: Engine, draft: UnitDraft) -> CommitResult:
    """Write `draft`, then settle. Raises `UnitNotFound`, `DraftError`, `UnitMoved`, `VersionConflict`,
    `StaleReference`, `CommitRefused` and `WriteConflict` (a deadlock lost twice); nothing is written then."""
    plan, created, _closure = retry_on_deadlock(lambda: _commit_once(engine, draft))
    settled = settle(engine)
    return _result(engine, plan, created, settled)


def _result(engine: Engine, plan: Plan, created: Mapping[int, int], settled: SettleResult) -> CommitResult:
    real = {r.id if r.id > 0 else created[r.id] for r in plan.rows}
    touched = [i for i in settled.touched_entry_ids if i not in real]
    with engine.connect() as conn:
        rows = entries_by_ids(conn, [*sorted(real), *touched[:OTHER_ROWS_CAP]])
    other = touched[OTHER_ROWS_CAP:]
    unit_rows = [r for r in rows if r.id in real]
    units: list[CommittedUnit] = []
    entries = [
        UnitEntry(r.id, r.source_transaction_id, r.type, r.category_id, r.counterpart_entry_id, r.derivation)
        for r in unit_rows
    ]
    for unit in units_of(entries).values():
        units.append(
            CommittedUnit(
                anchor_entry_id=unit[0].id, entry_ids=tuple(e.id for e in unit), state=unit_state(list(unit))
            )
        )
    consequences = tuple(Consequence(created.get(c.entry_id, c.entry_id), c.kind) for c in plan.consequences)
    return CommitResult(
        created=dict(created),
        removed_entry_ids=tuple(e.id for e in plan.removed),
        entries=tuple(rows),
        other_entry_ids=tuple(other[:OTHER_IDS_CAP]),
        truncated=len(other) > OTHER_IDS_CAP,
        units=tuple(sorted(units, key=lambda u: u.anchor_entry_id)),
        consequences=consequences,
        versions={r.id: r.version for r in unit_rows},
        settle=settled,
    )
