"""User-authored source transactions: the entry form's writes (spec §3.9, §5.6, §5.7, §5.9).

``create_source`` enters a movement on an unsynced account (I1, I40): the source row, its one entry
(I3) and the account's derived entries are written in one transaction. ``update_source`` edits its
amount, date or purpose (never its account): the entries are fitted to the row (I3), a pair that no
longer fits is broken, every remaining entry is resolved afresh (§5.9) and the account's derived
entries are recomputed. ``delete_source`` removes the row and its entries through the removal
routine (§5.6). All three settle after they commit; the edit and the delete take ``dry_run``, which
runs the same code in a transaction that is rolled back and reports what a real run would do.

Lock order of every write (architecture §5.2): the settle lock shared (`previewable`), then the
accounts ascending (the row's, and those of the transfer partners the edit may write, read before
the lock and read again under it: a changed set extends the lock set and the transaction runs again,
as `ingest/duplicates.py` does), then the source row, then the entry rows ascending.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import EllipsisType
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.balance.derived import recompute_derived
from app.core.domain.errors import VersionConflict
from app.core.ingest.entries import insert_entry
from app.core.ingest.removal import Affected, entry_scope, remove_entries, unpair
from app.core.ledger.dimensions import previewable
from app.core.ledger.entries import EntryRow, entries_by_ids
from app.core.plugins.classifier import EntryInput
from app.core.resolution import Resolved, resolve_afresh
from app.core.resolution.confirmed import units_binds, units_sql
from app.core.resolution.load import load_accounts, load_rules
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import load_snapshot
from app.core.settle.resolution import new_derivation
from app.core.settle.settle import SettleResult, settle
from app.core.stale import StaleReference
from app.core.units.read import UnitView, get_unit
from app.utils.db.locks import WriteConflict, lock_accounts, lock_rows, retry_on_deadlock

MAX_PURPOSE = 500
_LOCK_ROUNDS = 3


# ---- errors ------------------------------------------------------------------------------------


class SourceError(Exception):
    """An entry-form write was refused; the message states the rule. Nothing was written."""


class SourceMissing(SourceError, LookupError):
    def __init__(self, source_id: int) -> None:
        self.source_id = source_id
        super().__init__(f"source transaction {source_id} does not exist")


class AccountSynced(SourceError):
    """I40: user-authored transactions exist only on unsynced accounts."""

    def __init__(self, account_id: int) -> None:
        self.account_id = account_id
        super().__init__(
            f"account {account_id} is synced: transactions are entered by hand only on unsynced accounts"
        )


class NotUserAuthored(SourceError):
    """An imported row is immutable and never deleted: it is marked as a duplicate instead (I2)."""

    def __init__(self, source_id: int) -> None:
        self.source_id = source_id
        super().__init__(
            f"source transaction {source_id} was imported: an imported row is never edited or deleted "
            "(mark it as a duplicate instead)"
        )


class SourceIdTaken(SourceError):
    """The client's id is the identity of an imported row on this account."""

    def __init__(self, client_id: str) -> None:
        super().__init__(f"the id {client_id!r} is already the identity of an imported row on this account")


class EmptyEdit(SourceError):
    def __init__(self) -> None:
        super().__init__("an edit changes the amount, the date or the purpose: none was given")


# ---- results -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Units:
    """The units a write concerns, read after settling: the written source's first."""

    views: tuple[UnitView, ...] = ()

    @property
    def entries(self) -> tuple[EntryRow, ...]:
        seen: dict[int, EntryRow] = {}
        for v in self.views:
            for e in v.entries:
                seen[e.id] = e
        return tuple(seen[i] for i in sorted(seen))


@dataclass(frozen=True)
class Created:
    source_id: int
    created: bool  # False: the client's id was already entered (idempotent repeat)
    units: Units
    settle: SettleResult


