"""A database error never leaks statement content into a run's error text, the API or the log."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy.exc import DataError

from app.core.domain.errors import ContractViolation
from app.core.ingest import run as run_module
from app.core.ingest.run import run_error_text
from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api
from tests.plugins.importers.csv.fixtures import giro_bytes

api = h.api
make_api = h.make_api

MARKER = "PRIVATE-MARKER-4711"


def _leaky(*args, **kwargs):
    raise DataError(
        "INSERT INTO source_transaction ...",
        {"purpose": MARKER},
        Exception(f"DETAIL: Key (purpose)=({MARKER}) is bad"),
    )


def test_a_database_error_stores_a_fixed_message_and_leaks_nothing(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.DEBUG)
    inst, acct = api.world()
    monkeypatch.setattr(run_module, "insert_entries", _leaky)
    with pytest.raises(DataError):
        api.upload(inst, acct, giro_bytes())
    runs = api.client.get("/api/importers/runs")
    assert runs.status_code == 200
    (run,) = runs.json()
    assert run["status"] == "failed"
    assert run["error_text"].startswith("DataError")
    assert MARKER not in runs.text
    assert MARKER not in api.client.get(f"/api/importers/runs/{run['id']}").text
    stored = api.one("SELECT error_text FROM import_run")[0]
    assert MARKER not in stored and "Key (" not in stored
    assert MARKER not in caplog.text and MARKER not in "".join(r.getMessage() for r in caplog.records)


def test_a_failing_fail_run_logs_the_type_not_the_message(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.DEBUG)
    inst, acct = api.world()
    monkeypatch.setattr(run_module, "insert_entries", _leaky)
    monkeypatch.setattr(run_module, "fail_run", _leaky)
    with pytest.raises(DataError):
        api.upload(inst, acct, giro_bytes())
    assert MARKER not in caplog.text
    assert "DataError" in caplog.text


def test_domain_errors_keep_their_message():
    assert run_error_text(ContractViolation("zero_amount", "row 3 has a zero amount")).endswith(
        "row 3 has a zero amount"
    )
    assert run_error_text(RuntimeError("secret")) == "RuntimeError: unexpected error"
