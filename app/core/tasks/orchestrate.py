"""The orchestration of a task (architecture §5.3): one coroutine that runs its jobs in sequence.

Each job runs in a worker thread (`asyncio.to_thread`), because an importer blocks; the coroutine
only decides, at each job boundary, whether to go on. A task ends `completed` (every job attempted ran
to its end, whatever its runs' results), `aborted`, `abandoned` (no client for longer than the grace,
checked at job boundaries, so a reload that straddles one does not end a sync) or `crashed` (a bug in
the orchestration: every run the jobs started and did not end is failed, retryable). The task is marked
ended and its claims freed before `task_ended` is emitted (`TaskRegistry.finish`).

Settling: each ingest settles after its commit; the task settles once more at its end only if some
run's settling reported an error.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from app.core.importers.plan import JobPlan
from app.core.settle.settle import settle
from app.core.tasks.registry import Started, TaskRegistry
from app.core.tasks.runner import JobEnv, fail_open_runs, run_job
from app.core.tasks.task import Outcome, Task, TaskKind

log = logging.getLogger(__name__)


async def run_task(registry: TaskRegistry, task: Task, jobs: Sequence[JobPlan], env: JobEnv) -> None:
    """Run `jobs` in order, then end the task. Never raises, except `CancelledError` after ending it."""
    outcome: Outcome = "completed"
    reached = 0  # jobs begun
    settle_failed = False
    cancelled: BaseException | None = None
    try:
        for index, job in enumerate(jobs):
            if task.aborting:
                outcome = "aborted"
            elif index > 0 and task.detached_for() > task.tuning.abandon_grace_s:
                outcome = "abandoned"
            if outcome != "completed":
                break
            reached = index + 1
            try:
                result = await asyncio.to_thread(run_job, env, task, job)
            finally:
                registry.release_instance(task, job.instance_id)
            settle_failed = settle_failed or result.settle_failed
        if outcome == "completed" and task.aborting:
            outcome = "aborted"  # the abort came during the last job: its runs were discarded
        if settle_failed:
            settled = await asyncio.to_thread(settle, env.engine)
            if settled.error is not None:
                log.error("the final settle failed: %s", settled.error)
    except BaseException as exc:
        outcome = "crashed"
        log.error("task crashed: %s", type(exc).__name__)
        try:
            fail_open_runs(env.engine, task)  # synchronously: the loop may be shutting down
        except Exception as err:
            log.error("could not fail the open runs: %s", type(err).__name__)
        if not isinstance(exc, Exception):
            cancelled = exc
    registry.finish(task, outcome, [j.instance_id for j in jobs[reached:]])
    if cancelled is not None:
        raise cancelled


def launch(
    registry: TaskRegistry,
    task: Task,
    jobs: Sequence[JobPlan],
    env: JobEnv,
    loop: asyncio.AbstractEventLoop | None = None,
) -> Any:
    """Start `run_task`: on the running loop (called from a coroutine), or, from a thread of the API's
    pool, on `loop`. The handle is kept on the task so nothing collects it."""
    coroutine = run_task(registry, task, jobs, env)
    if loop is None:
        task.handle = asyncio.get_running_loop().create_task(coroutine)
    else:
        task.handle = asyncio.run_coroutine_threadsafe(coroutine, loop)
    return task.handle


def start_task(
    registry: TaskRegistry,
    env: JobEnv,
    user_id: int,
    kind: TaskKind,
    jobs: Sequence[JobPlan],
    *,
    skip_busy: bool = False,
    loop: asyncio.AbstractEventLoop | None = None,
) -> Started:
    """Take the claims, create the task and launch it: the one call a start route makes after
    validating (`plan_start`, `plan_discovery`). Raises `TaskActive` or `InstanceBusy`; nothing runs then."""
    started = registry.start(user_id, kind, jobs, skip_busy=skip_busy)
    launch(registry, started.task, started.jobs, env, loop)
    return started
