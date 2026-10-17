"""Starting a sync: where each fetch starts, what "sync everything" would do, and the validation of a
start (spec §5.4, §5.11; architecture §4.1, §5.5).

Everything here is a read: no task, no lock, no write. The caller (the API) hands in a connection, the
registered importers and today's date in the household's zone, and gets back what to run or the refusal.

An **item** is one fetch: the transactions of one account of one instance, or one accountless kind
(documents). A **job** is one instance with its items; a sync is a list of jobs and runs them in
instance order (architecture §5.3). "Sync everything", "fetch this account", "run this credential" and
"run a failed run again" are all lists of items, so the engine has one entry point.

The start of a fetch is derived when its run begins, never carried from a plan (spec §5.4): `JobPlan`
holds only an explicit `since`, which the user may give for an account without coverage.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import Connection, text

from app.core.accounts import AccountMissing
from app.core.importers.instances import (
    AccountClosed,
    InstanceDisabled,
    InstanceMissing,
    NotAnAccountSource,
)
from app.core.importers.upload import AccountNotLinked
from app.core.plugins.errors import InvalidProfile
from app.core.plugins.fetch import FetchImporter

OVERLAP_DAYS = 7  # a fetch with coverage starts this far before it (spec §5.4: bookings appear late)

SinceSource = Literal["coverage", "latest_entry", "importer_default"]
Kind = Literal["transactions", "documents"]


# ---- refusals ------------------------------------------------------------------------------
# Unknown instance/account, a disabled instance, a closed account, an unlinked account and a
# discovery of an instance without transactions reuse the errors that already carry those codes
# (`InstanceMissing`, `AccountMissing`, `InstanceDisabled`, `AccountClosed`, `AccountNotLinked`,
# `NotAnAccountSource`); the rest of architecture §4.1's list is here.


class StartRefused(Exception):
    """A start was refused as a whole; nothing was started. The message states the rule."""


class InstanceForbidden(StartRefused):
    """The instance belongs to the other user (spec §5.11): 403 `forbidden`."""

    def __init__(self, instance_id: int) -> None:
        super().__init__(f"importer instance {instance_id} belongs to another user")


class NotAFetchSource(StartRefused):
    """A file importer: it is uploaded to, not synced (409 `not_a_fetch_source`)."""

    def __init__(self, instance_id: int) -> None:
        super().__init__(f"importer instance {instance_id} is a file importer: upload a file to it")


class ImporterUnavailable(StartRefused):
    """The instance's importer is not registered in this deployment (409 `importer_unavailable`)."""

    def __init__(self, name: str) -> None:
        super().__init__(f"importer {name!r} is not available in this deployment")


class StartNotEditable(StartRefused):
    """A `since` for an account with coverage (422 `start_not_editable`): its start is derived."""

    def __init__(self, account_id: int) -> None:
        super().__init__(f"account {account_id} has coverage: its fetch start is derived, not chosen")


class NothingToSync(StartRefused):
    """Nothing is left to do (422 `nothing_to_sync`)."""

    def __init__(self) -> None:
        super().__init__("nothing to sync: no linked open account and no document source to run")


