"""The prompter an importer asks through (architecture §5.5): `ask` blocks its thread on the task's
one-slot hand-off until an answer, a cancel, an abort or the timeout.

It never retries and never stores an answer: the answer goes from the task's slot into the return
value and is not kept (architecture §5.6).
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.plugins.errors import ChallengeAbandoned, ChallengeExpired
from app.core.plugins.fetch import Answer, Prompt, TanPrompt
from app.core.tasks.task import Task


class TaskPrompter:
    """One per job. `run_id` says which run is current, None while signing in (it labels the prompt)."""

    def __init__(self, task: Task, instance_id: int, run_id: Callable[[], int | None] = lambda: None) -> None:
        self._task = task
        self._instance_id = instance_id
        self._run_id = run_id

    def ask(
        self,
        prompt: Prompt,
        *,
        poll: Callable[[], bool] | None = None,
        timeout_s: float | None = None,
    ) -> Answer:
        decoupled = isinstance(prompt, TanPrompt) and prompt.medium == "decoupled"
        if decoupled and poll is None:
            raise ValueError("a decoupled prompt needs a poll function")
        timeout = self._task.tuning.prompt_timeout_s if timeout_s is None else timeout_s
        opened = self._task.begin_prompt(
            prompt, instance_id=self._instance_id, run_id=self._run_id(), timeout_s=timeout
        )
        outcome, answer = self._task.wait_prompt(opened, timeout_s=timeout, poll=poll if decoupled else None)
        match outcome:
            case "answered":
                return answer
            case "confirmed":
                return None
            case "expired":
                raise ChallengeExpired("the challenge timed out")
            case "aborted":
                raise ChallengeAbandoned("the sync was aborted")
            case _:  # cancelled
                raise ChallengeAbandoned("the challenge was cancelled")
