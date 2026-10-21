"""OIDC sign-in against a mock provider (architecture §5.6, D226). No test touches the network."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import create_app
from app.startup import reconcile_users
from app.utils.config import OidcConfig, Secret
from tests.api.conftest import PASSWORDS
from tests.oidc_provider import ACCESS_TOKEN, CLIENT_ID, CLIENT_SECRET, CODE, ISSUER, MockProvider

BASE_URL = "http://localhost"


@pytest.fixture
def provider(clock) -> MockProvider:
    return MockProvider(clock.now().timestamp())


@pytest.fixture
def make_oidc(api_config, api_engine, provider):
    clients: list[TestClient] = []

    def make(**overrides) -> TestClient:
        oidc = OidcConfig(
            issuer=ISSUER,
            client_id=CLIENT_ID,
            client_secret=Secret(CLIENT_SECRET),
            base_url=BASE_URL,
            **overrides,
        )
        cfg = replace(api_config, oidc=oidc)
        client = TestClient(
            create_app(cfg, api_engine, oidc_transport=provider.transport()), base_url=BASE_URL
        )
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.close()


def begin(client: TestClient, provider: MockProvider) -> str:
    """The browser's first leg; returns the state."""
    r = client.get("/api/session/oidc", follow_redirects=False)
    assert r.status_code == 303
    return provider.saw_authorization(r.headers["location"])["state"][0]


def callback(client: TestClient, state: str, code: str = CODE, **extra: str):
    params = {"state": state, "code": code, **extra}
    return client.get("/api/session/oidc/callback", params=params, follow_redirects=False)


def sign_in(client: TestClient, provider: MockProvider):
    return callback(client, begin(client, provider))


def refused(r, code: str) -> None:
    assert r.status_code == 303
    assert r.headers["location"] == f"/login?error={code}"
    assert "ledgehog_session" not in r.headers.get("set-cookie", "")


def user_row(engine, login: str):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id, login, pw_hash, display_name, disabled, source FROM app_user WHERE login = :l"),
            {"l": login},
        ).one_or_none()


