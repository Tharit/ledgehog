"""The job of one importer instance (architecture §5.3, §5.5): plain synchronous code, called from a
worker thread by the orchestration (or directly, in a test).

    open (may prompt) → each item in order → close → write back `state`

An item is one fetch: each linked open account from its derived start, then each accountless kind. A
run is started just before its own fetch, so `running` and `started_at` are true; the fetch runs outside
any transaction, with no lock and no connection held (a prompt may come at any point); then ingest
writes the delivery in its own transaction and settles.

What a failure ends is its class's `scope` (`errors.py`): an item failure fails that run and the next
item goes on; an instance failure fails the remaining runs with the same error and ends the instance.
A failed sign-in starts a run per planned item and fails each at once. Whatever happens, no run this
job started is left `running`, the session is closed and the importer's `state` is written back if it
changed. A failed run writes nothing (ingest guarantees it).

Nothing here logs a message that could hold what the user typed: errors are logged by type.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Engine, text

from app.core.domain.errors import RunRefused
from app.core.importers.instances import save_state
from app.core.importers.plan import JobPlan, PlannedItem, documents_start, fetch_start
from app.core.ingest.documents import ingest_documents
from app.core.ingest.run import (
    fail_run,
    ingest_delivery,
    run_error_text,
    run_retryable,
    start_run,
)
from app.core.plugins.errors import ChallengeAbandoned, error_code, scope_of
from app.core.plugins.fetch import DiscoveredAccount, FetchImporter, FetchSession
from app.core.tasks.prompter import TaskPrompter
from app.core.tasks.task import Task

log = logging.getLogger(__name__)

ABORTED = "the sync was aborted"


@dataclass(frozen=True, slots=True)
class JobEnv:
    """What a job needs and the task does not carry: the engine, the registered importers, the fetch day
    (today in the household's zone, spec §5.1) and who started it (recorded on the runs)."""

    engine: Engine
    importers: Mapping[str, object]
    fetch_day: date
    user_id: int | None


@dataclass(slots=True)
class JobOutcome:
    settle_failed: bool = False  # some run's settling reported an error: the task settles once more
    failed: bool = False  # the instance could not continue (instance_failed was emitted)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """A discovery's result, held on the task; matched against the accounts when it is read."""

    instance_id: int
    accounts: tuple[DiscoveredAccount, ...]


@dataclass(frozen=True, slots=True)
class _Instance:
    """The instance as the job read it: what the importer needs and the runs record."""

    name: str  # the importer's name, recorded on each run
    importer: FetchImporter
    settings: dict[str, Any]
    minor_units: dict[str, int]


class _Ctx:
    """The job's mutable bits the prompter reads: which run is current (None while signing in)."""

    def __init__(self) -> None:
        self.run_id: int | None = None


def run_job(env: JobEnv, task: Task, job: JobPlan) -> JobOutcome:
    """Run one instance of a sync, or a discovery's one job, to its end. Never raises for a failure
    of the importer or of a run: those end the run or the instance and are reported as events."""
    out = JobOutcome()
    ctx = _Ctx()
    task.emit("instance_started", {"instance_id": job.instance_id})
    state: dict[str, Any] = {}
    original: dict[str, Any] = {}
    session: FetchSession | None = None
    pending: list[PlannedItem] = list(job.items)
    try:
        try:
            inst, state = _read_instance(env, job.instance_id)
            original = copy.deepcopy(state)
            prompter = TaskPrompter(task, job.instance_id, lambda: ctx.run_id)
            session = inst.importer.open(inst.settings, state, prompter, today=env.fetch_day)
            if task.kind == "discovery":
                task.set_result(DiscoveryResult(job.instance_id, tuple(session.accounts())))
                return out
        except Exception as exc:  # the sign-in (or the list) failed: the instance ends
            _end_instance(env, task, job, pending, exc, out)
            return out
        while pending:
            item = pending.pop(0)
            if task.aborting:
                _end_instance(env, task, job, [item, *pending], ChallengeAbandoned(ABORTED), out)
                return out
            failure = _run_item(env, task, job, ctx, session, inst, item, state, out)
            if failure is not None and scope_of(failure) == "instance":
                _end_instance(env, task, job, pending, failure, out)
                return out
        return out
    finally:
        _close(session)
        _write_back(env, job.instance_id, state, original)
        fail_open_runs(env.engine, task)


# ---- one item ------------------------------------------------------------------------------


def _run_item(
    env: JobEnv,
    task: Task,
    job: JobPlan,
    ctx: _Ctx,
    session: FetchSession,
    inst: _Instance,
    item: PlannedItem,
    state: dict[str, Any],
    out: JobOutcome,
) -> Exception | None:
    """One item's run, from `start_run` to `run_finished` or `run_failed`. Returns the failure, if any;
    the caller decides by its scope whether the instance goes on. A document delivery's `position` is
    applied to `state` (the working copy, written back when the job ends) only after its ingest."""
    base = {"instance_id": job.instance_id, "account_id": item.account_id, "kind": item.kind}
    try:
        external_ref, currency, since = _item_facts(env, job.instance_id, inst, item)
    except Exception as exc:  # the account or link changed after the start, or a bad setting
        run_id = _fail_new_run(env, job, inst, item, exc)
        task.emit("run_failed", {"run_id": run_id, **base, **_failure_fields(exc)})
        return exc
    run_id = _start(env, job, inst, item)
    task.track_run(run_id)
    ctx.run_id = run_id
    task.emit("run_started", {"run_id": run_id, **base, "since": since.isoformat()})
    try:
        if item.kind == "transactions":
            assert external_ref is not None
            fetched = session.fetch_account(
                external_ref,
                since=since,
                today=env.fetch_day,
                currency=currency,
                minor_units_of=inst.minor_units.__getitem__,
            )
            if task.aborting:  # a delivery that arrives after the abort is discarded
                raise ChallengeAbandoned(ABORTED)
            settled = ingest_delivery(
                env.engine,
                run_id,
                fetched.rows,
                reported_balance=fetched.reported_balance,
                reported_balance_on=fetched.balance_on,
                covered_from=fetched.covered_from,
                covered_through=fetched.covered_through,
                importer_stats=fetched.importer_stats,
            ).settle
        else:
            delivery = session.fetch_documents(
                since=since, today=env.fetch_day, minor_units_of=inst.minor_units.__getitem__
            )
            if task.aborting:
                raise ChallengeAbandoned(ABORTED)
            settled = ingest_documents(
                env.engine,
                run_id,
                delivery.documents,
                covered_through=delivery.covered_through,
                covered_from=delivery.covered_from,
                importer_stats=delivery.importer_stats,
            ).settle
            if delivery.position:  # only now: the documents are written (architecture §5.5)
                state.update(delivery.position)
        stats = _stored_stats(env.engine, run_id)
    except Exception as exc:
        _fail_quietly(env.engine, run_id, exc)
        task.untrack_run(run_id)
        task.emit("run_failed", {"run_id": run_id, **base, **_failure_fields(exc)})
        if error_code(exc) == "unexpected":
            log.error("run %s failed unexpectedly: %s", run_id, type(exc).__name__)
        return exc
    finally:
        ctx.run_id = None
    task.untrack_run(run_id)
    if settled is not None and settled.error is not None:
        out.settle_failed = True
    task.emit("run_finished", {"run_id": run_id, **base, "stats": stats})
    return None


def _item_facts(
    env: JobEnv, instance_id: int, inst: _Instance, item: PlannedItem
) -> tuple[str | None, str, date]:
    """(the account's reference at this login, its currency, the start), read in one short
    connection. The start is derived now (spec §5.4); an explicit one counts only where there is still
    no coverage."""
    if item.kind == "documents":
        return None, "", documents_start(inst.importer, inst.settings, env.fetch_day)
    assert item.account_id is not None
    with env.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT a.currency, a.closed_on, s.external_ref FROM account a"
                " LEFT JOIN account_source s ON s.account_id = a.id AND s.importer_instance_id = :i"
                " WHERE a.id = :a"
            ),
            {"a": item.account_id, "i": instance_id},
        ).one_or_none()
        if row is None:
            raise RunRefused("account_missing", f"account {item.account_id} does not exist")
        if row.external_ref is None:
            raise RunRefused(
                "account_not_linked",
                f"account {item.account_id} is not linked to importer instance {instance_id}",
            )
        if row.closed_on is not None:
            raise RunRefused("account_closed", f"account {item.account_id} is closed")
        derived = fetch_start(conn, item.account_id, inst.importer, inst.settings, env.fetch_day)
    since = item.since if item.since is not None and derived.source != "coverage" else derived.since
    return str(row.external_ref), str(row.currency), since


