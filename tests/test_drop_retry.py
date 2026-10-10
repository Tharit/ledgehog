"""`drop_database` survives a background process it may not terminate.

`DROP DATABASE ... WITH (FORCE)` terminates every other session on the database. A
role without superuser may not terminate a Postgres background process (autovacuum,
say) that happens to be attached, and the statement fails with InsufficientPrivilege
until that process detaches. It is transient, so the drop retries a few times.
"""

from __future__ import annotations

import psycopg.errors
import pytest

from app.utils.config import Config
from app.utils.db import admin


class _FakeConn:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: object) -> None:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeConn:
    conn = _FakeConn([])
    monkeypatch.setattr(admin, "connect", lambda cfg: conn)
    monkeypatch.setattr(admin, "_DROP_RETRY_DELAY", 0.0)
    return conn


def _privilege() -> psycopg.errors.InsufficientPrivilege:
    return psycopg.errors.InsufficientPrivilege("permission denied to terminate process")


def test_a_transient_privilege_error_is_retried(fake: _FakeConn, admin_cfg: Config) -> None:
    fake.failures = [_privilege(), _privilege()]
    admin.drop_database(admin_cfg, "test_retry_me")
    assert fake.calls == 3


def test_a_persistent_privilege_error_is_raised_after_the_attempts(
    fake: _FakeConn, admin_cfg: Config
) -> None:
    fake.failures = [_privilege() for _ in range(admin._DROP_ATTEMPTS + 5)]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin.drop_database(admin_cfg, "test_retry_me")
    assert fake.calls == admin._DROP_ATTEMPTS


def test_other_errors_are_not_retried(fake: _FakeConn, admin_cfg: Config) -> None:
    fake.failures = [psycopg.errors.SyntaxError("boom")]
    with pytest.raises(psycopg.errors.SyntaxError):
        admin.drop_database(admin_cfg, "test_retry_me")
    assert fake.calls == 1
