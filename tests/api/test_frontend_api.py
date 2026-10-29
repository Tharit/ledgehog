"""Serving the SPA bundle and the security headers (architecture §6.7)."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.api.frontend import FrontendError
from app.main import FRONTEND

SCRIPT = "\n\t\t\t\t{ const boot = 1; }\n\t\t\t"
INDEX = (
    '<!doctype html><html><head><script src="/a.js"></script></head>'
    f"<body><script>{SCRIPT}</script></body></html>"
)
HASH = "'sha256-" + base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode() + "'"


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    directory = tmp_path / "build"
    (directory / "_app").mkdir(parents=True)
    (directory / "index.html").write_text(INDEX)
    (directory / "_app" / "app.js").write_text("export {}")
    (tmp_path / "secret.txt").write_text("outside the bundle")
    return directory


@pytest.fixture
def served(api_config, api_engine, bundle):
    with TestClient(create_app(api_config, api_engine, frontend=bundle)) as client:
        yield client


def test_every_response_carries_the_policy_and_its_companions(served):
    for response in (served.get("/api/me"), served.get("/"), served.get("/_app/app.js")):
        policy = response.headers["content-security-policy"]
        assert f"script-src 'self' {HASH};" in policy
        assert policy.startswith("default-src 'none'; ")
        assert policy.endswith("require-trusted-types-for 'script'; trusted-types svelte-trusted-html")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cross-origin-opener-policy"] == "same-origin"


def test_unknown_paths_get_index_html_and_assets_are_served(served):
    for path in ("/ledger", "/accounts/3"):
        response = served.get(path)
        assert response.status_code == 200
        assert response.text == INDEX
    assert served.get("/_app/app.js").text == "export {}"


def test_unknown_api_path_keeps_the_error_envelope(served):
    response = served.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "content-security-policy" in response.headers


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/_app/../../secret.txt", "/..%2fsecret.txt"]
)
def test_paths_outside_the_bundle_are_never_served(served, path):
    assert "outside the bundle" not in served.get(path).text


def test_two_inline_scripts_refuse_the_start(api_config, api_engine, bundle):
    (bundle / "index.html").write_text(INDEX + "<script>other()</script>")
    with pytest.raises(FrontendError, match="2 inline scripts"):
        create_app(api_config, api_engine, frontend=bundle)


def test_no_inline_script_refuses_the_start(api_config, api_engine, bundle):
    (bundle / "index.html").write_text('<script src="/a.js"></script>')
    with pytest.raises(FrontendError, match="0 inline scripts"):
        create_app(api_config, api_engine, frontend=bundle)


def test_without_a_bundle_only_the_api_is_served(api_config, api_engine, tmp_path, caplog):
    with caplog.at_level("INFO", logger="app.api.frontend"):
        app = create_app(api_config, api_engine, frontend=tmp_path / "missing")
    assert str(tmp_path / "missing") in caplog.text
    with TestClient(app) as client:
        response = client.get("/ledger")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert response.headers["content-security-policy"].count("script-src 'self';") == 1
        assert "sha256" not in response.headers["content-security-policy"]


def test_the_real_bundle_holds_exactly_one_inline_script():
    index = FRONTEND / "index.html"
    if not index.is_file():
        pytest.skip("the frontend is not built")
    from app.api.frontend import script_hash

    script_hash(index.read_text(encoding="utf-8"))