@dataclass(frozen=True)
class EditEffects:
    """What an edit does beyond rewriting the row: all ascending entry ids."""

    collapsed_entry_ids: tuple[int, ...] = ()  # split entries deleted, absorbed by the original
    unpaired_entry_ids: tuple[int, ...] = ()  # surviving entries that lost their counterpart, partners too
    deleted_entry_ids: tuple[int, ...] = ()  # every entry the edit removes
    rederived_entry_ids: tuple[int, ...] = ()  # entries whose values or keys were derived again
    followed_entry_ids: tuple[int, ...] = ()  # partners that followed the new amount (spec §5.7)
    returned_to_review_ids: tuple[int, ...] = ()  # confirmed before, not confirmed now
    # the versions a real run must carry: the source's entries and the partners it unpairs
    versions: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class Edited:
    source_id: int
    dry_run: bool
    effects: EditEffects
    units: Units  # empty on a dry run
    settle: SettleResult | None  # None on a dry run


@dataclass(frozen=True)
class DeleteCounts:
    entries: int
    confirmed_entries: int  # removed entries whose unit was confirmed (spec §6 'removes confirmed entries')
    tagged_entries: int
    tag_memberships: int
    partners_returning_to_review: int
    freed_documents: int


@dataclass(frozen=True)
class Deleted:
    source_id: int
    dry_run: bool
    removed: tuple[EntryRow, ...]  # as they stood: versions, tags
    counts: DeleteCounts
    freed_document_ids: tuple[int, ...]
    partners: tuple[EntryRow, ...]  # dry run: as they stand; real run: after settling
    units: Units  # real run: the units of the partners left behind
    settle: SettleResult | None


# ---- helpers -----------------------------------------------------------------------------------


def clean_purpose(value: str | None) -> str | None:
    """Trimmed; blank means none."""
    if value is None:
        return None
    return value.strip() or None


def _ints(rows: Any) -> list[int]:
    return [int(i) for i in rows]


def _read_units(engine: Engine, entry_ids: Sequence[int]) -> Units:
    """The unit of each entry (those that still exist), deduplicated, in the order asked."""
    views: dict[int, UnitView] = {}
    with engine.connect() as conn:
        for entry_id in entry_ids:
            view = get_unit(conn, entry_id)
            if view is not None and view.anchor_entry_id not in views:
                views[view.anchor_entry_id] = view
    return Units(tuple(views.values()))


def _ok_of(conn: Connection, entry_ids: Sequence[int]) -> dict[int, bool]:
    """Whether the unit of each of these existing entries is confirmed, as stored (confirmed.py)."""
    if not entry_ids:
        return {}
    rows = conn.execute(
        text(f"SELECT u.id, u.unit_ok FROM ({units_sql(of_entries=True)}) AS u WHERE u.id = ANY(:ids)"),
        {**units_binds(), "ids": list(entry_ids)},
    )
    return {int(r.id): bool(r.unit_ok) for r in rows}


def _check_versions(conn: Connection, expected: Mapping[int, int], written: Sequence[int]) -> None:
    """Lock the entries the write touches (ascending) and compare their versions before any write.

    Entries the write does not touch are not compared. A written entry the caller carries no version for
    counts as moved: the caller's view was incomplete (architecture §4.1).
    """
    lock_rows(conn, "ledger_entry", written)
    current = {
        int(r.id): int(r.version)
        for r in conn.execute(
            text("SELECT id, version FROM ledger_entry WHERE id = ANY(:ids)"), {"ids": sorted(set(written))}
        )
    }
    stale = tuple(sorted(i for i in set(written) if expected.get(i) != current.get(i)))
    if stale:
        raise VersionConflict(stale)


class _AccountsMissing(Exception):
    """The partners involved sit on accounts that were not locked; run again with them added."""

    def __init__(self, accounts: set[int]) -> None:
        super().__init__("accounts to lock: " + ", ".join(map(str, sorted(accounts))))
        self.accounts = accounts


@dataclass(frozen=True)
class _Locked:
    source: Any  # the source_transaction row (id, account_id, importer, amount, currency, booked_on, purpose)
    entry_ids: tuple[int, ...]  # the source's entries, ascending: the first is the original
    partner_ids: tuple[int, ...]  # their partners outside the source, ascending


