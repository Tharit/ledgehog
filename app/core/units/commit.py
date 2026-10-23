"""`commit` (architecture §4.1, §5.2, spec §5.9, §6): the draft written, in one transaction, then settled.

The transaction takes the settle lock shared, then the account locks ascending for every account of the
unit, then the entry rows ascending (`utils.db.locks`). The unit is the unit AS DRAFTED: the anchor's closure
plus the closure of every partner the draft picks (which holds the former partners of both legs) and of
every carrier of a document it picks (all the carriers of a document are one unit, I21). The
proposals the preview shows are taken as picks first (`preview.resolve_draft`, limited to those whose
entries the client carries versions for): a commit accepts every proposal shown, as the user's decision. The
unit is read BEFORE the locks to know which accounts to take; after them the closure is read again, and a
different one is `UnitMoved` (409): the
draft was made for a unit that is no longer that unit. Then the versions the client carries are checked
(`VersionConflict`, naming the entries that moved or that the client gave no version for) and the draft is
laid over the stored state AGAIN, under the locks, by the same `overlay.plan_unit` the preview used. A
result that would break an invariant is refused by code (`CommitRefused`, the preview's machine codes); the
deferred triggers are a net, not the check.

A counter-leg (spec §5.7) is created here and nowhere else: after the locks and the checks a user-authored
source transaction on the counter-account (importer NULL, a random `source_id`, the leg's date and purpose, a
`raw` naming the entry it was created for), its one entry typed `transfer` and paired with the leg, every key
`user`. The counter-account is part of the lock set (the plan under the locks decides which accounts it is: a
changed set takes the transaction again with more locks, as `ledger/sources.py` does), and its derived
entries are recomputed. A source that follows its partner's amount is written with it.

A document the draft picks (spec §5.8) is part of it: the picked documents and the ones the unit carries are
locked, in id order, right after the settle lock and BEFORE the accounts - the order document ingest takes
(documents, then the carriers' accounts, then the entries), so the two cannot deadlock. A pick that names a
document that is gone is `StaleReference` (409), one at another version, or one that an entry the client
carries no version for has been linked to since (a carrier the preview did not show), is `UnitMoved` (409,
with the document and the reason; the unique indexes of I35 are the net under the check). A
commit that carries no document key for a transaction that is offered documents or awaits one is refused
(`document_decision_required`, 422) unless the draft picks or says "none".

What is written: a pair the draft breaks is undone (`removal.unpair`, so a partner is left behind as
the removal routine leaves it), removed entries go through `removal.remove_entries`, created entries are
inserted with real ids and inherit the original's tags (the draft's tag change on top), the tag changes of
stored entries are membership writes that move no version, and every entry of the draft takes the values
and the keys the plan derived (§5.9). An entry whose values already are the plan's is not written at all,
so a commit that changes nothing bumps nothing and succeeds. A commit does not confirm (D165): `settle` runs
after the commit and reports its own failure in the result, never raising into the committed write.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass

import psycopg.errors
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.balance.derived import recompute_derived
from app.core.domain.errors import VersionConflict
from app.core.ingest.duplicates import _check_versions
from app.core.ingest.entries import insert_entry
from app.core.ingest.removal import remove_entries, unpair
from app.core.ledger.entries import EntryRow, entries_by_ids
from app.core.matching import MAX_WINDOW
from app.core.settle.settle import SettleResult, settle
from app.core.stale import StaleReference, stale_from_integrity
from app.core.units.closure import UnitEntry, units_of
from app.core.units.draft import UnitDraft
from app.core.units.lookup import unit_ids_of
from app.core.units.overlay import plan_unit
from app.core.units.plan import Consequence, Plan, PlannedRow, Problem
from app.core.units.preview import UnitNotFound, resolve_draft
from app.core.units.state import UnitState, document_facts_of_flags, leg_states_of_flags, unit_state
from app.core.units.stored import (
    document_pick_ids,
    drafted_closure,
    load_stored_entries,
    load_world,
    missing_tag,
)
from app.utils.db.errors import constraint_name
from app.utils.db.locks import WriteConflict, lock_accounts, lock_rows, lock_settle_shared, retry_on_deadlock

# rows of settle-touched entries beyond the unit that the response carries in full; the rest are ids
OTHER_ROWS_CAP = 200
OTHER_IDS_CAP = 5000

_ENTITY = {
    "category_id": "category",
    "payee_id": "payee",
    "counter_account_id": "account",
    "document_id": "document",
}
# problems that say the document the user chose is not what the preview saw: a conflict, not a refusal
_DOCUMENT_MOVED = {"document_taken": "taken", "document_changed": "version"}


class UnitMoved(Exception):
    """The unit's closure changed between reading it and holding its locks, or the document the draft picks
    is no longer what the preview saw (`reason`: `taken` by another entry, or at another `version`).
    Nothing was written."""

    def __init__(
        self, anchor_entry_id: int, *, document_id: int | None = None, reason: str | None = None
    ) -> None:
        self.anchor_entry_id = anchor_entry_id
        self.document_id = document_id
        self.reason = reason
        super().__init__(
            f"the unit of entry {anchor_entry_id} changed while it was being committed: reload it"
            if document_id is None
            else f"document {document_id} is no longer what was shown ({reason}): reload the unit"
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


def _read_drafted_closure(conn: Connection, draft: UnitDraft) -> tuple[int, ...] | None:
    """The unit as drafted: the anchor's closure, the closure of each picked partner and of the carriers of
    each picked document (ascending)."""
    anchor = _read_closure(conn, draft.anchor_entry_id)
    if anchor is None:
        return None
    return tuple(sorted(drafted_closure(conn, draft, anchor)))


_UNSEEN_CARRIER = text(
    "SELECT document_id FROM ledger_entry"
    " WHERE document_id = ANY(CAST(:docs AS bigint[])) AND id <> ALL(CAST(:seen AS bigint[]))"
    " ORDER BY document_id LIMIT 1"
)


def _taken_since(conn: Connection, draft: UnitDraft, anchor_entry_id: int, seen: Collection[int]) -> None:
    """A document the draft picks that an entry the client carries no version for carries (the preview
    brought every carrier into the unit): linked since, so what the client saw is not the unit (409)."""
    docs = document_pick_ids(draft)
    if not docs:
        return
    found = conn.execute(_UNSEEN_CARRIER, {"docs": docs, "seen": sorted(seen)}).scalar()
    if found is not None:
        raise UnitMoved(anchor_entry_id, document_id=int(found), reason="taken")


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
    " type, payee_id, category_id, counter_account_id, description, note, document_line_id, derivation)"
    " VALUES (:src, :account, :amount, :currency, :booked_on, :value_on, :type, :payee, :category, :counter,"
    " :description, :note, :line, CAST(:derivation AS jsonb)) RETURNING id"
)

# `:line` is the entry's line of the transaction's document (spec §5.8), written in the same statement as
# `:document`: set with a pick of a document of one line, on each entry a split along the lines made, cleared
# whenever the link is changed or dropped
_UPDATE = text(
    "UPDATE ledger_entry SET type = :type, payee_id = :payee, category_id = :category,"
    " counter_account_id = :counter, amount = :amount, description = :description, note = :note,"
    " counterpart_entry_id = :counterpart, document_id = :document, document_line_id = :line,"
    " derivation = CAST(:derivation AS jsonb) WHERE id = :id"
)
# a line an entry of the unit holds and another is to take, let go of first
_FREE_LINES = text("UPDATE ledger_entry SET document_line_id = NULL WHERE id = ANY(:ids)")
_LINE_IDS = text(
    "SELECT l.document_id, l.line_no, l.id FROM external_document_line AS l"
    " JOIN unnest(CAST(:docs AS bigint[]), CAST(:nos AS int[])) AS v(d, n)"
    " ON l.document_id = v.d AND l.line_no = v.n"
)


_LOCK_ROUNDS = 3


class _MoreLocks(Exception):
    """The plan under the locks creates counter-legs on accounts that are not locked: run again with them."""

    def __init__(self, accounts: set[int]) -> None:
        super().__init__("accounts to lock: " + ", ".join(map(str, sorted(accounts))))
        self.accounts = accounts


def counter_leg_accounts(plan: Plan) -> set[int]:
    """The accounts the counter-legs of `plan` are created on."""
    return {r.account_id for r in plan.rows if r.counter_leg_for is not None}


def _insert_counter_leg(conn: Connection, row: PlannedRow) -> int:
    """The counter-leg (spec §5.7): a user-authored source transaction on the counter-account (I1, I40: the
    trigger holds, the plan has checked it first), its entry, typed `transfer` and paired with the leg."""
    leg = row.counter_leg_for
    assert leg is not None
    w = row.written
    source_id = int(
        conn.execute(
            text(
                "INSERT INTO source_transaction (account_id, source_id, amount, currency, booked_on,"
                " purpose, raw) VALUES (:a, :s, :amount, :currency, :on, :purpose, CAST(:raw AS jsonb))"
                " RETURNING id"
            ),
            {
                "a": row.account_id,
                "s": str(uuid.uuid4()),
                "amount": row.amount,
                "currency": row.currency,
                "on": row.booked_on,
                "purpose": row.purpose,
                "raw": json.dumps({"counter_leg_for": leg}),
            },
        ).scalar_one()
    )
    entry_id = insert_entry(conn, source_id)
    conn.execute(
        text(
            "UPDATE ledger_entry SET type = 'transfer', counter_account_id = :counter,"
            " counterpart_entry_id = :leg, derivation = CAST(:derivation AS jsonb) WHERE id = :id"
        ),
        {
            "counter": w.counter_account_id,
            "leg": leg,
            "derivation": json.dumps(w.derivation),
            "id": entry_id,
        },
    )
    return entry_id


def _stale(plan: Plan) -> None:
    for p in plan.problems:
        if p.code == "stale_reference":
            field = p.field or "id"
            found = p.detail.get("id")
            raise StaleReference(field, _ENTITY.get(field, "row"), int(found) if found is not None else None)


def _moved(plan: Plan, anchor_entry_id: int) -> None:
    """A document the draft picks that was taken or has moved on since the preview: a conflict (409)."""
    for p in plan.problems:
        if p.code in _DOCUMENT_MOVED:
            found = p.detail.get("document_id")
            raise UnitMoved(
                anchor_entry_id,
                document_id=int(found) if found is not None else None,
                reason=_DOCUMENT_MOVED[p.code],
            )


def _documents_of(conn: Connection, draft: UnitDraft, closure: tuple[int, ...]) -> list[int]:
    """The documents a commit locks: those the draft names, and those the unit's entries carry now."""
    carried = conn.execute(
        text("SELECT document_id FROM ledger_entry WHERE id = ANY(:ids) AND document_id IS NOT NULL"),
        {"ids": list(closure)},
    ).scalars()
    return sorted({*document_pick_ids(draft), *(int(d) for d in carried)})