# ---- failures ------------------------------------------------------------------------------


def _failure_fields(exc: BaseException) -> dict[str, Any]:
    return {"code": error_code(exc), "message": run_error_text(exc), "retryable": run_retryable(exc)}


def _start(env: JobEnv, job: JobPlan, inst: _Instance, item: PlannedItem) -> int:
    return start_run(
        env.engine,
        item.account_id,
        item.kind,
        importer=inst.name,
        importer_instance_id=job.instance_id,
        started_by=env.user_id,
    )


def _fail_quietly(engine: Engine, run_id: int, exc: BaseException) -> None:
    """End the run `failed` with the error's stored text. Never raises: the caller is reporting."""
    try:
        fail_run(engine, run_id, run_error_text(exc), retryable=run_retryable(exc))
    except Exception as err:  # the type only: a database error's message quotes statement content
        log.error("could not mark run %s failed: %s", run_id, type(err).__name__)


def _fail_new_run(env: JobEnv, job: JobPlan, inst: _Instance, item: PlannedItem, exc: BaseException) -> int:
    """A run for an item that never got to fetch: started and failed at once, so the account page
    shows a failed run to retry."""
    run_id = _start(env, job, inst, item)
    _fail_quietly(env.engine, run_id, exc)
    return run_id


def _end_instance(
    env: JobEnv,
    task: Task,
    job: JobPlan,
    remaining: list[PlannedItem],
    exc: BaseException,
    out: JobOutcome,
) -> None:
    """An instance-scope failure (or an abort, or a failed sign-in): fail every remaining item's run with
    the same error and emit `instance_failed` listing them. A discovery has no runs: the list is empty."""
    run_ids: list[int] = []
    if remaining:
        name = _stored_importer_name(env.engine, job.instance_id)
        for item in remaining:
            try:
                run_id = start_run(
                    env.engine,
                    item.account_id,
                    item.kind,
                    importer=name,
                    importer_instance_id=job.instance_id,
                    started_by=env.user_id,
                )
                _fail_quietly(env.engine, run_id, exc)
                run_ids.append(run_id)
            except Exception as err:  # a run that cannot even be started: the others still fail
                log.error("could not fail a run of instance %s: %s", job.instance_id, type(err).__name__)
    out.failed = True
    if error_code(exc) == "unexpected":
        log.error("instance %s failed unexpectedly: %s", job.instance_id, type(exc).__name__)
    task.emit("instance_failed", {"instance_id": job.instance_id, **_failure_fields(exc), "run_ids": run_ids})


