"""scripts/dump_openapi.py: the schema to a file, with no database and no server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import dump_openapi

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_database(monkeypatch):
    # an address nothing listens on: a connection attempt would fail (or hang) the test
    for k in list(os.environ):
        if k.startswith(("POSTGRES_", "USER_", "MODEL_")) or k in ("BASE_CURRENCY", "TIMEZONE"):
            monkeypatch.delenv(k)
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "1")


def test_writes_the_deterministic_schema(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert dump_openapi.main(["--out", str(a)]) == 0
    assert dump_openapi.main(["--out", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()
    text = a.read_text()
    assert text.endswith("}\n")
    doc = json.loads(text)
    assert text == json.dumps(doc, indent=2, sort_keys=True) + "\n"
    assert "/api/importers/instances/{instance_id}/upload" in doc["paths"]
    assert "unused" not in capsys.readouterr().out  # no secret is printed


def test_two_processes_produce_identical_bytes(tmp_path):
    outs = [tmp_path / "1.json", tmp_path / "2.json"]
    for out in outs:
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "dump_openapi.py"), "--out", str(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        assert r.returncode == 0, r.stderr
    assert outs[0].read_bytes() == outs[1].read_bytes()


def test_refuses_a_missing_parent_directory_without_creating_it(tmp_path, capsys):
    out = tmp_path / "frontend" / "openapi.json"
    assert dump_openapi.main(["--out", str(out)]) == 2
    assert "does not exist" in capsys.readouterr().err
    assert not out.parent.exists()


def test_default_target_is_frontend_openapi_json():
    assert dump_openapi.DEFAULT_OUT == ROOT / "frontend" / "openapi.json"


def test_check_passes_when_equal_and_fails_with_a_diff_when_not(tmp_path, capsys):
    out = tmp_path / "openapi.json"
    assert dump_openapi.main(["--out", str(out)]) == 0
    assert dump_openapi.main(["--out", str(out), "--check"]) == 0
    stored = out.read_text()
    out.write_text(stored.replace('"Ledgehog"', '"Stale"'))
    capsys.readouterr()
    assert dump_openapi.main(["--out", str(out), "--check"]) == 1
    err = capsys.readouterr().err
    assert "Stale" in err and "Ledgehog" in err and err.startswith("---")
    assert out.read_text() != stored  # --check never writes


def test_check_fails_when_the_file_is_missing(tmp_path, capsys):
    assert dump_openapi.main(["--out", str(tmp_path / "none.json"), "--check"]) == 1
    assert "missing" in capsys.readouterr().err


def test_runs_with_no_postgres_reachable_and_opens_no_connection(tmp_path, monkeypatch):
    import psycopg

    def refuse(*a, **k):
        raise AssertionError("a database connection was attempted")

    monkeypatch.setattr(psycopg.Connection, "connect", refuse)
    assert dump_openapi.main(["--out", str(tmp_path / "o.json")]) == 0
