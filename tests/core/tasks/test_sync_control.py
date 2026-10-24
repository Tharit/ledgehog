"""A task's control flow against the scripted `testfetch`, real database (architecture §4.3, §5.3, §5.6,
§8): sequence, cancel, abort, timeout, abandonment, a crash, no lock across a prompt, the final settle, and
the redaction test."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.ingest.run import start_run
from app.core.settle.settle import SettleResult
from app.core.tasks import TaskRegistry
from app.core.tasks import orchestrate as orchestrate_module
from app.utils.db.locks import lock_accounts, lock_settle_exclusive
from tests import lockwatch
from tests.core.tasks.helpers import FAST, open_prompt, until
from tests.core.tasks.rig import DOC, Rig, acct

PIN = {"ask": "secret", "subject": "pin"}


@pytest.fixture
def rig(isolated_engine: Engine) -> Rig:
    return Rig(isolated_engine)


def settings(*refs: str, **kw: Any) -> dict[str, Any]:
    return {"default_start": "2026-06-01", "accounts": [acct(r) for r in refs], **kw}


def ended(handle: Any) -> tuple[Any, ...]:
    """(outcome, ok, failed, not_started) of the one `task_ended`."""
    [data] = handle.of("task_ended")
    return data["outcome"], data["ok"], data["failed"], data["not_started"]


def two_instances(rig: Rig, first: dict[str, Any], second: dict[str, Any]) -> tuple[int, int]:
    one = rig.instance(first, label="First", emits=("transactions",))
    two = rig.instance(second, label="Second", emits=("transactions",))
    rig.link(one, "F1"), rig.link(two, "S1")
    return one, two


# ---- sequence ----------------------------------------------------------------------------------


def test_instances_run_one_after_another_and_the_second_prompts_only_after_the_first_ended(rig: Rig) -> None:
    one, two = two_instances(rig, settings("F1", open=[PIN]), settings("S1", open=[PIN]))
    handle = rig.start()
    first = open_prompt(handle.task)
    assert first.data["instance_id"] == one
    assert handle.names().count("instance_started") == 1  # the second has not begun
    assert rig.registry.is_held(two)  # but it is already claimed
    handle.task.answer(first.data["prompt_id"], "1111")
    second = open_prompt(handle.task, first.id)
    assert second.data["instance_id"] == two
    names = handle.names()
    assert names.index("run_finished") < [i for i, n in enumerate(names) if n == "instance_started"][1]
    assert not rig.registry.is_held(one) and rig.registry.is_held(two)  # a claim goes when its job ends
    handle.task.answer(second.data["prompt_id"], "2222")
    handle.wait()
    assert not rig.registry.is_held(two)
    assert [d["instance_id"] for d in handle.of("instance_started")] == [one, two]
    assert handle.of("task_ended")[0]["ok"] == 2


def test_a_slow_first_instance_delays_the_second_and_nothing_overlaps(rig: Rig) -> None:
    one, two = two_instances(rig, settings("F1", open=[{"sleep_ms": 250}]), settings("S1"))
    handle = rig.run()
    names = handle.names()
    assert names == [
        "task_started",
        "instance_started",
        "run_started",
        "run_finished",
        "instance_started",
        "run_started",
        "run_finished",
        "task_ended",
    ]
    first, second = rig.runs()
    assert first.finished_at <= second.started_at  # the second began after the first had finished


def test_a_cancelled_prompt_ends_that_instance_and_the_next_goes_on(rig: Rig) -> None:
    one, two = two_instances(rig, settings("F1", open=[PIN]), settings("S1"))
    handle = rig.start()
    handle.answer(cancel=True)
    handle.wait()
    failed = handle.of("instance_failed")[0]
    assert (failed["instance_id"], failed["code"], failed["retryable"]) == (one, "challenge_abandoned", True)
    assert [d["outcome"] for d in handle.of("prompt_resolved")] == ["cancelled"]
    assert [(r.importer_instance_id, r.status) for r in rig.runs()] == [(one, "failed"), (two, "ok")]
    assert handle.of("task_ended")[0]["outcome"] == "completed"


def test_an_unanswered_prompt_expires_its_instance_and_the_next_goes_on(rig: Rig) -> None:
    one, two = two_instances(rig, settings("F1", open=[{**PIN, "timeout_s": 0.1}]), settings("S1"))
    handle = rig.run()
    failed = handle.of("instance_failed")[0]
    assert (failed["instance_id"], failed["code"], failed["retryable"]) == (one, "challenge_expired", True)
    assert [d["outcome"] for d in handle.of("prompt_resolved")] == ["expired"]
    assert [(r.importer_instance_id, r.status) for r in rig.runs()] == [(one, "failed"), (two, "ok")]
    assert handle.of("task_ended")[0]["outcome"] == "completed"


# ---- abort -------------------------------------------------------------------------------------------


def test_abort_at_a_prompt_fails_the_runs_as_abandoned_and_lists_what_never_started(rig: Rig) -> None:
    one = rig.instance(settings("F1", "F2", open=[PIN]), label="First", emits=("transactions",))
    two = rig.instance(settings("S1"), label="Second", emits=("transactions",))
    rig.link(one, "F1"), rig.link(one, "F2"), rig.link(two, "S1")
    handle = rig.start()
    open_prompt(handle.task)
    handle.task.abort()
    handle.wait()
    assert [d["outcome"] for d in handle.of("prompt_resolved")] == ["aborted"]
    failed = handle.of("instance_failed")[0]
    assert (failed["code"], failed["retryable"], len(failed["run_ids"])) == ("challenge_abandoned", True, 2)
    runs = rig.runs()
    assert [(r.importer_instance_id, r.status, r.retryable) for r in runs] == [(one, "failed", True)] * 2
    assert ended(handle) == ("aborted", 0, 2, [two])
    assert rig.q("SELECT count(*) FROM source_transaction")[0][0] == 0
    assert handle.task.status().aborting is True
    assert not rig.registry.is_held(one) and not rig.registry.is_held(two)
    rig.assert_none_running()


def test_abort_between_accounts_discards_the_delivery_in_flight(rig: Rig) -> None:
    slow = {"ref": "A2", "history_start": "2026-06-01", "fetch": [{"sleep_ms": 400}]}
    one = rig.instance(
        {"default_start": "2026-06-01", "accounts": [acct("A1"), slow, acct("A3")]},
        label="First",
        emits=("transactions",),
    )
    two = rig.instance(settings("S1"), label="Second", emits=("transactions",))
    a1, a2, a3 = rig.link(one, "A1"), rig.link(one, "A2"), rig.link(one, "A3")
    rig.link(two, "S1")
    handle = rig.start()
    until(lambda: len(handle.of("run_started")) == 2, "the second account's fetch to begin")
    handle.task.abort()
    handle.wait()
    runs = rig.runs()
    assert [(r.account_id, r.status) for r in runs] == [(a1, "ok"), (a2, "failed"), (a3, "failed")]
    assert runs[1].error_text == "ChallengeAbandoned: the sync was aborted" and runs[1].retryable is True
    assert rig.rows(a1) == 14 and rig.rows(a2) == 0 and rig.rows(a3) == 0  # the delivery was not ingested
    assert rig.q("SELECT count(*) FROM balance_record WHERE account_id = :a", a=a2)[0][0] == 0
    failed = handle.of("run_failed")[0]
    assert (failed["run_id"], failed["code"]) == (runs[1].id, "challenge_abandoned")
    assert handle.of("instance_failed")[0]["run_ids"] == [runs[2].id]  # the remaining runs, same error
    assert ended(handle) == ("aborted", 1, 2, [two])
    rig.assert_none_running()


def test_abort_of_a_finished_task_changes_nothing(rig: Rig) -> None:
    one, _ = two_instances(rig, settings("F1"), settings("S1"))
    handle = rig.run()
    before = handle.names()
    handle.task.abort()
    assert handle.names() == before and not handle.task.aborting
    assert one


# ---- abandonment ---------------------------------------------------------------------------------------


def test_a_task_nobody_watches_stops_at_the_end_of_the_current_instance(rig: Rig) -> None:
    one, two = two_instances(rig, settings("F1", open=[{"sleep_ms": 100}]), settings("S1"))
    handle = rig.run(attach=False)  # no stream attached, grace zero
    assert ended(handle) == ("abandoned", 1, 0, [two])
    # the instance under way finished; the next was never reached
    assert [(r.importer_instance_id, r.status) for r in rig.runs()] == [(one, "ok")]


def test_the_grace_keeps_a_reload_from_ending_a_sync(isolated_engine: Engine) -> None:
    rig = Rig(isolated_engine, TaskRegistry(replace(FAST, abandon_grace_s=60.0)))
    two_instances(rig, settings("F1", open=[{"sleep_ms": 100}]), settings("S1"))
    handle = rig.run(attach=False)
    assert handle.of("task_ended")[0]["outcome"] == "completed" and len(rig.runs()) == 2


def test_an_attached_stream_keeps_the_task_going(rig: Rig) -> None:
    two_instances(rig, settings("F1", open=[{"sleep_ms": 100}]), settings("S1"))
    handle = rig.run()  # attached by default
    assert handle.of("task_ended")[0]["outcome"] == "completed" and len(rig.runs()) == 2


# ---- a crash ---------------------------------------------------------------------------------------------


def test_a_crash_of_the_orchestration_leaves_no_run_running(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, two = two_instances(rig, settings("F1"), settings("S1"))
    account = int(rig.q("SELECT account_id FROM account_source WHERE importer_instance_id = :i", i=one)[0][0])

    def crashing(env: Any, task: Any, job: Any) -> Any:
        run_id = start_run(
            env.engine, account, "transactions", importer="testfetch", importer_instance_id=one
        )
        task.track_run(run_id)
        raise RuntimeError("a bug in the runner")

    monkeypatch.setattr(orchestrate_module, "run_job", crashing)
    handle = rig.run()
    assert ended(handle) == ("crashed", 0, 0, [two])
    [run] = rig.runs()
    assert (run.status, run.retryable) == ("failed", True)
    assert run.error_text.startswith("interrupted")
    rig.assert_none_running()
    assert rig.registry.active(rig.user_id) is None and not rig.registry.is_held(two)
    assert handle.task.status().outcome == "crashed"


def test_an_importers_unexpected_error_is_not_a_crash(rig: Rig) -> None:
    two_instances(rig, settings("F1", open=[{"raise": "unexpected"}]), settings("S1"))
    handle = rig.run()
    assert handle.of("instance_failed")[0]["code"] == "unexpected"
    assert handle.of("task_ended")[0]["outcome"] == "completed"
    assert [r.status for r in rig.runs()] == ["failed", "ok"]


# ---- nothing is held across a prompt ------------------------------------------------------------


def _idle_in_transaction(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                    " AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                )
            ).scalar_one()
        )


def _nothing_is_held(rig: Rig, account: int) -> None:
    assert lockwatch.advisory_held(rig.engine) == 0
    assert _idle_in_transaction(rig.engine) == 0
    with rig.engine.connect() as conn, conn.begin():  # settle exclusively and the account lock: at once
        conn.execute(text("SET LOCAL lock_timeout = '500ms'"))
        lock_settle_exclusive(conn)
        lock_accounts(conn, [account])


def test_no_lock_and_no_transaction_is_held_while_a_prompt_is_open(rig: Rig) -> None:
    iid = rig.instance(
        settings("A1", open=[PIN]) | {"accounts": [acct("A1", fetch=[{"ask": "tan", "medium": "text"}])]},
        emits=("transactions",),
    )
    account = rig.link(iid, "A1")
    handle = rig.start()
    login = open_prompt(handle.task)  # signing in
    _nothing_is_held(rig, account)
    assert rig.q("SELECT count(*) FROM import_run WHERE status = 'running'")[0][0] == 0
    handle.task.answer(login.data["prompt_id"], "1234")
    data_call = open_prompt(handle.task, login.id)  # a TAN for the account's own fetch
    assert data_call.data["run_id"] is not None
    _nothing_is_held(rig, account)
    assert rig.q("SELECT count(*) FROM import_run WHERE status = 'running'")[0][0] == 1  # committed: visible
    handle.task.answer(data_call.data["prompt_id"], "5678")
    handle.wait()
    assert handle.of("task_ended")[0]["ok"] == 1


# ---- settling ----------------------------------------------------------------------------------------------


def _spy_final_settle(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(orchestrate_module, "settle", lambda engine: calls.append(1) or SettleResult())
    return calls


def test_the_task_settles_once_more_only_after_a_run_whose_settle_failed(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.ingest.run as ingest_run

    two_instances(rig, settings("F1"), settings("S1"))
    final = _spy_final_settle(monkeypatch)
    rig.run()
    assert final == []  # each ingest settled; nothing more to do

    monkeypatch.setattr(ingest_run, "settle", lambda engine: SettleResult(error="boom"))
    rig2 = rig.run()
    assert final == [1]  # two runs reported an error: one final settle, not two
    assert [r.status for r in rig.runs()][-2:] == ["ok", "ok"]  # a failed settle never fails a run
    assert rig2.of("task_ended")[0]["outcome"] == "completed"


# ---- redaction ----------------------------------------------------------------------------------


def test_what_the_user_typed_is_nowhere_after_a_failed_instance(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    pin, tan = "PIN-SENTINEL-8f3a", "TAN-SENTINEL-77c1"
    wrong, data_tan = "WRONG-SENTINEL-19d2", "DATA-SENTINEL-4e0b"
    caplog.set_level(logging.DEBUG)
    first = rig.instance(
        settings("F1", open=[PIN, {"ask": "tan", "medium": "text"}, {"raise": "auth_rejected"}]),
        label="First",
        emits=("transactions",),
    )
    second = rig.instance(
        settings("S1", open=[{"ask": "secret", "subject": "password", "expect": "the-right-one"}]),
        label="Second",
        emits=("transactions",),
    )
    data_call = [{"ask": "tan", "medium": "text"}, {"raise": "source_unavailable"}]
    third = rig.instance(
        {"default_start": "2026-06-01", "accounts": [acct("T1", fetch=data_call)]},
        label="Third",
        emits=("transactions",),
    )
    for iid, ref in ((first, "F1"), (second, "S1"), (third, "T1")):
        rig.link(iid, ref)
    handle = rig.start()
    seen = handle.answer(pin).id
    seen = handle.answer(tan, after=seen).id
    seen = handle.answer(wrong, after=seen).id
    handle.answer(data_tan, after=seen)
    handle.wait()
    codes = [d["code"] for d in handle.of("instance_failed")]
    assert codes == ["auth_rejected", "auth_rejected", "source_unavailable"]

    sentinels = (pin, tan, wrong, data_tan)
    where = {
        "events": repr(handle.task.events_after(0)),
        "status": repr(handle.task.status()),
        "error_text": json.dumps([r.error_text for r in rig.runs()]),
        "state": json.dumps([r.state for r in rig.q("SELECT state FROM importer_instance ORDER BY id")]),
        "settings": json.dumps(
            [r.settings for r in rig.q("SELECT settings FROM importer_instance ORDER BY id")]
        ),
        "runs": json.dumps([dict(r._mapping) for r in rig.runs()], default=str),
        "log": caplog.text,
    }
    for name, haystack in where.items():
        for sentinel in sentinels:
            assert sentinel not in haystack, f"{sentinel} leaked into {name}"
    assert caplog.records  # the log was captured at debug: the absence above is not an empty log


def test_abort_during_a_document_fetch_discards_the_delivery_and_its_position(rig: Rig) -> None:
    iid = rig.instance(
        {
            "start_date": "2026-06-01",
            "documents": [DOC],
            "documents_position": {"last_uid": 7},
            "documents_fetch": [{"sleep_ms": 400}],
        },
        emits=("documents",),
    )
    handle = rig.start()
    until(lambda: len(handle.of("run_started")) == 1, "the document fetch to begin")
    handle.task.abort()
    handle.wait()
    assert [r.status for r in rig.runs()] == ["failed"]
    assert rig.q("SELECT count(*) FROM external_document")[0][0] == 0
    assert rig.state(iid) == {}  # the position is not applied: the source is read again
    rig.assert_none_running()
