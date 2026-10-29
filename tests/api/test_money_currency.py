"""An amount never travels without its currency (architecture §4.5): the importer and run routes.

The rule: every JSON object that holds an amount (`amount`, `balance`, `before`, `after` as an
integer, or any `*_minor` field) also holds a `currency` field next to it: the account's currency.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import (
    BalanceReport,
    DryRunReport,
    IncomingRow,
    ParsedFile,
    SampleRow,
    SyntheticReport,
)
from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api, error_of
from tests.plugins.importers.csv.fixtures import giro_bytes

api = h.api
make_api = h.make_api

_AMOUNT_KEYS = {"amount", "balance", "before", "after"}


def bare_amounts(node: Any, path: str = "$") -> list[str]:
    """Paths of objects that hold an amount without a currency."""
    found: list[str] = []
    if isinstance(node, dict):
        pair = {"before", "after"} <= node.keys() and all(
            node[k] is None or isinstance(node[k], int) for k in ("before", "after")
        )
        holds = pair or any(
            (k.endswith("_minor") or k in _AMOUNT_KEYS) and isinstance(v, int) and not isinstance(v, bool)
            for k, v in node.items()
        )
        if holds and "currency" not in node:
            found.append(path)
        for k, v in node.items():
            found += bare_amounts(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += bare_amounts(v, f"{path}[{i}]")
    return found


def _report() -> DryRunReport:
    return DryRunReport(
        rows_read=1,
        emitted=1,
        sample=(SampleRow(row=2, booked_on=date(2026, 8, 5), amount_minor=-100, cells=("x",)),),
        balance=BalanceReport(100, date(2026, 8, 9), "figure", 90, date(2026, 8, 10)),
        synthetic=SyntheticReport(amount_minor=5, booked_on=date(2026, 8, 7), row_count=2, sum_minor=-5),
    )


def test_the_checker_flags_a_bare_amount():
    assert bare_amounts({"a": {"amount_minor": 1}, "b": {"amount": 2, "currency": "EUR"}}) == ["$.a"]


def test_a_dry_run_and_a_real_upload_carry_the_currency(api: Api):
    inst, acct = api.world()
    dry = api.upload(inst, acct, giro_bytes(), dry_run=True)
    assert dry.status_code == 200, dry.text
    assert dry.json()["report"]["balance"]["currency"] == "EUR"
    assert all(s["currency"] == "EUR" for s in dry.json()["report"]["sample"])
    assert bare_amounts(dry.json()) == []
    real = api.upload(inst, acct, giro_bytes())
    assert real.status_code == 200, real.text
    summary = real.json()["summary"]
    assert summary["balance"]["currency"] == "EUR"
    assert summary["unexplained_difference"]["currency"] == "EUR"
    assert bare_amounts(real.json()) == []


def test_the_report_synthetic_block_carries_the_currency(make_api):
    stub = _Stub(ParsedFile((_row(),), None, None, date(2026, 8, 10), date(2026, 8, 1), {}, _report()))
    api = make_api(importers={"csv": stub})
    inst, acct = api.world()
    body = api.upload(inst, acct, b"x", dry_run=True).json()
    assert body["report"]["synthetic"]["currency"] == "EUR"
    assert bare_amounts(body) == []


def test_a_parse_failure_report_in_the_error_details_carries_the_currency(make_api):
    stub = _Stub(error=ParseFailed("nope", report=_report()))
    api = make_api(importers={"csv": stub})
    inst, acct = api.world()
    err = error_of(api.upload(inst, acct, b"x"), 422, "parse_failed")
    assert bare_amounts(err["details"]) == []
    assert err["details"]["report"]["balance"]["currency"] == "EUR"


def test_the_run_views_and_revert_carry_the_currency(api: Api):
    inst, acct = api.world()
    assert api.upload(inst, acct, giro_bytes()).status_code == 200
    runs = api.client.get("/api/importers/runs")
    assert runs.status_code == 200 and bare_amounts(runs.json()) == []
    run_id = runs.json()["runs"][0]["id"]
    assert runs.json()["runs"][0]["stats"]["balance"]["currency"] == "EUR"
    one = api.client.get(f"/api/importers/runs/{run_id}")
    assert bare_amounts(one.json()) == []
    preview = api.client.post(f"/api/importers/runs/{run_id}/revert", json={"dry_run": True})
    assert preview.status_code == 200 and preview.json()["derived_changes"]
    assert bare_amounts(preview.json()) == []
    done = api.client.post(
        f"/api/importers/runs/{run_id}/revert", json={"expected_versions": preview.json()["versions"]}
    )
    assert done.status_code == 200, done.text
    assert bare_amounts(done.json()) == []


def _row() -> IncomingRow:
    return IncomingRow(
        amount_minor=-100,
        currency="EUR",
        booked_on=date(2026, 8, 5),
        source_format="csv:stub",
        raw={"n": 1},
        purpose="p",
    )


class _Stub:
    def __init__(self, parsed: ParsedFile | None = None, error: Exception | None = None) -> None:
        self.parsed, self.error = parsed, error

    def validate_settings(self, settings: Any) -> None:
        return None

    def parse(self, data: bytes, profile: Any, **kw: Any) -> ParsedFile:
        if self.error is not None:
            raise self.error
        assert self.parsed is not None
        return self.parsed