def _accounts_of(conn: Connection, entry_ids: Collection[int]) -> set[int]:
    if not entry_ids:
        return set()
    return {
        int(a)
        for a in conn.execute(
            text("SELECT DISTINCT account_id FROM ledger_entry WHERE id = ANY(:ids)"),
            {"ids": sorted(entry_ids)},
        ).scalars()
    }


def _entry_ids(conn: Connection, source_id: int) -> list[int]:
    return _ints(
        conn.execute(
            text("SELECT id FROM ledger_entry WHERE source_transaction_id = :s ORDER BY id"), {"s": source_id}
        ).scalars()
    )


def _lock_source(conn: Connection, source_id: int, extra: set[int]) -> _Locked:
    """Lock accounts and the source row (the settle lock is held), then load what the write is about.

    Raises `SourceMissing` and `NotUserAuthored`; `_AccountsMissing` when the partners moved to
    accounts that are not locked yet.
    """
    account = conn.execute(
        text("SELECT account_id FROM source_transaction WHERE id = :i"), {"i": source_id}
    ).scalar_one_or_none()
    if account is None:
        raise SourceMissing(source_id)
    _, partners = entry_scope(conn, _entry_ids(conn, source_id))
    locked = {int(account), *extra, *_accounts_of(conn, partners)}
    lock_accounts(conn, locked)
    lock_rows(conn, "source_transaction", [source_id])
    row = conn.execute(
        text(
            "SELECT id, account_id, importer, amount, currency, booked_on, purpose"
            " FROM source_transaction WHERE id = :i"
        ),
        {"i": source_id},
    ).one_or_none()
    if row is None:
        raise SourceMissing(source_id)
    if row.importer is not None:
        raise NotUserAuthored(source_id)
    entry_ids = _entry_ids(conn, source_id)
    _, partners = entry_scope(conn, entry_ids)
    involved = _accounts_of(conn, partners)
    if not involved <= locked:
        raise _AccountsMissing(involved)
    return _Locked(row, tuple(entry_ids), tuple(partners))


def _rounds[T](engine: Engine, dry_run: bool, work: Callable[[Connection, set[int]], T]) -> T:
    """Run `work(conn, extra_accounts)` as one write transaction, again with more locks when the
    partners it reads moved between the read and the locks."""

    def once(extra: frozenset[int]) -> T:
        return retry_on_deadlock(lambda: previewable(engine, dry_run, lambda conn: work(conn, set(extra))))

    extra: frozenset[int] = frozenset()
    for _ in range(_LOCK_ROUNDS):
        try:
            return once(extra)
        except _AccountsMissing as missing:
            extra |= missing.accounts
    raise WriteConflict()


# ---- create ------------------------------------------------------------------------------------


def create_source(
    engine: Engine,
    *,
    client_id: str,
    account_id: int,
    amount: int,
    booked_on: date,
    purpose: str | None,
) -> Created:
    """Enter a movement on an unsynced account: its source row, its one entry, the derived entries.

    `client_id` is the form's random id, the row's `source_id`: a repeat on the same account returns the
    row already entered (`created=False`) and writes nothing. Raises `StaleReference` (field
    `account_id`) for an unknown account and `AccountSynced` for a synced one.
    """
    purpose = clean_purpose(purpose)
    form = {
        "id": client_id,
        "account_id": account_id,
        "amount": amount,
        "booked_on": booked_on.isoformat(),
        "purpose": purpose,
    }

    def run(conn: Connection) -> tuple[int, int, bool]:
        lock_accounts(conn, [account_id])
        account = conn.execute(
            text(
                "SELECT currency, (closed_on IS NULL AND EXISTS"
                " (SELECT 1 FROM account_source s WHERE s.account_id = account.id)) AS synced"
                " FROM account WHERE id = :a"
            ),
            {"a": account_id},
        ).one_or_none()
        if account is None:
            raise StaleReference("account_id", "account", account_id)
        known = conn.execute(
            text("SELECT id, importer FROM source_transaction WHERE account_id = :a AND source_id = :s"),
            {"a": account_id, "s": client_id},
        ).one_or_none()
        if known is not None:
            if known.importer is not None:
                raise SourceIdTaken(client_id)
            first = conn.execute(
                text("SELECT min(id) FROM ledger_entry WHERE source_transaction_id = :s"), {"s": known.id}
            ).scalar_one()
            return int(known.id), int(first), False
        if account.synced:
            raise AccountSynced(account_id)
        source_id = int(
            conn.execute(
                text(
                    "INSERT INTO source_transaction (account_id, source_id, amount, currency, booked_on,"
                    " purpose, raw) VALUES (:a, :s, :amount, :currency, :on, :purpose, CAST(:raw AS jsonb))"
                    " RETURNING id"
                ),
                {
                    "a": account_id,
                    "s": client_id,
                    "amount": amount,
                    "currency": account.currency,
                    "on": booked_on,
                    "purpose": purpose,
                    "raw": json.dumps(form),
                },
            ).scalar_one()
        )
        entry_id = insert_entry(conn, source_id)
        recompute_derived(conn, account_id)
        return source_id, entry_id, True

    source_id, entry_id, created = retry_on_deadlock(lambda: previewable(engine, False, run))
    result = settle(engine) if created else SettleResult()
    return Created(source_id, created, _read_units(engine, [entry_id]), result)


