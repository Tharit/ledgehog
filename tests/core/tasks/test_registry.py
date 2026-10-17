"""The registry: one active task per user, one holder per instance, retention and eviction, and a task
hidden from another user (architecture §4.3, §5.3). No database, no event loop."""

from __future__ import annotations

import pytest

from app.core.importers.plan import JobPlan, PlannedItem
from app.core.tasks import InstanceBusy, TaskActive, TaskRegistry, TaskTuning
from app.utils import clock
from tests.core.tasks.helpers import FAST

ITEM = (PlannedItem("transactions", 5),)


def jobs(*instance_ids: int) -> list[JobPlan]:
    return [JobPlan(i, ITEM) for i in instance_ids]


def test_start_creates_a_task_and_emits_task_started_with_the_plan() -> None:
    registry = TaskRegistry(FAST)
    started = registry.start(
        1, "sync", [JobPlan(3, (PlannedItem("transactions", 5), PlannedItem("documents", None)))]
    )
    first = started.task.events_after(0)[0]
    assert (first.id, first.name) == (1, "task_started")
    assert first.data["kind"] == "sync"
    assert first.data["instances"] == [
        {
            "instance_id": 3,
            "items": [{"account_id": 5, "kind": "transactions"}, {"account_id": None, "kind": "documents"}],
        }
    ]
    assert started.busy == () and registry.is_held(3) and registry.held_instances() == {3}


def test_a_second_start_by_one_user_is_refused_with_the_task_id() -> None:
    registry = TaskRegistry(FAST)
    first = registry.start(1, "sync", jobs(3)).task
    with pytest.raises(TaskActive) as err:
        registry.start(1, "sync", jobs(4))
    assert err.value.task_id == first.task_id
    assert not registry.is_held(4)  # nothing was claimed


def test_two_users_run_different_instances_at_once() -> None:
    registry = TaskRegistry(FAST)
    a = registry.start(1, "sync", jobs(3)).task
    b = registry.start(2, "sync", jobs(4)).task
    assert registry.active(1) is a and registry.active(2) is b


def test_an_instance_another_task_holds_is_busy() -> None:
    registry = TaskRegistry(FAST)
    registry.start(1, "sync", jobs(3, 4))
    with pytest.raises(InstanceBusy) as err:
        registry.start(2, "sync", jobs(4, 5))
    assert err.value.instance_ids == (4,)
    assert not registry.is_held(5)  # all or nothing


def test_everything_leaves_out_busy_instances_and_reports_them() -> None:
    registry = TaskRegistry(FAST)
    registry.start(1, "sync", jobs(3))
    started = registry.start(2, "sync", jobs(3, 4), skip_busy=True)
    assert [j.instance_id for j in started.jobs] == [4] and started.busy == (3,)
    assert started.task.instance_ids == (4,)


def test_everything_with_nothing_left_is_busy() -> None:
    registry = TaskRegistry(FAST)
    registry.start(1, "sync", jobs(3))
    with pytest.raises(InstanceBusy):
        registry.start(2, "sync", jobs(3), skip_busy=True)
    assert registry.active(2) is None


def test_a_claim_is_released_when_its_job_ends() -> None:
    registry = TaskRegistry(FAST)
    task = registry.start(1, "sync", jobs(3, 4)).task
    registry.release_instance(task, 3)
    assert not registry.is_held(3) and registry.is_held(4)
    other = registry.start(2, "sync", jobs(3)).task  # now free for another user
    assert registry.is_held(3)
    registry.release_instance(task, 3)  # not the holder any more: leaves the other's claim alone
    assert registry.is_held(3)
    registry.finish(other, "completed")


def test_the_task_is_ended_and_the_slot_free_before_task_ended_is_emitted() -> None:
    registry = TaskRegistry(FAST)
    task = registry.start(1, "sync", jobs(3, 4)).task
    seen: list[tuple[bool, bool, bool]] = []

    def on_event() -> None:
        if task.events_after(0)[-1].name == "task_ended":
            seen.append((task.ended, registry.active(1) is None, registry.is_held(3) or registry.is_held(4)))

    task.subscribe(on_event)
    registry.finish(task, "aborted", not_started=[4])
    assert seen == [(True, True, False)]
    assert task.events_after(0)[-1].data["not_started"] == [4]
    registry.start(1, "sync", jobs(3))  # a client reacting to task_ended may start the next task


def test_active_is_the_running_task_only() -> None:
    registry = TaskRegistry(FAST)
    task = registry.start(1, "sync", jobs(3)).task
    assert registry.active(1) is task
    registry.finish(task, "completed")
    assert registry.active(1) is None
    assert registry.get(task.task_id, 1) is task  # still there, for the replay and the status


def test_a_finished_task_stays_for_the_retention_and_is_then_swept() -> None:
    registry = TaskRegistry(TaskTuning(retention_s=0.1))
    task = registry.start(1, "sync", jobs(3)).task
    registry.finish(task, "completed")
    assert registry.get(task.task_id, 1) is task
    deadline = clock.monotonic() + 5
    while registry.get(task.task_id, 1) is not None:
        assert clock.monotonic() < deadline, "the finished task was never swept"
        clock.sleep(0.02)


def test_a_running_task_is_never_swept() -> None:
    registry = TaskRegistry(TaskTuning(retention_s=0.0))
    task = registry.start(1, "sync", jobs(3)).task
    clock.sleep(0.05)
    assert registry.get(task.task_id, 1) is task


def test_the_next_start_evicts_the_users_finished_task() -> None:
    registry = TaskRegistry(TaskTuning(retention_s=3600))
    old = registry.start(1, "sync", jobs(3)).task
    registry.finish(old, "completed")
    new = registry.start(1, "sync", jobs(3)).task
    assert registry.get(old.task_id, 1) is None and registry.get(new.task_id, 1) is new


def test_another_users_task_is_not_found() -> None:
    registry = TaskRegistry(FAST)
    task = registry.start(1, "sync", jobs(3)).task
    assert registry.get(task.task_id, 2) is None
    assert registry.active(2) is None
    assert registry.get("unknown", 1) is None


def test_discovery_is_a_task_like_any_other_with_no_items() -> None:
    registry = TaskRegistry(FAST)
    task = registry.start(1, "discovery", [JobPlan(3)]).task
    assert task.events_after(0)[0].data["instances"] == [{"instance_id": 3, "items": []}]
    with pytest.raises(TaskActive):  # one active task per user, discovery included
        registry.start(1, "sync", jobs(4))