def _line_ids(conn: Connection, plan: Plan) -> dict[tuple[int, int], int]:
    """The ids of the lines the plan's rows are written with, by (document, line number). The documents are
    locked and the plan was made under the lock, so the lines are as the plan read them; one that is gone is a
    stale reference."""
    wanted = sorted({r.written.document_line for r in plan.rows if r.written.document_line is not None})
    if not wanted:
        return {}
    found = {
        (int(r.document_id), int(r.line_no)): int(r.id)
        for r in conn.execute(_LINE_IDS, {"docs": [d for d, _n in wanted], "nos": [n for _d, n in wanted]})
    }
    for key in wanted:
        if key not in found:
            raise StaleReference("document_line", "document", key[0])
    return found


def _write(conn: Connection, plan: Plan) -> dict[int, int]:
    """The plan's writes; returns the real ids of the created entries by temporary id."""
    if plan.unpaired_entry_ids:
        unpair(conn, plan.unpaired_entry_ids)
    if plan.removed:
        remove_entries(conn, [e.id for e in plan.removed])
    for source_id, amount in sorted(plan.followed_sources.items()):  # I2, I3: a source follows its partner
        conn.execute(
            text(
                "UPDATE source_transaction SET amount = :a, raw = raw || CAST(:patch AS jsonb) WHERE id = :i"
            ),
            {"a": amount, "patch": json.dumps({"amount": amount}), "i": source_id},
        )
    changing = [r for r in plan.rows if r.stored is not None and r.written.accepted and _differs(r)]
    lines = _line_ids(conn, plan)
    # a line that moves from one entry of the unit to another is let go of first (the unique index on a
    # line is checked per row); with every line left to its entry this never happens
    taking = {r.written.document_line for r in plan.rows if r.written.document_line is not None}
    held = [
        r.id
        for r in changing
        if r.stored is not None
        and r.stored.document_line in taking
        and r.stored.document_line != r.written.document_line
    ]
    if held:
        conn.execute(_FREE_LINES, {"ids": sorted(held)})
    created: dict[int, int] = {}
    for row in plan.rows:
        if row.stored is not None:
            continue
        if row.counter_leg_for is not None:
            created[row.id] = _insert_counter_leg(conn, row)
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
                    "line": lines.get(w.document_line) if w.document_line is not None else None,
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
                "counterpart": created.get(w.counterpart_entry_id or 0, w.counterpart_entry_id),
                "document": w.document_id,
                "line": lines.get(w.document_line) if w.document_line is not None else None,
                "derivation": json.dumps(w.derivation),
            },
        )
    return created


