"""The worker logs one INFO line per asked entry: what came of it and why, never the payload, the reply or
the key."""

from __future__ import annotations

import logging
from collections.abc import Callable

import pytest
from sqlalchemy import Engine

from app.core.settle import settle
from tests.core.model.rig import Rig
from tests.core.model.test_worker import _edit_payload, _process_head, _toll, _user_decides

MakeAccount = Callable[..., int]
SECRET = "SECRET-REPLY-TEXT"


@pytest.fixture
def acct(isolated_engine: Engine, make_account: MakeAccount) -> int:
    with isolated_engine.begin() as conn:
        return make_account(conn)


def _lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name == "ledgehog.model" and r.levelno == logging.INFO
    ]


def _process(rig: Rig, caplog: pytest.LogCaptureFixture) -> str:
    with caplog.at_level(logging.INFO, logger="ledgehog.model"):
        _process_head(rig)
    lines = [m for m in _lines(caplog) if m.startswith("model asked about entry")]
    assert len(lines) == 1
    line = lines[0]
    assert "AUCAT" not in line and SECRET not in line  # neither the payload nor the reply
    assert all(SECRET not in r.getMessage() and "AUCAT" not in r.getMessage() for r in caplog.records)
    return line


def test_a_stored_answer(rig: Rig, acct: int, caplog: pytest.LogCaptureFixture) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = cat
    rig.endpoint.rationale = SECRET
    line = _process(rig, caplog)
    assert line.startswith(f"model asked about entry {e}: stored in ")


def test_a_stored_none_answer(rig: Rig, acct: int, caplog: pytest.LogCaptureFixture) -> None:
    e, _ = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = None
    rig.endpoint.rationale = SECRET
    line = _process(rig, caplog)
    assert line.startswith(f"model asked about entry {e}: stored, no fitting category in ")


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (f"{SECRET} not json", "not_json"),
        (f'["{SECRET}"]', "not_object"),
        ('{"category_id": null}', "no_rationale"),
        ('{"category_id": null, "rationale": "  "}', "empty_rationale"),
        (f'{{"category_id": "none", "rationale": "{SECRET}"}}', "bad_id_type"),
        (f'{{"category_id": 987654, "rationale": "{SECRET}"}}', "unknown_id"),
    ],
)
def test_no_answer_says_why(
    rig: Rig, acct: int, caplog: pytest.LogCaptureFixture, raw: str, reason: str
) -> None:
    e, _ = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.raw = raw
    line = _process(rig, caplog)
    assert line.startswith(f"model asked about entry {e}: no answer ({reason}) in ")


def test_a_truncated_reply(rig: Rig, acct: int, caplog: pytest.LogCaptureFixture) -> None:
    e, _ = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.raw = f'{{"category_id": 1, "rationale": "{SECRET}'
    rig.endpoint.finish_reason = "length"
    line = _process(rig, caplog)
    assert line.startswith(f"model asked about entry {e}: no answer (truncated) in ")


def test_dropped_because_the_user_decided(rig: Rig, acct: int, caplog: pytest.LogCaptureFixture) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = cat
    rig.endpoint.during = lambda: _user_decides(rig.engine, e, cat)
    line = _process(rig, caplog)
    assert f"entry {e}: dropped (entry gone or confirmed) in " in line


def test_dropped_because_the_payload_changed(rig: Rig, acct: int, caplog: pytest.LogCaptureFixture) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = cat

    def edit() -> None:
        with rig.engine.begin() as conn:
            _edit_payload(conn, "new text")

    rig.endpoint.during = edit
    line = _process(rig, caplog)
    assert f"entry {e}: dropped (payload changed) in " in line
