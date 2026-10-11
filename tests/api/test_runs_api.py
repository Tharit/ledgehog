"""The run list and reverting a run over HTTP (architecture §4.1, §4.4)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.api.routers import runs as runs_router
from app.core.ingest import revert as revert_module
from app.core.settle.settle import SettleResult
from app.utils.db.locks import WriteConflict
from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api, error_of
from tests.plugins.importers.csv.fixtures import PRIVATE, card_a_bytes, giro_bytes

api = h.api  # fixtures shared by the importer API tests
make_api = h.make_api

RUNS = "/api/importers/runs"
RUN_KEYS = {
    "id", "importer", "instance_id", "account_id", "kind", "status", "started_at", "finished_at",
    "started_by", "error_text", "covered_from", "covered_through", "stats", "reverted_at",
    "reverted_by", "revertible",
}  # fmt: skip


def _two_accounts(api: Api) -> tuple[int, int, int, int]:
    """(giro instance, giro account, card instance, card account), each with a first upload."""
    gi, ga = api.world("giro_with_preamble")
    ci, ca = api.world("card_footer_balance", name="Card", kind="card")
    assert api.upload(gi, ga, giro_bytes()).status_code == 200
    assert api.upload(ci, ca, card_a_bytes()).status_code == 200
    return gi, ga, ci, ca


def _ids(r) -> list[int]:
    assert r.status_code == 200, r.text
    return [run["id"] for run in r.json()]


# ---- the list ------------------------------------------------------------------------------


def test_the_list_is_newest_first_with_the_shape_and_revertible(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    assert api.upload(gi, ga, giro_bytes()).status_code == 200  # a second run on the giro account
    r = api.client.get(RUNS)
    assert r.status_code == 200
    runs = r.json()
    assert [x["id"] for x in runs] == sorted((x["id"] for x in runs), reverse=True) and len(runs) == 3
    assert set(runs[0]) == RUN_KEYS
    by_id = {x["id"]: x for x in runs}
    newest_giro, oldest_giro = runs[0], runs[2]
    assert (newest_giro["account_id"], oldest_giro["account_id"]) == (ga, ga)
    assert newest_giro["revertible"] is True and oldest_giro["revertible"] is False
    assert by_id[runs[1]["id"]]["account_id"] == ca and runs[1]["revertible"] is True
    assert newest_giro["status"] == "ok" and newest_giro["kind"] == "transactions"
    assert newest_giro["importer"] == "csv" and newest_giro["instance_id"] == gi
    assert newest_giro["started_at"] and newest_giro["finished_at"] and newest_giro["reverted_at"] is None
    assert oldest_giro["covered_from"] == "2026-08-18" and oldest_giro["covered_through"] == "2026-08-20"
    assert oldest_giro["stats"]["inserted"] == 3
    assert PRIVATE not in r.text


def test_the_list_filters(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    api.upload(gi, ga, b"not a statement at all\n")  # fails
    assert len(_ids(api.client.get(RUNS))) == 3
    assert len(_ids(api.client.get(RUNS, params={"account_id": ga}))) == 2
    assert len(_ids(api.client.get(RUNS, params={"account_id": ca}))) == 1
    assert len(_ids(api.client.get(RUNS, params={"instance_id": ci}))) == 1
    failed = api.client.get(RUNS, params={"status": "failed"}).json()
    assert len(failed) == 1 and failed[0]["status"] == "failed" and failed[0]["revertible"] is False
    assert failed[0]["error_text"] and PRIVATE not in failed[0]["error_text"]
    assert len(_ids(api.client.get(RUNS, params={"limit": 1}))) == 1
    both = api.client.get(RUNS, params={"account_id": ga, "status": "ok"})
    assert len(_ids(both)) == 1
    assert _ids(api.client.get(RUNS, params={"account_id": 999})) == []


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 501}, {"status": "weird"}, {"account_id": "x"}],
    ids=["limit-0", "limit-501", "status", "account-id"],
)
def test_bad_list_queries_are_validation_errors(api: Api, params):
    error_of(api.client.get(RUNS, params=params), 422, "validation_error")


def test_the_limit_may_be_500(api: Api):
    assert api.client.get(RUNS, params={"limit": 500}).status_code == 200


def test_one_run(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    (run_id,) = _ids(api.client.get(RUNS, params={"account_id": ca}))
    r = api.client.get(f"{RUNS}/{run_id}")
    assert r.status_code == 200 and set(r.json()) == RUN_KEYS and r.json()["id"] == run_id
    error_of(api.client.get(f"{RUNS}/999"), 404, "not_found")


# ---- revert --------------------------------------------------------------------------------


def _latest(api: Api, account: int) -> int:
    return _ids(api.client.get(RUNS, params={"account_id": account}))[0]


def test_a_revert_dry_run_returns_the_set_and_versions_and_writes_nothing(api: Api, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(revert_module, "settle", lambda engine: calls.append(1) or SettleResult())
    gi, ga, ci, ca = _two_accounts(api)
    run_id = _latest(api, ga)
    before = api.counts()
    r = api.client.post(f"{RUNS}/{run_id}/revert", json={"dry_run": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "run_id", "removed_entry_ids", "partner_entry_ids", "freed_document_ids", "repointed_source_ids",
        "cleared_duplicate_ids", "derived_changes", "versions", "settle",
    }  # fmt: skip
    assert body["run_id"] == run_id and body["settle"] is None and calls == []
    assert len(body["removed_entry_ids"]) == 3
    assert set(body["versions"]) >= {str(i) for i in body["removed_entry_ids"]}
    assert all(isinstance(v, int) for v in body["versions"].values())
    assert body["derived_changes"] and {"account_id", "before", "after"} <= set(body["derived_changes"][0])
    assert api.counts() == before
    assert api.client.get(f"{RUNS}/{run_id}").json()["status"] == "ok"


def test_a_real_revert_with_the_previews_versions_succeeds_and_settles_once(api: Api, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        revert_module, "settle", lambda engine: calls.append(1) or SettleResult(touched_entry_ids=(5,))
    )
    gi, ga, ci, ca = _two_accounts(api)
    run_id = _latest(api, ga)
    preview = api.client.post(f"{RUNS}/{run_id}/revert", json={"dry_run": True}).json()
    versions = {int(k): v for k, v in preview["versions"].items()}
    r = api.client.post(f"{RUNS}/{run_id}/revert", json={"expected_versions": versions})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["removed_entry_ids"] == preview["removed_entry_ids"]
    assert done["settle"] == {"touched_entry_ids": [5], "error": None} and calls == [1]
    run = api.client.get(f"{RUNS}/{run_id}").json()
    assert run["status"] == "reverted" and run["reverted_at"] and run["revertible"] is False
    assert api.one("SELECT count(*) FROM source_transaction WHERE account_id = :a", a=ga)[0] == 0
    assert api.one("SELECT count(*) FROM source_transaction WHERE account_id = :a", a=ca)[0] > 0
    api.assert_checks_clean()


def test_a_settle_error_comes_back_in_the_body_with_200(api: Api, monkeypatch):
    monkeypatch.setattr(revert_module, "settle", lambda engine: SettleResult(error="settle blew up"))
    gi, ga, ci, ca = _two_accounts(api)
    r = api.client.post(f"{RUNS}/{_latest(api, ga)}/revert", json={})
    assert r.status_code == 200 and r.json()["settle"]["error"] == "settle blew up"
    assert api.client.get(f"{RUNS}/{_latest(api, ga)}").json()["status"] == "reverted"


def test_a_revert_without_a_body_is_a_real_revert_without_version_checks(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    run_id = _latest(api, ga)
    assert api.client.post(f"{RUNS}/{run_id}/revert").status_code == 200
    assert api.client.get(f"{RUNS}/{run_id}").json()["status"] == "reverted"


def test_a_moved_version_is_a_409_conflict_naming_the_entries(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    run_id = _latest(api, ga)
    preview = api.client.post(f"{RUNS}/{run_id}/revert", json={"dry_run": True}).json()
    versions = {int(k): v for k, v in preview["versions"].items()}
    moved = preview["removed_entry_ids"][0]
    with api.engine.begin() as conn:
        conn.execute(text("UPDATE ledger_entry SET note = 'moved' WHERE id = :i"), {"i": moved})
    before = api.counts()
    err = error_of(
        api.client.post(f"{RUNS}/{run_id}/revert", json={"expected_versions": versions}), 409, "conflict"
    )
    assert err["details"] == {"entry_ids": [moved]}
    assert api.counts() == before
    # the same refusal in a preview that carries versions
    err = error_of(
        api.client.post(f"{RUNS}/{run_id}/revert", json={"dry_run": True, "expected_versions": versions}),
        409,
        "conflict",
    )
    assert err["details"]["entry_ids"] == [moved]


def test_an_entry_written_without_a_version_is_named_too(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    run_id = _latest(api, ga)
    err = error_of(
        api.client.post(f"{RUNS}/{run_id}/revert", json={"expected_versions": {}}), 409, "conflict"
    )
    assert len(err["details"]["entry_ids"]) == 3


def test_an_older_run_is_a_409_naming_the_newer_one(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    api.upload(gi, ga, giro_bytes())
    newer, older = _ids(api.client.get(RUNS, params={"account_id": ga}))
    before = api.counts()
    err = error_of(api.client.post(f"{RUNS}/{older}/revert", json={}), 409, "not_latest_run")
    assert err["details"] == {"newer_run_id": newer}
    assert api.counts() == before


def test_a_failed_or_reverted_run_is_not_revertible(api: Api):
    gi, ga, ci, ca = _two_accounts(api)
    api.upload(gi, ga, b"not a statement at all\n")
    (failed,) = [x["id"] for x in api.client.get(RUNS, params={"status": "failed"}).json()]
    err = error_of(api.client.post(f"{RUNS}/{failed}/revert", json={}), 409, "not_revertible")
    assert isinstance(err["details"]["reason"], str) and err["details"]["reason"]
    done = _latest(api, ca)
    assert api.client.post(f"{RUNS}/{done}/revert", json={}).status_code == 200
    again = error_of(api.client.post(f"{RUNS}/{done}/revert", json={}), 409, "not_revertible")
    assert again["details"]["reason"]


def test_a_missing_run(api: Api):
    error_of(api.client.post(f"{RUNS}/999/revert", json={}), 404, "not_found")
    error_of(api.client.post(f"{RUNS}/999/revert", json={"dry_run": True}), 404, "not_found")


def test_a_lost_deadlock_is_a_409_try_again(api: Api, monkeypatch):
    def boom(*a, **k):
        raise WriteConflict

    monkeypatch.setattr(runs_router, "revert_run", boom)
    error_of(api.client.post(f"{RUNS}/1/revert", json={}), 409, "try_again")


@pytest.mark.parametrize(
    "body",
    [{"dry_run": "maybe"}, {"expected_versions": {"a": 1}}, {"expected_versions": [1]}, {"extra": 1}],
    ids=["flag", "key", "shape", "extra-field"],
)
def test_revert_bodies_are_strict(api: Api, body):
    error_of(api.client.post(f"{RUNS}/1/revert", json=body), 422, "validation_error")


# ---- the whole flow ------------------------------------------------------------------------


def test_the_whole_flow_leaves_the_integrity_views_empty(api: Api):
    c = api.client
    account = api.account("Giro", kind="checking", currency="EUR")
    inst = api.instance("giro_with_preamble")  # create from a preset
    assert api.link(inst, account, dry_run=True)["dry_run"] is True  # preview: nothing linked yet
    assert c.get("/api/importers/instances").json()[0]["accounts"] == []
    api.link(inst, account)

    dry = api.upload(inst, account, giro_bytes(), dry_run=True).json()
    assert dry["summary"]["inserted"] == 3 and api.counts()["import_run"] == 0
    first = api.upload(inst, account, giro_bytes()).json()
    assert first["summary"]["inserted"] == 3
    (listed,) = c.get(RUNS, params={"account_id": account}).json()
    assert listed["id"] == first["run_id"] and listed["revertible"] is True
    assert c.get("/api/importers/instances").json()[0]["last_run_at"] is not None

    again = api.upload(inst, account, giro_bytes()).json()
    assert again["summary"]["inserted"] == 0 and again["summary"]["skipped_by_identity"] == 3
    newer, older = (x["id"] for x in c.get(RUNS, params={"account_id": account}).json())
    assert newer == again["run_id"] and older == first["run_id"]
    error_of(c.post(f"{RUNS}/{older}/revert", json={}), 409, "not_latest_run")

    # the repeat run removes nothing; the first can be reverted once the repeat is gone
    for run_id in (newer, older):
        preview = c.post(f"{RUNS}/{run_id}/revert", json={"dry_run": True}).json()
        versions = {int(k): v for k, v in preview["versions"].items()}
        done = c.post(f"{RUNS}/{run_id}/revert", json={"expected_versions": versions})
        assert done.status_code == 200, done.text
        assert done.json()["removed_entry_ids"] == preview["removed_entry_ids"]
    assert [x["status"] for x in c.get(RUNS).json()] == ["reverted", "reverted"]
    assert api.counts()["source_transaction"] == 0 and api.counts()["ledger_entry"] == 0
    api.assert_checks_clean()
