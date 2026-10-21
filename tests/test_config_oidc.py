"""The OIDC variables of utils/config.py (architecture §5.7)."""

from pathlib import Path

import pytest

from app.utils.config import ConfigError
from tests.test_config import load

OIDC = {
    "OIDC_ISSUER": "https://idp.example/realms/home/",
    "OIDC_CLIENT_ID": "ledgehog",
    "OIDC_CLIENT_SECRET": "very-secret-oidc",
    "BASE_URL": "https://ledger.example/",
}
USER = {"USER_1_LOGIN": "anna", "USER_1_NAME": "Anna"}


def test_no_oidc_by_default():
    assert load().oidc is None


def test_oidc_with_its_defaults():
    o = load(**OIDC).oidc
    assert o is not None
    assert o.issuer == "https://idp.example/realms/home"
    assert o.base_url == "https://ledger.example"
    assert o.redirect_uri == "https://ledger.example/api/session/oidc/callback"
    assert o.scopes == ("openid", "email", "profile")
    assert (o.login_attribute, o.displayname_attribute) == ("email", "name")
    assert o.allowed_group is None and o.enforced is False


def test_oidc_overrides():
    o = load(
        **OIDC,
        OIDC_SCOPES="openid groups",
        OIDC_LOGIN_ATTRIBUTE="preferred_username",
        OIDC_DISPLAYNAME_ATTRIBUTE="nickname",
        OIDC_ALLOWED_GROUP="family",
        OIDC_ENFORCED="true",
    ).oidc
    assert o is not None
    assert o.scopes == ("openid", "groups")
    assert (o.login_attribute, o.displayname_attribute, o.allowed_group) == (
        "preferred_username",
        "nickname",
        "family",
    )
    assert o.enforced is True


@pytest.mark.parametrize("missing", ["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"])
def test_the_three_come_together(missing):
    with pytest.raises(ConfigError, match=missing):
        load(**{**OIDC, missing: None})


def test_base_url_is_required_with_oidc():
    with pytest.raises(ConfigError, match="BASE_URL"):
        load(**{**OIDC, "BASE_URL": None})


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("BASE_URL", "ledger.example"),
        ("BASE_URL", "https://ledger.example/app"),
        ("BASE_URL", "ftp://ledger.example"),
        ("OIDC_ISSUER", "not a url"),
        ("OIDC_ISSUER", "https://idp.example/?x=1"),
        ("OIDC_SCOPES", "email profile"),
        ("OIDC_CLIENT_ID", ""),
        ("OIDC_ALLOWED_GROUP", ""),
        ("OIDC_LOGIN_ATTRIBUTE", ""),
        ("OIDC_ENFORCED", "yes"),
        ("OIDC_ENFORCED", "1"),
    ],
)
def test_a_bad_value_names_the_variable(var, value):
    with pytest.raises(ConfigError, match=var):
        load(**{**OIDC, var: value})


def test_enforced_requires_oidc():
    with pytest.raises(ConfigError, match="OIDC_ENFORCED"):
        load(OIDC_ENFORCED="true")


def test_enforced_must_be_strictly_true_or_false_even_without_oidc():
    with pytest.raises(ConfigError, match="OIDC_ENFORCED"):
        load(OIDC_ENFORCED="maybe")


def test_the_client_secret_has_a_file_variant(tmp_path: Path):
    f = tmp_path / "secret"
    f.write_text("from-a-file\n", encoding="utf-8")
    env = {**OIDC, "OIDC_CLIENT_SECRET": None, "OIDC_CLIENT_SECRET_FILE": str(f)}
    o = load(**env).oidc
    assert o is not None and o.client_secret.reveal() == "from-a-file"
    with pytest.raises(ConfigError, match="OIDC_CLIENT_SECRET"):
        load(**{**OIDC, "OIDC_CLIENT_SECRET_FILE": str(f)})


def test_the_secret_never_renders_nor_appears_in_an_error():
    c = load(**OIDC)
    assert "very-secret-oidc" not in repr(c) and "very-secret-oidc" not in str(c.oidc)
    with pytest.raises(ConfigError) as err:
        load(**{**OIDC, "OIDC_SCOPES": "email"})
    assert "very-secret-oidc" not in str(err.value)


def test_a_password_is_optional_only_when_enforced():
    with pytest.raises(ConfigError, match="USER_1_PASSWORD"):
        load(**USER)
    with pytest.raises(ConfigError, match="USER_1_PASSWORD"):
        load(**OIDC, **USER)
    c = load(**OIDC, **USER, OIDC_ENFORCED="true")
    assert c.users[0].password is None
    c = load(**OIDC, **USER, USER_1_PASSWORD="pw-1234567", OIDC_ENFORCED="true")
    assert c.users[0].password is not None