_TAG_ADD = text(
    "INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id)"
    " SELECT :e, unnest(CAST(:t AS bigint[])) ON CONFLICT DO NOTHING"
)
_TAG_REMOVE = text("DELETE FROM ledger_entry_tag WHERE ledger_entry_id = :e AND tag_id = ANY(:t)")


def _apply_tags(conn: Connection, draft: UnitDraft) -> None:
    """The draft's tag changes on stored entries, as membership changes (idempotent, composing with
    any tagging made elsewhere since the unit was read). A created row got its tags, the change
    included, with its insert.
    `ledger_entry_tag` writes touch no entry row: no version moves."""
    for i, e in enumerate(draft.entries):
        if e.is_new:
            continue
        if e.tags_remove:
            conn.execute(_TAG_REMOVE, {"e": e.id, "t": sorted(set(e.tags_remove))})
        if e.tags_add:
            try:
                conn.execute(_TAG_ADD, {"e": e.id, "t": sorted(set(e.tags_add))})
            except DBAPIError as exc:  # a tag deleted since the check: still one named conflict
                stale = stale_from_integrity(exc)
                if stale is None or stale.entity != "tag":
                    raise
                raise StaleReference(f"entries[{i}].tags.add", "tag", stale.entity_id) from exc


def _followers_accounts(plan: Plan) -> set[int]:
    """The accounts of the sources that follow their partner: their balance moves with the amount."""
    return {r.account_id for r in plan.rows if r.source_transaction_id in plan.followed_sources}


