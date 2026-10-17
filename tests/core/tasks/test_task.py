"""The task and its prompter, without a database or an event loop (architecture §5.3, §8): the hand-off
between a blocked importer thread and the request that answers it."""

from __future__ import annotations

import pytest

from app.core.plugins.errors import AuthRejected, ChallengeAbandoned, ChallengeExpired
from app.core.plugins.fetch import (
    ChoicePrompt,
    Option,
    SecretPrompt,
    SecretText,
    TanPrompt,
    TextPrompt,
)
from app.core.tasks import InvalidAnswer, PromptNotOpen, Task, TaskPrompter, TaskTuning
from tests.core.tasks.helpers import FAST, Asked, names, open_prompt, until


def make_task(tuning: TaskTuning = FAST) -> tuple[Task, TaskPrompter]:
    task = Task("t1", 1, "sync", tuning, (7,))
    return task, TaskPrompter(task, 7)


def resolved(task: Task) -> list[str]:
    return [e.data["outcome"] for e in task.events_after(0) if e.name == "prompt_resolved"]


# ---- the hand-off -----------------------------------------------------------------------------


def test_an_answer_reaches_the_blocked_importer_and_is_never_kept() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, SecretPrompt("pin"))
    event = open_prompt(task)
    assert event.data["prompt"] == {"kind": "secret", "subject": "pin"}
    assert event.data["instance_id"] == 7 and event.data["run_id"] is None and "expires_at" in event.data
    task.answer(event.data["prompt_id"], "s3cret-pin")
    got = asked.result()
    assert isinstance(got, SecretText) and got.reveal() == "s3cret-pin"
    assert resolved(task) == ["answered"]
    assert "s3cret-pin" not in repr(task.events_after(0)) and "s3cret-pin" not in repr(task.__dict__)


def test_a_resolved_prompt_replays_without_its_body() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, TanPrompt("image", "scan", image=b"IMG", image_mime="image/png"))
    event = open_prompt(task)
    assert "image_b64" in event.data["prompt"]  # while open the reattaching tab gets it
    assert "image_b64" in repr(task.events_after(0)[0].data)
    task.answer(event.data["prompt_id"], "123456")
    asked.result()
    replay = task.events_after(0)
    assert [e.name for e in replay] == ["prompt", "prompt_resolved"]
    assert "prompt" not in replay[0].data and replay[0].data["prompt_id"] == event.data["prompt_id"]
    assert "image_b64" not in repr(replay)


def test_a_wrong_prompt_id_is_refused_and_the_prompt_stays_open() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, SecretPrompt("pin"))
    event = open_prompt(task)
    with pytest.raises(PromptNotOpen):
        task.answer("not-the-id", "x")
    assert not asked.done.is_set()
    task.answer(event.data["prompt_id"], "right")
    assert asked.result().reveal() == "right"


def test_a_duplicate_answer_is_refused() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, SecretPrompt("pin"))
    pid = open_prompt(task).data["prompt_id"]
    task.answer(pid, "first")
    with pytest.raises(PromptNotOpen):
        task.answer(pid, "second")
    assert asked.result().reveal() == "first"


def test_nothing_is_open_before_any_prompt_and_after_the_end() -> None:
    task, prompter = make_task()
    with pytest.raises(PromptNotOpen):
        task.answer("x", "y")
    asked = Asked(prompter, SecretPrompt("pin"))
    pid = open_prompt(task).data["prompt_id"]
    task.mark_ended("completed")
    with pytest.raises(ChallengeAbandoned):
        asked.result()
    with pytest.raises(PromptNotOpen):
        task.answer(pid, "late")


def test_a_cancel_abandons_the_challenge() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, SecretPrompt("pin"))
    task.answer(open_prompt(task).data["prompt_id"], cancel=True)
    with pytest.raises(ChallengeAbandoned):
        asked.result()
    assert resolved(task) == ["cancelled"]


def test_a_timeout_expires_the_challenge_and_a_late_answer_is_refused() -> None:
    task, prompter = make_task(TaskTuning(prompt_timeout_s=0.1, poll_interval_s=0.02))
    asked = Asked(prompter, SecretPrompt("pin"))
    pid = open_prompt(task).data["prompt_id"]
    with pytest.raises(ChallengeExpired):
        asked.result()
    assert resolved(task) == ["expired"]
    with pytest.raises(PromptNotOpen):
        task.answer(pid, "too late")


def test_the_importer_may_pass_its_own_timeout() -> None:
    task, prompter = make_task()  # the default is five seconds
    asked = Asked(prompter, SecretPrompt("pin"), timeout_s=0.05)
    with pytest.raises(ChallengeExpired):
        asked.result()


def test_abort_resolves_the_open_prompt_and_nothing_is_asked_afterwards() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, SecretPrompt("pin"))
    open_prompt(task)
    task.abort()
    with pytest.raises(ChallengeAbandoned):
        asked.result()
    assert resolved(task) == ["aborted"] and task.aborting
    before = len(task.events_after(0))
    with pytest.raises(ChallengeAbandoned):
        prompter.ask(SecretPrompt("pin"))
    assert len(task.events_after(0)) == before  # no prompt event for a user who stopped it


def test_aborting_an_ended_task_is_a_no_op() -> None:
    task, _ = make_task()
    task.mark_ended("completed")
    task.abort()
    assert not task.aborting and task.status().outcome == "completed"


# ---- what an answer may be --------------------------------------------------------------------


