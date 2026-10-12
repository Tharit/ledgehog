"""Payee writes (spec §3.6, architecture §4.1 'Management writes'): create, update, delete, merge.

Same shape as categories: one transaction (settle lock shared, then the payee rows ascending), a
settle after the commit, and a dry run that runs the real code and rolls it back. A merge repoints
entries and rules (`payee_id` and `condition_payee_id`) under the settling flag: no version moves,
nothing is derived again, keys stay. The target's attributes win.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import EllipsisType
from typing import Any

import psycopg.errors
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.ledger.dimensions import (
    DimensionError,
    DuplicateName,
    InvalidValue,
    check_count,
    clean_name,
    clean_presentation,
    clean_text,
    previewable,
    require_count,
)
from app.core.ledger.lookups import PayeeRow, get_payee
from app.core.settle.settle import SettleResult, settle
from app.core.stale import StaleReference
from app.utils.db.errors import constraint_name
from app.utils.db.locks import lock_rows, lock_settle_shared, retry_on_deadlock


class PayeeMissing(DimensionError):
    def __init__(self, payee_id: int) -> None:
        self.payee_id = payee_id
        super().__init__(f"payee {payee_id} does not exist")


class PayeeInUse(DimensionError):
    """Delete refused: entries still reference it; merge it instead."""

    def __init__(self, payee_id: int, held: dict[str, int]) -> None:
        self.held = held
        what = ", ".join(f"{n} {name}" for name, n in held.items())
        super().__init__(f"payee {payee_id} is used by {what} and cannot be deleted: merge it instead")


@dataclass(frozen=True)
class PayeeWritten:
    payee: PayeeRow
    settle: SettleResult


@dataclass(frozen=True)
class RuleRef:
    id: int
    name: str
    sets: str
    role: str  # "sets": the rule sets this payee; "condition": it names it as a condition


@dataclass(frozen=True)
class PayeeDeleteResult:
    payee: PayeeRow
    held: dict[str, int]  # `entries` when any entry references it
    rules: tuple[RuleRef, ...]  # the rules that go with it (deleted only by a real run)
    deleted_rule_ids: tuple[int, ...]  # real run only
    deleted: bool
    settle: SettleResult | None


@dataclass(frozen=True)
class PayeeMergeResult:
    source_id: int
    target: PayeeRow  # as it stands (it keeps its own attributes)
    entry_count: int  # what `expected_count` confirms
    entry_ids: tuple[int, ...]  # real run only
    setting_rule_ids: tuple[int, ...]  # rules repointed whose `payee_id` it was
    condition_rule_ids: tuple[int, ...]  # rules repointed whose `condition_payee_id` it was
    source_document_provider: str | None
    document_provider_lost: bool  # the source names a provider the target does not
    settle: SettleResult | None = None


def _duplicate(exc: DBAPIError) -> bool:
    return constraint_name(exc) == "ux_payee_name"


def _view(conn: Connection, payee_id: int) -> PayeeRow:
    found = get_payee(conn, payee_id)
    if found is None:
        raise PayeeMissing(payee_id)
    return found


def create_payee(
    engine: Engine,
    *,
    name: str,
    note: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    document_provider: str | None = None,
) -> PayeeWritten:
    values = {
        "n": clean_name(name),
        "note": clean_text(note),
        "i": clean_presentation("icon", icon),
        "c": clean_presentation("color", color),
        "d": clean_text(document_provider),
    }

    def run() -> PayeeRow:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            try:
                new_id = conn.execute(
                    text(
                        "INSERT INTO payee (name, note, icon, color, document_provider)"
                        " VALUES (:n, :note, :i, :c, :d) RETURNING id"
                    ),
                    values,
                ).scalar_one()
            except DBAPIError as exc:
                if _duplicate(exc):
                    raise DuplicateName("payee") from exc
                raise
            return _view(conn, int(new_id))

    return PayeeWritten(retry_on_deadlock(run), settle(engine))


def update_payee(
    engine: Engine,
    payee_id: int,
    *,
    name: str | EllipsisType = ...,
    note: str | None | EllipsisType = ...,
    icon: str | None | EllipsisType = ...,
    color: str | None | EllipsisType = ...,
    document_provider: str | None | EllipsisType = ...,
) -> PayeeWritten:
    """Change what is given (`...` leaves a field alone, `None` clears `note`, `icon`, `color`, provider).

    Always settles: matching and waiting for documents read `document_provider` (spec §3.6).
    """
    sets: dict[str, Any] = {}
    if not isinstance(name, EllipsisType):
        sets["name"] = clean_name(name)
    if not isinstance(note, EllipsisType):
        sets["note"] = clean_text(note)
    if not isinstance(icon, EllipsisType):
        sets["icon"] = clean_presentation("icon", icon)
    if not isinstance(color, EllipsisType):
        sets["color"] = clean_presentation("color", color)
    if not isinstance(document_provider, EllipsisType):
        sets["document_provider"] = clean_text(document_provider)

    def run() -> PayeeRow:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if not lock_rows(conn, "payee", [payee_id]):
                raise PayeeMissing(payee_id)
            if sets:
                assignments = ", ".join(f"{col} = :{col}" for col in sets)  # columns are fixed above
                try:
                    conn.execute(
                        text(f"UPDATE payee SET {assignments} WHERE id = :id"),  # noqa: S608
                        {**sets, "id": payee_id},
                    )
                except DBAPIError as exc:
                    if _duplicate(exc):
                        raise DuplicateName("payee") from exc
                    raise
            return _view(conn, payee_id)

    return PayeeWritten(retry_on_deadlock(run), settle(engine))


def _rules_of(conn: Connection, payee_id: int) -> tuple[RuleRef, ...]:
    rows = conn.execute(
        text(
            "SELECT id, name, sets, CASE WHEN payee_id = :p THEN 'sets' ELSE 'condition' END AS role"
            " FROM rule WHERE payee_id = :p OR condition_payee_id = :p ORDER BY id FOR UPDATE"
        ),
        {"p": payee_id},
    )
    return tuple(RuleRef(int(r.id), r.name, r.sets, r.role) for r in rows)


def _entries_of(conn: Connection, payee_id: int) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM ledger_entry WHERE payee_id = :p"), {"p": payee_id}
        ).scalar_one()
    )


class _Backstop(Exception):
    """The RESTRICT foreign key refused a delete the pre-check let through (a concurrent write)."""


def delete_payee(engine: Engine, payee_id: int, *, dry_run: bool = False) -> PayeeDeleteResult:
    """Delete a payee no entry references, with the rules that set it or name it as a condition.

    `dry_run` lists those rules and what stands in the way, and writes nothing. A real delete of a
    payee entries still reference is `PayeeInUse`: it is merged instead.
    """

    def work(conn: Connection) -> PayeeDeleteResult:
        if not lock_rows(conn, "payee", [payee_id]):
            raise PayeeMissing(payee_id)
        row = _view(conn, payee_id)
        entries = _entries_of(conn, payee_id)
        held = {"entries": entries} if entries else {}
        rules = _rules_of(conn, payee_id)
        if dry_run:
            return PayeeDeleteResult(row, held, rules, (), False, None)
        if held:
            raise PayeeInUse(payee_id, held)
        try:
            with conn.begin_nested():
                conn.execute(text("DELETE FROM payee WHERE id = :p"), {"p": payee_id})  # rules cascade
        except DBAPIError as exc:
            if isinstance(exc.orig, psycopg.errors.ForeignKeyViolation | psycopg.errors.RestrictViolation):
                raise _Backstop from exc
            raise
        return PayeeDeleteResult(row, {}, rules, tuple(r.id for r in rules), True, None)

    try:
        result = retry_on_deadlock(lambda: previewable(engine, dry_run, work))
    except _Backstop:
        with engine.connect() as conn:
            raise PayeeInUse(payee_id, {"entries": _entries_of(conn, payee_id)}) from None
    return result if dry_run else replace(result, settle=settle(engine))


def merge_payee(
    engine: Engine, source_id: int, target_id: int, *, dry_run: bool, expected_count: int | None
) -> PayeeMergeResult:
    """Merge `source_id` into `target_id` (spec §3.6); `dry_run` reports and writes nothing.

    Entries (`payee_id`) and rules (`payee_id`, `condition_payee_id`) are repointed under the
    settling flag, then the source is deleted last. The target's attributes win; the result says
    when that loses the source's `document_provider`. The real run carries the dry run's
    `entry_count`; another number writes nothing (`MergeCountChanged`).
    """
    require_count(dry_run, expected_count)

    def work(conn: Connection) -> PayeeMergeResult:
        found = lock_rows(conn, "payee", [source_id, target_id])
        if source_id not in found:
            raise PayeeMissing(source_id)
        if target_id not in found:
            raise StaleReference("into", "payee", target_id)
        if source_id == target_id:
            raise InvalidValue("into", "a payee cannot be merged into itself")
        source, target = _view(conn, source_id), _view(conn, target_id)
        conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))  # no version bumps (D200)
        params = {"s": source_id, "t": target_id}
        entry_ids = [
            int(i)
            for i in conn.execute(
                text("UPDATE ledger_entry SET payee_id = :t WHERE payee_id = :s RETURNING id"), params
            ).scalars()
        ]
        setting = [
            int(i)
            for i in conn.execute(
                text("UPDATE rule SET payee_id = :t WHERE payee_id = :s RETURNING id"), params
            ).scalars()
        ]
        condition = [
            int(i)
            for i in conn.execute(
                text("UPDATE rule SET condition_payee_id = :t WHERE condition_payee_id = :s RETURNING id"),
                params,
            ).scalars()
        ]
        conn.execute(text("DELETE FROM payee WHERE id = :s"), {"s": source_id})
        check_count(dry_run, expected_count, len(entry_ids))
        return PayeeMergeResult(
            source_id=source_id,
            target=target,
            entry_count=len(entry_ids),
            entry_ids=() if dry_run else tuple(sorted(entry_ids)),
            setting_rule_ids=tuple(sorted(setting)),
            condition_rule_ids=tuple(sorted(condition)),
            source_document_provider=source.document_provider,
            document_provider_lost=source.document_provider is not None
            and source.document_provider != target.document_provider,
        )

    result = retry_on_deadlock(lambda: previewable(engine, dry_run, work))
    return result if dry_run else replace(result, settle=settle(engine))
