"""Account discovery over HTTP (architecture §4.1, §5.3): a task like a sync whose result is the list of
accounts a credential reaches, each matched to the household's accounts when the status is read."""

from __future__ import annotations

from datetime import date

from app.core.accounts import close_account
from tests.api import sync_helpers as h
from tests.api.sync_helpers import PIN, Sync, error_of

sync = h.sync  # fixtures shared by the sync API tests
make_sync = h.make_sync


def discover(sync: Sync, instance: int, **kw):
    return (kw.get("client") or sync.client).post(f"/api/importers/instances/{instance}/discover-accounts")


def test_a_discovery_is_a_task_whose_result_is_the_matched_account_list(sync: Sync):
    accounts = [
        {"ref": "LINKED", "name": "Giro"},
        {"ref": "KNOWN", "name": "Savings", "kind_hint": "savings"},
        {"ref": "GONE", "name": "Old card", "kind_hint": "card"},
        {
            "ref": "POCKET-USD",
            "name": "Wallet USD",
            "currency": "USD",
            "capabilities": ["transactions", "balance"],
        },
        {"ref": "DEPOT", "name": "Depot", "capabilities": [], "kind_hint": "depot"},
        {"ref": "NEW", "name": "Brand new"},
    ]
    inst = sync.instance({"accounts": accounts})
    linked = sync.account("Giro")
    sync.link(inst, linked, "LINKED")
    known = sync.account("Savings", external_ref="KNOWN")  # holds the reference, not linked
    gone = sync.account("Old card", external_ref="GONE")
    close_account(sync.engine, gone, date(2026, 8, 1))

    r = discover(sync, inst)
    assert (r.status_code, set(r.json())) == (202, {"task_id"}), r.text
    task = r.json()["task_id"]
    st = sync.wait_ended(task)
    assert (st["kind"], st["status"], st["outcome"]) == ("discovery", "ended", "completed")
    assert set(st["result"]) == {"instance_id", "accounts"} and st["result"]["instance_id"] == inst
    by_ref = {e["account"]["external_ref"]: e for e in st["result"]["accounts"]}
    assert list(by_ref) == [a["ref"] for a in accounts]  # in the importer's order
    assert by_ref["LINKED"]["linked_account_id"] == linked and by_ref["LINKED"]["matches_account"] is None
    assert by_ref["KNOWN"]["linked_account_id"] is None
    assert by_ref["KNOWN"]["matches_account"] == {"id": known, "closed": False}
    assert by_ref["GONE"]["matches_account"] == {"id": gone, "closed": True}  # a closed account is reported
    assert by_ref["NEW"]["linked_account_id"] is None and by_ref["NEW"]["matches_account"] is None
    pocket = by_ref["POCKET-USD"]["account"]
    assert (pocket["currency"], pocket["capabilities"]) == ("USD", ["balance", "transactions"])
    depot = by_ref["DEPOT"]["account"]
    assert (depot["capabilities"], depot["kind_hint"]) == ([], "depot")  # nothing fetchable
    assert by_ref["KNOWN"]["account"] == {
        "external_ref": "KNOWN", "name": "Savings", "currency": "EUR", "kind_hint": "savings",
        "capabilities": ["balance", "transactions"],
    }  # fmt: skip


def test_a_discovery_writes_no_run_and_its_stream_is_three_events(sync: Sync):
    inst = sync.instance({"accounts": [{"ref": "A1"}]})
    task = discover(sync, inst).json()["task_id"]
    sync.wait_ended(task)
    frames = sync.events(task)
    assert [f.event for f in frames] == ["task_started", "instance_started", "task_ended"]
    assert frames[0].data == {"kind": "discovery", "instances": [{"instance_id": inst, "items": []}]}
    assert frames[2].data == {"outcome": "completed", "ok": 0, "failed": 0, "not_started": []}
    assert sync.run_count() == 0


