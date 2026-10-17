"""Threads and waits for the task tests: an importer's blocked `ask` runs on a thread, the test plays the
user."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from app.core.plugins.fetch import Prompt
from app.core.tasks import Event, Task, TaskPrompter, TaskTuning
from app.utils import clock

FAST = TaskTuning(
    prompt_timeout_s=5.0, poll_interval_s=0.02, abandon_grace_s=0.0, retention_s=0.2, keepalive_s=0.05
)
WAIT = 5.0


class Asked:
    """An `ask` running on its own thread; `value` or `error` once it returned."""

    def __init__(self, prompter: TaskPrompter, prompt: Prompt, **kw: Any) -> None:
        self.value: Any = None
        self.error: BaseException | None = None
        self.done = threading.Event()

        def run() -> None:
            try:
                self.value = prompter.ask(prompt, **kw)
            except BaseException as exc:
                self.error = exc
            finally:
                self.done.set()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def result(self) -> Any:
        assert self.done.wait(WAIT), "the ask never returned"
        self.thread.join(WAIT)
        if self.error is not None:
            raise self.error
        return self.value


def open_prompt(task: Task, after: int = 0) -> Event:
    """The next `prompt` event above `after` that still carries its body (it is open)."""
    deadline = clock.monotonic() + WAIT
    seen = after
    while clock.monotonic() < deadline:
        for event in task.wait_for_events(seen, 0.05):
            seen = max(seen, event.id)
            if event.name == "prompt" and "prompt" in event.data:
                return event
    raise AssertionError("no prompt was opened")


def names(task: Task) -> list[str]:
    return [e.name for e in task.events_after(0)]


def until(condition: Callable[[], bool], what: str = "the condition") -> None:
    deadline = clock.monotonic() + WAIT
    while not condition():
        if clock.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        clock.sleep(0.01)
