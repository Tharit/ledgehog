import ast
import dataclasses
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.utils.config import Config, ConfigError

BASE = {
    "POSTGRES_HOST": "db.example",
    "POSTGRES_PORT": "5433",
    "POSTGRES_DB": "ledger",
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "s3cret-pw",
    "BASE_CURRENCY": "EUR",
    "TIMEZONE": "Europe/Berlin",
}


def load(**overrides: str | None) -> Config:
    env = {**BASE, **overrides}
    return Config.from_env({k: v for k, v in env.items() if v is not None})


def test_loads_typed_values():
    c = load()
    assert c.db.host == "db.example"
    assert c.db.port == 5433
    assert c.db.name == "ledger"
    assert c.db.user == "app"
    assert c.db.password.reveal() == "s3cret-pw"
    assert c.base_currency == "EUR"
    assert c.timezone == ZoneInfo("Europe/Berlin")


def test_defaults_where_safe():
    c = load(POSTGRES_HOST=None, POSTGRES_PORT=None)
    assert (c.db.host, c.db.port) == ("localhost", 5432)
    assert c.max_rate_age_days == 7
    assert c.matching_window_days == 7
    assert (c.document_window_back_days, c.document_window_ahead_days) == (60, 7)
    assert c.locale == "en"
    assert c.users == ()
    assert c.model is None


def test_overrides_windows_and_locale():
    c = load(
        MAX_RATE_AGE_DAYS="3",
        MATCHING_WINDOW_DAYS="10",
        DOCUMENT_WINDOW_BACK_DAYS="0",
        DOCUMENT_WINDOW_AHEAD_DAYS="14",
        LOCALE="de-DE",
    )
    assert (c.max_rate_age_days, c.matching_window_days) == (3, 10)
    assert (c.document_window_back_days, c.document_window_ahead_days) == (0, 14)
    assert c.locale == "de-DE"


@pytest.mark.parametrize(
    "var", ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "BASE_CURRENCY", "TIMEZONE"]
)
def test_missing_required_variable_is_named(var):
    with pytest.raises(ConfigError, match=var):
        load(**{var: None})


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("POSTGRES_PORT", "abc"),
        ("POSTGRES_PORT", "70000"),
        ("BASE_CURRENCY", "eur"),
        ("BASE_CURRENCY", "EURO"),
        ("TIMEZONE", "Mars/Olympus"),
        ("MAX_RATE_AGE_DAYS", "-1"),
        ("MATCHING_WINDOW_DAYS", "-1"),
        ("MATCHING_WINDOW_DAYS", "1.5"),
        ("DOCUMENT_WINDOW_BACK_DAYS", ""),
        ("DOCUMENT_WINDOW_AHEAD_DAYS", "-1"),
    ],
)
def test_bad_value_is_named(var, value):
    with pytest.raises(ConfigError, match=var):
        load(**{var: value})


def test_secret_never_appears_in_repr_or_str():
    c = load(USER_1_LOGIN="a", USER_1_NAME="A", USER_1_PASSWORD="hunter2-pw", MODEL_API_KEY="k-123456")
    for text in (repr(c), str(c), repr(c.db), str(c.db.password), repr(c.users[0]), repr(c.model)):
        assert "s3cret-pw" not in text
        assert "hunter2-pw" not in text
        assert "k-123456" not in text


def test_error_messages_do_not_contain_secrets():
    with pytest.raises(ConfigError) as e:
        load(POSTGRES_PORT="s3cret-pw")
    assert "s3cret-pw" not in str(e.value)


def test_file_variant_for_secrets(tmp_path: Path):
    f = tmp_path / "pw"
    f.write_text("from-file\n")
    c = load(POSTGRES_PASSWORD=None, POSTGRES_PASSWORD_FILE=str(f))
    assert c.db.password.reveal() == "from-file"


def test_file_and_plain_variable_together_is_an_error(tmp_path: Path):
    f = tmp_path / "pw"
    f.write_text("x")
    with pytest.raises(ConfigError, match="POSTGRES_PASSWORD"):
        load(POSTGRES_PASSWORD_FILE=str(f))


