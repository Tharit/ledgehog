"""Shared builders for the importer API tests (instances, upload, runs). All data is synthetic.

The fixtures are imported into each test module (`from tests.api.importers_helpers import api`)."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api import create_app
from app.core.accounts import create_account
from app.core.plugins.importer import FileImporter, ParsedFile
from app.plugins.importers.csv import CsvImporter, load_presets
from app.utils.config import Config
from tests.api.conftest import login
from tests.conftest import CLOCK_START

# the giro and card fixtures are dated August 2026: the household "today" is a few days later
API_TODAY = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
TABLES = ("import_run", "source_transaction", "ledger_entry", "balance_record", "account_source")


class SpyCsv(CsvImporter):
    """The real CSV importer that records its calls (and can be told to fail)."""

    def __init__(self) -> None:
        self.parse_calls = 0
        self.validate_calls = 0

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        self.validate_calls += 1
        super().validate_settings(settings)

    def parse(self, data: bytes, profile: Mapping[str, Any], **kw: Any) -> ParsedFile:
        self.parse_calls += 1
        return super().parse(data, profile, **kw)


@dataclass
class Api:
    client: TestClient
    engine: Engine
    importer: SpyCsv
    config: Config
    _made: list[int] = field(default_factory=list)

    # ---- seeding (straight into the core: the endpoints under test are not the setup) ----------

    def account(self, name: str = "Giro", *, kind: str = "checking", currency: str = "EUR") -> int:
        return create_account(self.engine, name=name, kind=kind, currency=currency)

    def instance(
        self, preset: str | Mapping[str, Any] = "consorsbank_giro", *, label: str = "Giro CSV"
    ) -> int:
        settings = load_presets()[preset] if isinstance(preset, str) else dict(preset)
        r = self.client.post(
            "/api/importers/instances", json={"importer": "csv", "label": label, "settings": settings}
        )
        assert r.status_code == 201, r.text
        return int(r.json()["id"])

    def link(self, instance: int, account: int, **body: Any) -> dict[str, Any]:
        r = self.client.post(
            f"/api/importers/instances/{instance}/links", json={"account_id": account, **body}
        )
        assert r.status_code == 200, r.text
        return r.json()

    def world(self, preset: str = "consorsbank_giro", **account: Any) -> tuple[int, int]:
        """(instance id, account id) with the account linked."""
        acct = self.account(**account)
        inst = self.instance(preset)
        self.link(inst, acct)
        return inst, acct

    def upload(
        self,
        instance: int,
        account: int,
        data: bytes,
        *,
        dry_run: bool | None = None,
        filename: str = "export.csv",
        client: TestClient | None = None,
    ):
        form: dict[str, str] = {"account_id": str(account)}
        if dry_run is not None:
            form["dry_run"] = "true" if dry_run else "false"
        return (client or self.client).post(
            f"/api/importers/instances/{instance}/upload",
            files={"file": (filename, data, "text/csv")},
            data=form,
        )

    # ---- inspection --------------------------------------------------------------------------

    def one(self, sql: str, **params: Any) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).one()

    def counts(self) -> dict[str, int]:
        return {t: int(self.one(f"SELECT count(*) FROM {t}")[0]) for t in TABLES}  # noqa: S608

    def assert_checks_clean(self) -> None:
        with self.engine.connect() as conn:
            views = [
                r[0]
                for r in conn.execute(
                    text("SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_check_%'")
                )
            ]
            assert views, "no integrity views found"
            for v in views:
                bad = conn.execute(text(f"SELECT * FROM {v}")).all()  # noqa: S608
                assert not bad, f"{v} reports {bad}"


def error_of(response, status: int, code: str) -> dict[str, Any]:
    """Assert the envelope's status and code; returns the error object."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == code, body
    return body["error"]


@pytest.fixture
def make_api(api_config: Config, api_engine: Engine, clock) -> Iterator[Callable[..., Api]]:
    clients: list[TestClient] = []

    def make(importers: Mapping[str, FileImporter] | None = None, *, signed_in: bool = True) -> Api:
        spy = SpyCsv()
        app = create_app(api_config, api_engine, importers={"csv": spy} if importers is None else importers)
        client = TestClient(app, base_url="http://localhost")  # the cookie is Secure elsewhere
        clients.append(client)
        if signed_in:
            assert login(client).status_code == 200
        return Api(client, api_engine, spy, api_config)

    clock.advance(API_TODAY - CLOCK_START)
    yield make
    for c in clients:
        c.close()


@pytest.fixture
def api(make_api: Callable[..., Api]) -> Api:
    return make_api()