# ---- edit --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Plan:
    """What fitting the entries to the edited row takes (I3, §5.6); pure."""

    amounts: dict[int, int]  # entry id -> its new amount, for the entries that change
    collapse: tuple[int, ...]
    unpair: tuple[int, ...]  # surviving entries whose pair breaks


def plan_amounts(
    old_amount: int,
    new_amount: int,
    entries: Sequence[tuple[int, int]],
    paired: Mapping[int, str | None],
    currency: str,
    following: Collection[int] = (),
) -> _Plan:
    """The edit's effect on the entries `[(id, amount)]` (ascending, the first is the original).

    The residual (the original) absorbs the change; where that would change its sign or reach zero the
    split collapses: the others go and the original takes the whole amount. A changed amount breaks a
    same-currency pair, a changed sign breaks any pair; `paired` maps the paired entries to their partner's
    currency. A same-currency pair whose partner FOLLOWS (`following`: the entries whose partner is a
    user-authored single-entry leg on an unsynced account, spec §5.7) stands through an amount change, the
    partner taking the negated amount. A date change is not in the plan: it leaves pairs standing.
    """
    original_id, original_amount = entries[0]
    amounts: dict[int, int] = {}
    collapse: tuple[int, ...] = ()
    if new_amount != old_amount:
        if len(entries) == 1:
            amounts[original_id] = new_amount
        else:
            absorbed = original_amount + (new_amount - old_amount)
            if absorbed == 0 or (absorbed > 0) != (original_amount > 0):
                collapse = tuple(i for i, _ in entries[1:])
                amounts[original_id] = new_amount
            else:
                amounts[original_id] = absorbed
    survivors = [i for i, _ in entries if i not in collapse]
    sign_changed = (new_amount > 0) != (old_amount > 0)
    breaks = tuple(
        i
        for i in survivors
        if i in paired and (sign_changed or (i in amounts and paired[i] == currency and i not in following))
    )
    return _Plan(amounts, collapse, breaks)


def _input(row: Any, purpose: str | None, booked_on: date, amount: int) -> EntryInput:
    """A user-authored entry as resolution reads it: only the purpose of the source (§5.9)."""
    return EntryInput(
        entry_id=int(row.id),
        account_id=int(row.account_id),
        currency=str(row.currency),
        booked_on=booked_on,
        amount=amount,
        user_authored=True,
        purpose=purpose,
    )