def test_an_empty_secret_or_tan_is_refused_and_the_prompt_stays_open() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, TanPrompt("text", "enter it"))
    pid = open_prompt(task).data["prompt_id"]
    for empty in ("", None):
        with pytest.raises(InvalidAnswer) as err:
            task.answer(pid, empty)
        assert err.value.field == "value"
    assert not asked.done.is_set()
    task.answer(pid, "654321")
    assert asked.result().reveal() == "654321"


def test_a_choice_takes_only_a_listed_option() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, ChoicePrompt("tan_medium", (Option("1", "Phone"), Option("2", "Card"))))
    event = open_prompt(task)
    assert event.data["prompt"]["options"] == [{"id": "1", "label": "Phone"}, {"id": "2", "label": "Card"}]
    with pytest.raises(InvalidAnswer):
        task.answer(event.data["prompt_id"], "3")
    task.answer(event.data["prompt_id"], "2")
    assert asked.result() == "2"


def test_a_text_prompt_returns_plain_text() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, TextPrompt("tan_medium_name"))
    task.answer(open_prompt(task).data["prompt_id"], "My phone")
    assert asked.result() == "My phone"


# ---- decoupled challenges ---------------------------------------------------------------------


def test_a_decoupled_challenge_is_confirmed_by_the_importers_poll() -> None:
    task, prompter = make_task()
    calls: list[int] = []

    def poll() -> bool:
        calls.append(1)
        return len(calls) >= 3

    asked = Asked(prompter, TanPrompt("decoupled", "confirm in the app"), poll=poll)
    assert asked.result() is None
    assert len(calls) == 3 and resolved(task) == ["confirmed"]


def test_a_decoupled_challenge_the_bank_refuses_ends_with_the_banks_error() -> None:
    task, prompter = make_task()

    def poll() -> bool:
        raise AuthRejected("the bank refused")

    asked = Asked(prompter, TanPrompt("decoupled", "confirm"), poll=poll)
    with pytest.raises(AuthRejected):
        asked.result()
    assert resolved(task) == ["cancelled"]


def test_a_decoupled_challenge_nobody_confirms_expires() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, TanPrompt("decoupled", "confirm"), poll=lambda: False, timeout_s=0.1)
    with pytest.raises(ChallengeExpired):
        asked.result()
    assert resolved(task) == ["expired"]


def test_a_decoupled_challenge_accepts_only_the_cancel() -> None:
    task, prompter = make_task()
    asked = Asked(prompter, TanPrompt("decoupled", "confirm"), poll=lambda: False)
    pid = open_prompt(task).data["prompt_id"]
    with pytest.raises(InvalidAnswer):
        task.answer(pid, "123456")
    assert not asked.done.is_set()
    task.answer(pid, cancel=True)
    with pytest.raises(ChallengeAbandoned):
        asked.result()


def test_a_decoupled_challenge_needs_a_poll() -> None:
    _, prompter = make_task()
    with pytest.raises(ValueError):
        prompter.ask(TanPrompt("decoupled", "confirm"))


def test_a_poll_is_never_called_for_a_typed_challenge() -> None:
    task, prompter = make_task()
    calls: list[int] = []
    asked = Asked(prompter, TanPrompt("text", "enter"), poll=lambda: calls.append(1) or True)
    task.answer(open_prompt(task).data["prompt_id"], "1")
    asked.result()
    assert calls == []


# ---- events, replay, subscribers --------------------------------------------------------------


def test_event_ids_run_from_one_and_a_replay_returns_the_rest() -> None:
    task, _ = make_task()
    for n in range(5):
        event = task.emit("instance_started", {"instance_id": n})
        assert event.id == n + 1
    assert [e.id for e in task.events_after(0)] == [1, 2, 3, 4, 5]
    assert [e.id for e in task.events_after(3)] == [4, 5]
    assert task.events_after(5) == [] and task.status().last_event_id == 5


def test_subscribers_are_woken_by_every_change_and_counted() -> None:
    task, prompter = make_task()
    woken: list[int] = []
    handle = task.subscribe(lambda: woken.append(1))
    assert task.attached == 1 and task.detached_for() == 0.0
    task.emit("instance_started", {"instance_id": 1})
    asked = Asked(prompter, SecretPrompt("pin"))
    pid = open_prompt(task).data["prompt_id"]
    task.answer(pid, "x")
    asked.result()
    assert len(woken) >= 3  # the event, the prompt, the resolution
    task.unsubscribe(handle)
    assert task.attached == 0
    until(lambda: task.detached_for() > 0.0, "the detached clock")
    task.unsubscribe(handle)  # idempotent


def test_a_task_with_no_stream_ever_counts_as_detached_since_creation() -> None:
    task, _ = make_task()
    until(lambda: task.detached_for() > 0.0, "the detached clock")
    task.subscribe(lambda: None)
    assert task.detached_for() == 0.0


def test_a_failing_subscriber_never_reaches_the_emitter() -> None:
    task, _ = make_task()

    def boom() -> None:
        raise RuntimeError("closed loop")

    task.subscribe(boom)
    task.emit("instance_started", {"instance_id": 1})  # does not raise
    assert names(task) == ["instance_started"]


def test_the_task_ended_counts_come_from_the_runs_it_saw() -> None:
    task, _ = make_task()
    task.emit("run_finished", {"run_id": 1, "stats": {}})
    task.emit("run_failed", {"run_id": 2})
    task.emit("instance_failed", {"instance_id": 7, "run_ids": [3, 4]})
    task.mark_ended("completed")
    task.emit_ended((9,))
    last = task.events_after(0)[-1]
    assert last.name == "task_ended"
    assert dict(last.data) == {"outcome": "completed", "ok": 1, "failed": 3, "not_started": [9]}
    status = task.status()
    assert (status.status, status.outcome, status.aborting) == ("ended", "completed", False)
