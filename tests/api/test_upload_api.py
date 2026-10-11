"""Uploading a file to a linked account over HTTP (architecture §4.1, §4.4; csv.md §7)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest

from app.core.accounts import close_account
from app.core.importers.instances import create_instance
from app.core.ingest import run as run_module
from app.core.plugins.errors import SourceUnavailable
from app.core.plugins.importer import DryRunReport, IncomingRow, ParsedFile
from app.core.settle.settle import SettleResult
from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api, error_of
from tests.plugins.importers.csv.fixtures import PRIVATE, card_a_bytes, giro_bytes

api = h.api  # fixtures shared by the importer API tests
make_api = h.make_api

BASE = "/api/importers/instances"
MAX_FILE = 10 * 1024 * 1024


class Stub:
    """A file importer that returns what it was given, or raises."""

    def __init__(self, parsed: ParsedFile | None = None, error: Exception | None = None) -> None:
        self.parsed, self.error = parsed, error
        self.calls: list[dict[str, Any]] = []

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        return None

    def parse(self, data: bytes, profile: Mapping[str, Any], **kw: Any) -> ParsedFile:
        self.calls.append(kw)
        if self.error is not None:
            raise self.error
        assert self.parsed is not None
        return self.parsed


def _parsed(*, balance: int | None = None, balance_on: date | None = None) -> ParsedFile:
    row = IncomingRow(
        amount_minor=-100,
        currency="EUR",
        booked_on=date(2026, 8, 5),
        source_format="csv:stub",
        raw={"n": 1},
        purpose="p",
    )
    return ParsedFile(
        rows=(row,),
        reported_balance=balance,
        balance_on=balance_on,
        covered_through=date(2026, 8, 10),
        data_start=date(2026, 8, 1),
        importer_stats={"filtered": 0, "synthetic_skipped": 0},
        report=DryRunReport(rows_read=1, emitted=1),
    )


def _stub_world(make_api, stub: Stub) -> tuple[Api, int, int]:
    api = make_api(importers={"csv": stub})
    inst, acct = api.world("giro_with_preamble")
    return api, inst, acct


# ---- dry run -------------------------------------------------------------------------------


def test_a_dry_run_answers_200_with_the_summary_and_the_report_and_writes_nothing(api: Api):
    inst, acct = api.world()
    before = api.counts()
    r = api.upload(inst, acct, giro_bytes(), dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"run_id", "dry_run", "summary", "report", "settle", "failure", "importer_stats"}
    assert body["dry_run"] is True and body["run_id"] is None
    assert body["settle"] is None and body["failure"] is None
    assert body["summary"]["inserted"] == 3
    report = body["report"]
    assert report["rows_read"] >= 3 and report["emitted"] == 3
    assert report["encoding"] and report["delimiter"] == ";"
    assert report["balance"] == {
        "amount_minor": 124456,
        "dated_on": "2026-08-19",
        "source": report["balance"]["source"],
        "figure_minor": 123456,
        "figure_on": "2026-08-20",
        "rolled_back_by_minor": report["balance"]["rolled_back_by_minor"],
        "rolled_back_rows": report["balance"]["rolled_back_rows"],
    }
    assert {"count", "examples"} <= set(report["skipped"])
    assert all({"row", "booked_on", "amount_minor", "cells"} <= set(s) for s in report["sample"])
    assert report["sample"][0]["booked_on"].startswith("2026-08-")
    assert api.counts() == before
    assert PRIVATE not in r.text


def test_the_household_today_is_handed_to_the_importer(make_api):
    stub = Stub(_parsed())
    api, inst, acct = _stub_world(make_api, stub)
    assert api.upload(inst, acct, b"x", dry_run=True).status_code == 200
    assert stub.calls[0]["today"] == date(2026, 8, 21) and stub.calls[0]["account_currency"] == "EUR"


def test_a_dry_run_failure_comes_back_inside_a_200_and_writes_nothing(api: Api):
    inst, acct = api.world(currency="USD")
    before = api.counts()
    r = api.upload(inst, acct, giro_bytes(), dry_run=True)
    assert r.status_code == 200
    failure = r.json()["failure"]
    assert (failure["kind"], failure["rule"]) == ("contract_violation", "currency_mismatch")
    assert r.json()["report"]["currency_mismatch"]["count"] > 0 and r.json()["summary"] == {}
    assert api.counts() == before
    assert PRIVATE not in r.text


def test_a_dry_run_without_a_header_row_is_a_parse_failure_inside_a_200(api: Api):
    inst, acct = api.world()
    before = api.counts()
    r = api.upload(inst, acct, b"nothing;useful\nhere;at all\n", dry_run=True)
    assert r.status_code == 200
    assert r.json()["failure"]["kind"] == "parse_failed" and r.json()["failure"]["rule"] is None
    assert api.counts() == before


def test_a_dry_run_that_breaks_the_balance_date_rule_is_a_failure_inside_a_200(make_api):
    bad = _parsed(balance=500, balance_on=date(2026, 8, 12))  # after the coverage: I36
    api, inst, acct = _stub_world(make_api, Stub(bad))
    before = api.counts()
    r = api.upload(inst, acct, b"x", dry_run=True)
    assert r.status_code == 200
    assert r.json()["failure"]["rule"] == "balance_after_coverage"
    assert api.counts() == before
    real = api.upload(inst, acct, b"x")
    err = error_of(real, 422, "contract_violation")
    assert err["details"] == {"rule": "balance_after_coverage"}


# ---- real run ------------------------------------------------------------------------------


def test_a_real_run_answers_200_with_the_run_summary_and_report(api: Api):
    inst, acct = api.world()
    r = api.upload(inst, acct, giro_bytes(), dry_run=False)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False and body["failure"] is None
    assert body["summary"]["inserted"] == 3 and body["summary"]["skipped_by_identity"] == 0
    assert body["settle"] == {"touched_entry_ids": body["settle"]["touched_entry_ids"], "error": None}
    assert api.one("SELECT status FROM import_run WHERE id = :i", i=body["run_id"]).status == "ok"
    assert body["report"]["emitted"] == 3
    assert PRIVATE not in r.text
    api.assert_checks_clean()


def test_the_dry_flag_defaults_to_a_real_run(api: Api):
    inst, acct = api.world()
    assert api.upload(inst, acct, giro_bytes()).json()["dry_run"] is False
    assert api.counts()["import_run"] == 1


def test_a_reupload_skips_everything(api: Api):
    inst, acct = api.world("card_footer_balance", kind="card")
    first = api.upload(inst, acct, card_a_bytes()).json()
    again = api.upload(inst, acct, card_a_bytes()).json()
    assert again["summary"]["inserted"] == 0
    assert again["summary"]["skipped_by_identity"] == first["summary"]["inserted"] > 0
    assert again["run_id"] != first["run_id"]


def test_one_settle_per_real_write(api: Api, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        run_module, "settle", lambda engine: calls.append(1) or SettleResult(touched_entry_ids=(3,))
    )
    inst, acct = api.world()
    r = api.upload(inst, acct, giro_bytes())
    assert calls == [1] and r.json()["settle"] == {"touched_entry_ids": [3], "error": None}
    api.upload(inst, acct, giro_bytes(), dry_run=True)
    assert calls == [1]  # a dry run never settles


def test_a_settle_error_is_in_the_body_with_200(api: Api, monkeypatch):
    monkeypatch.setattr(run_module, "settle", lambda engine: SettleResult(error="settle blew up"))
    inst, acct = api.world()
    r = api.upload(inst, acct, giro_bytes())
    assert r.status_code == 200 and r.json()["settle"]["error"] == "settle blew up"
    assert r.json()["summary"]["inserted"] == 3


# ---- failures of a real run ----------------------------------------------------------------


def test_a_parse_failure_is_a_422_that_is_not_retryable_and_leaks_no_file_content(api: Api):
    inst, acct = api.world()
    data = f"{PRIVATE};nothing;useful\nmore;lines\n".encode()
    r = api.upload(inst, acct, data)
    err = error_of(r, 422, "parse_failed")
    assert err["details"]["retryable"] is False
    assert "rows_read" in err["details"]["report"]
    assert PRIVATE not in r.text
    assert api.one("SELECT status FROM import_run").status == "failed"
    assert api.counts()["source_transaction"] == 0


def test_a_failure_the_report_carries_is_not_echoed_beyond_the_report(api: Api):
    inst, acct = api.world(currency="USD")
    r = api.upload(inst, acct, giro_bytes())
    err = error_of(r, 422, "contract_violation")
    assert err["details"] == {"rule": "currency_mismatch"}
    assert PRIVATE not in r.text
    assert api.one("SELECT status FROM import_run").status == "failed"


def test_a_retryable_importer_error_says_so(make_api):
    api, inst, acct = _stub_world(make_api, Stub(error=SourceUnavailable("bank down")))
    err = error_of(api.upload(inst, acct, b"x"), 502, "source_unavailable")
    assert err["details"] == {"retryable": True} and err["message"] == "bank down"
    dry = api.upload(inst, acct, b"x", dry_run=True)
    assert dry.status_code == 200 and dry.json()["failure"]["kind"] == "importer_error"


# ---- refusals ------------------------------------------------------------------------------


def test_an_unregistered_importer_is_a_422_and_nothing_is_written(make_api):
    api = make_api(importers={})
    inst = create_instance(
        api.engine, importer="csv", label="x", settings={}, emits=["transactions"], access="shared"
    )
    acct = api.account()
    api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct})
    before = api.counts()
    error_of(api.upload(inst, acct, b"x"), 422, "importer_not_available")
    error_of(api.upload(inst, acct, b"x", dry_run=True), 422, "importer_not_available")
    assert api.counts() == before


@pytest.mark.parametrize("dry_run", [False, True])
def test_the_refusals_are_envelope_errors_that_write_nothing(api: Api, dry_run: bool):
    inst, acct = api.world()
    before = api.counts()
    other = api.account("Other")
    closed = api.account("Closed")
    api.link(inst, closed)
    close_account(api.engine, closed, date(2026, 8, 1))
    docs = create_instance(
        api.engine, importer="csv", label="docs", settings={}, emits=["documents"], access="shared"
    )
    before = api.counts()
    up = lambda i, a: api.upload(i, a, giro_bytes(), dry_run=dry_run)  # noqa: E731
    error_of(up(999, acct), 404, "not_found")
    error_of(up(inst, 999), 404, "not_found")
    error_of(up(inst, other), 409, "account_not_linked")
    error_of(up(inst, closed), 409, "account_closed")
    error_of(up(docs, acct), 409, "not_a_file_source")
    api.client.put(f"{BASE}/{inst}", json={"disabled": True})
    error_of(up(inst, acct), 409, "instance_disabled")
    assert api.counts() == before


def test_deleting_an_instance_with_runs_is_refused_and_suggests_disabling(api: Api):
    inst, acct = api.world()
    assert api.upload(inst, acct, giro_bytes()).status_code == 200
    err = error_of(api.client.delete(f"{BASE}/{inst}"), 409, "instance_has_runs")
    assert "disable" in err["message"]
    assert len(api.client.get(BASE).json()) == 1


# ---- the file ------------------------------------------------------------------------------


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_file_over_10_mib_is_refused_before_it_is_parsed(api: Api, dry_run: bool):
    inst, acct = api.world()
    before = api.counts()
    r = api.upload(inst, acct, b"x" * (MAX_FILE + 1), dry_run=dry_run)
    err = error_of(r, 413, "file_too_large")
    assert str(MAX_FILE) in err["message"] or "10" in err["message"]
    assert api.importer.parse_calls == 0 and api.counts() == before


def test_a_file_of_exactly_10_mib_is_parsed(api: Api):
    inst, acct = api.world()
    r = api.upload(inst, acct, b"x" * MAX_FILE, dry_run=True)
    assert r.status_code == 200 and r.json()["failure"]["kind"] == "parse_failed"
    assert api.importer.parse_calls == 1


def test_the_upload_form_is_strict(api: Api):
    inst, acct = api.world()
    url = f"{BASE}/{inst}/upload"
    c = api.client
    file = {"file": ("a.csv", b"x", "text/csv")}
    error_of(c.post(url, files=file), 422, "validation_error")  # no account_id
    error_of(c.post(url, files=file, data={"account_id": "abc"}), 422, "validation_error")
    error_of(
        c.post(url, files=file, data={"account_id": str(acct), "dry_run": "maybe"}), 422, "validation_error"
    )
    error_of(c.post(url, files=file, data={"account_id": str(acct), "extra": "1"}), 422, "validation_error")
    error_of(
        c.post(url, data={"account_id": str(acct)}, files={"other": ("a", b"x")}), 422, "validation_error"
    )
    error_of(c.post(url, json={"account_id": acct}), 422, "validation_error")  # not multipart
    assert api.importer.parse_calls == 0


def test_the_file_bytes_reach_the_importer_exactly(make_api):
    stub = Stub(_parsed())
    api, inst, acct = _stub_world(make_api, stub)
    payload = b"\xef\xbb\xbfa;b\r\n\xff\x00 --not-a-boundary\r\nlast line without newline"
    seen: list[bytes] = []
    stub.parse = lambda data, profile, **kw: seen.append(data) or stub.parsed  # type: ignore[method-assign,assignment]
    assert api.upload(inst, acct, payload, dry_run=True).status_code == 200
    assert seen == [payload]