def _afresh(
    conn: Connection,
    rows: Sequence[Any],
    original_id: int,
    purpose: str | None,
    booked_on: date,
    exclude: frozenset[int],
) -> list[int]:
    """Resolve these entries afresh, every value derived again, and write what differs.

    A transfer needs the original entry (I31): another entry that would resolve to one keeps no value.
    The writer's own transaction, so versions move like any user's edit. Returns the entries rewritten.
    """
    if not rows:
        return []
    accounts = load_accounts(conn)
    classifiers = classifiers_for(load_rules(conn))
    snapshot = load_snapshot(conn)
    written: list[int] = []
    for row in rows:
        resolved = resolve_afresh(
            _input(row, purpose, booked_on, int(row.amount)),
            accounts=accounts,
            classifiers=classifiers,
            history=snapshot,
            exclude_entry_ids=exclude,
        )
        kind = resolved.get("type")
        if kind is not None and kind.value == "transfer" and row.id != original_id:
            resolved = Resolved()
        derivation = new_derivation(row.derivation, resolved)
        values = {
            "type": str(resolved["type"].value) if "type" in resolved else None,
            "payee_id": _value(resolved, "payee"),
            "category_id": _value(resolved, "category"),
            "counter_account_id": _value(resolved, "counter_account"),
        }
        same = (
            values["type"] == row.type
            and values["payee_id"] == row.payee_id
            and values["category_id"] == row.category_id
            and values["counter_account_id"] == row.counter_account_id
            and derivation == dict(row.derivation)
        )
        if same:
            continue
        conn.execute(
            text(
                "UPDATE ledger_entry SET type = :type, payee_id = :payee_id, category_id = :category_id,"
                " counter_account_id = :counter_account_id, derivation = CAST(:d AS jsonb) WHERE id = :id"
            ),
            {**values, "d": json.dumps(derivation), "id": row.id},
        )
        written.append(int(row.id))
    return written


def _value(resolved: Resolved, name: Any) -> int | None:
    d = resolved.get(name)
    return None if d is None else int(d.value)


_ENTRY_ROWS = text(
    "SELECT e.id, e.account_id, e.currency, e.amount, e.type, e.payee_id, e.category_id,"
    " e.counter_account_id, e.derivation, e.version, e.counterpart_entry_id, p.currency AS partner_currency,"
    " p.account_id AS partner_account, p.source_transaction_id AS partner_source,"
    " (ps.importer IS NULL) AS partner_authored,"
    " (SELECT count(*) FROM ledger_entry x WHERE x.source_transaction_id = p.source_transaction_id)"
    " AS partner_entries,"
    " (pa.closed_on IS NULL AND EXISTS (SELECT 1 FROM account_source s WHERE s.account_id = pa.id))"
    " AS partner_synced"
    " FROM ledger_entry e LEFT JOIN ledger_entry p ON p.id = e.counterpart_entry_id"
    " LEFT JOIN source_transaction ps ON ps.id = p.source_transaction_id"
    " LEFT JOIN account pa ON pa.id = p.account_id"
    " WHERE e.id = ANY(:ids) ORDER BY e.id"
)


def update_source(
    engine: Engine,
    source_id: int,
    *,
    amount: int | None = None,
    booked_on: date | None = None,
    purpose: str | None | EllipsisType = ...,
    expected_versions: Mapping[int, int] | None = None,
    dry_run: bool = False,
) -> Edited:
    """Edit a user-authored row's amount, date or purpose (spec §5.6), the entries following.

    `purpose=...` leaves it, a blank or `None` clears it. A real run carries `expected_versions` for every
    entry it writes (the source's entries and the partners it unpairs; a dry run reports them in
    `effects.versions`), else `VersionConflict` names the moved and the missing ones. A dry run writes
    nothing; a real run settles after it commits.
    """
    if amount is None and booked_on is None and purpose is ...:
        raise EmptyEdit
    if amount == 0:
        raise ValueError("an amount is never zero")

    def work(conn: Connection, extra: set[int]) -> tuple[EditEffects, list[int]]:
        locked = _lock_source(conn, source_id, extra)
        effects = _edit(conn, locked, amount, booked_on, purpose, expected_versions, dry_run)
        return effects, [i for i in locked.entry_ids if i not in effects.deleted_entry_ids]

    effects, own = _rounds(engine, dry_run, work)
    if dry_run:
        return Edited(source_id, True, effects, Units(), None)
    result = settle(engine)
    partners = [i for i in effects.unpaired_entry_ids if i not in own]
    return Edited(source_id, False, effects, _read_units(engine, [*own, *partners]), result)


