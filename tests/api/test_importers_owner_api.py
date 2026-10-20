"""Who may manage an importer instance (spec §5.11, architecture §4.1): the owner of a login, or either
user for a shared instance. Reading is open: the other user reads everything, settings included."""

from __future__ import annotations

import pytest

from tests.api import sync_helpers as h
from tests.api.sync_helpers import Sync, acct, error_of

sync = h.sync  # fixtures shared by the sync API tests
make_sync = h.make_sync

BASE = "/api/importers/instances"


def _managing(inst: int, account: int, client):
    """One call per managing route, by the given client; each is (name, response)."""
    return {
        "update": client.put(f"{BASE}/{inst}", json={"label": "Renamed"}),
        "link_dry_run": client.post(
            f"{BASE}/{inst}/links", json={"account_id": account, "external_ref": "A1", "dry_run": True}
        ),
        "link": client.post(f"{BASE}/{inst}/links", json={"account_id": account, "external_ref": "A1"}),
        "unlink": client.delete(f"{BASE}/{inst}/links/{account}"),
        "reset": client.post(f"{BASE}/{inst}/reset"),
        "delete": client.delete(f"{BASE}/{inst}"),
    }


def test_the_other_user_may_not_manage_an_owner_instance_and_the_owner_may(sync: Sync):
    theirs = sync.instance({"accounts": [acct("A1")]}, label="Anna's bank", access="owner", owner="anna")
    account = sync.account()
    # ben (the other client) is refused on every managing route, and nothing changed
    for response in _managing(theirs, account, sync.other).values():
        error_of(response, 403, "forbidden")
    error_of(sync.other.post(f"{BASE}/{theirs}/discover-accounts"), 403, "forbidden")
    row = next(i for i in sync.client.get(BASE).json() if i["id"] == theirs)
    assert (row["label"], row["accounts"]) == ("Anna's bank", [])
    # anna succeeds on each
    for name, response in _managing(theirs, account, sync.client).items():
        assert response.status_code == 200, (name, response.text)


def test_either_user_manages_a_shared_instance(sync: Sync):
    shared = sync.instance({"accounts": [acct("A1")]}, label="Shared", access="shared")
    account = sync.account()
    for client in (sync.client, sync.other):
        assert client.put(f"{BASE}/{shared}", json={"label": "By someone"}).status_code == 200
        assert (
            client.post(
                f"{BASE}/{shared}/links", json={"account_id": account, "external_ref": "A1"}
            ).status_code
            == 200
        )
        assert client.delete(f"{BASE}/{shared}/links/{account}").status_code == 200
        assert client.post(f"{BASE}/{shared}/reset").status_code == 200


def test_a_missing_instance_is_404_not_403(sync: Sync):
    error_of(sync.other.put(f"{BASE}/9999", json={"label": "x"}), 404, "not_found")
    error_of(sync.other.delete(f"{BASE}/9999"), 404, "not_found")


def test_the_other_user_reads_everything_and_is_told_what_they_may_manage(sync: Sync):
    mine = sync.instance({"accounts": [acct("A1")], "note": "x"}, label="Mine", access="owner", owner="anna")
    shared = sync.instance({"accounts": []}, label="Shared", access="shared")
    by_id = {i["id"]: i for i in sync.other.get(BASE).json()}
    seen = by_id[mine]
    assert seen["settings"] == {"accounts": [acct("A1")], "note": "x"}  # settings are not withheld
    assert (seen["access"], seen["owner_id"], seen["owner_name"], seen["manageable"]) == (
        "owner",
        sync.user_id("anna"),
        "Anna",
        False,
    )
    assert (by_id[shared]["owner_name"], by_id[shared]["manageable"]) == (None, True)
    own = {i["id"]: i for i in sync.client.get(BASE).json()}
    assert own[mine]["manageable"] is True


@pytest.mark.parametrize("path", ["/api/importers", "/api/importers/runs"])
def test_the_catalog_and_the_runs_stay_readable_by_the_other_user(sync: Sync, path: str):
    assert sync.other.get(path).status_code == 200
