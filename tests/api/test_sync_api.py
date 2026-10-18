"""The sync operations over HTTP (architecture §4.1, §4.3): the plan, a start and its refusals, the active
task, the status, answers to prompts, the abort, and that another user's task does not exist for you.

The task itself is tested without HTTP (tests/core/tasks); here the endpoints are, against the scripted
`testfetch` importer."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from app.core.accounts import close_account
from tests.api import sync_helpers as h
from tests.api.sync_helpers import PIN, Sync, error_of

sync = h.sync  # fixtures shared by the sync API tests
make_sync = h.make_sync

CHOICE = {
    "ask": "choice",
    "subject": "tan_medium",
    "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
}
SENTINEL = "SENTINEL-7f3a-do-not-leak"


def names(frames) -> list[str]:
    return [f.event for f in frames]


# ---- the plan ---------------------------------------------------------------------------------


def test_the_plan_lists_instances_accounts_and_where_each_fetch_starts(sync: Sync):
    inst, (a1, a2) = sync.world(refs=("A1", "A2"), label="Bank")
    only_docs = sync.instance({"documents": []}, label="Docs", emits=("documents",))
    r = sync.client.get("/api/sync/plan")
    assert r.status_code == 200, r.text
    plan = {p["instance_id"]: p for p in r.json()}
    assert set(plan) == {inst, only_docs}
    bank = plan[inst]
    assert (bank["importer"], bank["label"], bank["busy"]) == ("testfetch", "Bank", False)
    assert [(a["account_id"], a["external_ref"]) for a in bank["accounts"]] == [(a1, "A1"), (a2, "A2")]
    first = bank["accounts"][0]
    # no coverage and no entries: the importer's own default (thirty days before today), editable
    assert (first["since"], first["since_source"], first["editable"]) == (
        "2026-07-22",
        "importer_default",
        True,
    )
    assert bank["documents_since"] is None  # it emits no documents
    assert plan[only_docs]["accounts"] == [] and plan[only_docs]["documents_since"] is not None


def test_the_plan_shows_a_derived_start_that_is_not_editable_once_there_is_coverage(sync: Sync):
    inst, (a1,) = sync.world()
    sync.wait_ended(sync.started())
    (acc,) = next(p for p in sync.client.get("/api/sync/plan").json() if p["instance_id"] == inst)["accounts"]
    assert acc["account_id"] == a1 and acc["since_source"] == "coverage" and acc["editable"] is False
    assert acc["since"] == "2026-08-13"  # synced through the 20th, a week of overlap before it


def test_the_plan_leaves_out_the_other_users_instances_and_marks_a_held_one_busy(sync: Sync):
    shared, _ = sync.world(label="Shared")
    mine, _ = sync.world(label="Mine", access="owner", owner="anna")
    theirs, _ = sync.world(label="Theirs", access="owner", owner="ben")
    anna = {p["instance_id"] for p in sync.client.get("/api/sync/plan").json()}
    ben = {p["instance_id"] for p in sync.other.get("/api/sync/plan").json()}
    assert anna == {shared, mine} and ben == {shared, theirs}
    # a task holds an instance: the plan says so, for everyone
    blocked, _ = sync.world({"open": [PIN]}, label="Blocked")
    task = sync.started([{"instance_id": blocked}])
    sync.open_prompt(task)
    for who in (sync.client, sync.other):
        busy = {p["instance_id"]: p["busy"] for p in who.get("/api/sync/plan").json()}
        assert busy[blocked] is True and busy[shared] is False


def test_a_file_importer_and_a_disabled_instance_are_not_in_the_plan(sync: Sync):
    live, _ = sync.world(label="Live")
    off, _ = sync.world(label="Off")
    csv = sync.instance({}, label="CSV", importer="csv", emits=("transactions",))
    assert sync.client.put(f"/api/importers/instances/{off}", json={"disabled": True}).status_code == 200
    assert [p["instance_id"] for p in sync.client.get("/api/sync/plan").json()] == [live]
    assert csv not in [p["instance_id"] for p in sync.client.get("/api/sync/plan").json()]


# ---- starting ---------------------------------------------------------------------------------


def test_an_empty_body_starts_everything_the_user_may_run(sync: Sync):
    shared, (a1,) = sync.world(label="Shared")
    mine, (a2,) = sync.world(label="Mine", access="owner", owner="anna")
    sync.world(label="Theirs", access="owner", owner="ben")
    r = sync.start()
    assert (r.status_code, set(r.json())) == (202, {"task_id", "busy"}) and r.json()["busy"] == []
    task = r.json()["task_id"]
    st = sync.wait_ended(task)
    assert (st["kind"], st["outcome"]) == ("sync", "completed")
    frames = sync.events(task)
    assert frames[0].event == "task_started" and frames[-1].event == "task_ended"
    assert [i["instance_id"] for i in frames[0].data["instances"]] == [shared, mine]
    assert sorted(f.data["account_id"] for f in frames if f.event == "run_finished") == [a1, a2]


def test_an_explicit_item_runs_one_account_and_nothing_else(sync: Sync):
    inst, (a1, a2) = sync.world(refs=("A1", "A2"))
    task = sync.started([{"instance_id": inst, "account_id": a2}])
    sync.wait_ended(task)
    done = [f for f in sync.events(task) if f.event == "run_finished"]
    assert [f.data["account_id"] for f in done] == [a2]
    assert [r for r in (sync.run_count(f"account_id = {a1}"),)] == [0]


def test_a_start_for_an_account_without_coverage_may_choose_where_it_starts(sync: Sync):
    inst, (a1,) = sync.world()
    task = sync.started([{"instance_id": inst, "account_id": a1, "since": "2026-08-15"}])
    sync.wait_ended(task)
    (started,) = [f for f in sync.events(task) if f.event == "run_started"]
    assert started.data["since"] == "2026-08-15"


def test_since_for_an_account_with_coverage_is_refused_and_nothing_starts(sync: Sync):
    inst, (a1,) = sync.world()
    sync.wait_ended(sync.started())
    error_of(
        sync.start([{"instance_id": inst, "account_id": a1, "since": "2026-08-15"}]),
        422,
        "start_not_editable",
    )
    assert sync.client.get("/api/sync/active").status_code == 204


def test_a_start_is_validated_as_a_whole(sync: Sync):
    inst, (a1,) = sync.world()
    before = sync.run_count()
    r = sync.start([{"instance_id": inst, "account_id": a1}, {"instance_id": inst + 999}])
    error_of(r, 404, "not_found")
    assert sync.client.get("/api/sync/active").status_code == 204 and sync.run_count() == before


def test_unknown_instance_and_account_are_404(sync: Sync):
    inst, _ = sync.world()
    error_of(sync.start([{"instance_id": 9999}]), 404, "not_found")
    error_of(sync.start([{"instance_id": inst, "account_id": 9999}]), 404, "not_found")


def test_an_account_not_linked_to_the_instance_is_409(sync: Sync):
    inst, _ = sync.world()
    stranger = sync.account("Stranger")
    error_of(sync.start([{"instance_id": inst, "account_id": stranger}]), 409, "account_not_linked")


def test_the_other_users_instance_is_403(sync: Sync):
    theirs, _ = sync.world(access="owner", owner="ben")
    error_of(sync.start([{"instance_id": theirs}]), 403, "forbidden")


def test_a_disabled_instance_is_409(sync: Sync):
    inst, _ = sync.world()
    sync.client.put(f"/api/importers/instances/{inst}", json={"disabled": True})
    error_of(sync.start([{"instance_id": inst}]), 409, "instance_disabled")


def test_a_file_importer_is_not_a_fetch_source(sync: Sync):
    csv = sync.instance({}, importer="csv", emits=("transactions",))
    error_of(sync.start([{"instance_id": csv}]), 409, "not_a_fetch_source")


def test_an_importer_not_registered_here_is_unavailable(sync: Sync):
    ghost = sync.instance({}, importer="ghost", emits=("transactions",))
    error_of(sync.start([{"instance_id": ghost}]), 409, "importer_unavailable")


def test_a_closed_account_is_409(sync: Sync):
    inst, (a1,) = sync.world()
    close_account(sync.engine, a1, date(2026, 8, 1))
    error_of(sync.start([{"instance_id": inst, "account_id": a1}]), 409, "account_closed")


def test_transactions_of_an_instance_that_emits_none_is_not_an_account_source(sync: Sync):
    docs = sync.instance({"documents": []}, emits=("documents",))
    error_of(sync.start([{"instance_id": docs, "kind": "transactions"}]), 409, "not_an_account_source")


def test_nothing_to_sync_is_422(sync: Sync):
    error_of(sync.start(), 422, "nothing_to_sync")  # no instance at all
    sync.world()
    error_of(sync.start([]), 422, "nothing_to_sync")  # an explicit empty list


def test_items_that_make_no_sense_are_422_naming_the_field(sync: Sync):
    inst, (a1,) = sync.world()
    r = sync.start([{"instance_id": inst, "since": "2026-08-15"}])  # a start needs its account
    err = error_of(r, 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "items", "since"]
    r = sync.start([{"instance_id": inst, "account_id": a1, "since": "2030-01-01"}])  # after today
    assert error_of(r, 422, "validation_error")["details"][0]["location"][-1] == "since"
    r = sync.start([{"instance_id": inst, "account_id": a1, "kind": "documents"}])
    assert error_of(r, 422, "validation_error")["details"][0]["location"][-1] == "kind"
    error_of(
        sync.client.post("/api/sync", json={"items": [{"instance_id": inst, "bogus": 1}]}),
        422,
        "validation_error",
    )
    error_of(sync.client.post("/api/sync", json={"items": [{"instance_id": 0}]}), 422, "validation_error")


def test_a_second_start_while_one_runs_is_task_active_with_the_task_to_reattach_to(sync: Sync):
    inst, _ = sync.world({"open": [PIN]})
    first = sync.started()
    sync.open_prompt(first)
    err = error_of(sync.start(), 409, "task_active")
    assert err["details"] == {"task_id": first}


def test_an_instance_another_task_holds_is_busy(sync: Sync):
    held, _ = sync.world({"open": [PIN]}, label="Held")
    free, (free_account,) = sync.world(label="Free")
    first = sync.started([{"instance_id": held}], client=sync.client)
    sync.open_prompt(first)
    # an explicit item for it is refused ...
    err = error_of(sync.start([{"instance_id": held}], client=sync.other), 409, "instance_busy")
    assert err["details"] == {"instance_ids": [held]}
    # ... "everything" leaves it out and says so
    r = sync.start(client=sync.other)
    assert r.status_code == 202 and r.json()["busy"] == [held], r.text
    task = r.json()["task_id"]
    sync.wait_ended(task, sync.other)
    assert [
        f.data["account_id"] for f in sync.events(task, client=sync.other) if f.event == "run_finished"
    ] == [free_account]


def test_everything_with_every_instance_held_is_instance_busy(sync: Sync):
    held, _ = sync.world({"open": [PIN]})
    sync.open_prompt(sync.started())
    err = error_of(sync.start(client=sync.other), 409, "instance_busy")
    assert err["details"] == {"instance_ids": [held]}


def test_a_start_needs_a_session(sync: Sync):
    from fastapi.testclient import TestClient

    anonymous = TestClient(sync.app, base_url="http://localhost")
    assert anonymous.post("/api/sync").status_code == 401
    assert anonymous.get("/api/sync/plan").status_code == 401
    assert anonymous.get("/api/sync/active").status_code == 401


# ---- the active task and the status ----------------------------------------------------------------


def test_active_is_204_without_a_task_and_the_status_while_one_runs(sync: Sync):
    assert sync.client.get("/api/sync/active").status_code == 204
    inst, _ = sync.world({"open": [PIN]})
    task = sync.started()
    sync.open_prompt(task)
    r = sync.client.get("/api/sync/active")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task and body["kind"] == "sync" and body["status"] == "running"
    assert body == sync.status(task)
    assert (body["aborting"], body["outcome"], body["result"]) == (False, None, None)
    assert body["last_event_id"] == 3  # task_started, instance_started, prompt
    assert sync.other.get("/api/sync/active").status_code == 204  # not another user's


def test_a_finished_task_is_not_active_but_keeps_its_status(sync: Sync):
    sync.world()
    task = sync.started()
    st = sync.wait_ended(task)
    assert (st["status"], st["outcome"], st["aborting"]) == ("ended", "completed", False)
    assert st["last_event_id"] == len(sync.events(task))
    assert sync.client.get("/api/sync/active").status_code == 204


def test_an_unknown_task_is_404(sync: Sync):
    error_of(sync.client.get("/api/sync/tasks/nope"), 404, "not_found")
    error_of(sync.client.get("/api/sync/tasks/nope/events"), 404, "not_found")
    error_of(sync.client.post("/api/sync/tasks/nope/abort"), 404, "not_found")
    error_of(
        sync.client.post("/api/sync/tasks/nope/input", json={"prompt_id": "x", "cancel": True}),
        404,
        "not_found",
    )


# ---- another user's task does not exist -------------------------------------------------------------


def test_another_users_task_is_404_for_status_stream_input_and_abort(sync: Sync):
    sync.world({"open": [PIN]})
    task = sync.started()
    prompt = sync.open_prompt(task)
    base = f"/api/sync/tasks/{task}"
    error_of(sync.other.get(base), 404, "not_found")
    error_of(sync.other.get(f"{base}/events"), 404, "not_found")
    error_of(
        sync.other.post(f"{base}/input", json={"prompt_id": prompt["prompt_id"], "value": "1234"}),
        404,
        "not_found",
    )
    error_of(sync.other.post(f"{base}/abort"), 404, "not_found")
    st = sync.status(task)  # untouched: still running, still waiting for its owner
    assert st["status"] == "running" and st["aborting"] is False
    assert sync.answer(task, prompt["prompt_id"], "1234").status_code == 204


# ---- answering a prompt -----------------------------------------------------------------------------


def test_an_answer_is_204_and_the_task_goes_on(sync: Sync):
    inst, (a1,) = sync.world({"open": [PIN]})
    task = sync.started()
    prompt = sync.open_prompt(task)
    assert prompt["prompt"] == {"kind": "secret", "subject": "pin"} and prompt["run_id"] is None
    r = sync.answer(task, prompt["prompt_id"], "1234")
    assert (r.status_code, r.content) == (204, b"")
    st = sync.wait_ended(task)
    assert st["outcome"] == "completed"
    frames = sync.events(task)
    assert "run_finished" in names(frames)
    (resolved,) = [f for f in frames if f.event == "prompt_resolved"]
    assert resolved.data == {"prompt_id": prompt["prompt_id"], "outcome": "answered"}


def test_a_wrong_pin_fails_the_instance_not_the_request(sync: Sync):
    sync.world({"open": [PIN]})
    task = sync.started()
    prompt = sync.open_prompt(task)
    assert sync.answer(task, prompt["prompt_id"], "0000").status_code == 204
    sync.wait_ended(task)
    (failed,) = [f for f in sync.events(task) if f.event == "instance_failed"]
    assert failed.data["code"] == "auth_rejected" and failed.data["retryable"] is True


def test_a_cancel_resolves_the_prompt_cancelled(sync: Sync):
    sync.world({"open": [PIN]})
    task = sync.started()
    prompt = sync.open_prompt(task)
    r = sync.client.post(
        f"/api/sync/tasks/{task}/input", json={"prompt_id": prompt["prompt_id"], "cancel": True}
    )
    assert r.status_code == 204
    sync.wait_ended(task)
    frames = sync.events(task)
    assert [f.data["outcome"] for f in frames if f.event == "prompt_resolved"] == ["cancelled"]
    assert [f.data["code"] for f in frames if f.event == "instance_failed"] == ["challenge_abandoned"]


def test_a_duplicate_or_late_or_unknown_answer_is_prompt_not_open(sync: Sync):
    sync.world({"open": [PIN]})
    task = sync.started()
    prompt = sync.open_prompt(task)
    pid = prompt["prompt_id"]
    error_of(sync.answer(task, "not-this-one", "1234"), 409, "conflict")
    assert sync.answer(task, pid, "1234").status_code == 204
    err = error_of(sync.answer(task, pid, "1234"), 409, "conflict")  # the same answer again
    assert err["details"] == {"reason": "prompt_not_open"}
    sync.wait_ended(task)
    err = error_of(sync.answer(task, pid, "1234"), 409, "conflict")  # after the end
    assert err["details"] == {"reason": "prompt_not_open"}


def test_an_answer_with_no_prompt_open_is_prompt_not_open(sync: Sync):
    sync.world()
    task = sync.started()
    sync.wait_ended(task)
    assert error_of(sync.answer(task, "x", "1"), 409, "conflict")["details"] == {"reason": "prompt_not_open"}


def test_an_invalid_choice_is_422_naming_value_and_the_prompt_stays_open(sync: Sync):
    sync.world({"open": [CHOICE]})
    task = sync.started()
    prompt = sync.open_prompt(task)
    pid = prompt["prompt_id"]
    err = error_of(sync.answer(task, pid, "zzz"), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "value"]
    error_of(sync.answer(task, pid, ""), 422, "validation_error")  # nothing to answer with
    error_of(
        sync.client.post(f"/api/sync/tasks/{task}/input", json={"prompt_id": pid}), 422, "validation_error"
    )
    assert sync.status(task)["status"] == "running"
    assert sync.answer(task, pid, "a").status_code == 204  # still open: a valid answer is taken
    sync.wait_ended(task)


def test_a_secret_never_comes_back_in_an_error_or_a_log(sync: Sync, caplog: pytest.LogCaptureFixture):
    sync.world({"open": [CHOICE]})
    task = sync.started()
    pid = sync.open_prompt(task)["prompt_id"]
    caplog.set_level(logging.DEBUG)
    wrong_value = sync.answer(task, pid, SENTINEL)  # a choice it does not list
    wrong_type = sync.client.post(
        f"/api/sync/tasks/{task}/input", json={"prompt_id": pid, "value": {"nested": SENTINEL}}
    )
    extra_field = sync.client.post(
        f"/api/sync/tasks/{task}/input", json={"prompt_id": pid, "value": "a", "pin": SENTINEL}
    )
    for r in (wrong_value, wrong_type, extra_field):
        assert r.status_code == 422 and SENTINEL not in r.text, r.text
    assert SENTINEL not in caplog.text
    assert sync.answer(task, pid, "a").status_code == 204


def test_the_secret_is_absent_from_events_status_and_logs_after_a_failed_sign_in(
    sync: Sync, caplog: pytest.LogCaptureFixture
):
    inst, _ = sync.world({"open": [PIN]})
    caplog.set_level(logging.DEBUG)
    task = sync.started()
    assert sync.answer(task, sync.open_prompt(task)["prompt_id"], SENTINEL).status_code == 204
    sync.wait_ended(task)
    seen = repr([(f.event, f.data) for f in sync.events(task)]) + repr(sync.status(task)) + caplog.text
    assert SENTINEL not in seen
    plan = sync.client.get("/api/importers/instances").text
    assert SENTINEL not in plan


# ---- abort ------------------------------------------------------------------------------------------


def test_abort_stops_a_task_blocked_on_a_prompt(sync: Sync):
    sync.world({"open": [PIN]})
    task = sync.started()
    sync.open_prompt(task)
    r = sync.client.post(f"/api/sync/tasks/{task}/abort")
    assert r.status_code == 202
    assert r.json()["task_id"] == task and r.json()["aborting"] is True
    st = sync.wait_ended(task)
    assert (st["outcome"], st["aborting"]) == ("aborted", True)
    frames = sync.events(task)
    assert [f.data["outcome"] for f in frames if f.event == "prompt_resolved"] == ["aborted"]
    assert frames[-1].event == "task_ended" and frames[-1].data["outcome"] == "aborted"
    assert sync.client.get("/api/sync/active").status_code == 204  # the user may start the next


def test_aborting_an_ended_task_is_a_no_op(sync: Sync):
    sync.world()
    task = sync.started()
    done = sync.wait_ended(task)
    before = sync.events(task)
    r = sync.client.post(f"/api/sync/tasks/{task}/abort")
    assert r.status_code == 200 and r.json() == done
    assert sync.events(task) == before


def test_aborting_twice_is_harmless(sync: Sync):
    sync.world({"open": [PIN]})
    task = sync.started()
    sync.open_prompt(task)
    assert sync.client.post(f"/api/sync/tasks/{task}/abort").status_code == 202
    assert sync.client.post(f"/api/sync/tasks/{task}/abort").status_code in (200, 202)
    assert sync.wait_ended(task)["outcome"] == "aborted"


# ---- reset while held -----------------------------------------------------------------------------


def test_reset_is_refused_while_a_task_holds_the_instance(sync: Sync):
    inst, _ = sync.world({"open": [PIN]})
    task = sync.started()
    sync.open_prompt(task)
    err = error_of(sync.client.post(f"/api/importers/instances/{inst}/reset"), 409, "instance_busy")
    assert err["details"] == {"instance_ids": [inst]}
    sync.client.post(f"/api/sync/tasks/{task}/abort")
    sync.wait_ended(task)
    assert sync.client.post(f"/api/importers/instances/{inst}/reset").status_code == 200