class InvalidItem(StartRefused):
    """An item that does not make sense (422 `validation_error`, naming `field`)."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


# ---- values --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FetchStart:
    since: date
    source: SinceSource


@dataclass(frozen=True, slots=True)
class ItemRequest:
    """One entry of `POST /api/sync`'s `items`.

    Only `instance_id`: that whole instance. With `account_id`: that account. With `kind`: that
    kind (`documents`, or `transactions` for every linked open account). `since` goes with an
    account only.
    """

    instance_id: int
    account_id: int | None = None
    kind: Kind | None = None
    since: date | None = None


@dataclass(frozen=True, slots=True)
class PlannedItem:
    kind: Kind
    account_id: int | None  # None for documents
    since: date | None = None  # an explicit start; None: derived when the run begins


@dataclass(frozen=True, slots=True)
class JobPlan:
    """One instance and what to run against it, in order: accounts by id, then the accountless kinds.
    A discovery's job has no items."""

    instance_id: int
    items: tuple[PlannedItem, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanAccount:
    account_id: int
    external_ref: str
    since: date
    since_source: SinceSource
    editable: bool  # exactly where there is no coverage (spec §5.4)


@dataclass(frozen=True, slots=True)
class PlanInstance:
    instance_id: int
    importer: str
    label: str
    busy: bool  # another task holds the instance
    accounts: tuple[PlanAccount, ...]
    documents_since: date | None  # None: the instance delivers no documents


# ---- the fetch start -----------------------------------------------------------------------


def fetch_start(
    conn: Connection, account_id: int, importer: FetchImporter, settings: Mapping[str, Any], today: date
) -> FetchStart:
    """Where the next fetch of an account starts (spec §5.4).

    With coverage: `synced_through` minus the overlap, but never before the day after the account's
    latest user-authored row (imports are not deduplicated against those). Without coverage: the day
    after the latest entry, derived ones included, so hand-kept history and the import meet. With
    neither: the importer's own default. Never later than `today`, which a fetch may not start after.
    """
    row = conn.execute(
        text(
            "SELECT (SELECT synced_through FROM v_account_coverage WHERE account_id = :a) AS through,"
            " (SELECT max(booked_on) FROM source_transaction"
            "   WHERE account_id = :a AND importer IS NULL) AS latest_user,"
            " (SELECT max(booked_on) FROM ledger_entry WHERE account_id = :a) AS latest_entry"
        ),
        {"a": account_id},
    ).one()
    if row.through is not None:
        since = row.through - timedelta(days=OVERLAP_DAYS)
        if row.latest_user is not None:
            since = max(since, row.latest_user + timedelta(days=1))
        return FetchStart(min(since, today), "coverage")
    if row.latest_entry is not None:
        return FetchStart(min(row.latest_entry + timedelta(days=1), today), "latest_entry")
    return FetchStart(min(importer.default_fetch_start(settings, today=today), today), "importer_default")


def documents_start(importer: FetchImporter, settings: Mapping[str, Any], today: date) -> date:
    """Where a document fetch starts: the instance's `start_date` (spec §5.5), else the importer's
    default. Documents have no coverage-based start."""
    raw = settings.get("start_date")
    if raw is None:
        return importer.default_fetch_start(settings, today=today)
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise InvalidProfile("start_date: must be an ISO date") from None


# ---- reading instances ---------------------------------------------------------------------

_INSTANCE_COLUMNS = "id, importer, label, emits, access, owner_id, settings, disabled"


def _is_fetch(importer: object) -> bool:
    return isinstance(importer, FetchImporter)


def _kinds(instance: Any, importer: FetchImporter) -> set[str]:
    """The kinds a sync can run against an instance: what it emits that its importer delivers (rates
    have no run path yet)."""
    return {"transactions", "documents"} & set(instance.emits) & set(importer.emits)


def _linked_open_accounts(conn: Connection, instance_id: int) -> list[Any]:
    return list(
        conn.execute(
            text(
                "SELECT s.account_id, s.external_ref FROM account_source s"
                " JOIN account a ON a.id = s.account_id"
                " WHERE s.importer_instance_id = :i AND a.closed_on IS NULL ORDER BY s.account_id"
            ),
            {"i": instance_id},
        ).all()
    )


def _may_run(instance: Any, user_id: int) -> bool:
    """Spec §5.11: the owner, or anyone for a shared instance."""
    return bool(instance.access == "shared" or instance.owner_id == user_id)


def _eligible(
    conn: Connection, user_id: int, importers: Mapping[str, object]
) -> list[tuple[Any, FetchImporter]]:
    """The instances "sync everything" covers, in id order: the user's own and the shared ones,
    enabled, of a registered fetch importer."""
    out: list[tuple[Any, FetchImporter]] = []
    for inst in conn.execute(
        text(f"SELECT {_INSTANCE_COLUMNS} FROM importer_instance WHERE NOT disabled ORDER BY id")  # noqa: S608
    ):
        importer = importers.get(inst.importer)
        if _may_run(inst, user_id) and importer is not None and isinstance(importer, FetchImporter):
            out.append((inst, importer))
    return out


def read_plan(
    conn: Connection,
    user_id: int,
    importers: Mapping[str, object],
    today: date,
    busy: Collection[int] = (),
) -> tuple[PlanInstance, ...]:
    """What "sync everything" would do for `user_id`: per instance, its open linked accounts with the
    start each fetch would use, where it comes from and whether the user may change it, and the
    document start. `busy` are the instances another task holds. Instances with nothing to run are
    left out, as the start leaves them out."""
    plan: list[PlanInstance] = []
    for inst, importer in _eligible(conn, user_id, importers):
        kinds = _kinds(inst, importer)
        accounts: list[PlanAccount] = []
        if "transactions" in kinds:
            for link in _linked_open_accounts(conn, inst.id):
                start = fetch_start(conn, link.account_id, importer, inst.settings, today)
                accounts.append(
                    PlanAccount(
                        link.account_id,
                        link.external_ref,
                        start.since,
                        start.source,
                        start.source != "coverage",
                    )
                )
        docs = documents_start(importer, inst.settings, today) if "documents" in kinds else None
        if accounts or docs is not None:
            plan.append(
                PlanInstance(inst.id, inst.importer, inst.label, inst.id in busy, tuple(accounts), docs)
            )
    return tuple(plan)


# ---- validating a start --------------------------------------------------------------------


def _need_instance(
    conn: Connection, user_id: int, instance_id: int, importers: Mapping[str, object]
) -> tuple[Any, FetchImporter]:
    """The refusals of one instance, in architecture §4.1's order."""
    inst = conn.execute(
        text(f"SELECT {_INSTANCE_COLUMNS} FROM importer_instance WHERE id = :i"),  # noqa: S608
        {"i": instance_id},
    ).one_or_none()
    if inst is None:
        raise InstanceMissing(instance_id)
    if not _may_run(inst, user_id):
        raise InstanceForbidden(instance_id)
    if inst.disabled:
        raise InstanceDisabled(instance_id)
    importer = importers.get(inst.importer)
    if importer is None:
        raise ImporterUnavailable(inst.importer)
    if not _is_fetch(importer):
        raise NotAFetchSource(instance_id)
    assert isinstance(importer, FetchImporter)
    return inst, importer


def _account_item(
    conn: Connection, inst: Any, account_id: int, since: date | None, today: date
) -> PlannedItem:
    acct = conn.execute(text("SELECT closed_on FROM account WHERE id = :a"), {"a": account_id}).one_or_none()
    if acct is None:
        raise AccountMissing(account_id)
    linked = conn.execute(
        text("SELECT 1 FROM account_source WHERE account_id = :a AND importer_instance_id = :i"),
        {"a": account_id, "i": inst.id},
    ).first()
    if linked is None:
        raise AccountNotLinked(inst.id, account_id)
    if acct.closed_on is not None:
        raise AccountClosed(account_id)
    if since is not None:
        if since > today:
            raise InvalidItem("since", "since must be a date no later than today")
        has_coverage = conn.execute(
            text("SELECT synced_through FROM v_account_coverage WHERE account_id = :a"), {"a": account_id}
        ).scalar_one_or_none()
        if has_coverage is not None:
            raise StartNotEditable(account_id)
    return PlannedItem("transactions", account_id, since)


def plan_start(
    conn: Connection,
    user_id: int,
    items: Sequence[ItemRequest] | None,
    importers: Mapping[str, object],
    today: date,
) -> tuple[JobPlan, ...]:
    """Expand a start into jobs, validating it as a whole: raises the first refusal and nothing starts.

    `items` None is "sync everything": every instance the user may run, leaving out silently what an
    explicit item would be refused for. Instances come in id order; within one, accounts by id, then
    documents. Which instances another task holds is the registry's to say, at the claim.
    """
    if items is None:
        jobs = _everything(conn, user_id, importers)
    else:
        jobs = _explicit(conn, user_id, items, importers, today)
    if not jobs:
        raise NothingToSync
    return jobs


def _everything(conn: Connection, user_id: int, importers: Mapping[str, object]) -> tuple[JobPlan, ...]:
    jobs: list[JobPlan] = []
    for inst, importer in _eligible(conn, user_id, importers):
        kinds = _kinds(inst, importer)
        planned: list[PlannedItem] = []
        if "transactions" in kinds:
            planned += [
                PlannedItem("transactions", link.account_id) for link in _linked_open_accounts(conn, inst.id)
            ]
        if "documents" in kinds:
            planned.append(PlannedItem("documents", None))
        if planned:
            jobs.append(JobPlan(inst.id, tuple(planned)))
    return tuple(jobs)


def _explicit(
    conn: Connection,
    user_id: int,
    items: Sequence[ItemRequest],
    importers: Mapping[str, object],
    today: date,
) -> tuple[JobPlan, ...]:
    accounts: dict[int, dict[int, date | None]] = {}  # instance -> account -> explicit since
    documents: set[int] = set()
    instances: dict[int, tuple[Any, FetchImporter]] = {}
    for item in items:
        if item.since is not None and item.account_id is None:
            raise InvalidItem("since", "a start applies to one account: name the account")
        if item.account_id is not None and item.kind == "documents":
            raise InvalidItem("kind", "documents have no account")
        if item.instance_id not in instances:
            instances[item.instance_id] = _need_instance(conn, user_id, item.instance_id, importers)
        inst, importer = instances[item.instance_id]
        kinds = _kinds(inst, importer)
        mine = accounts.setdefault(item.instance_id, {})
        if item.account_id is not None:
            if "transactions" not in kinds:
                raise NotAnAccountSource(inst.id)
            planned = _account_item(conn, inst, item.account_id, item.since, today)
            before = mine.get(item.account_id)
            if before is not None and planned.since is not None and before != planned.since:
                raise InvalidItem("since", f"account {item.account_id} is given two different starts")
            mine[item.account_id] = planned.since or before
        elif item.kind == "documents":
            if "documents" not in kinds:
                raise InvalidItem("kind", f"importer instance {inst.id} does not deliver documents")
            documents.add(inst.id)
        elif item.kind == "transactions":
            if "transactions" not in kinds:
                raise NotAnAccountSource(inst.id)
            for link in _linked_open_accounts(conn, inst.id):
                mine.setdefault(link.account_id, None)
        else:  # the whole instance
            if "transactions" in kinds:
                for link in _linked_open_accounts(conn, inst.id):
                    mine.setdefault(link.account_id, None)
            if "documents" in kinds:
                documents.add(inst.id)
    jobs: list[JobPlan] = []
    for instance_id in sorted(instances):
        planned_items = [PlannedItem("transactions", a, s) for a, s in sorted(accounts[instance_id].items())]
        if instance_id in documents:
            planned_items.append(PlannedItem("documents", None))
        if planned_items:
            jobs.append(JobPlan(instance_id, tuple(planned_items)))
    return tuple(jobs)


def plan_discovery(
    conn: Connection, user_id: int, instance_id: int, importers: Mapping[str, object]
) -> JobPlan:
    """The refusals of a discovery (architecture §4.1): as a start, and `NotAnAccountSource` for an
    instance that does not emit transactions. Its job has no items."""
    inst, importer = _need_instance(conn, user_id, instance_id, importers)
    if "transactions" not in _kinds(inst, importer):
        raise NotAnAccountSource(instance_id)
    return JobPlan(instance_id)
