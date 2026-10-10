"""The one reader of the environment (architecture §5.7).

Parses and validates everything once, names the offending variable on failure,
and exposes one immutable typed object. Secrets are `Secret` values that never
render in repr/str, and each accepts a `<NAME>_FILE` variant. Error messages
name variables but never echo values.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """A missing or invalid configuration variable; the message names it."""

    def __init__(self, variable: str, problem: str) -> None:
        super().__init__(f"{variable}: {problem}")
        self.variable = variable


class Secret:
    """A string that refuses to render itself."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: Secret


@dataclass(frozen=True, slots=True)
class UserConfig:
    login: str
    name: str
    password: Secret


@dataclass(frozen=True, slots=True)
class ModelConfig:
    endpoint: str
    name: str
    api_key: Secret | None


@dataclass(frozen=True, slots=True)
class Config:
    db: DatabaseConfig
    base_currency: str
    timezone: ZoneInfo
    locale: str
    max_rate_age_days: int
    matching_window_days: int
    document_window_days: int
    users: tuple[UserConfig, ...]
    model: ModelConfig | None

    def with_database(self, name: str) -> Config:
        """A copy pointing at another database (test and dev contexts, architecture §9)."""
        return replace(self, db=replace(self.db, name=name))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Config:
        return _Reader(os.environ if environ is None else environ).read()


_USER_VAR = re.compile(r"^USER_(\d+)_(LOGIN|NAME|PASSWORD|PASSWORD_FILE)$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class _Reader:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = env

    def text(self, var: str, default: str | None = None) -> str:
        value = self.env.get(var)
        if value is None:
            if default is None:
                raise ConfigError(var, "required but not set")
            return default
        if value.strip() == "":
            raise ConfigError(var, "must not be empty")
        return value

    def integer(self, var: str, default: int, lo: int, hi: int | None = None) -> int:
        raw = self.env.get(var)
        if raw is None:
            return default
        try:
            n = int(raw)
        except ValueError:
            raise ConfigError(var, "must be an integer") from None
        if n < lo or (hi is not None and n > hi):
            bound = f"between {lo} and {hi}" if hi is not None else f"at least {lo}"
            raise ConfigError(var, f"must be {bound}")
        return n

    def secret(self, var: str, *, required: bool = True) -> Secret | None:
        plain, file_var = self.env.get(var), f"{var}_FILE"
        path = self.env.get(file_var)
        if plain is not None and path is not None:
            raise ConfigError(var, f"set together with {file_var}; use only one")
        if path is not None:
            try:
                with open(path, encoding="utf-8") as fh:
                    value = fh.read().rstrip("\r\n")
            except OSError:
                raise ConfigError(file_var, "file is not readable") from None
            if value == "":
                raise ConfigError(file_var, "file is empty")
            return Secret(value)
        if plain is not None:
            if plain == "":
                raise ConfigError(var, "must not be empty")
            return Secret(plain)
        if required:
            raise ConfigError(var, f"required but not set (or {file_var})")
        return None

    def users(self) -> tuple[UserConfig, ...]:
        indexes = sorted(
            {int(m.group(1)) for k in self.env if (m := _USER_VAR.match(k))}
        )
        if indexes != list(range(1, len(indexes) + 1)):
            expected = next(i for i in range(1, len(indexes) + 2) if i not in indexes)
            raise ConfigError(f"USER_{expected}", "user groups must be numbered from 1 without gaps")
        users: list[UserConfig] = []
        seen: set[str] = set()
        for n in indexes:
            login = self.text(f"USER_{n}_LOGIN")
            name = self.text(f"USER_{n}_NAME")
            password = self.secret(f"USER_{n}_PASSWORD")
            assert password is not None
            if login in seen:
                raise ConfigError(f"USER_{n}_LOGIN", "duplicate login")
            seen.add(login)
            users.append(UserConfig(login, name, password))
        return tuple(users)

    def model(self) -> ModelConfig | None:
        endpoint, name = self.env.get("MODEL_ENDPOINT"), self.env.get("MODEL_NAME")
        if endpoint is None and name is None:
            return None
        return ModelConfig(
            self.text("MODEL_ENDPOINT"),
            self.text("MODEL_NAME"),
            self.secret("MODEL_API_KEY", required=False),
        )

    def read(self) -> Config:
        password = self.secret("POSTGRES_PASSWORD")
        assert password is not None
        db = DatabaseConfig(
            host=self.text("POSTGRES_HOST", "localhost"),
            port=self.integer("POSTGRES_PORT", 5432, 1, 65535),
            name=self.text("POSTGRES_DB"),
            user=self.text("POSTGRES_USER"),
            password=password,
        )
        base = self.text("BASE_CURRENCY")
        if not _CURRENCY.match(base):
            raise ConfigError("BASE_CURRENCY", "must be a three-letter upper-case ISO code")
        tz_name = self.text("TIMEZONE")
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ConfigError("TIMEZONE", "unknown time zone") from None
        return Config(
            db=db,
            base_currency=base,
            timezone=tz,
            locale=self.text("LOCALE", "en"),
            max_rate_age_days=self.integer("MAX_RATE_AGE_DAYS", 7, 0),
            matching_window_days=self.integer("MATCHING_WINDOW_DAYS", 7, 0),
            document_window_days=self.integer("DOCUMENT_WINDOW_DAYS", 7, 0),
            users=self.users(),
            model=self.model(),
        )
