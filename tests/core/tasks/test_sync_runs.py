"""A sync against the scripted `testfetch`, real database (architecture §5.3, §5.5, §8): the runs it
makes, the two-run rule, what a failure ends, the sign-in, the importer's state, discovery."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine

from app.core.accounts import close_account
from app.core.importers.instances import reset_instance, update_instance
from app.core.importers.plan import ItemRequest, JobPlan
from app.core.tasks import DiscoveryResult
from app.core.tasks import runner as runner_module
from tests.core.tasks.helpers import open_prompt
from tests.core.tasks.rig import DOC, Handle, Rig, acct


@pytest.fixture
def rig(isolated_engine: Engine) -> Rig:
    return Rig(isolated_engine)


def full_settings(**kw: Any) -> dict[str, Any]:
    return {
        "default_start": "2026-06-01",
        "accounts": [acct("A1", rows_per_day=2), acct("A2", history_start="2026-06-05")],
        "start_date": "2026-06-01",
        "documents": [DOC],
        **kw,
    }


def reconciled(stats: Any) -> bool:
    """The run left no unexplained difference (the view has no row for a zero one)."""
    return stats["unexplained_difference"]["after"] in (None, 0) and stats["since_zero"] == []


def one_ended(handle: Handle) -> dict[str, Any]:
    ended = handle.of("task_ended")
    assert len(ended) == 1 and handle.names()[-1] == "task_ended"
    return dict(ended[0])


# ---- a clean sync ------------------------------------------------------------------------------


def test_a_clean_sync_of_two_accounts_and_documents(rig: Rig) -> None:
    iid = rig.instance(full_settings())
    a1, a2 = rig.link(iid, "A1"), rig.link(iid, "A2")
    handle = rig.run()
    assert handle.names() == [
        "task_started",
        "instance_started",
        "run_started",
        "run_finished",
        "run_started",
        "run_finished",
        "run_started",
        "run_finished",
        "task_ended",
    ]
    assert [e.id for e in handle.task.events_after(0)] == list(range(1, 10))
    assert one_ended(handle) == {"outcome": "completed", "ok": 3, "failed": 0, "not_started": []}
    runs = rig.runs()
    assert [(r.status, r.emits, r.account_id, r.importer, r.started_by) for r in runs] == [
        ("ok", "transactions", a1, "testfetch", rig.user_id),
        ("ok", "transactions", a2, "testfetch", rig.user_id),
        ("ok", "documents", None, "testfetch", rig.user_id),
    ]
    started, finished = handle.of("run_started"), handle.of("run_finished")
    assert [s["run_id"] for s in started] == [r.id for r in runs]
    assert [(s["account_id"], s["kind"], s["since"]) for s in started] == [
        (a1, "transactions", "2026-06-01"),
        (a2, "transactions", "2026-06-01"),
        (None, "documents", "2026-06-01"),
    ]
    for done, run in zip(finished, runs, strict=True):
        assert done["run_id"] == run.id and done["stats"] == run.stats  # the stored statistics
    assert (finished[0]["stats"]["inserted"], finished[1]["stats"]["inserted"]) == (28, 10)
    assert finished[2]["stats"] == {"inserted": 1, "updated": 0, "kept": 0, "changed": 0, "importer": {}}
    assert (rig.rows(a1), rig.rows(a2)) == (28, 10)
    assert rig.q("SELECT count(*) FROM external_document")[0][0] == 1
    assert rig.q("SELECT count(*) FROM balance_record")[0][0] == 2
    assert all(r.covered_through == date(2026, 6, 14) for r in runs)
    assert rig.state(iid) == {}
    rig.assert_none_running()


def test_the_two_run_rule_overlapping_fetches_reconcile_to_zero(rig: Rig) -> None:
    iid = rig.instance(full_settings(), emits=("transactions",))
    a1, a2 = rig.link(iid, "A1"), rig.link(iid, "A2")
    first = rig.run()
    assert [d["stats"]["inserted"] for d in first.of("run_finished")] == [28, 10]

    second = rig.run()  # the same day: the overlap re-delivers what is there
    stats = [d["stats"] for d in second.of("run_finished")]
    assert [s["inserted"] for s in stats] == [0, 0]
    assert [s["skipped_by_identity"] for s in stats] == [16, 8]  # 8 days of overlap, from 06-07
    assert all(reconciled(s) for s in stats)
    assert [d["since"] for d in second.of("run_started")] == ["2026-06-07", "2026-06-07"]

    later = replace(rig.env, fetch_day=date(2026, 6, 17))  # two days on: new bookings and the overlap
    third = rig.run(env=later)
    stats = [d["stats"] for d in third.of("run_finished")]
    assert [s["inserted"] for s in stats] == [4, 2]
    assert [s["skipped_by_identity"] for s in stats] == [16, 8]
    assert all(reconciled(s) for s in stats)
    assert (rig.rows(a1), rig.rows(a2)) == (32, 12)


def test_an_explicit_since_counts_only_for_an_account_without_coverage(rig: Rig) -> None:
    iid = rig.instance(full_settings(), emits=("transactions",))
    a1 = rig.link(iid, "A1")
    jobs = rig.jobs([ItemRequest(iid, account_id=a1, since=date(2026, 6, 10))])
    handle = rig.run(jobs)
    assert handle.of("run_started")[0]["since"] == "2026-06-10"
    assert rig.rows(a1) == 10  # 06-10..06-14, two rows a day
    # coverage exists now: the same override is ignored, the start is derived again
    again = rig.run(jobs)
    assert again.of("run_started")[0]["since"] == "2026-06-07"


# ---- what a failure ends -----------------------------------------------------------------------


def test_an_item_failure_fails_that_run_and_the_next_item_goes_on(rig: Rig) -> None:
    settings = full_settings(accounts=[acct("A1", fetch=[{"raise": "parse_failed"}]), acct("A2")])
    iid = rig.instance(settings, emits=("transactions",))
    a1, a2 = rig.link(iid, "A1"), rig.link(iid, "A2")
    handle = rig.run()
    assert handle.names() == [
        "task_started",
        "instance_started",
        "run_started",
        "run_failed",
        "run_started",
        "run_finished",
        "task_ended",
    ]
    failed = handle.of("run_failed")[0]
    assert (failed["code"], failed["retryable"], failed["account_id"]) == ("parse_failed", False, a1)
    assert failed["message"].startswith("ParseFailed: ")
    bad, good = rig.runs()
    assert (bad.status, bad.retryable, bad.covered_through, bad.error_text) == (
        "failed",
        False,
        None,
        failed["message"],
    )
    assert good.status == "ok" and rig.rows(a1) == 0 and rig.rows(a2) == 14
    balances = rig.q("SELECT count(*) FROM balance_record WHERE account_id = :a", a=a1)
    assert balances[0][0] == 0  # nothing was written for the failed run
    assert one_ended(handle) == {"outcome": "completed", "ok": 1, "failed": 1, "not_started": []}


@pytest.mark.parametrize("code", ["account_unsupported", "unexpected"])
def test_other_item_scope_classes_also_continue(rig: Rig, code: str) -> None:
    settings = full_settings(accounts=[acct("A1", fetch=[{"raise": code}]), acct("A2")])
    iid = rig.instance(settings, emits=("transactions",))
    rig.link(iid, "A1"), rig.link(iid, "A2")
    handle = rig.run()
    assert handle.of("run_failed")[0]["code"] == code and not handle.of("instance_failed")
    assert [r.status for r in rig.runs()] == ["failed", "ok"]
    unexpected = rig.runs()[0]
    assert unexpected.retryable is False
    if code == "unexpected":
        assert unexpected.error_text == "RuntimeError: unexpected error"  # the message is not kept


def test_a_contract_violation_fails_its_run_only(rig: Rig) -> None:
    settings = full_settings(accounts=[acct("A1", currency="CHF"), acct("A2")])  # rows in the wrong currency
    iid = rig.instance(settings, emits=("transactions",))
    a1, a2 = rig.link(iid, "A1"), rig.link(iid, "A2")
    handle = rig.run()
    failed = handle.of("run_failed")[0]
    assert (failed["code"], failed["retryable"]) == ("contract_violation", False)
    assert rig.rows(a1) == 0 and rig.rows(a2) == 14


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        ("source_unavailable", True),
        ("challenge_expired", True),
        ("auth_rejected", True),
        ("bank_setup_required", False),
        ("not_registered", False),
    ],
)
def test_an_instance_failure_fails_the_remaining_runs_with_the_same_error(
    rig: Rig, code: str, retryable: bool
) -> None:
    settings = full_settings(accounts=[acct("A1"), acct("A2", fetch=[{"raise": code}]), acct("A3")])
    iid = rig.instance(settings, emits=("transactions",))
    a1, a2, a3 = rig.link(iid, "A1"), rig.link(iid, "A2"), rig.link(iid, "A3")
    handle = rig.run()
    runs = rig.runs()
    assert [(r.account_id, r.status) for r in runs] == [(a1, "ok"), (a2, "failed"), (a3, "failed")]
    assert [r.retryable for r in runs[1:]] == [retryable, retryable]
    assert runs[1].error_text == runs[2].error_text and runs[1].error_text is not None
    assert handle.names() == [
        "task_started",
        "instance_started",
        "run_started",
        "run_finished",
        "run_started",
        "run_failed",
        "instance_failed",  # the third was never fetched: no run_started for it
        "task_ended",
    ]
    failed, instance = handle.of("run_failed")[0], handle.of("instance_failed")[0]
    assert (failed["code"], failed["retryable"], failed["run_id"]) == (code, retryable, runs[1].id)
    assert dict(instance) == {
        "instance_id": iid,
        "code": code,
        "message": runs[2].error_text,
        "retryable": retryable,
        "run_ids": [runs[2].id],
    }
    assert rig.rows(a2) == 0 and rig.rows(a3) == 0
    assert one_ended(handle) == {"outcome": "completed", "ok": 1, "failed": 2, "not_started": []}
    rig.assert_none_running()


def test_the_other_instances_go_on_after_one_fails(rig: Rig) -> None:
    broken = rig.instance(
        full_settings(accounts=[acct("B", fetch=[{"raise": "source_unavailable"}])]), label="Broken"
    )
    fine = rig.instance(full_settings(accounts=[acct("F")]), label="Fine")
    rig.link(broken, "B"), rig.link(fine, "F")
    handle = rig.run()
    # the broken instance's account and documents, then the fine one's
    assert [r.status for r in rig.runs()] == ["failed", "failed", "ok", "ok"]
    assert one_ended(handle)["outcome"] == "completed"
    assert [d["instance_id"] for d in handle.of("instance_started")] == [broken, fine]


def test_a_failed_sign_in_fails_one_run_per_planned_item(rig: Rig) -> None:
    settings = full_settings(open=[{"ask": "secret", "subject": "pin", "expect": "1234"}])
    iid = rig.instance(settings)
    a1, a2 = rig.link(iid, "A1"), rig.link(iid, "A2")
    handle = rig.start()
    prompt = handle.answer("0000")
    assert prompt.data["run_id"] is None and prompt.data["instance_id"] == iid  # no run while signing in
    handle.wait()
    assert handle.names() == [
        "task_started",
        "instance_started",
        "prompt",
        "prompt_resolved",
        "instance_failed",
        "task_ended",
    ]
    runs = rig.runs()
    assert [(r.account_id, r.emits, r.status, r.retryable) for r in runs] == [
        (a1, "transactions", "failed", True),
        (a2, "transactions", "failed", True),
        (None, "documents", "failed", True),
    ]
    assert {r.error_text for r in runs} == {"AuthRejected: the PIN was rejected"}
    failed = handle.of("instance_failed")[0]
    assert failed["run_ids"] == [r.id for r in runs] and failed["code"] == "auth_rejected"
    assert not handle.of("run_started") and not handle.of("run_failed")
    assert one_ended(handle) == {"outcome": "completed", "ok": 0, "failed": 3, "not_started": []}
    assert rig.rows(a1) == 0 and rig.q("SELECT count(*) FROM source_transaction")[0][0] == 0
    rig.assert_none_running()


def test_a_wrong_tan_on_a_data_call_ends_the_instance_without_asking_again(rig: Rig) -> None:
    ask = {"ask": "tan", "medium": "text", "expect": "111"}
    settings = full_settings(accounts=[acct("A1", fetch=[ask]), acct("A2", fetch=[ask])])
    iid = rig.instance(settings, emits=("transactions",))
    rig.link(iid, "A1"), rig.link(iid, "A2")
    handle = rig.start()
    prompt = handle.answer("999")
    assert prompt.data["run_id"] is not None  # a data call: the run exists
    handle.wait()
    assert len(handle.of("prompt")) == 1  # the second account never asked
    assert [r.status for r in rig.runs()] == ["failed", "failed"]
    assert handle.of("instance_failed")[0]["code"] == "auth_rejected"


def test_a_closed_account_after_the_plan_fails_its_run_and_the_rest_goes_on(rig: Rig) -> None:
    iid = rig.instance(full_settings(), emits=("transactions",))
    a1, a2 = rig.link(iid, "A1"), rig.link(iid, "A2")
    jobs = rig.jobs()
    close_account(rig.engine, a1, date(2026, 6, 1))
    handle = rig.run(jobs)
    failed = handle.of("run_failed")[0]
    assert (failed["code"], failed["retryable"]) == ("account_closed", False)
    assert [(r.account_id, r.status) for r in rig.runs()] == [(a1, "failed"), (a2, "ok")]


def test_an_instance_disabled_after_the_plan_ends_like_a_failed_sign_in(rig: Rig) -> None:
    iid = rig.instance(full_settings(), emits=("transactions",))
    rig.link(iid, "A1"), rig.link(iid, "A2")
    jobs = rig.jobs()
    update_instance(rig.engine, iid, disabled=True)
    handle = rig.run(jobs)
    failed = handle.of("instance_failed")[0]
    assert (failed["code"], failed["retryable"], len(failed["run_ids"])) == ("instance_disabled", False, 2)
    assert [r.status for r in rig.runs()] == ["failed", "failed"]


# ---- the importer's state -----------------------------------------------------------------------


CHOICE = {
    "ask": "choice",
    "subject": "tan_medium",
    "options": [{"id": "1", "label": "Phone"}, {"id": "2", "label": "Card"}],
    "remember": "medium",
    "unless_state": "medium",
}


def test_state_is_written_back_once_and_a_remembered_choice_is_not_asked_again(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[dict[str, Any]] = []
    real = runner_module.save_state

    def spy(engine: Engine, instance_id: int, state: Any) -> bool:
        saved.append(dict(state))
        return real(engine, instance_id, state)

    monkeypatch.setattr(runner_module, "save_state", spy)
    iid = rig.instance(full_settings(open=[CHOICE]), emits=("transactions",))
    rig.link(iid, "A1"), rig.link(iid, "A2")
    first = rig.start()
    first.answer("2")
    first.wait()
    assert rig.state(iid) == {"medium": "2"} and saved == [{"medium": "2"}]

    second = rig.run()  # remembered: no prompt, and an unchanged state is not written again
    assert not second.of("prompt") and saved == [{"medium": "2"}]
    assert one_ended(second)["ok"] == 2

    reset_instance(rig.engine, iid)
    third = rig.start()  # reset returns the instance to asking
    third.answer("1")
    third.wait()
    assert rig.state(iid) == {"medium": "1"}


def test_state_is_written_back_after_a_failed_sign_in_too(rig: Rig) -> None:
    iid = rig.instance(full_settings(open=[CHOICE, {"raise": "auth_rejected"}]), emits=("transactions",))
    rig.link(iid, "A1")
    handle = rig.start()
    handle.answer("2")
    handle.wait()
    assert handle.of("instance_failed")[0]["code"] == "auth_rejected"
    assert rig.state(iid) == {"medium": "2"}  # the medium is not asked for again after a bad login


def test_state_is_written_back_after_a_failed_run_too(rig: Rig) -> None:
    settings = full_settings(open=[CHOICE], accounts=[acct("A1", fetch=[{"raise": "source_unavailable"}])])
    iid = rig.instance(settings, emits=("transactions",))
    rig.link(iid, "A1")
    handle = rig.start()
    handle.answer("1")
    handle.wait()
    assert rig.state(iid) == {"medium": "1"}


# ---- every prompt kind -------------------------------------------------------------------------------


def test_every_prompt_kind_through_the_real_prompter(rig: Rig) -> None:
    open_steps = [
        {"ask": "secret", "subject": "pin", "expect": "1234"},
        {"ask": "tan", "medium": "text", "expect": "111"},
        {"ask": "tan", "medium": "image", "expect": "222"},
        {"ask": "tan", "medium": "decoupled", "polls": 2},
        {"ask": "choice", "subject": "tan_medium", "options": [{"id": "9", "label": "Nine"}]},
        {"ask": "text", "subject": "tan_medium_name", "remember": "medium_name"},
    ]
    iid = rig.instance(full_settings(open=open_steps), emits=("transactions",))
    rig.link(iid, "A1"), rig.link(iid, "A2")
    handle = rig.start()
    seen: list[dict[str, Any]] = []
    after = 0
    for answer in ["1234", "111", "222", None, "9", "My phone"]:
        if answer is None:  # the decoupled challenge is confirmed by the importer's poll alone
            event = open_prompt(handle.task, after)
        else:
            event = handle.answer(answer, after=after)
        seen.append(dict(event.data["prompt"]))
        after = event.id
    handle.wait()
    assert [(p["kind"], p.get("medium") or p["subject"]) for p in seen] == [
        ("secret", "pin"),
        ("tan", "text"),
        ("tan", "image"),
        ("tan", "decoupled"),
        ("choice", "tan_medium"),
        ("text", "tan_medium_name"),
    ]
    assert seen[2]["image_mime"] == "image/png" and len(seen[2]["image_b64"]) > 20
    assert [d["outcome"] for d in handle.of("prompt_resolved")] == [
        "answered",
        "answered",
        "answered",
        "confirmed",
        "answered",
        "answered",
    ]
    assert rig.state(iid) == {"medium_name": "My phone"}
    assert one_ended(handle)["ok"] == 2
    # every resolved prompt replays without its body
    assert all("prompt" not in d for d in handle.of("prompt"))


# ---- discovery ---------------------------------------------------------------------------------------


def discovery_settings(**kw: Any) -> dict[str, Any]:
    return {
        "accounts": [
            acct("MAIN-EUR", name="Main"),
            acct("MAIN-USD", name="Main USD", currency="USD"),
            acct("DEPOT", name="Depot", kind_hint="depot", capabilities=[]),
        ],
        **kw,
    }


def test_a_discovery_opens_lists_and_closes_writing_no_run(rig: Rig) -> None:
    iid = rig.instance(discovery_settings(open=[CHOICE]), emits=("transactions",))
    handle = rig.start([JobPlan(iid)], kind="discovery")
    handle.answer("2")
    handle.wait()
    assert handle.names() == [
        "task_started",
        "instance_started",
        "prompt",
        "prompt_resolved",
        "task_ended",
    ]
    assert one_ended(handle) == {"outcome": "completed", "ok": 0, "failed": 0, "not_started": []}
    status = handle.task.status()
    assert status.status == "ended" and isinstance(status.result, DiscoveryResult)
    assert status.result.instance_id == iid
    assert [(a.external_ref, a.currency, sorted(a.capabilities)) for a in status.result.accounts] == [
        ("MAIN-EUR", "EUR", ["balance", "transactions"]),
        ("MAIN-USD", "USD", ["balance", "transactions"]),  # a second-currency pocket is its own entry
        ("DEPOT", "EUR", []),  # listed, nothing fetchable
    ]
    assert rig.q("SELECT count(*) FROM import_run")[0][0] == 0
    assert rig.q("SELECT count(*) FROM source_transaction")[0][0] == 0
    assert rig.state(iid) == {"medium": "2"}  # state is written back for a discovery too


def test_a_failed_discovery_is_an_instance_failure_with_no_runs(rig: Rig) -> None:
    iid = rig.instance(discovery_settings(open=[{"raise": "bank_setup_required"}]), emits=("transactions",))
    handle = rig.run([JobPlan(iid)], kind="discovery")
    failed = handle.of("instance_failed")[0]
    assert (failed["code"], failed["retryable"], failed["run_ids"]) == ("bank_setup_required", False, [])
    assert handle.task.status().result is None and rig.q("SELECT count(*) FROM import_run")[0][0] == 0
    assert one_ended(handle)["outcome"] == "completed"


# ---- documents: position, the importer's counts, the currency lookup ----------------------------------


def doc_settings(**kw: Any) -> dict[str, Any]:
    return {"start_date": "2026-06-01", "documents": [DOC], **kw}


def test_a_documents_position_is_applied_to_the_state_once_ingested(rig: Rig) -> None:
    iid = rig.instance(doc_settings(documents_position={"last_uid": 7}), emits=("documents",))
    rig.run()
    assert [r.status for r in rig.runs()] == ["ok"]
    assert rig.state(iid) == {"last_uid": 7}


def test_a_failed_ingest_leaves_the_position_unapplied(rig: Rig) -> None:
    broken = {**DOC, "currency": "QQQ"}  # a currency the ledger does not know: the ingest fails
    iid = rig.instance(
        doc_settings(documents=[broken], documents_position={"last_uid": 7}), emits=("documents",)
    )
    rig.run()
    assert [r.status for r in rig.runs()] == ["failed"]
    assert rig.state(iid) == {}


def test_a_failed_fetch_leaves_the_position_unapplied(rig: Rig) -> None:
    iid = rig.instance(
        doc_settings(documents_position={"last_uid": 7}, documents_fetch=[{"raise": "source_unavailable"}]),
        emits=("documents",),
    )
    rig.run()
    assert [r.status for r in rig.runs()] == ["failed"]
    assert rig.state(iid) == {}


def test_a_documents_run_stores_the_importers_counts_and_gets_the_currency_exponents(rig: Rig) -> None:
    rig.instance(
        doc_settings(documents_stats={"skipped": 3}, documents_exponents=["EUR", "JPY"]),
        emits=("documents",),
    )
    handle = rig.run()
    stats = handle.of("run_finished")[0]["stats"]
    assert stats["importer"] == {"skipped": 3, "exponent_EUR": 2, "exponent_JPY": 0}
    assert rig.runs()[0].stats["importer"] == stats["importer"]


def test_a_documents_run_without_counts_stores_an_empty_importer_entry(rig: Rig) -> None:
    rig.instance(doc_settings(), emits=("documents",))
    assert rig.run().of("run_finished")[0]["stats"]["importer"] == {}
