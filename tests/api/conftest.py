from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api import create_app
from app.startup import ensure_base_currency, reconcile_users
from app.utils.config import Config, Secret, UserConfig

PASSWORDS = {"anna": "anna-pw-1111", "ben": "ben-pw-2222", "old": "old-pw-3333"}


@pytest.fixture
def api_config(isolated_db: Config) -> Config:
    users = tuple(UserConfig(login, login.title(), Secret(pw)) for login, pw in PASSWORDS.items())
    return replace(isolated_db, users=users)


@pytest.fixture
def api_engine(isolated_engine: Engine, api_config: Config) -> Engine:
    with isolated_engine.begin() as conn:
        ensure_base_currency(conn, api_config.base_currency)
        reconcile_users(conn, api_config.users)
        conn.execute(text("UPDATE app_user SET disabled = true WHERE login = 'old'"))
    return isolated_engine


@pytest.fixture
def make_client(api_config: Config, api_engine: Engine, clock):
    clients: list[TestClient] = []

    def make(base_url: str = "http://localhost", **kwargs) -> TestClient:
        client = TestClient(create_app(api_config, api_engine), base_url=base_url, **kwargs)
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.close()


@pytest.fixture
def client(make_client) -> Iterator[TestClient]:
    yield make_client()


def login(client: TestClient, who: str = "anna", path: str = "/api/login"):
    return client.post(path, json={"login": who, "password": PASSWORDS[who]})
