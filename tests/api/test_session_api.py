from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.utils.auth import SESSION_LIFETIME
from tests.api.conftest import PASSWORDS, login

ENVELOPE_KEYS = {"code", "message", "details"}


def _assert_envelope(resp, status, code):
    assert resp.status_code == status
    body = resp.json()
    assert set(body) == {"error"} and set(body["error"]) == ENVELOPE_KEYS
    assert body["error"]["code"] == code
    return body["error"]


def test_login_ok_returns_user_and_sets_cookie(client):
    r = login(client)
    assert r.status_code == 200
    assert r.json() == {"id": r.json()["id"], "login": "anna", "display_name": "Anna"}
    assert "pw_hash" not in r.text and PASSWORDS["anna"] not in r.text
    assert "ledgehog_session" in client.cookies


def test_session_resource_is_the_same_as_the_friendly_aliases(client):
    assert login(client, path="/api/session").status_code == 200
    assert client.get("/api/session").json()["login"] == "anna"
    assert client.delete("/api/session").status_code == 204
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"login": "anna", "password": "wrong"},
        {"login": "nobody", "password": "whatever"},
        {"login": "old", "password": PASSWORDS["old"]},  # disabled, right password
    ],
    ids=["wrong-password", "unknown-login", "disabled-user"],
)
def test_failed_login_is_one_401_shape(client, body):
    err = _assert_envelope(client.post("/api/login", json=body), 401, "invalid_credentials")
    assert err["message"] == "Wrong login or password." and err["details"] is None
    assert "ledgehog_session" not in client.cookies


def test_failed_logins_are_indistinguishable(client):
    a = client.post("/api/login", json={"login": "anna", "password": "x"})
    b = client.post("/api/login", json={"login": "ghost", "password": "x"})
    assert a.json() == b.json() and a.status_code == b.status_code


def test_cookie_attributes_on_localhost(make_client):
    for base in ("http://localhost", "http://127.0.0.1", "http://[::1]"):
        c = make_client(base)
        header = login(c).headers["set-cookie"].lower()
        assert header.startswith("ledgehog_session=")
        assert "httponly" in header and "samesite=lax" in header and "path=/" in header
        assert "secure" not in header.split(";"), base
        assert f"max-age={int(SESSION_LIFETIME.total_seconds())}" in header


def test_cookie_is_secure_for_any_other_host(make_client):
    c = make_client("https://ledger.example.org")
    header = login(c).headers["set-cookie"].lower()
    assert "secure" in [p.strip() for p in header.split(";")]
    assert "httponly" in header and "samesite=lax" in header


def test_me_without_cookie_is_401_envelope(client):
    err = _assert_envelope(client.get("/api/me"), 401, "unauthenticated")
    assert err["details"] is None


def test_me_with_unknown_session_id_is_401(client):
    client.cookies.set("ledgehog_session", "not-a-real-session-id")
    _assert_envelope(client.get("/api/me"), 401, "unauthenticated")


def test_me_returns_the_user(client):
    login(client, "ben")
    assert client.get("/api/me").json()["login"] == "ben"


def test_logout_deletes_the_session_row_and_clears_the_cookie(client, api_engine):
    login(client)
    r = client.post("/api/logout")
    assert r.status_code == 204 and r.content == b""
    assert "ledgehog_session=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()
    with api_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM session")).scalar_one() == 0
    assert client.get("/api/me").status_code == 401


def test_logout_without_a_session_is_still_204(client):
    assert client.post("/api/logout").status_code == 204


def test_replaying_a_logged_out_session_id_fails(client):
    login(client)
    sid = client.cookies["ledgehog_session"]
    client.post("/api/logout")
    client.cookies.set("ledgehog_session", sid)
    assert client.get("/api/me").status_code == 401


def test_expired_session_is_401(client, clock):
    login(client)
    clock.advance(SESSION_LIFETIME + timedelta(seconds=1))
    _assert_envelope(client.get("/api/me"), 401, "unauthenticated")