def test_unreadable_secret_file_is_named(tmp_path: Path):
    with pytest.raises(ConfigError, match="POSTGRES_PASSWORD_FILE"):
        load(POSTGRES_PASSWORD=None, POSTGRES_PASSWORD_FILE=str(tmp_path / "nope"))


def test_indexed_users():
    c = load(
        USER_1_LOGIN="alice",
        USER_1_NAME="Alice",
        USER_1_PASSWORD="pw-a",
        USER_2_LOGIN="bob",
        USER_2_NAME="Bob",
        USER_2_PASSWORD="pw-b",
    )
    assert [(u.login, u.name, u.password.reveal()) for u in c.users] == [
        ("alice", "Alice", "pw-a"),
        ("bob", "Bob", "pw-b"),
    ]


def test_user_password_file_variant(tmp_path: Path):
    f = tmp_path / "p"
    f.write_text("pw-from-file\n")
    c = load(USER_1_LOGIN="a", USER_1_NAME="A", USER_1_PASSWORD_FILE=str(f))
    assert c.users[0].password.reveal() == "pw-from-file"


@pytest.mark.parametrize(
    ("env", "named"),
    [
        ({"USER_1_LOGIN": "a", "USER_1_NAME": "A"}, "USER_1_PASSWORD"),
        ({"USER_1_LOGIN": "a", "USER_1_PASSWORD": "p"}, "USER_1_NAME"),
        ({"USER_1_NAME": "A", "USER_1_PASSWORD": "p"}, "USER_1_LOGIN"),
        ({"USER_2_LOGIN": "a", "USER_2_NAME": "A", "USER_2_PASSWORD": "p"}, "USER_1"),
    ],
)
def test_incomplete_or_gapped_user_groups_are_named(env, named):
    with pytest.raises(ConfigError, match=named):
        load(**env)


def test_duplicate_logins_rejected():
    with pytest.raises(ConfigError, match="USER_2_LOGIN"):
        load(
            USER_1_LOGIN="a",
            USER_1_NAME="A",
            USER_1_PASSWORD="p",
            USER_2_LOGIN="a",
            USER_2_NAME="B",
            USER_2_PASSWORD="q",
        )


def test_model_is_optional_and_needs_endpoint_and_name_together():
    assert load().model is None
    c = load(MODEL_ENDPOINT="http://llm", MODEL_NAME="m")
    assert c.model is not None
    assert (c.model.endpoint, c.model.name, c.model.api_key) == ("http://llm", "m", None)
    with pytest.raises(ConfigError, match="MODEL_NAME"):
        load(MODEL_ENDPOINT="http://llm")


def test_model_reasoning_effort_is_optional_and_strict():
    base = {"MODEL_ENDPOINT": "http://llm", "MODEL_NAME": "m"}
    assert load(**base).model.reasoning_effort is None  # type: ignore[union-attr]
    for effort in ("low", "medium", "high"):
        assert load(**base, MODEL_REASONING_EFFORT=effort).model.reasoning_effort == effort  # type: ignore[union-attr]
    for bad in ("max", "High", ""):
        with pytest.raises(ConfigError, match="MODEL_REASONING_EFFORT"):
            load(**base, MODEL_REASONING_EFFORT=bad)


def test_vision_model_is_optional_and_needs_endpoint_and_name_together():
    assert load().vision_model is None
    c = load(VISION_MODEL_ENDPOINT="http://vlm", VISION_MODEL_NAME="v")
    assert c.vision_model is not None
    assert (c.vision_model.endpoint, c.vision_model.name, c.vision_model.api_key) == ("http://vlm", "v", None)
    with pytest.raises(ConfigError, match="VISION_MODEL_NAME"):
        load(VISION_MODEL_ENDPOINT="http://vlm")
    with pytest.raises(ConfigError, match="VISION_MODEL_ENDPOINT"):
        load(VISION_MODEL_NAME="v")