def _edit(
    conn: Connection,
    locked: _Locked,
    amount: int | None,
    booked_on: date | None,
    purpose: str | None | EllipsisType,
    expected: Mapping[int, int] | None,
    dry_run: bool,
) -> EditEffects:
    src = locked.source
    new_amount = src.amount if amount is None else amount
    new_on = src.booked_on if booked_on is None else booked_on
    new_purpose = src.purpose if purpose is ... else clean_purpose(purpose)
    ids = list(locked.entry_ids)
    everything = [*ids, *locked.partner_ids]
    rows = {int(r.id): r for r in conn.execute(_ENTRY_ROWS, {"ids": everything})}
    own = [rows[i] for i in ids]
    if (new_amount, new_on, new_purpose) == (src.amount, src.booked_on, src.purpose):
        # nothing about the row changes: no input changed, so nothing is resolved again
        lock_rows(conn, "ledger_entry", everything)
        return EditEffects(versions=tuple((i, int(rows[i].version)) for i in ids))

    # a partner that follows (spec §5.7): user-authored, the only entry of its source, on an unsynced account
    followable = {
        int(r.id)
        for r in own
        if r.counterpart_entry_id is not None
        and r.partner_currency == src.currency
        and r.partner_authored
        and int(r.partner_entries) == 1
        and not r.partner_synced
    }
    plan = plan_amounts(
        int(src.amount),
        int(new_amount),
        [(int(r.id), int(r.amount)) for r in own],
        {int(r.id): r.partner_currency for r in own if r.counterpart_entry_id is not None},
        str(src.currency),
        following=followable,
    )
    followed = sorted(
        i for i in followable if i in plan.amounts and i not in plan.unpair and i not in plan.collapse
    )
    scope_ids = [i for i in ids if i not in plan.collapse]
    _, partners_all = entry_scope(conn, ids)
    broken_partners = sorted(int(rows[i].counterpart_entry_id) for i in plan.unpair)
    followers = {i: int(rows[i].counterpart_entry_id) for i in followed}
    written = sorted({*ids, *broken_partners, *followers.values(), *entry_scope(conn, plan.collapse)[1]})
    if dry_run:
        lock_rows(conn, "ledger_entry", everything)
    elif expected is None:
        raise VersionConflict(tuple(written))
    else:
        _check_versions(conn, expected, written)
    versions = tuple((i, int(r.version)) for i, r in sorted(rows.items()) if i in written)

    before = _ok_of(conn, everything)
    deleted: Affected = Affected()
    if plan.collapse:
        deleted = remove_entries(conn, plan.collapse, scope=entry_scope(conn, plan.collapse))
    unpaired = unpair(conn, plan.unpair) if plan.unpair else Affected()

    conn.execute(
        text(
            "UPDATE source_transaction SET amount = :amount, booked_on = :on, purpose = :purpose,"
            " raw = raw || CAST(:patch AS jsonb) WHERE id = :i"
        ),
        {
            "amount": new_amount,
            "on": new_on,
            "purpose": new_purpose,
            "patch": json.dumps(
                {"amount": new_amount, "booked_on": new_on.isoformat(), "purpose": new_purpose}
            ),
            "i": src.id,
        },
    )
    conn.execute(
        text("UPDATE ledger_entry SET booked_on = :on WHERE id = ANY(:ids) AND booked_on <> :on"),
        {"on": new_on, "ids": scope_ids},
    )
    for entry_id, entry_amount in plan.amounts.items():
        conn.execute(
            text("UPDATE ledger_entry SET amount = :a WHERE id = :i"), {"a": entry_amount, "i": entry_id}
        )

    for i, partner in followers.items():  # the partner follows (I2, I3): its source and its entry
        follow = -plan.amounts[i]
        conn.execute(
            text(
                "UPDATE source_transaction SET amount = :a, raw = raw || CAST(:patch AS jsonb) WHERE id = :s"
            ),
            {"a": follow, "patch": json.dumps({"amount": follow}), "s": int(rows[i].partner_source)},
        )
        conn.execute(text("UPDATE ledger_entry SET amount = :a WHERE id = :i"), {"a": follow, "i": partner})
        recompute_derived(conn, int(rows[i].partner_account))

    current = list(conn.execute(_ENTRY_ROWS, {"ids": scope_ids}))
    still_paired = {int(r.id) for r in current if r.counterpart_entry_id is not None}
    resolvable = [r for r in current if int(r.id) not in still_paired]
    rederived = _afresh(conn, resolvable, ids[0], new_purpose, new_on, frozenset({*ids, *partners_all}))
    recompute_derived(conn, int(src.account_id))

    after = _ok_of(conn, [*scope_ids, *partners_all])
    returned = sorted(i for i, ok in after.items() if not ok and before.get(i, False))
    return EditEffects(
        collapsed_entry_ids=tuple(deleted.removed_entry_ids),
        unpaired_entry_ids=tuple(
            sorted({*unpaired.unpaired_entry_ids, *deleted.partner_entry_ids} - set(plan.collapse))
        ),
        deleted_entry_ids=tuple(deleted.removed_entry_ids),
        rederived_entry_ids=tuple(sorted(rederived)),
        returned_to_review_ids=tuple(returned),
        followed_entry_ids=tuple(sorted(followers.values())),
        versions=versions,
    )


