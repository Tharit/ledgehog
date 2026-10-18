"""Ids out of range are a 422 at the API boundary, never a 500 from the database (finding 1)."""

from __future__ import annotations

import re

import pytest

from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api, error_of

api = h.api
make_api = h.make_api

BAD_IDS = [0, -1, 2**63, 10**20]


def _id_routes(app) -> list[tuple[str, str]]:
    found = []
    for path, item in app.openapi()["paths"].items():
        # a task is named by an opaque token (architecture §4.3), not an integer entity id
        if re.search(r"\{\w*_id\}", path) and "{task_id}" not in path:
            for method in item:
                found.append((method.upper(), path))
    return found


def test_there_are_path_id_routes_to_check(api: Api):
    assert len(_id_routes(api.client.app)) >= 14


@pytest.mark.parametrize("bad", BAD_IDS)
def test_every_path_id_rejects_out_of_range_ids(api: Api, bad: int):
    routes = _id_routes(api.client.app)
    assert routes
    for method, path in routes:
        for name in re.findall(r"\{(\w*_id)\}", path):
            url = re.sub(r"\{(\w*_id)\}", lambda m, n=name, b=bad: str(b if m.group(1) == n else 1), path)
            r = api.client.request(method, url, json={})
            assert r.status_code == 422, (method, url, r.status_code, r.text)
            body = r.json()
            assert body["error"]["code"] == "validation_error"
            assert any("path" in d["location"] for d in body["error"]["details"]), (method, url, body)


@pytest.mark.parametrize("bad", BAD_IDS)
def test_body_account_id_of_a_link_is_bounded(api: Api, bad: int):
    inst = api.instance()
    r = api.client.post(f"/api/importers/instances/{inst}/links", json={"account_id": bad})
    error_of(r, 422, "validation_error")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_upload_form_account_id_is_bounded(api: Api, bad: int):
    inst = api.instance()
    r = api.upload(inst, bad, b"a;b\n")
    error_of(r, 422, "validation_error")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_expected_versions_keys_and_values_are_bounded(api: Api, bad: int):
    r = api.client.post("/api/importers/runs/1/revert", json={"expected_versions": {str(bad): 1}})
    error_of(r, 422, "validation_error")
    r = api.client.post("/api/importers/runs/1/revert", json={"expected_versions": {"1": bad}})
    if bad > 0:
        error_of(r, 422, "validation_error")
    else:
        # a version of 0 or below never exists either
        error_of(r, 422, "validation_error")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_run_list_filters_are_bounded(api: Api, bad: int):
    for param in ("account_id", "instance_id"):
        error_of(api.client.get("/api/importers/runs", params={param: bad}), 422, "validation_error")