def test_disabled_users_existing_session_is_401(client, api_engine):
    login(client)
    with api_engine.begin() as conn:
        conn.execute(text("UPDATE app_user SET disabled = true WHERE login = 'anna'"))
    assert client.get("/api/me").status_code == 401


def test_use_slides_the_expiry(client, api_engine, clock):
    login(client)
    clock.advance(timedelta(days=10))
    r = client.get("/api/me")
    assert r.status_code == 200
    assert "ledgehog_session=" in r.headers["set-cookie"]  # cookie kept in step
    with api_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT expires_at FROM session")).scalar_one()
            == clock.now() + SESSION_LIFETIME
        )
    clock.advance(SESSION_LIFETIME - timedelta(days=1))  # past the original 30 days, inside the slid one
    assert client.get("/api/me").status_code == 200


def test_rapid_use_does_not_rewrite_the_session(client, api_engine, clock):
    login(client)
    with api_engine.connect() as conn:
        before = conn.execute(text("SELECT expires_at FROM session")).scalar_one()
    clock.advance(timedelta(minutes=5))
    r = client.get("/api/me")
    assert "set-cookie" not in r.headers
    with api_engine.connect() as conn:
        assert conn.execute(text("SELECT expires_at FROM session")).scalar_one() == before


def test_config_needs_a_session_and_contains_no_secret(client, api_config):
    _assert_envelope(client.get("/api/config"), 401, "unauthenticated")
    login(client)
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json() == {
        "base_currency": "EUR",
        "timezone": api_config.timezone.key,
        "locale": "en",
        "max_rate_age_days": 7,
        "matching_window_days": 7,
        "document_window_days": 7,
    }
    secrets = [*PASSWORDS.values(), api_config.db.password.reveal(), api_config.db.user]
    for s in secrets:
        assert s not in r.text


def test_no_secret_in_logs_or_responses_across_login_flows(client, api_config, caplog):
    texts = []
    with caplog.at_level(logging.DEBUG):
        texts.append(login(client).text)
        texts.append(client.post("/api/login", json={"login": "anna", "password": "bad-guess-9999"}).text)
        texts.append(client.post("/api/login", json={"login": "anna"}).text)  # 422 path
        texts.append(client.get("/api/me").text)
        texts.append(client.post("/api/logout").text)
    sid_logged = client.cookies.get("ledgehog_session")
    out = caplog.text + "".join(texts)
    for s in (*PASSWORDS.values(), "bad-guess-9999", api_config.db.password.reveal()):
        assert s not in out
    assert sid_logged is None


def test_validation_error_envelope_never_echoes_the_input(client):
    r = client.post("/api/login", json={"login": "anna", "password": "hunter2-leak", "extra": 1})
    err = _assert_envelope(r, 422, "validation_error")
    assert "hunter2-leak" not in r.text
    assert err["details"][0]["location"] == ["body", "extra"]
    _assert_envelope(client.post("/api/login", json={"login": 5}), 422, "validation_error")
    _assert_envelope(client.post("/api/login", content=b"{not json"), 422, "validation_error")


def test_unknown_path_and_wrong_method_use_the_envelope(client):
    _assert_envelope(client.get("/api/nope"), 404, "not_found")
    _assert_envelope(client.get("/api/login"), 405, "method_not_allowed")


def test_unexpected_error_is_a_generic_500_envelope(api_config, api_engine, caplog):
    from fastapi.testclient import TestClient

    from app.api import create_app

    app = create_app(api_config, api_engine)

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("password=leaky-secret-value")

    with (
        TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as c,
        caplog.at_level(logging.DEBUG),
    ):
        r = c.get("/api/boom")
    err = _assert_envelope(r, 500, "internal_error")
    assert "leaky" not in r.text and "leaky" not in caplog.text and err["message"]
