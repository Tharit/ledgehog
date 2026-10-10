from __future__ import annotations

from dataclasses import replace

import pytest

from app.utils.config import Config, Secret, UserConfig


def user(login: str, name: str | None = None, password: str | None = None) -> UserConfig:
    return UserConfig(login, name or login.title(), Secret(password or f"pw-{login}-0000"))


@pytest.fixture
def make_config(isolated_db: Config):
    """A Config for the per-test database, with the given users."""

    def make(*users: UserConfig, base_currency: str = "EUR") -> Config:
        return replace(isolated_db, users=tuple(users), base_currency=base_currency)

    return make
