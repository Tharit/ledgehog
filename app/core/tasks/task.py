"""One task: a sync or a discovery, its events and its one open prompt (architecture §4.2, §4.3, §5.3).

The party awaiting an answer is a blocked importer thread, not a coroutine, so the task is plain
threaded code: one lock (a condition), the event list, the single open prompt with a one-slot
hand-off, the abort flag and the subscribers. `/input` fills the slot from the request threadpool, the
importer's thread takes it; nothing needs an event loop, and a task is tested without one.

Secrets (architecture §5.6): an answer is wrapped in `SecretText` the moment it arrives, sits in the
slot only until the importer thread takes it, and is never recorded on the task, which keeps the
prompt (its payload) and that it was answered. A resolved prompt loses its body in the replay log,
because a photoTAN image is credential-grade (spec §7).

Subscribers are wake-up callbacks, called from whichever thread emitted; the async layer bridges them
with `loop.call_soon_threadsafe` and then reads `events_after`. A subscriber is an attached SSE
stream: the count of them, and since when there are none, is what abandonment (§4.3) reads.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from app.core.plugins.errors import ChallengeAbandoned
from app.core.plugins.fetch import (
    Answer,
    ChoicePrompt,
    Prompt,
    SecretPrompt,
    SecretText,
    TanPrompt,
    prompt_payload,
)
from app.utils import clock

log = logging.getLogger(__name__)

TaskKind = Literal["sync", "discovery"]
Outcome = Literal["completed", "aborted", "abandoned", "crashed"]
PromptOutcome = Literal["answered", "confirmed", "cancelled", "expired", "aborted"]


@dataclass(frozen=True, slots=True)
class TaskTuning:
    """The timing constants of a task, one value handed to the registry and overridable in tests.
    They are not configuration: five environment variables for numbers nobody will tune."""

    prompt_timeout_s: float = 300.0  # an unanswered prompt ends its instance with ChallengeExpired
    poll_interval_s: float = 3.0  # a decoupled challenge is polled this often
    abandon_grace_s: float = 30.0  # a task without a client stops at a job boundary after this
    retention_s: float = 15 * 60.0  # a finished task stays this long
    keepalive_s: float = 15.0  # the SSE comment line, read by the endpoint


@dataclass(frozen=True, slots=True)
class Event:
    """One event of a task. `id` is 1, 2, 3, ... per task; `data` is a flat JSON-able object."""

    id: int
    name: str
    data: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TaskStatus:
    """What `GET /api/sync/tasks/{id}` answers (architecture §4.3)."""

    task_id: str
    kind: TaskKind
    status: Literal["running", "ended"]
    aborting: bool
    outcome: Outcome | None
    last_event_id: int
    result: Any


class PromptNotOpen(Exception):
    """An answer for a prompt that is not the one open now: late, duplicate, from another tab, or the
    task has ended (409 `conflict`, `details.reason` `prompt_not_open`)."""

    reason = "prompt_not_open"

    def __init__(self) -> None:
        super().__init__("that prompt is not open")


class InvalidAnswer(Exception):
    """An answer that cannot be used (422 `validation_error` naming `field`); the prompt stays open."""

    def __init__(self, message: str, field: str = "value") -> None:
        self.field = field
        super().__init__(message)


class _Open:
    """The open prompt: its identity, what it accepts, and the one-slot hand-off. Held by the task
    while open and by the waiting importer thread until it has taken the answer."""

    __slots__ = ("answer", "decoupled", "event_id", "kind", "options", "outcome", "prompt_id")

    def __init__(self, prompt_id: str, event_id: int, prompt: Prompt) -> None:
        self.prompt_id = prompt_id
        self.event_id = event_id
        self.decoupled = isinstance(prompt, TanPrompt) and prompt.medium == "decoupled"
        self.kind: Literal["secret", "choice", "text"]
        if isinstance(prompt, SecretPrompt | TanPrompt):  # answered with SecretText
            self.kind = "secret"
        elif isinstance(prompt, ChoicePrompt):
            self.kind = "choice"
        else:
            self.kind = "text"
        self.options = (
            frozenset(o.id for o in prompt.options) if isinstance(prompt, ChoicePrompt) else frozenset()
        )
        self.outcome: PromptOutcome | None = None
        self.answer: Answer = None


class Task:
    """Thread-safe. `emit` may be called from any thread; so may every other method."""

    def __init__(
        self, task_id: str, user_id: int, kind: TaskKind, tuning: TaskTuning, instance_ids: tuple[int, ...]
    ) -> None:
        self.task_id = task_id
        self.user_id = user_id
        self.kind: TaskKind = kind
        self.tuning = tuning
        self.instance_ids = instance_ids
        self._cond = threading.Condition()
        self._events: list[Event] = []
        self._subs: dict[int, Callable[[], None]] = {}
        self._next_sub = 1
        self._detached_since: float | None = clock.monotonic()  # a stream never opened counts
        self._status: Literal["running", "ended"] = "running"
        self._outcome: Outcome | None = None
        self._ended_at: float | None = None
        self._aborting = False
        self._open: _Open | None = None
        self._result: Any = None
        self._ok = 0
        self._failed = 0
        self._open_runs: set[int] = set()
        self.handle: Any = None  # the asyncio task or future running it, kept so it is not collected

    # ---- events -------------------------------------------------------------------------

    def emit(self, name: str, data: Mapping[str, Any]) -> Event:
        """Append an event, wake the subscribers and return it."""
        with self._cond:
            event = self._append_locked(name, data)
            wakes = self._wakes_locked()
        self._wake(wakes)
        return event

    def _append_locked(self, name: str, data: Mapping[str, Any]) -> Event:
        event = Event(len(self._events) + 1, name, dict(data))
        self._events.append(event)
        if name == "run_finished":
            self._ok += 1
        elif name == "run_failed":
            self._failed += 1
        elif name == "instance_failed":
            self._failed += len(data.get("run_ids", ()))
        return event

    def _wakes_locked(self) -> list[Callable[[], None]]:
        self._cond.notify_all()
        return list(self._subs.values())

    @staticmethod
    def _wake(wakes: list[Callable[[], None]]) -> None:
        for wake in wakes:
            try:
                wake()
            except Exception as exc:  # a subscriber's problem never reaches the importer's thread
                log.warning("a task subscriber failed: %s", type(exc).__name__)

    def events_after(self, last_id: int = 0, *, replay: bool = False) -> list[Event]:
        """The events with an id above `last_id` (0 is the whole task). A `replay` leaves out every
        `run_progress` that a later one of the same run supersedes; ids stay as assigned."""
        with self._cond:
            events = self._events[max(last_id, 0) :]
        if not replay:
            return events
        latest = {e.data["run_id"]: e.id for e in events if e.name == "run_progress"}
        return [e for e in events if e.name != "run_progress" or latest[e.data["run_id"]] == e.id]

    def wait_for_events(self, last_id: int, timeout_s: float) -> list[Event]:
        """Block until an event above `last_id` exists, the task has ended or the timeout passes."""
        deadline = clock.monotonic() + timeout_s
        with self._cond:
            while len(self._events) <= last_id and self._status == "running":
                remaining = deadline - clock.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            return self._events[max(last_id, 0) :]

    # ---- subscribers (attached streams) -------------------------------------------------

    def subscribe(self, wake: Callable[[], None]) -> int:
        """Attach a stream: `wake` is called, from any thread, whenever the task changed."""
        with self._cond:
            handle = self._next_sub
            self._next_sub += 1
            self._subs[handle] = wake
            self._detached_since = None
            return handle

    def unsubscribe(self, handle: int) -> None:
        with self._cond:
            self._subs.pop(handle, None)
            if not self._subs and self._detached_since is None:
                self._detached_since = clock.monotonic()

    @property
    def attached(self) -> int:
        with self._cond:
            return len(self._subs)

    def detached_for(self) -> float:
        """Seconds with no stream attached (0 while one is), since creation for a stream never opened."""
        with self._cond:
            if self._detached_since is None:
                return 0.0
            return clock.monotonic() - self._detached_since

    # ---- prompts ------------------------------------------------------------------------

    def begin_prompt(
        self, prompt: Prompt, *, instance_id: int, run_id: int | None, timeout_s: float
    ) -> _Open:
        """Emit a `prompt` event and open its slot. Raises `ChallengeAbandoned` if the task was
        aborted or has ended: nothing is asked of a user who stopped it."""
        payload = prompt_payload(prompt)
        with self._cond:
            if self._aborting or self._status == "ended":
                raise ChallengeAbandoned("the sync was aborted")
            if self._open is not None:
                raise RuntimeError("a task has one open prompt at a time")
            prompt_id = secrets.token_urlsafe(8)
            expires_at = clock.now() + timedelta(seconds=timeout_s)
            event = self._append_locked(
                "prompt",
                {
                    "prompt_id": prompt_id,
                    "instance_id": instance_id,
                    "run_id": run_id,
                    "expires_at": expires_at.isoformat(),
                    "prompt": payload,
                },
            )
            opened = _Open(prompt_id, event.id, prompt)
            self._open = opened
            wakes = self._wakes_locked()
        self._wake(wakes)
        return opened

    def wait_prompt(
        self, opened: _Open, *, timeout_s: float, poll: Callable[[], bool] | None = None
    ) -> tuple[PromptOutcome, Answer]:
        """Block the importer's thread until the prompt is resolved; return how and the answer.

        Resolved by `answer` (answered or cancelled), `abort` (aborted), the timeout (expired) or, for a
        decoupled prompt, `poll` returning True (confirmed). `poll` runs on this thread, outside the
        lock, every `tuning.poll_interval_s`; if it raises, the prompt is resolved `cancelled` and the
        error goes to the importer, which knows the bank's verdict.
        """
        deadline = clock.monotonic() + timeout_s
        interval = self.tuning.poll_interval_s
        next_poll = clock.monotonic() + interval
        while True:
            wakes: list[Callable[[], None]] = []
            with self._cond:
                if opened.outcome is None:
                    now = clock.monotonic()
                    if now >= deadline:
                        wakes = self._resolve_locked(opened, "expired")
                    else:
                        until = min(deadline, next_poll) if poll is not None else deadline
                        self._cond.wait(max(until - now, 0.0))
                outcome = opened.outcome
                answer: Answer = None
                if outcome is not None:
                    answer, opened.answer = opened.answer, None
            self._wake(wakes)
            if outcome is not None:
                return outcome, answer
            if poll is not None and clock.monotonic() >= next_poll:
                next_poll = clock.monotonic() + interval
                try:
                    confirmed = poll()
                except BaseException:
                    self._resolve(opened, "cancelled")
                    raise
                if confirmed:
                    self._resolve(opened, "confirmed")

    def answer(self, prompt_id: str, value: str | SecretText | None = None, *, cancel: bool = False) -> None:
        """Answer the open prompt or cancel it (`POST …/input`).

        `PromptNotOpen` for anything but the prompt open now; `InvalidAnswer` (the prompt stays open)
        for a value it cannot take: an empty secret, TAN or text, an option the choice does not list,
        or any value for a decoupled challenge (only a cancel).
        """
        with self._cond:
            opened = self._open
            if self._status == "ended" or opened is None or opened.prompt_id != prompt_id or opened.outcome:
                raise PromptNotOpen
            if cancel:
                wakes = self._resolve_locked(opened, "cancelled")
            else:
                text = value.reveal() if isinstance(value, SecretText) else value
                if opened.decoupled:
                    raise InvalidAnswer("a challenge confirmed in the app is not answered with a value")
                if text is None or text == "":
                    raise InvalidAnswer("an answer is required")
                if opened.kind == "choice" and text not in opened.options:
                    raise InvalidAnswer("the answer is not one of the options")
                opened.answer = SecretText(text) if opened.kind == "secret" else text
                wakes = self._resolve_locked(opened, "answered")
            self._cond.notify_all()
        self._wake(wakes)

    def _resolve(self, opened: _Open, outcome: PromptOutcome) -> None:
        with self._cond:
            wakes = self._resolve_locked(opened, outcome)
            self._cond.notify_all()
        self._wake(wakes)

    def _resolve_locked(self, opened: _Open, outcome: PromptOutcome) -> list[Callable[[], None]]:
        """Resolve once: emit `prompt_resolved`, drop the prompt event's body, close the slot."""
        if opened.outcome is not None:
            return []
        opened.outcome = outcome
        if self._open is opened:
            self._open = None
        old = self._events[opened.event_id - 1]
        self._events[opened.event_id - 1] = Event(
            old.id, old.name, {k: v for k, v in old.data.items() if k != "prompt"}
        )
        self._append_locked("prompt_resolved", {"prompt_id": opened.prompt_id, "outcome": outcome})
        return self._wakes_locked()

    # ---- abort and end ------------------------------------------------------------------

    @property
    def aborting(self) -> bool:
        with self._cond:
            return self._aborting

    def abort(self) -> None:
        """Stop the task: set the flag and resolve the open prompt aborted. A bank call in flight is
        not interrupted. Aborting an ended task is a no-op."""
        with self._cond:
            if self._status == "ended" or self._aborting:
                return
            self._aborting = True
            wakes = (
                self._resolve_locked(self._open, "aborted")
                if self._open is not None
                else self._wakes_locked()
            )
        self._wake(wakes)

    def mark_ended(self, outcome: Outcome) -> None:
        """Mark the task ended (before `task_ended` is emitted). Any prompt still open resolves aborted."""
        with self._cond:
            if self._status == "ended":
                return
            self._status = "ended"
            self._outcome = outcome
            self._ended_at = clock.monotonic()
            wakes = (
                self._resolve_locked(self._open, "aborted")
                if self._open is not None
                else self._wakes_locked()
            )
        self._wake(wakes)

    def emit_ended(self, not_started: tuple[int, ...]) -> Event:
        """The `task_ended` event: the outcome, the counts of ok and failed runs, the instances never
        reached."""
        with self._cond:
            outcome = self._outcome
            ok, failed = self._ok, self._failed
        return self.emit(
            "task_ended",
            {"outcome": outcome, "ok": ok, "failed": failed, "not_started": list(not_started)},
        )

    # ---- state read by the registry, the runner and the endpoints --------------------------

    @property
    def ended(self) -> bool:
        with self._cond:
            return self._status == "ended"

    def ended_for(self) -> float | None:
        """Seconds since the task was marked ended, None while it runs."""
        with self._cond:
            return None if self._ended_at is None else clock.monotonic() - self._ended_at

    def set_result(self, result: Any) -> None:
        with self._cond:
            self._result = result

    def status(self) -> TaskStatus:
        with self._cond:
            return TaskStatus(
                task_id=self.task_id,
                kind=self.kind,
                status=self._status,
                aborting=self._aborting,
                outcome=self._outcome,
                last_event_id=len(self._events),
                result=self._result,
            )

    def track_run(self, run_id: int) -> None:
        """A run this task started and has not ended; failed if the task crashes."""
        with self._cond:
            self._open_runs.add(run_id)

    def untrack_run(self, run_id: int) -> None:
        with self._cond:
            self._open_runs.discard(run_id)

    def open_run_ids(self) -> list[int]:
        with self._cond:
            return sorted(self._open_runs)