def test_vision_model_is_independent_of_the_model():
    c = load(VISION_MODEL_ENDPOINT="http://vlm", VISION_MODEL_NAME="v")
    assert c.model is None and c.vision_model is not None


def test_vision_model_key_from_file_and_never_shown(tmp_path):
    f = tmp_path / "key"
    f.write_text("vk-987654\n")
    c = load(VISION_MODEL_ENDPOINT="http://vlm", VISION_MODEL_NAME="v", VISION_MODEL_API_KEY_FILE=str(f))
    assert c.vision_model is not None and c.vision_model.api_key is not None
    assert c.vision_model.api_key.reveal() == "vk-987654"
    assert "vk-987654" not in repr(c) and "vk-987654" not in repr(c.vision_model)
    with pytest.raises(ConfigError, match="VISION_MODEL_API_KEY_FILE"):
        load(
            VISION_MODEL_ENDPOINT="http://vlm",
            VISION_MODEL_NAME="v",
            VISION_MODEL_API_KEY_FILE=str(tmp_path / "nope"),
        )


def test_config_is_immutable():
    c = load()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.base_currency = "USD"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.db.name = "x"  # type: ignore[misc]
    assert isinstance(c.users, tuple)


def test_with_database_name_returns_a_copy():
    c = load()
    d = c.with_database("test_abc")
    assert d.db.name == "test_abc"
    assert c.db.name == "ledger"
    assert d.db.password.reveal() == "s3cret-pw"


def test_from_env_defaults_to_the_process_environment(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    assert Config.from_env().db.name == "ledger"


def test_only_config_module_reads_the_environment():
    app = Path(__file__).resolve().parent.parent / "app"
    allowed = app / "utils" / "config.py"
    offenders = []
    for p in app.rglob("*.py"):
        if p == allowed:
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Attribute) and n.attr in {"environ", "getenv", "environb"}:
                offenders.append(str(p.relative_to(app)))
    assert offenders == []


def test_expose_openapi_defaults_off():
    assert load().expose_openapi is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("TRUE", True), ("True", True), ("false", False), ("False", False), ("FALSE", False)],
)
def test_expose_openapi_reads_a_strict_boolean(raw, expected):
    assert load(EXPOSE_OPENAPI=raw).expose_openapi is expected


@pytest.mark.parametrize("raw", ["1", "0", "yes", "no", "on", "", " true", "tru"])
def test_expose_openapi_rejects_anything_else_naming_the_variable(raw):
    with pytest.raises(ConfigError) as err:
        load(EXPOSE_OPENAPI=raw)
    assert err.value.variable == "EXPOSE_OPENAPI"
    assert "EXPOSE_OPENAPI" in str(err.value)


def test_enable_test_importers_defaults_off():
    assert load().enable_test_importers is False


@pytest.mark.parametrize("raw", ["true", "TRUE", "True"])
def test_enable_test_importers_reads_a_strict_boolean(raw):
    assert load(ENABLE_TEST_IMPORTERS=raw).enable_test_importers is True
    assert load(ENABLE_TEST_IMPORTERS="false").enable_test_importers is False


@pytest.mark.parametrize("raw", ["1", "0", "yes", "no", "on", "", " true", "tru"])
def test_enable_test_importers_rejects_anything_else_naming_the_variable(raw):
    with pytest.raises(ConfigError) as err:
        load(ENABLE_TEST_IMPORTERS=raw)
    assert err.value.variable == "ENABLE_TEST_IMPORTERS"
    assert "ENABLE_TEST_IMPORTERS" in str(err.value)


def test_the_fints_product_id_is_optional_and_not_a_secret():
    assert load().fints_product_id is None
    assert load(FINTS_PRODUCT_ID=" ABC123 ").fints_product_id == "ABC123"


def test_a_blank_fints_product_id_names_the_variable():
    with pytest.raises(ConfigError) as err:
        load(FINTS_PRODUCT_ID="  ")
    assert err.value.variable == "FINTS_PRODUCT_ID"