# ---- delete ------------------------------------------------------------------------------------


def delete_source(
    engine: Engine,
    source_id: int,
    *,
    expected_versions: Mapping[int, int] | None = None,
    dry_run: bool = False,
) -> Deleted:
    """Delete a user-authored row and its entries through the removal routine (spec §5.6).

    Partners return to review keeping their values (minus a counter-account the pair set), freed documents
    come back, the account's derived entries are recomputed. A real run carries `expected_versions` for the
    row's entries and their partners (the dry run's rows show them); it settles after it commits. A dry run
    reports what would go (entries with their tags, the partners) and writes nothing.
    """

    def work(
        conn: Connection, extra: set[int]
    ) -> tuple[tuple[EntryRow, ...], DeleteCounts, Affected, list[int]]:
        locked = _lock_source(conn, source_id, extra)
        ids = list(locked.entry_ids)
        partners = list(locked.partner_ids)
        written = sorted({*ids, *partners})
        if dry_run:
            lock_rows(conn, "ledger_entry", written)
        elif expected_versions is None:
            raise VersionConflict(tuple(written))
        else:
            _check_versions(conn, expected_versions, written)
        removed = entries_by_ids(conn, ids)
        ok = _ok_of(conn, ids)
        freed = _ints(
            conn.execute(
                text("SELECT document_id FROM ledger_entry WHERE id = ANY(:ids) AND document_id IS NOT NULL"),
                {"ids": ids},
            ).scalars()
        )
        counts = DeleteCounts(
            entries=len(ids),
            confirmed_entries=sum(1 for i in ids if ok.get(i, False)),
            tagged_entries=sum(1 for e in removed if e.tag_ids),
            tag_memberships=sum(len(e.tag_ids) for e in removed),
            partners_returning_to_review=len(partners),
            freed_documents=len(freed),
        )
        affected = remove_entries(conn, ids, scope=(ids, partners))
        conn.execute(text("DELETE FROM source_transaction WHERE id = :i"), {"i": source_id})
        # the dry run reads the partners as they stand before the rollback
        return removed, counts, affected, partners

    removed, counts, affected, partners = _rounds(engine, dry_run, work)
    if dry_run:
        # rolled back: the partners and the row are as they were
        with engine.connect() as conn:
            return Deleted(
                source_id,
                True,
                removed,
                counts,
                affected.freed_document_ids,
                entries_by_ids(conn, partners),
                Units(),
                None,
            )
    result = settle(engine)
    with engine.connect() as conn:
        left = entries_by_ids(conn, partners)
    return Deleted(
        source_id,
        False,
        removed,
        counts,
        affected.freed_document_ids,
        left,
        _read_units(engine, partners),
        result,
    )


__all__ = [
    "AccountSynced",
    "Created",
    "Deleted",
    "EditEffects",
    "Edited",
    "EmptyEdit",
    "NotUserAuthored",
    "SourceError",
    "SourceIdTaken",
    "SourceMissing",
    "Units",
    "clean_purpose",
    "create_source",
    "delete_source",
    "plan_amounts",
    "update_source",
]