def _differs(row: PlannedRow) -> bool:
    s, w = row.stored, row.written
    assert s is not None
    return (
        (s.type, s.payee_id, s.category_id, s.counter_account_id, s.amount, s.description, s.note)
        != (w.type, w.payee_id, w.category_id, w.counter_account_id, w.amount, w.description, w.note)
        or dict(s.derivation) != dict(w.derivation)
        or s.counterpart_entry_id != w.counterpart_entry_id
        or s.document_id != w.document_id
        or s.document_line != w.document_line
    )


def _commit_once(
    engine: Engine, draft: UnitDraft, extra_accounts: Collection[int] = ()
) -> tuple[Plan, dict[int, int], tuple[int, ...]]:
    closure: tuple[int, ...] = ()
    try:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            before = _read_drafted_closure(conn, draft)
            if before is None:
                raise UnitNotFound(draft.anchor_entry_id)
            closure = before
            lock_rows(conn, "external_document", _documents_of(conn, draft, before))
            locked = _accounts_of(conn, before) | set(extra_accounts)
            lock_accounts(conn, locked)
            lock_rows(conn, "ledger_entry", before)
            after = _read_drafted_closure(conn, draft)
            _taken_since(conn, draft, draft.anchor_entry_id, draft.versions)
            if after != before:
                raise UnitMoved(draft.anchor_entry_id)
            _check_versions(conn, draft.versions, written=before)
            stored = load_stored_entries(conn, draft.anchor_entry_id, before)
            plan = plan_unit(stored, draft, load_world(conn, stored, draft))
            _stale(plan)
            _moved(plan, draft.anchor_entry_id)
            if (gone := missing_tag(conn, draft)) is not None:
                raise StaleReference(f"entries[{gone[0]}].tags.add", "tag", gone[1])
            if plan.problems:
                raise CommitRefused(plan.problems)
            if not (needed := counter_leg_accounts(plan)) <= locked:
                raise _MoreLocks(needed)
            created = _write(conn, plan)
            _apply_tags(conn, draft)
            for account_id in sorted(needed | _followers_accounts(plan)):
                recompute_derived(conn, account_id)
        return plan, created, before
    except DBAPIError as exc:
        orig = exc.orig
        if isinstance(orig, psycopg.errors.UniqueViolation):
            if (constraint_name(exc) or "").startswith("ux_le_document"):
                # a document taken between the check and the write (I35): the pick moved
                raise UnitMoved(draft.anchor_entry_id, reason="taken") from exc
            # a partner or a transfer slot taken between the check and the write: a named conflict
            raise VersionConflict(closure) from exc
        if isinstance(orig, psycopg.errors.CheckViolation | psycopg.errors.RaiseException):
            raise CommitRefused(
                (Problem("invariant_violated", detail={"constraint": constraint_name(exc)}),)
            ) from exc
        raise