def test_the_result_is_matched_when_it_is_read_so_linking_from_it_shows_at_once(sync: Sync):
    inst = sync.instance({"accounts": [{"ref": "A1", "name": "Giro"}]})
    task = discover(sync, inst).json()["task_id"]
    sync.wait_ended(task)
    (entry,) = sync.status(task)["result"]["accounts"]
    assert entry["linked_account_id"] is None and entry["matches_account"] is None
    # create-or-link, with the ordinary operations
    made = sync.client.post(
        "/api/ledger/accounts",
        json={"name": "Giro", "kind": "checking", "currency": "EUR", "external_ref": "A1"},
    )
    assert made.status_code == 201, made.text
    account_id = made.json()["account"]["id"]
    (entry,) = sync.status(task)["result"]["accounts"]
    assert entry["matches_account"] == {"id": account_id, "closed": False}
    sync.link(inst, account_id, "A1")
    (entry,) = sync.status(task)["result"]["accounts"]
    assert entry["linked_account_id"] == account_id and entry["matches_account"] is None


def test_a_running_discovery_has_no_result_yet_and_a_sync_never_has_one(sync: Sync):
    inst = sync.instance({"accounts": [{"ref": "A1"}], "open": [PIN]})
    task = discover(sync, inst).json()["task_id"]
    prompt = sync.open_prompt(task)
    st = sync.status(task)
    assert (st["kind"], st["status"], st["result"]) == ("discovery", "running", None)
    assert sync.answer(task, prompt["prompt_id"], "1234").status_code == 204
    assert sync.wait_ended(task)["result"] is not None
    sync.world()
    done = sync.started()
    assert sync.wait_ended(done)["result"] is None


def test_a_discovery_that_cannot_sign_in_ends_with_instance_failed_and_no_result(sync: Sync):
    inst = sync.instance({"accounts": [{"ref": "A1"}], "open": [PIN]})
    task = discover(sync, inst).json()["task_id"]
    assert sync.answer(task, sync.open_prompt(task)["prompt_id"], "0000").status_code == 204
    st = sync.wait_ended(task)
    assert st["result"] is None
    (failed,) = [f for f in sync.events(task) if f.event == "instance_failed"]
    assert failed.data["code"] == "auth_rejected" and failed.data["run_ids"] == []


def test_a_discovery_is_refused_as_a_start_is(sync: Sync):
    error_of(discover(sync, 9999), 404, "not_found")
    theirs = sync.instance({}, access="owner", owner="ben")
    error_of(discover(sync, theirs), 403, "forbidden")
    csv = sync.instance({}, importer="csv", emits=("transactions",))
    error_of(discover(sync, csv), 409, "not_a_fetch_source")
    ghost = sync.instance({}, importer="ghost", emits=("transactions",))
    error_of(discover(sync, ghost), 409, "importer_unavailable")
    docs = sync.instance({"documents": []}, emits=("documents",))
    error_of(discover(sync, docs), 409, "not_an_account_source")
    off = sync.instance({"accounts": [{"ref": "A1"}]})
    sync.client.put(f"/api/importers/instances/{off}", json={"disabled": True})
    error_of(discover(sync, off), 409, "instance_disabled")
    assert sync.client.get("/api/sync/active").status_code == 204  # nothing was started


def test_a_discovery_holds_the_instance_and_the_users_one_task(sync: Sync):
    inst = sync.instance({"accounts": [{"ref": "A1"}], "open": [PIN]})
    other = sync.instance({"accounts": [{"ref": "B1"}]})
    task = discover(sync, inst).json()["task_id"]
    sync.open_prompt(task)
    assert error_of(discover(sync, other), 409, "task_active")["details"] == {"task_id": task}
    assert error_of(discover(sync, inst, client=sync.other), 409, "instance_busy")["details"] == {
        "instance_ids": [inst]
    }
    error_of(sync.client.post(f"/api/importers/instances/{inst}/reset"), 409, "instance_busy")
    # ... and may be answered and aborted like a sync
    assert sync.client.post(f"/api/sync/tasks/{task}/abort").status_code == 202
    assert sync.wait_ended(task)["outcome"] == "aborted"


def test_another_users_discovery_is_404(sync: Sync):
    inst = sync.instance({"accounts": [{"ref": "A1"}]})
    task = discover(sync, inst).json()["task_id"]
    sync.wait_ended(task)
    error_of(sync.other.get(f"/api/sync/tasks/{task}"), 404, "not_found")
    error_of(sync.other.get(f"/api/sync/tasks/{task}/events"), 404, "not_found")