def count_users(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM app_user")).scalar_one()


# -- the first leg --------------------------------------------------------------------------


def test_the_app_starts_with_the_provider_down_and_contacts_it_at_the_first_sign_in(make_oidc, provider):
    provider.down = True
    client = make_oidc()
    assert provider.requests == []  # nothing at start
    r = client.get("/api/session/oidc", follow_redirects=False)
    refused(r, "oidc_unavailable")
    provider.down = False
    assert client.get("/api/session/oidc", follow_redirects=False).status_code == 303


def test_start_redirects_to_the_provider_with_pkce_state_and_nonce(make_oidc, provider):
    client = make_oidc(allowed_group=None)
    r = client.get("/api/session/oidc", follow_redirects=False)
    assert r.status_code == 303
    parts = urlsplit(r.headers["location"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ISSUER}/auth"
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert q["response_type"] == "code"
    assert q["client_id"] == CLIENT_ID
    assert q["redirect_uri"] == f"{BASE_URL}/api/session/oidc/callback"
    assert q["scope"] == "openid email profile"
    assert q["code_challenge_method"] == "S256"
    assert q["state"] and q["nonce"] and q["code_challenge"]
    assert CLIENT_SECRET not in r.headers["location"]
    cookie = r.headers["set-cookie"]
    assert f"ledgehog_oidc_state={q['state']}" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    assert "Path=/api/session/oidc" in cookie


def test_oidc_routes_do_not_exist_without_oidc(client):
    assert client.get("/api/session/oidc", follow_redirects=False).status_code == 404
    assert client.get("/api/session/oidc/callback", follow_redirects=False).status_code == 404


# -- a new user -----------------------------------------------------------------------------


def test_a_new_user_is_created_without_a_password_and_signed_in(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", "email_verified": True, "name": "Zoe Z."}
    r = sign_in(client, provider)
    assert r.status_code == 303 and r.headers["location"] == "/"
    row = user_row(api_engine, "zoe@home.test")
    assert (row.source, row.pw_hash, row.display_name, row.disabled) == ("oidc", None, "Zoe Z.", False)
    with api_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT method FROM session WHERE user_id = :u"), {"u": row.id}).scalar_one()
            == "oidc"
        )
    me = client.get("/api/session")
    assert me.status_code == 200 and me.json()["login"] == "zoe@home.test"
    # the cookie rules are the session's own
    assert "HttpOnly" in r.headers["set-cookie"]
    # the code exchange carried the verifier, the redirect address and the client's credentials
    form = provider.token_requests[0]
    assert provider.pkce_ok is True
    assert form["redirect_uri"] == f"{BASE_URL}/api/session/oidc/callback"
    assert form["grant_type"] == "authorization_code"
    assert provider.token_auth[0] and provider.token_auth[0].startswith("Basic ")


def test_without_a_name_claim_the_login_is_the_display_name(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    sign_in(client, provider)
    assert user_row(api_engine, "zoe@home.test").display_name == "zoe@home.test"


def test_the_name_claim_wins_on_every_sign_in(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", "name": "Zoe"}
    sign_in(client, provider)
    provider.claims = {"email": "zoe@home.test", "name": "Zoe Zed"}
    sign_in(client, provider)
    assert user_row(api_engine, "zoe@home.test").display_name == "Zoe Zed"
    provider.claims = {"email": "zoe@home.test"}
    provider.drop = {"name"}
    sign_in(client, provider)
    assert user_row(api_engine, "zoe@home.test").display_name == "Zoe Zed"  # absent: unchanged


def test_a_custom_login_and_name_attribute(make_oidc, provider, api_engine):
    client = make_oidc(login_attribute="preferred_username", displayname_attribute="nickname")
    provider.claims = {"preferred_username": "zed", "nickname": "Zed"}
    sign_in(client, provider)
    row = user_row(api_engine, "zed")
    assert (row.display_name, row.source) == ("Zed", "oidc")


def test_no_login_claim_refuses(make_oidc, provider, api_engine):
    client = make_oidc()
    before = count_users(api_engine)
    provider.claims = {"name": "Nobody"}
    refused(sign_in(client, provider), "oidc_no_login")
    assert count_users(api_engine) == before


# -- the handover ---------------------------------------------------------------------------


def test_a_configured_user_is_handed_to_the_provider(make_oidc, provider, api_engine, api_config, caplog):
    client = make_oidc(login_attribute="preferred_username")
    provider.claims = {"preferred_username": "anna", "name": "Anna Provider"}
    assert user_row(api_engine, "anna").source == "config"
    r = sign_in(client, provider)
    assert r.headers["location"] == "/"
    row = user_row(api_engine, "anna")
    assert (row.source, row.pw_hash, row.display_name) == ("oidc", None, "Anna Provider")

    # the password no longer works, and fails like a wrong one
    wrong = client.post("/api/session", json={"login": "anna", "password": "wrong-wrong"})
    gone = client.post("/api/session", json={"login": "anna", "password": PASSWORDS["anna"]})
    assert gone.status_code == wrong.status_code == 401
    assert gone.json() == wrong.json()

    # the start leaves them alone, and logs the configured login it ignored
    with caplog.at_level(logging.INFO, logger="ledgehog.startup"), api_engine.begin() as conn:
        result = reconcile_users(conn, api_config.users)
    assert result.ignored == ("anna",)
    assert "anna" not in result.rehashed + result.renamed + result.disabled
    row = user_row(api_engine, "anna")
    assert (row.source, row.pw_hash, row.display_name, row.disabled) == ("oidc", None, "Anna Provider", False)


def test_a_claim_differing_in_case_signs_into_the_existing_user(make_oidc, provider, api_engine):
    client = make_oidc(login_attribute="preferred_username")
    before = count_users(api_engine)
    provider.claims = {"preferred_username": "ANNA", "name": "Anna Provider"}
    assert sign_in(client, provider).headers["location"] == "/"
    assert count_users(api_engine) == before  # no duplicate
    assert user_row(api_engine, "ANNA") is None
    row = user_row(api_engine, "anna")
    assert (row.source, row.pw_hash, row.display_name) == ("oidc", None, "Anna Provider")  # handed over
    assert client.get("/api/session").json()["login"] == "anna"


def test_users_differing_only_in_case_make_the_match_ambiguous(make_oidc, provider, api_engine):
    client = make_oidc()
    with api_engine.begin() as conn:
        for login in ("Bob@home.test", "bob@home.test"):
            conn.execute(
                text(
                    "INSERT INTO app_user (login, pw_hash, display_name, source) "
                    "VALUES (:l, NULL, :l, 'oidc')"
                ),
                {"l": login},
            )
    before = count_users(api_engine)
    provider.claims = {"email": "BOB@home.test"}
    refused(sign_in(client, provider), "oidc_failed")
    assert count_users(api_engine) == before


def test_a_provider_user_absent_from_the_environment_is_not_disabled(
    make_oidc, provider, api_engine, api_config
):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    sign_in(client, provider)
    with api_engine.begin() as conn:
        result = reconcile_users(conn, api_config.users)
    assert result.disabled == ()
    assert user_row(api_engine, "zoe@home.test").disabled is False


# -- who is admitted ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("groups", "ok"),
    [(["family", "admins"], True), (["guests"], False), ([], False), ("family", True), (None, False)],
)
def test_the_allowed_group_is_needed_at_every_sign_in(make_oidc, provider, api_engine, groups, ok):
    client = make_oidc(allowed_group="family")
    provider.claims = {"email": "zoe@home.test"}
    if groups is not None:
        provider.claims["groups"] = groups
    r = sign_in(client, provider)
    if ok:
        assert r.headers["location"] == "/"
        assert user_row(api_engine, "zoe@home.test") is not None
    else:
        refused(r, "oidc_not_allowed")
        assert user_row(api_engine, "zoe@home.test") is None


def _log_text(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx")


def test_the_group_refusal_log_tells_an_absent_claim_from_a_missing_group(make_oidc, provider, caplog):
    client = make_oidc(allowed_group="family")
    provider.claims = {"email": "zoe@home.test"}
    with caplog.at_level(logging.INFO):
        refused(sign_in(client, provider), "oidc_not_allowed")
    text = _log_text(caplog)
    assert "oidc_not_allowed: the groups claim is absent" in text
    assert "oidc: groups claim:" not in text
    caplog.clear()
    provider.claims = {"email": "zoe@home.test", "groups": ["guests-club", "staff-team"]}
    with caplog.at_level(logging.INFO):
        refused(sign_in(client, provider), "oidc_not_allowed")
    text = _log_text(caplog)
    assert (
        "oidc_not_allowed: the allowed group 'family' is not among the user's groups "
        "['guests-club', 'staff-team']"
    ) in text
    caplog.clear()
    provider.claims = {"email": "zoe@home.test", "groups": ["Family\r", " family"]}
    with caplog.at_level(logging.INFO):
        refused(sign_in(client, provider), "oidc_not_allowed")
    assert "the user's groups ['Family\\r', ' family']" in _log_text(caplog)


@pytest.mark.parametrize(
    ("groups", "shape"),
    [
        ("family,guests-club", "oidc: groups claim: str, 18 chars, contains comma"),
        ("a b;c", "oidc: groups claim: str, 5 chars, contains space, contains semicolon"),
        (
            ["guests-club", "x@y.test"],
            "oidc: groups claim: list, 2 entries, item types str, an entry contains @",
        ),
        (["guests-club", 7], "oidc: groups claim: list, 2 entries, item types int, str"),
        (5, "oidc: groups claim: int"),
    ],
)
def test_the_shape_line_of_the_groups_claim_names_no_group(make_oidc, provider, caplog, groups, shape):
    client = make_oidc(allowed_group="family")
    provider.claims = {"email": "zoe@home.test", "groups": groups}
    with caplog.at_level(logging.INFO):
        sign_in(client, provider)
    text = _log_text(caplog)
    assert shape in text
    shape_line = next(line for line in text.splitlines() if "oidc: groups claim:" in line)
    for name in ("guests-club", "family", "x@y.test"):
        assert name not in shape_line


def test_a_known_user_needs_the_group_too(make_oidc, provider, api_engine):
    client = make_oidc(allowed_group="family", login_attribute="preferred_username")
    provider.claims = {"preferred_username": "anna", "groups": ["guests"]}
    refused(sign_in(client, provider), "oidc_not_allowed")
    row = user_row(api_engine, "anna")
    assert row.source == "config" and row.pw_hash is not None  # a refusal hands nothing over


def test_a_group_revoked_at_the_provider_takes_effect_at_the_next_sign_in(make_oidc, provider):
    client = make_oidc(allowed_group="family")
    provider.claims = {"email": "zoe@home.test", "groups": ["family"]}
    assert sign_in(client, provider).headers["location"] == "/"
    assert client.get("/api/session").status_code == 200
    provider.claims = {"email": "zoe@home.test", "groups": []}
    refused(sign_in(client, provider), "oidc_not_allowed")
    assert client.get("/api/session").status_code == 200  # the running session is not re-checked


def test_an_unverified_email_is_refused(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", "email_verified": False}
    refused(sign_in(client, provider), "oidc_unverified")
    assert user_row(api_engine, "zoe@home.test") is None


def test_email_verified_only_matters_for_the_email_claim(make_oidc, provider):
    client = make_oidc(login_attribute="preferred_username")
    provider.claims = {"preferred_username": "zed", "email_verified": False}
    assert sign_in(client, provider).headers["location"] == "/"


def test_a_missing_email_verified_is_admitted(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    assert sign_in(client, provider).headers["location"] == "/"


def test_a_disabled_user_is_refused(make_oidc, provider, api_engine):
    client = make_oidc(login_attribute="preferred_username")
    provider.claims = {"preferred_username": "old"}
    refused(sign_in(client, provider), "oidc_disabled")
    assert user_row(api_engine, "old").source == "config"


def test_a_disabled_provider_user_is_refused(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    sign_in(client, provider)
    with api_engine.begin() as conn:
        conn.execute(text("UPDATE app_user SET disabled = true WHERE login = 'zoe@home.test'"))
    refused(sign_in(client, provider), "oidc_disabled")


# -- claims from userinfo -------------------------------------------------------------------


def test_missing_claims_are_taken_from_userinfo(make_oidc, provider, api_engine):
    client = make_oidc(allowed_group="family")
    provider.drop = {"email", "name", "groups"}
    provider.userinfo = {"sub": "sub-1", "email": "zoe@home.test", "name": "Zoe U.", "groups": ["family"]}
    r = sign_in(client, provider)
    assert r.headers["location"] == "/"
    assert user_row(api_engine, "zoe@home.test").display_name == "Zoe U."
    assert provider.userinfo_auth == [f"Bearer {ACCESS_TOKEN}"]


def test_userinfo_is_not_asked_when_the_id_token_has_everything(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", "name": "Zoe"}
    provider.userinfo = {"sub": "sub-1", "email": "other@home.test"}
    sign_in(client, provider)
    assert provider.userinfo_auth == []


def test_the_id_token_wins_over_userinfo(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    provider.userinfo = {"sub": "sub-1", "email": "other@home.test", "name": "From Userinfo"}
    sign_in(client, provider)
    assert user_row(api_engine, "zoe@home.test").display_name == "From Userinfo"
    assert user_row(api_engine, "other@home.test") is None


def test_a_userinfo_subject_mismatch_is_refused(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.drop = {"email"}
    provider.userinfo = {"sub": "someone-else", "email": "victim@home.test"}
    before = count_users(api_engine)
    refused(sign_in(client, provider), "oidc_failed")
    assert count_users(api_engine) == before


def test_a_missing_login_with_no_userinfo_refuses(make_oidc, provider):
    client = make_oidc()
    provider.drop = {"email"}
    refused(sign_in(client, provider), "oidc_no_login")


def test_a_login_that_userinfo_lacks_too_is_missing(make_oidc, provider):
    client = make_oidc()
    provider.drop = {"email"}
    provider.userinfo = {"sub": "sub-1"}  # answers, but without the login
    refused(sign_in(client, provider), "oidc_no_login")


def test_a_missing_name_is_not_fatal_when_userinfo_fails(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    provider.userinfo = None  # no endpoint: the name stays absent
    assert sign_in(client, provider).headers["location"] == "/"


def _oidc_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "ledgehog.oidc"]


def _assert_no_values(caplog, *values: str) -> None:
    text = "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx")
    for value in (ACCESS_TOKEN, CODE, CLIENT_SECRET, *values):
        assert value not in text


def test_the_log_names_the_id_token_claims_and_the_userinfo_claims_never_their_values(
    make_oidc, provider, caplog
):
    client = make_oidc()
    provider.drop = {"email"}
    provider.userinfo = {"sub": "sub-1", "email": "zoe@home.test", "name": "Zoe U."}
    with caplog.at_level(logging.INFO, logger="ledgehog.oidc"):
        assert sign_in(client, provider).headers["location"] == "/"
    lines = _oidc_lines(caplog)
    assert "oidc: id_token claims: aud, exp, iat, iss, nonce, sub" in lines
    assert "oidc: claims missing from the id_token: email, name" in lines
    assert "oidc: userinfo claims: email, name, sub" in lines
    # the new user's login is logged by the existing "user created" line, so only the other values are checked
    _assert_no_values(caplog, "Zoe U.", provider.id_token())


def test_the_log_says_why_userinfo_was_not_asked_and_what_refused(make_oidc, provider, caplog):
    client = make_oidc()
    provider.drop = {"email"}
    with caplog.at_level(logging.INFO, logger="ledgehog.oidc"):
        refused(sign_in(client, provider), "oidc_no_login")
    lines = _oidc_lines(caplog)
    assert "oidc: id_token claims: aud, exp, iat, iss, nonce, sub" in lines
    assert "oidc: claims missing from the id_token: email, name" in lines
    assert "oidc: userinfo not asked: the provider has no userinfo endpoint" in lines
    _assert_no_values(caplog)


def test_the_log_says_when_the_userinfo_request_failed_without_its_body(make_oidc, provider, caplog):
    client = make_oidc()
    provider.drop = {"email"}
    provider.userinfo = {"sub": "sub-1", "email": "zoe@home.test"}
    provider.userinfo_status = 500
    with caplog.at_level(logging.INFO, logger="ledgehog.oidc"):
        refused(sign_in(client, provider), "oidc_unavailable")
    failed = [m for m in _oidc_lines(caplog) if m.startswith("oidc: the userinfo request failed")]
    assert len(failed) == 1
    assert "HTTPStatusError" in failed[0]
    _assert_no_values(caplog, "zoe@home.test", "secret-body")


def test_unverified_email_from_userinfo_is_refused(make_oidc, provider):
    client = make_oidc()
    provider.drop = {"email"}
    provider.userinfo = {"sub": "sub-1", "email": "zoe@home.test", "email_verified": False}
    refused(sign_in(client, provider), "oidc_unverified")


# -- state, nonce and the token -------------------------------------------------------------


def test_a_return_without_the_binding_cookie_is_refused(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    state = begin(client, provider)
    client.cookies.clear()  # another browser: the login CSRF case
    refused(callback(client, state), "oidc_failed")
    assert user_row(api_engine, "zoe@home.test") is None
    assert provider.token_requests == []


def test_a_cookie_for_another_state_is_refused(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    state = begin(client, provider)
    other = begin(client, provider)  # replaces the cookie with the second state
    assert other != state
    refused(callback(client, state), "oidc_failed")


def test_an_unknown_state_is_refused(make_oidc, provider):
    client = make_oidc()
    begin(client, provider)
    client.cookies.set("ledgehog_oidc_state", "forged", path="/api/session/oidc")
    refused(callback(client, "forged"), "oidc_failed")


def test_a_state_is_good_once(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    state = begin(client, provider)
    assert callback(client, state).headers["location"] == "/"
    client.cookies.set("ledgehog_oidc_state", state, path="/api/session/oidc")
    refused(callback(client, state), "oidc_failed")


def test_a_pending_sign_in_expires(make_oidc, provider, clock):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    state = begin(client, provider)
    clock.advance(timedelta(minutes=11))
    refused(callback(client, state), "oidc_failed")


def test_the_state_cookie_is_spent_by_the_return(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    r = sign_in(client, provider)
    assert "ledgehog_oidc_state" not in client.cookies
    assert any("ledgehog_oidc_state" in h for h in r.headers.get_list("set-cookie"))


def test_the_provider_returning_an_error_is_refused(make_oidc, provider):
    client = make_oidc()
    state = begin(client, provider)
    r = client.get(
        "/api/session/oidc/callback",
        params={"state": state, "error": "access_denied"},
        follow_redirects=False,
    )
    refused(r, "oidc_failed")


def test_a_nonce_mismatch_is_refused(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", "nonce": "replayed-from-another-sign-in"}
    refused(sign_in(client, provider), "oidc_failed")
    assert user_row(api_engine, "zoe@home.test") is None


def test_a_missing_nonce_is_refused(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    provider.drop = {"nonce"}
    refused(sign_in(client, provider), "oidc_failed")


def test_an_expired_id_token_is_refused(make_oidc, provider, clock):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", "exp": int(clock.now().timestamp()) - 3600}
    refused(sign_in(client, provider), "oidc_failed")


@pytest.mark.parametrize(
    "bad",
    [
        {"iss": "https://evil.test/realms/home"},
        {"aud": "another-client"},
        {"aud": [CLIENT_ID, "another-client"], "azp": "another-client"},
        {"sub": ""},
    ],
)
def test_an_id_token_with_a_wrong_claim_is_refused(make_oidc, provider, bad):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", **bad}
    refused(sign_in(client, provider), "oidc_failed")


def test_an_audience_list_with_our_client_as_authorized_party_is_accepted(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test", "aud": [CLIENT_ID, "other"], "azp": CLIENT_ID}
    assert sign_in(client, provider).headers["location"] == "/"


def test_a_token_signed_with_another_key_is_refused(make_oidc, provider, api_engine):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    provider.sign_with = provider.other_key
    refused(sign_in(client, provider), "oidc_failed")
    assert user_row(api_engine, "zoe@home.test") is None


def test_a_failing_code_exchange_is_refused(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    state = begin(client, provider)
    refused(callback(client, state, code="not-the-code"), "oidc_failed")


def test_a_provider_that_dies_between_the_legs_is_a_refusal_not_an_error(make_oidc, provider):
    client = make_oidc()
    provider.claims = {"email": "zoe@home.test"}
    state = begin(client, provider)
    provider.down = True
    refused(callback(client, state), "oidc_failed")


def test_a_refusal_leaves_no_user_and_no_session_behind(make_oidc, provider, api_engine):
    client = make_oidc(allowed_group="family")
    provider.claims = {"email": "zoe@home.test", "groups": []}
    with api_engine.connect() as conn:
        sessions_before = conn.execute(text("SELECT count(*) FROM session")).scalar_one()
    refused(sign_in(client, provider), "oidc_not_allowed")
    with api_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM session")).scalar_one() == sessions_before
    assert client.get("/api/session").status_code == 401


# -- enforcement and the config view --------------------------------------------------------


def test_config_says_whether_oidc_is_offered_and_enforced(make_oidc):
    assert make_oidc().get("/api/config").json()["oidc_offered"] is True
    body = make_oidc().get("/api/config").json()
    assert (body["oidc_offered"], body["oidc_enforced"]) == (True, False)
    body = make_oidc(enforced=True).get("/api/config").json()
    assert (body["oidc_offered"], body["oidc_enforced"]) == (True, True)
    assert CLIENT_SECRET not in str(body) and ISSUER not in str(body)


def test_enforced_refuses_the_password_path(make_oidc, provider):
    client = make_oidc(enforced=True)
    for path in ("/api/session", "/api/login"):
        r = client.post(path, json={"login": "anna", "password": PASSWORDS["anna"]})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "password_login_disabled"
    provider.claims = {"email": "zoe@home.test"}
    assert sign_in(client, provider).headers["location"] == "/"
    assert client.get("/api/session").status_code == 200


def test_not_enforced_offers_both(make_oidc):
    client = make_oidc()
    r = client.post("/api/session", json={"login": "anna", "password": PASSWORDS["anna"]})
    assert r.status_code == 200


def test_a_user_without_a_password_cannot_sign_in_with_one(client, api_engine):
    with api_engine.begin() as conn:
        conn.execute(text("UPDATE app_user SET pw_hash = NULL WHERE login = 'anna'"))
    r = client.post("/api/session", json={"login": "anna", "password": ""})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    r = client.post("/api/session", json={"login": "anna", "password": "anything"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


# -- secrets --------------------------------------------------------------------------------


def test_no_secret_reaches_a_log_or_a_response(make_oidc, provider, caplog):
    client = make_oidc(allowed_group="family")
    seen: list[str] = []
    with caplog.at_level(logging.DEBUG):
        provider.claims = {"email": "zoe@home.test", "groups": ["family"]}
        state = begin(client, provider)
        r = callback(client, state)
        seen += [r.text, str(r.headers.get("location"))]
        # a failing leg too
        provider.claims = {"email": "zoe@home.test", "groups": []}
        state = begin(client, provider)
        r = callback(client, state)
        seen += [r.text, str(r.headers.get("location"))]
        state = begin(client, provider)
        r = callback(client, state, code="wrong-code")
        seen += [r.text, str(r.headers.get("location"))]
        provider.down = True
        r = client.get("/api/session/oidc", follow_redirects=False)
        seen += [r.text, str(r.headers.get("location"))]
        seen.append(client.get("/api/config").text)
    # the application's own logs: the test client's httpx logs its own request URLs, which is not the app
    app_logs = "\n".join(r.getMessage() for r in caplog.records if r.name != "httpx")
    out = app_logs + "".join(seen)
    for secret in (
        CLIENT_SECRET,
        ACCESS_TOKEN,
        CODE,
        "wrong-code",
        state,
        provider.id_token(),
        provider.nonce,
    ):
        assert secret and secret not in out
    assert '"id_token"' not in out  # the log names the id_token's claims, but never dumps a token response


def test_the_oidc_config_does_not_render_the_secret():
    oidc = OidcConfig(ISSUER, CLIENT_ID, Secret(CLIENT_SECRET), BASE_URL)
    assert CLIENT_SECRET not in repr(oidc) and CLIENT_SECRET not in str(oidc)


def test_httpx_is_the_transport_in_use(provider):
    # the mock provider answers through httpx.MockTransport, so no test can reach a real host
    assert isinstance(provider.transport(), httpx.MockTransport)