def _commit_locking(engine: Engine, draft: UnitDraft, accounts: set[int]) -> tuple[Plan, dict[int, int]]:
    """`_commit_once`, again with more account locks while the plan under the locks needs them."""

    def attempt(extra: frozenset[int]) -> tuple[Plan, dict[int, int], tuple[int, ...]]:
        return retry_on_deadlock(lambda: _commit_once(engine, draft, extra))

    extra = frozenset(accounts)
    for _round in range(_LOCK_ROUNDS):
        try:
            plan, created, _closure = attempt(extra)
            return plan, created
        except _MoreLocks as more:
            extra |= more.accounts
    raise WriteConflict()


def commit_unit(engine: Engine, draft: UnitDraft) -> CommitResult:
    """Write `draft`, then settle. Raises `UnitNotFound`, `DraftError`, `UnitMoved`, `VersionConflict`,
    `StaleReference`, `CommitRefused` and `WriteConflict` (a deadlock lost twice); nothing is written then."""
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        resolved = resolve_draft(conn, draft, seen=draft.versions)
    effective = resolved.draft
    resolved_plan = resolved.plan
    # a pick is checked against the widest window (the cap): the user chose the partner, and every other
    # rule still applies; `window_days` only says which window the proposals were shown for
    effective = dataclasses.replace(effective, window_days=MAX_WINDOW)
    plan, created = _commit_locking(engine, effective, counter_leg_accounts(resolved_plan))
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
        UnitEntry(
            r.id,
            r.source_transaction_id,
            r.type,
            r.category_id,
            r.counterpart_entry_id,
            r.derivation,
            r.document_id,
        )
        for r in unit_rows
    ]
    leg_states = leg_states_of_flags({r.id: r.review_flags for r in unit_rows})
    facts = document_facts_of_flags([(r.id, r.review_flags) for r in unit_rows if r.type == "flow"])
    for unit in units_of(entries).values():
        units.append(
            CommittedUnit(
                anchor_entry_id=unit[0].id,
                entry_ids=tuple(e.id for e in unit),
                state=unit_state(list(unit), leg_states, facts),
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