def fail_open_runs(engine: Engine, task: Task) -> None:
    """Fail, retryable, every run the task started and did not end: the crash safety net, so no run is
    left `running` (start-up marks those of a dead process, but a live one must not leak them)."""
    for run_id in task.open_run_ids():
        try:
            fail_run(engine, run_id, "interrupted: the sync stopped before the run finished", retryable=True)
        except Exception as err:
            log.error("could not mark run %s failed: %s", run_id, type(err).__name__)
        task.untrack_run(run_id)


# ---- the instance, the session, the state ------------------------------------------------------


def _read_instance(env: JobEnv, instance_id: int) -> tuple[_Instance, dict[str, Any]]:
    """The instance and the working copy of its `state`, in one short connection: nothing stays open
    after it. A refusal (deleted, disabled or its importer gone since the start) ends the instance like
    a failed sign-in."""
    with env.engine.connect() as conn:
        row = conn.execute(
            text("SELECT importer, settings, state, disabled FROM importer_instance WHERE id = :i"),
            {"i": instance_id},
        ).one_or_none()
        if row is None:
            raise RunRefused("instance_missing", f"importer instance {instance_id} does not exist")
        if row.disabled:
            raise RunRefused("instance_disabled", f"importer instance {instance_id} is disabled")
        importer = env.importers.get(row.importer)
        if not isinstance(importer, FetchImporter):
            raise RunRefused("importer_unavailable", f"importer {row.importer!r} is not available")
        minor_units = {
            str(r.code): int(r.minor_units)
            for r in conn.execute(text("SELECT code, minor_units FROM currency"))
        }
    inst = _Instance(str(row.importer), importer, dict(row.settings), minor_units)
    return inst, copy.deepcopy(dict(row.state))


def _stored_importer_name(engine: Engine, instance_id: int) -> str:
    with engine.connect() as conn:
        name = conn.execute(
            text("SELECT importer FROM importer_instance WHERE id = :i"), {"i": instance_id}
        ).scalar_one_or_none()
    return str(name) if name is not None else "unknown"


def _stored_stats(engine: Engine, run_id: int) -> dict[str, Any]:
    """The run's stored statistics, as `GET /api/importers/runs/{id}` returns them."""
    with engine.connect() as conn:
        return dict(
            conn.execute(text("SELECT stats FROM import_run WHERE id = :i"), {"i": run_id}).scalar_one()
        )


def _close(session: FetchSession | None) -> None:
    if session is None:
        return
    try:
        session.close()
    except Exception as exc:  # by type, and dropped
        log.warning("closing a session failed: %s", type(exc).__name__)


def _write_back(env: JobEnv, instance_id: int, state: dict[str, Any], original: dict[str, Any]) -> None:
    """The importer's `state`, written back when the job ends whatever the outcome, if it changed."""
    if state == original:
        return
    try:
        save_state(env.engine, instance_id, state)
    except Exception as exc:
        log.error("could not save the state of instance %s: %s", instance_id, type(exc).__name__)
