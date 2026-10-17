"""The task registry and its claims (architecture §4.3, §5.3).

In memory, one process (the app runs one worker). It holds the tasks by token with the owning user, the
user's one active task and one holder per instance. Starting a task takes both claims in one step; a
claim on an instance is released when its job ends, or at the task's end for an instance never reached.

Endpoints run in a threadpool, so every method takes the registry's lock; the lock is never held across
anything that blocks. The registry hides a task from another user: `get` answers None for it, which the
API turns into 404 `not_found`, not 403.

A finished task stays `retention_s` (15 minutes), so a client that reconnects just after `task_ended`
still gets its replay; the sweep is lazy, on each start and read. The user's finished task is evicted
when they start the next one.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.importers.plan import JobPlan
from app.core.tasks.task import Outcome, Task, TaskKind, TaskTuning


class TaskActive(Exception):
    """The user already has a running task (409 `task_active`); `task_id` lets a client reattach."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__("a sync is already running")


class InstanceBusy(Exception):
    """Another task holds the instance (409 `instance_busy`); `instance_ids` are the held ones."""

    def __init__(self, instance_ids: Sequence[int]) -> None:
        self.instance_ids = tuple(instance_ids)
        super().__init__(f"importer instance(s) {list(self.instance_ids)} are in use by another sync")


@dataclass(frozen=True, slots=True)
class Started:
    task: Task
    jobs: tuple[JobPlan, ...]  # what runs: the plan less the instances another task held, if skipped
    busy: tuple[int, ...]  # instances left out because another task holds them


class TaskRegistry:
    def __init__(self, tuning: TaskTuning | None = None) -> None:
        self.tuning = tuning or TaskTuning()
        self._lock = threading.Lock()
        self._tasks: dict[str, Task] = {}
        self._by_user: dict[int, str] = {}  # the user's latest task, running or finished
        self._holders: dict[int, str] = {}  # instance id -> the task holding it

    # ---- starting ---------------------------------------------------------------------

    def start(
        self, user_id: int, kind: TaskKind, jobs: Sequence[JobPlan], *, skip_busy: bool = False
    ) -> Started:
        """Create the task and take both claims, atomically; emit `task_started`.

        `TaskActive` when the user has a running task. `InstanceBusy` when another task holds an
        instance — unless `skip_busy` ("sync everything"), which drops those and reports them; if
        nothing remains it is `InstanceBusy` all the same. The user's finished task is evicted.
        """
        with self._lock:
            self._sweep_locked()
            previous = self._tasks.get(self._by_user.get(user_id, ""))
            if previous is not None:
                if not previous.ended:
                    raise TaskActive(previous.task_id)
                self._evict_locked(previous)
            held = tuple(j.instance_id for j in jobs if j.instance_id in self._holders)
            kept = tuple(jobs)
            if held:
                kept = tuple(j for j in jobs if j.instance_id not in held) if skip_busy else ()
                if not kept:
                    raise InstanceBusy(held)
            task = Task(
                secrets.token_urlsafe(16), user_id, kind, self.tuning, tuple(j.instance_id for j in kept)
            )
            self._tasks[task.task_id] = task
            self._by_user[user_id] = task.task_id
            for job in kept:
                self._holders[job.instance_id] = task.task_id
            task.emit(
                "task_started",
                {
                    "kind": kind,
                    "instances": [
                        {
                            "instance_id": j.instance_id,
                            "items": [{"account_id": i.account_id, "kind": i.kind} for i in j.items],
                        }
                        for j in kept
                    ],
                },
            )
        return Started(task, kept, held)

    # ---- claims -----------------------------------------------------------------------

    def release_instance(self, task: Task, instance_id: int) -> None:
        """The instance's job ended: free it for another task."""
        with self._lock:
            if self._holders.get(instance_id) == task.task_id:
                del self._holders[instance_id]

    def finish(self, task: Task, outcome: Outcome, not_started: Sequence[int] = ()) -> None:
        """End a task: mark it ended and free its claims, then emit `task_ended`, in that order, so a
        client reacting to the event may start the next task at once."""
        task.mark_ended(outcome)
        with self._lock:
            for instance_id in [i for i, t in self._holders.items() if t == task.task_id]:
                del self._holders[instance_id]
        task.emit_ended(tuple(not_started))

    def is_held(self, instance_id: int) -> bool:
        """Whether a running task holds the instance (reset is refused meanwhile)."""
        with self._lock:
            return instance_id in self._holders

    def held_instances(self) -> frozenset[int]:
        """Every instance a task holds now: the plan's `busy`."""
        with self._lock:
            return frozenset(self._holders)

    # ---- lookup -----------------------------------------------------------------------

    def get(self, task_id: str, user_id: int) -> Task | None:
        """The task, or None if it is unknown, evicted or another user's."""
        with self._lock:
            self._sweep_locked()
            task = self._tasks.get(task_id)
            return task if task is not None and task.user_id == user_id else None

    def active(self, user_id: int) -> Task | None:
        """The user's running task; a finished one is not active."""
        with self._lock:
            self._sweep_locked()
            task = self._tasks.get(self._by_user.get(user_id, ""))
            return task if task is not None and not task.ended else None

    # ---- retention --------------------------------------------------------------------

    def _sweep_locked(self) -> None:
        for task in list(self._tasks.values()):
            age = task.ended_for()
            if age is not None and age > self.tuning.retention_s:
                self._evict_locked(task)

    def _evict_locked(self, task: Task) -> None:
        self._tasks.pop(task.task_id, None)
        if self._by_user.get(task.user_id) == task.task_id:
            del self._by_user[task.user_id]
