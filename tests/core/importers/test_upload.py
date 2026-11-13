"""Upload orchestration (architecture §4.1, §5.2, §5.5; csv.md §7): real runs and dry runs
through the CSV plugin and its synthetic fixtures, with a stub importer where a file cannot
express the case."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

from app.core.accounts import AccountMissing, close_account
from app.core.domain.errors import ContractViolation
from app.core.importers.instances import InstanceDisabled, InstanceMissing, link_account, update_instance
from app.core.importers.runs import get_run, list_runs
from app.core.importers.upload import (
    AccountClosed,
    AccountNotLinked,
    NotAFileSource,
    UploadResult,
    upload,
)
from app.core.ingest import run as run_module
from app.core.ingest.revert import revert_run
from app.core.plugins.errors import InvalidProfile, ParseFailed, SourceUnavailable
from app.core.plugins.importer import (
    DryRunReport,
    FileImporter,
    IncomingRow,
    ParsedFile,
)
from app.core.settle.settle import SettleResult
from app.plugins.importers.csv import CsvImporter, load_presets
from app.utils.db.locks import lock_accounts, lock_settle_exclusive
from tests import lockwatch
from tests.core.importers.conftest import Db, make_acct, make_instance
from tests.core.importers.conftest import db as db  # noqa: F401  (fixture)
from tests.plugins.importers.csv.fixtures import card_a_bytes, card_b_bytes, giro_bytes

TABLES = ("import_run", "source_transaction", "ledger_entry", "balance_record")


@dataclass(frozen=True)
class Preset:
    name: str
    data: Callable[[], bytes]
    kind: str
    today: date
    rows: int  # source rows a real run writes (the card's synthetic payment included)
    balance: tuple[int, date] | None
    covered: tuple[date, date]
    derived: int  # derived entries (the opening that makes the sum meet the record)


PRESETS = [
    Preset(
        "consorsbank_giro",
        giro_bytes,
        "checking",
        date(2030, 1, 1),
        3,
        (124456, date(2026, 8, 19)),
        (date(2026, 8, 18), date(2026, 8, 20)),
        1,
    ),
    Preset(
        "deutschebank_card",
        card_a_bytes,
        "card",
        date(2026, 8, 10),
        4,
        (-5110, date(2026, 8, 3)),
        (date(2026, 7, 30), date(2026, 8, 3)),
        0,  # the synthetic payment brings the card back to zero: the opening is zero, so none
    ),
    Preset(
        "amex_card",
        card_b_bytes,
        "card",
        date(2026, 8, 10),
        3,
        None,
        (date(2026, 8, 5), date(2026, 8, 7)),
        0,
    ),
]
BY_NAME = {p.name: p for p in PRESETS}
IDS = [p.name for p in PRESETS]


@dataclass
class World:
    db: Db
    instance: int
    account: int

    def up(
        self, data: bytes, *, importer: FileImporter | None = None, today: date, **kw: Any
    ) -> UploadResult:
        return upload(
            self.db.engine,
            instance_id=self.instance,
            account_id=self.account,
            data=data,
            importer=importer or CsvImporter(),
            user_id=kw.pop("user_id", None),
            today=today,
            **kw,
        )

    def counts(self) -> dict[str, int]:
        return {t: int(self.db.one(f"SELECT count(*) FROM {t}")[0]) for t in TABLES}  # noqa: S608

    def derived(self) -> list[tuple[str, date, int]]:
        return [
            (r.type, r.booked_on, r.amount)
            for r in self.db.q(
                "SELECT type, booked_on, amount FROM ledger_entry WHERE balance_record_id IS NOT NULL"
                " ORDER BY booked_on, id"
            )
        ]


def world(
    db: Db,
    preset: str | Mapping[str, Any] = "consorsbank_giro",
    *,
    kind: str = "checking",
    currency: str = "EUR",
) -> World:
    settings = load_presets()[preset] if isinstance(preset, str) else dict(preset)
    instance = make_instance(db, settings=settings)
    account = make_acct(db, kind=kind, currency=currency)
    link_account(db.engine, instance, account, f"acct-{account}")
    return World(db, instance, account)


def preset_world(db: Db, p: Preset) -> World:
    return world(db, p.name, kind=p.kind)


# ---- refusals ----------------------------------------------------------------------------


def _refusal(db: Db, how: str) -> tuple[World, type[Exception]]:
    w = world(db)
    if how == "disabled":
        update_instance(db.engine, w.instance, disabled=True)
        return w, InstanceDisabled
    if how == "unknown_instance":
        return World(db, 999_999, w.account), InstanceMissing
    if how == "unknown_account":
        return World(db, w.instance, 999_999), AccountMissing
    if how == "closed":
        close_account(db.engine, w.account, date(2026, 8, 1))
        return w, AccountClosed
    if how == "not_linked":
        return World(db, w.instance, make_acct(db, "Other")), AccountNotLinked
    if how == "not_file_source":
        doc = make_instance(db, label="docs", emits=["documents"])
        return World(db, doc, w.account), NotAFileSource
    raise AssertionError(how)


@pytest.mark.parametrize(
    "how", ["disabled", "unknown_instance", "unknown_account", "closed", "not_linked", "not_file_source"]
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_refusals_write_nothing(db: Db, how: str, dry_run: bool) -> None:
    w, error = _refusal(db, how)
    before = w.counts()
    with pytest.raises(error):
        w.up(giro_bytes(), today=date(2030, 1, 1), dry_run=dry_run)
    assert w.counts() == before


# ---- real runs, the three presets --------------------------------------------------------


@pytest.mark.parametrize("p", PRESETS, ids=IDS)
def test_real_upload_end_to_end(db: Db, p: Preset) -> None:
    w = preset_world(db, p)
    result = w.up(p.data(), today=p.today, user_id=None)
    assert result.run_id is not None and result.dry_run is False and result.failure is None
    run = db.one("SELECT * FROM import_run WHERE id = :i", i=result.run_id)
    assert run.status == "ok" and run.importer == "csv" and run.importer_instance_id == w.instance
    assert run.account_id == w.account
    assert (run.covered_from, run.covered_through) == p.covered
    assert int(db.one("SELECT count(*) FROM source_transaction")[0]) == p.rows
    assert (
        int(db.one("SELECT count(*) FROM ledger_entry WHERE source_transaction_id IS NOT NULL")[0]) == p.rows
    )
    assert result.summary["inserted"] == p.rows and result.summary["skipped_by_identity"] == 0
    assert result.summary["importer"] == dict(run.stats["importer"])
    assert set(run.stats["importer"]) == {"filtered", "synthetic_skipped"}
    assert result.settle is not None and result.settle.error is None
    assert result.report.rows_read > 0 and result.report.failure is None
    records = db.q("SELECT balance, balance_on, import_run_id FROM balance_record")
    if p.balance is None:
        assert records == [] and "balance" not in result.summary and w.derived() == []
    else:
        reported = [(r.balance, r.balance_on, r.import_run_id is not None) for r in records]
        assert reported == [(*p.balance, True)]
        assert result.summary["balance"] == {"balance_on": p.balance[1].isoformat(), "balance": p.balance[0]}
        assert len(w.derived()) == p.derived
    db.assert_checks_clean()


def test_giro_stats_and_started_by(db: Db) -> None:
    db.run("INSERT INTO app_user (login, pw_hash, display_name) VALUES ('anna', 'x', 'Anna')")
    uid = int(db.one("SELECT id FROM app_user")[0])
    p = BY_NAME["consorsbank_giro"]
    w = preset_world(db, p)
    result = w.up(p.data(), today=p.today, user_id=uid)
    assert result.summary["importer"] == {"filtered": 1, "synthetic_skipped": 0}
    view = get_run(db_conn(db), result.run_id)  # type: ignore[arg-type]
    assert view is not None and view.started_by == uid


def db_conn(db: Db) -> Any:
    return db.engine.connect()


def test_the_card_payment_is_a_synthetic_row(db: Db) -> None:
    p = BY_NAME["deutschebank_card"]
    w = preset_world(db, p)
    w.up(p.data(), today=p.today)
    rows = db.q("SELECT amount, source_format FROM source_transaction WHERE source_format = 'csv:synthetic'")
    assert [(r.amount, r.source_format) for r in rows] == [(5110, "csv:synthetic")]


# ---- re-upload ---------------------------------------------------------------------------


@pytest.mark.parametrize("p", PRESETS, ids=IDS)
def test_reupload_of_the_same_file_adds_nothing(db: Db, p: Preset) -> None:
    w = preset_world(db, p)
    first = w.up(p.data(), today=p.today)
    before = w.counts()
    derived = w.derived()
    second = w.up(p.data(), today=p.today)
    after = w.counts()
    assert second.summary["inserted"] == 0 and second.summary["skipped_by_identity"] == p.rows
    assert second.summary["inserted_as_duplicates"] == []
    assert after["source_transaction"] == before["source_transaction"]
    assert after["ledger_entry"] == before["ledger_entry"]
    assert after["import_run"] == before["import_run"] + 1
    assert w.derived() == derived  # the balance record changes nothing it already explained
    expected_records = before["balance_record"] + (0 if p.balance is None else 1)
    assert after["balance_record"] == expected_records
    assert second.run_id != first.run_id
    db.assert_checks_clean()


def test_a_changed_purpose_pairs_as_a_duplicate_by_amount(db: Db) -> None:
    p = BY_NAME["consorsbank_giro"]
    w = preset_world(db, p)
    w.up(p.data(), today=p.today)
    changed = p.data().replace(b"Abschlag", b"Abschlag Neu")
    assert changed != p.data()
    second = w.up(changed, today=p.today)
    assert second.summary["inserted"] == 0 and second.summary["skipped_by_identity"] == 2
    assert len(second.summary["inserted_as_duplicates"]) == 1
    assert int(db.one("SELECT count(*) FROM source_transaction WHERE duplicate_of IS NOT NULL")[0]) == 1
    assert int(db.one("SELECT count(*) FROM ledger_entry WHERE source_transaction_id IS NOT NULL")[0]) == 3
    db.assert_checks_clean()


# ---- failures of a real run --------------------------------------------------------------


def _only_failed_run(w: World) -> Any:
    assert w.counts() == {"import_run": 1, "source_transaction": 0, "ledger_entry": 0, "balance_record": 0}
    return w.db.one("SELECT * FROM import_run")


def test_a_parse_error_fails_the_run_and_is_reraised(db: Db) -> None:
    w = world(db)
    with pytest.raises(ParseFailed):
        w.up(b"no header in here\n1;2;3\n", today=date(2030, 1, 1))
    run = _only_failed_run(w)
    assert run.status == "failed" and run.error_text and run.finished_at is not None
    assert run.error_text.startswith("ParseFailed")
    assert run.retryable is False
    assert run.covered_through is None and run.importer_instance_id == w.instance


def test_a_missing_balance_label_fails_the_run(db: Db) -> None:
    settings = load_presets()["consorsbank_giro"]
    settings["balance"]["label"] = "Kontostand Nirgends"
    w = world(db, settings)
    with pytest.raises(ParseFailed, match="Nirgends"):
        w.up(giro_bytes(), today=date(2030, 1, 1))
    assert "Nirgends" in _only_failed_run(w).error_text


def test_an_invalid_profile_fails_the_run(db: Db) -> None:
    w = world(db, {})
    with pytest.raises(InvalidProfile):
        w.up(giro_bytes(), today=date(2030, 1, 1))
    assert _only_failed_run(w).status == "failed"


class Stub:
    """A file importer that returns what it was given, or raises."""

    def __init__(self, parsed: ParsedFile | None = None, error: Exception | None = None) -> None:
        self.parsed, self.error = parsed, error
        self.calls: list[dict[str, Any]] = []

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        return None

    def parse(self, data: bytes, profile: Mapping[str, Any], **kw: Any) -> ParsedFile:
        self.calls.append({"profile": dict(profile), **kw})
        if self.error is not None:
            raise self.error
        assert self.parsed is not None
        return self.parsed


def parsed(
    rows: list[IncomingRow],
    *,
    balance: int | None = None,
    balance_on: date | None = None,
    through: date = date(2026, 8, 10),
    start: date | None = date(2026, 8, 1),
    stats: Mapping[str, int] | None = None,
) -> ParsedFile:
    return ParsedFile(
        rows=tuple(rows),
        reported_balance=balance,
        balance_on=balance_on,
        covered_through=through,
        data_start=start,
        importer_stats=stats or {"filtered": 0, "synthetic_skipped": 0},
        report=DryRunReport(rows_read=len(rows), emitted=len(rows)),
    )


def irow(amount: int, day: int, **kw: Any) -> IncomingRow:
    base: dict[str, Any] = {
        "amount_minor": amount,
        "currency": "EUR",
        "booked_on": date(2026, 8, day),
        "source_format": "csv:stub",
        "raw": {"n": amount},
        "purpose": f"p{amount}",
    }
    base.update(kw)
    return IncomingRow(**base)


def test_an_importer_error_fails_the_run_with_its_message(db: Db) -> None:
    w = world(db)
    with pytest.raises(SourceUnavailable):
        w.up(b"", importer=Stub(error=SourceUnavailable("bank down")), today=date(2026, 8, 10))
    run = _only_failed_run(w)
    assert run.status == "failed" and "bank down" in run.error_text
    assert run.retryable is True  # SourceUnavailable: trying again can help


def test_the_importer_gets_the_profile_currency_exponents_and_today(db: Db) -> None:
    settings = load_presets()["consorsbank_giro"]
    w = world(db, settings)
    stub = Stub(parsed([irow(-100, 5)], through=date(2026, 8, 10)))
    w.up(b"x", importer=stub, today=date(2026, 8, 11), dry_run=True)
    (call,) = stub.calls
    assert (
        call["profile"] == settings
        and call["account_currency"] == "EUR"
        and call["today"] == date(2026, 8, 11)
    )
    assert call["minor_units_of"]("EUR") == 2 and call["minor_units_of"]("JPY") == 0
    with pytest.raises(KeyError):
        call["minor_units_of"]("ZZZ")


def test_the_importer_gets_the_instances_label_at_the_time_of_the_run(db: Db) -> None:
    w = world(db)
    stub = Stub(parsed([irow(-100, 5)], through=date(2026, 8, 10)))
    w.up(b"x", importer=stub, today=date(2026, 8, 11), dry_run=True)
    update_instance(db.engine, w.instance, label="Renamed")
    w.up(b"x", importer=stub, today=date(2026, 8, 11), dry_run=True)
    assert [c["name"] for c in stub.calls] == ["Giro CSV", "Renamed"]


def test_the_parse_runs_outside_any_database_transaction(db: Db) -> None:
    w = world(db)
    seen: list[int] = []

    class Probe(Stub):
        def parse(self, data: bytes, profile: Mapping[str, Any], **kw: Any) -> ParsedFile:
            with db.engine.connect() as conn:
                # no transaction of the upload is open: its running run is already committed
                seen.append(
                    int(
                        conn.execute(
                            text("SELECT count(*) FROM import_run WHERE status = 'running'")
                        ).scalar_one()
                    )
                )
                seen.append(
                    int(
                        conn.execute(
                            text(
                                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                                " AND state = 'idle in transaction'"
                            )
                        ).scalar_one()
                    )
                )
            return super().parse(data, profile, **kw)

    w.up(b"x", importer=Probe(parsed([irow(-100, 5)])), today=date(2026, 8, 10))
    assert seen == [1, 0]


def test_a_currency_mismatch_fails_a_real_run(db: Db) -> None:
    p = BY_NAME["consorsbank_giro"]
    w = world(db, p.name, kind=p.kind, currency="USD")
    with pytest.raises(ContractViolation) as exc:
        w.up(p.data(), today=p.today)
    assert exc.value.rule == "currency_mismatch"
    run = _only_failed_run(w)
    assert run.status == "failed" and "currency_mismatch" in run.error_text


# ---- dry runs ----------------------------------------------------------------------------


def _spy_settle(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(run_module, "settle", lambda engine: calls.append(1) or SettleResult())
    return calls


def _comparable(summary: Mapping[str, Any]) -> dict[str, Any]:
    out = {
        k: summary.get(k)
        for k in ("inserted", "skipped_by_identity", "balance", "unexplained_difference", "importer")
    }
    out["duplicates"] = len(summary["inserted_as_duplicates"])
    out["since_zero"] = len(summary["since_zero"])  # the ids are of rolled-back rows
    return out


@pytest.mark.parametrize("p", PRESETS, ids=IDS)
def test_a_dry_run_equals_the_real_run_and_persists_nothing(
    db: Db, p: Preset, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = preset_world(db, p)
    calls = _spy_settle(monkeypatch)
    before = w.counts()
    dry = w.up(p.data(), today=p.today, dry_run=True)
    assert w.counts() == before and calls == []
    assert dry.dry_run is True and dry.run_id is None and dry.settle is None and dry.failure is None
    real = w.up(p.data(), today=p.today)
    assert calls == [1] and real.run_id is not None and real.dry_run is False
    assert _comparable(dry.summary) == _comparable(real.summary)
    assert dry.summary["inserted"] == p.rows
    assert dry.report == real.report
    stored = get_run(db_conn(db), real.run_id)
    assert stored is not None and stored.stats == real.summary


def test_a_dry_run_of_a_reupload_shows_everything_skipped(db: Db) -> None:
    p = BY_NAME["consorsbank_giro"]
    w = preset_world(db, p)
    w.up(p.data(), today=p.today)
    before = w.counts()
    dry = w.up(p.data(), today=p.today, dry_run=True)
    assert dry.summary["inserted"] == 0 and dry.summary["skipped_by_identity"] == p.rows
    assert w.counts() == before


def test_a_dry_run_parse_failure_is_returned_with_the_report(db: Db) -> None:
    w = world(db)
    before = w.counts()
    result = w.up(b"no header in here\n", today=date(2030, 1, 1), dry_run=True)
    assert (
        result.failure is not None and result.failure.kind == "parse_failed" and result.failure.rule is None
    )
    assert result.failure.message and result.run_id is None and result.settle is None
    assert result.report.failure == result.failure.message
    assert result.summary == {} and w.counts() == before


def test_a_dry_run_importer_error_without_a_report(db: Db) -> None:
    w = world(db)
    result = w.up(
        b"", importer=Stub(error=SourceUnavailable("bank down")), today=date(2026, 8, 10), dry_run=True
    )
    assert result.failure is not None and result.failure.kind == "importer_error"
    assert "bank down" in result.failure.message and result.report == DryRunReport.empty()
    assert w.counts()["import_run"] == 0


def test_a_dry_run_invalid_profile_is_a_failure(db: Db) -> None:
    w = world(db, {})
    result = w.up(giro_bytes(), today=date(2030, 1, 1), dry_run=True)
    assert result.failure is not None and result.failure.kind == "invalid_profile"
    assert w.counts()["import_run"] == 0


def test_a_dry_run_currency_mismatch_is_a_failure_with_the_report(db: Db) -> None:
    p = BY_NAME["consorsbank_giro"]
    w = world(db, p.name, kind=p.kind, currency="USD")
    result = w.up(p.data(), today=p.today, dry_run=True)
    assert result.failure is not None
    assert (result.failure.kind, result.failure.rule) == ("contract_violation", "currency_mismatch")
    assert result.report.currency_mismatch.count > 0
    assert w.counts() == {"import_run": 0, "source_transaction": 0, "ledger_entry": 0, "balance_record": 0}


def test_i36_in_a_dry_run_is_a_failure_and_in_a_real_run_an_error(db: Db) -> None:
    w = world(db)
    bad = parsed([irow(-100, 5)], balance=500, balance_on=date(2026, 8, 12), through=date(2026, 8, 10))
    dry = w.up(b"x", importer=Stub(bad), today=date(2026, 8, 10), dry_run=True)
    assert dry.failure is not None and dry.failure.rule == "balance_after_coverage"
    assert w.counts()["import_run"] == 0
    with pytest.raises(ContractViolation) as exc:
        w.up(b"x", importer=Stub(bad), today=date(2026, 8, 10))
    assert exc.value.rule == "balance_after_coverage"
    assert w.db.one("SELECT status FROM import_run").status == "failed"


# ---- settle, the two-run rule ------------------------------------------------------------


def test_a_settle_error_does_not_undo_the_run(db: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db)
    monkeypatch.setattr(run_module, "settle", lambda engine: SettleResult(error="settle blew up"))
    result = w.up(b"x", importer=Stub(parsed([irow(-100, 5)])), today=date(2026, 8, 10))
    assert result.settle is not None and result.settle.error == "settle blew up"
    assert w.db.one("SELECT status FROM import_run").status == "ok"
    assert w.counts()["source_transaction"] == 1


def test_the_two_run_rule_through_upload(db: Db) -> None:
    w = world(db)
    one = parsed(
        [irow(-100, 1), irow(-200, 2)], balance=700, balance_on=date(2026, 8, 2), through=date(2026, 8, 2)
    )
    two = parsed(
        [irow(-100, 1), irow(-200, 2), irow(-50, 3)],
        balance=650,
        balance_on=date(2026, 8, 3),
        through=date(2026, 8, 3),
    )
    r1 = w.up(b"1", importer=Stub(one), today=date(2026, 8, 10))
    state1 = (w.derived(), w.counts())
    assert [t for t, _, _ in state1[0]] == ["opening"]
    r2 = w.up(b"2", importer=Stub(two), today=date(2026, 8, 10))
    assert r2.summary["inserted"] == 1 and r2.summary["skipped_by_identity"] == 2
    assert [t for t, _, _ in w.derived()] == ["opening"]  # run 2's balance is the true one: no reconciliation
    with db_conn(db) as conn:
        flags = {v.id: v.revertible for v in list_runs(conn)}
    assert flags == {r1.run_id: False, r2.run_id: True}
    assert r2.run_id is not None
    revert_run(db.engine, r2.run_id, user_id=None)
    assert w.derived() == state1[0]
    assert w.counts()["source_transaction"] == state1[1]["source_transaction"]
    with db_conn(db) as conn:
        flags = {v.id: (v.status, v.revertible) for v in list_runs(conn)}
    assert flags == {r1.run_id: ("ok", True), r2.run_id: ("reverted", False)}
    db.assert_checks_clean()


# ---- locks -------------------------------------------------------------------------------

_SETTLE_CLASS = 1 << 24
_ACCOUNT_CLASS = 2 << 24


def _until(cond: Callable[[], bool], what: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


def test_upload_lock_order_settle_shared_then_account(db: Db) -> None:
    w = world(db)
    stub = Stub(parsed([irow(-100, 5)]))
    done: list[Any] = []
    # the ACCOUNT lock is held elsewhere: the upload waits for it already holding settle shared
    with db.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            lock_accounts(holder, [w.account])
            thread = threading.Thread(
                target=lambda: done.append(w.up(b"x", importer=stub, today=date(2026, 8, 10)))
            )
            thread.start()
            _until(lambda: lockwatch.advisory_waiters(db.engine) >= 1, "the upload to wait for the account")
            shared = lockwatch.advisory_held(
                db.engine, exclude_pid=pid, classid=_SETTLE_CLASS, mode="ShareLock"
            )
            assert shared == 1
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1
    # settle is held EXCLUSIVELY elsewhere: the upload waits for it before any account lock
    done.clear()
    stub2 = Stub(parsed([irow(-300, 6)]))
    with db.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            lock_settle_exclusive(holder)
            thread = threading.Thread(
                target=lambda: done.append(w.up(b"x", importer=stub2, today=date(2026, 8, 10)))
            )
            thread.start()
            _until(lambda: lockwatch.advisory_waiters(db.engine) >= 1, "the upload to wait for settle")
            held = lockwatch.advisory_held(
                db.engine, exclude_pid=pid, classid=_ACCOUNT_CLASS, mode="ExclusiveLock"
            )
            assert held == 0
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1
