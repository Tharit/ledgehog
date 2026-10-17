"""The document run (spec §5.5): upsert, version, carriers re-resolved, coverage, refusals."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.domain.errors import ContractViolation, IngestError, RunRefused
from app.core.ingest.documents import DocumentRunResult, ingest_documents, reresolve_unconfirmed_carrier
from app.core.ingest.run import start_run
from app.core.plugins.fetch import FetchImporter
from app.core.plugins.importer import IncomingDocument
from tests.invariants.helpers import make_category, make_movement
from tests.plugins.importers.fakes import FakeDocumentImporter, document, line

THROUGH = date(2026, 6, 30)


def q(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


def deliver(
    engine: Engine,
    docs: Sequence[IncomingDocument],
    *,
    instance_id: int | None = None,
    covered_through: date | None = THROUGH,
    covered_from: date | None = None,
) -> DocumentRunResult:
    run_id = start_run(engine, None, "documents", importer="fake", importer_instance_id=instance_id)
    return ingest_documents(engine, run_id, docs, covered_through=covered_through, covered_from=covered_from)


def doc_row(engine: Engine, external_id: str = "D1") -> Any:
    return q(engine, "SELECT * FROM external_document WHERE external_id = :e", e=external_id)[0]


def make_instance(engine: Engine, emits: str = "{documents}", disabled: bool = False) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO importer_instance (importer, label, access, emits, disabled)"
                    " VALUES ('fake', 'fake', 'shared', CAST(:e AS text[]), :d) RETURNING id"
                ),
                {"e": emits, "d": disabled},
            ).scalar_one()
        )


def carrier(
    engine: Engine, make_account: Callable[..., int], doc_id: int, *, confirmed: bool
) -> tuple[int, int]:
    """An entry carrying the document; returns (entry id, payee id)."""
    with engine.begin() as conn:
        account = make_account(conn)
        _, entry = make_movement(conn, account, amount=-1000)
        payee = int(conn.execute(text("INSERT INTO payee (name) VALUES ('Shop') RETURNING id")).scalar_one())
        category = make_category(conn, "Gadgets")
        derivation: dict[str, Any] = {"document": {"pass": "matcher_decision"}}
        values: dict[str, Any] = {"p": payee, "c": None}
        if confirmed:
            derivation |= {"type": {"pass": "user"}, "payee": {"pass": "user"}, "category": {"pass": "user"}}
            values["c"] = category
        else:
            derivation |= {"payee": {"pass": "history", "basis": {}}}
        conn.execute(
            text(
                "UPDATE ledger_entry SET document_id = :d, payee_id = :p, category_id = :c,"
                " derivation = CAST(:dv AS jsonb) WHERE id = :e"
            ),
            {**values, "d": doc_id, "dv": json.dumps(derivation), "e": entry},
        )
    return entry, payee


def entry_row(engine: Engine, entry_id: int) -> Any:
    return q(engine, "SELECT * FROM ledger_entry WHERE id = :i", i=entry_id)[0]


def test_fake_satisfies_the_protocol():
    fake = FakeDocumentImporter([document("A"), document("B", occurred_on=date(2026, 1, 1))])
    assert isinstance(fake, FetchImporter)
    out = fake.fetch({}, since=date(2026, 3, 1), today=THROUGH)
    assert [d.external_id for d in out.documents] == ["A"]


def test_insert_with_lines_and_ok_run_with_coverage(isolated_engine):
    result = deliver(
        isolated_engine,
        [document(lines=(line("A", -400), line("B", -600, 2)))],
        covered_from=date(2026, 1, 1),
    )
    assert (result.inserted, result.updated, result.changed) == (1, 0, ())
    d = doc_row(isolated_engine)
    assert d.version == 1 and d.total == -1000 and d.import_run_id == result.run_id
    lines = q(
        isolated_engine,
        "SELECT line_no, description, amount, qty FROM external_document_line ORDER BY line_no",
    )
    assert [tuple(r) for r in lines] == [(1, "A", -400, None), (2, "B", -600, 2)]
    run = q(isolated_engine, "SELECT * FROM import_run WHERE id = :i", i=result.run_id)[0]
    assert (run.status, run.emits, run.account_id) == ("ok", "documents", None)
    assert (run.covered_from, run.covered_through) == (date(2026, 1, 1), THROUGH)


def test_upsert_is_idempotent(isolated_engine):
    deliver(isolated_engine, [document()])
    second = deliver(isolated_engine, [document()])
    assert (second.inserted, second.updated, second.changed) == (0, 1, ())
    assert doc_row(isolated_engine).version == 1
    assert len(q(isolated_engine, "SELECT 1 FROM external_document")) == 1
    assert len(q(isolated_engine, "SELECT 1 FROM external_document_line")) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"total_minor": -1100, "lines": (line(amount=-1100),)},
        {"currency": "USD"},
        {"merchant_name": "Other"},
        {"merchant_name": None},
        {"lines": (line("Renamed"),)},
        {"lines": (line(), line("More", -5))},
    ],
)
def test_version_moves_on_a_resolution_read_change(isolated_engine, change):
    deliver(isolated_engine, [document()])
    result = deliver(isolated_engine, [document(**change)])
    d = doc_row(isolated_engine)
    assert d.version == 2 and result.changed == (d.id,)


def test_version_stays_on_title_raw_and_date_only_changes(isolated_engine):
    deliver(isolated_engine, [document()])
    result = deliver(
        isolated_engine,
        [document(title="Other", raw={"n": 2}, occurred_on=date(2026, 6, 2))],
    )
    d = doc_row(isolated_engine)
    assert d.version == 1 and result.changed == ()
    assert (d.title, d.raw, d.occurred_on) == ("Other", {"n": 2}, date(2026, 6, 2))


def test_lines_are_replaced(isolated_engine):
    deliver(isolated_engine, [document(lines=(line("A", -400), line("B", -600)))])
    deliver(isolated_engine, [document(lines=(line("C", -1000),))])
    rows = q(isolated_engine, "SELECT line_no, description FROM external_document_line")
    assert [tuple(r) for r in rows] == [(1, "C")]


def test_changed_document_drops_link_of_unconfirmed_carrier(isolated_engine, make_account):
    deliver(isolated_engine, [document()])
    doc_id = doc_row(isolated_engine).id
    entry, _ = carrier(isolated_engine, make_account, doc_id, confirmed=False)
    result = deliver(isolated_engine, [document(total_minor=-1100)])
    assert result.reresolved_entry_ids == (entry,)
    row = entry_row(isolated_engine, entry)
    assert row.document_id is None and "document" not in row.derivation


def test_unchanged_document_keeps_the_link(isolated_engine, make_account):
    deliver(isolated_engine, [document()])
    doc_id = doc_row(isolated_engine).id
    entry, _ = carrier(isolated_engine, make_account, doc_id, confirmed=False)
    deliver(isolated_engine, [document(title="Other")])
    assert entry_row(isolated_engine, entry).document_id == doc_id


def test_confirmed_carrier_is_left_alone(isolated_engine, make_account):
    deliver(isolated_engine, [document()])
    doc_id = doc_row(isolated_engine).id
    entry, _ = carrier(isolated_engine, make_account, doc_id, confirmed=True)
    before = entry_row(isolated_engine, entry)
    result = deliver(isolated_engine, [document(total_minor=-1100)])
    assert result.reresolved_entry_ids == ()
    after = entry_row(isolated_engine, entry)
    assert after.document_id == doc_id and after.derivation == before.derivation
    assert (after.payee_id, after.category_id) == (before.payee_id, before.category_id)


def test_reresolve_seam_drops_link_and_key_and_user_values(isolated_engine, make_account):
    deliver(isolated_engine, [document()])
    doc_id = doc_row(isolated_engine).id
    entry, _ = carrier(isolated_engine, make_account, doc_id, confirmed=False)
    with isolated_engine.begin() as conn:
        assert reresolve_unconfirmed_carrier(conn, [entry]) == [entry]
        assert reresolve_unconfirmed_carrier(conn, []) == []
    row = entry_row(isolated_engine, entry)
    assert row.document_id is None and "document" not in row.derivation
    assert row.payee_id is None  # the history guess had no history to stand on


def test_seam_ignores_confirmed_entries(isolated_engine, make_account):
    deliver(isolated_engine, [document()])
    doc_id = doc_row(isolated_engine).id
    entry, _ = carrier(isolated_engine, make_account, doc_id, confirmed=True)
    with isolated_engine.begin() as conn:
        assert reresolve_unconfirmed_carrier(conn, [entry]) == []
    assert entry_row(isolated_engine, entry).document_id == doc_id


def test_coverage_is_required(isolated_engine):
    run_id = start_run(isolated_engine, None, "documents", importer="fake")
    with pytest.raises(ContractViolation) as exc:
        ingest_documents(isolated_engine, run_id, [document()], covered_through=None)
    assert exc.value.rule == "no_coverage"
    run = q(isolated_engine, "SELECT status, error_text FROM import_run WHERE id = :i", i=run_id)[0]
    assert run.status == "failed"
    assert q(isolated_engine, "SELECT 1 FROM external_document") == []


@pytest.mark.parametrize(
    ("docs", "rule"),
    [
        ([document(total_minor=0)], "zero_total"),
        ([document("X"), document("X")], "repeated_document"),
        ([document(currency="XXQ")], "unknown_currency"),
    ],
)
def test_contract_violations_fail_the_run_and_write_nothing(isolated_engine, docs, rule):
    run_id = start_run(isolated_engine, None, "documents", importer="fake")
    with pytest.raises(ContractViolation) as exc:
        ingest_documents(isolated_engine, run_id, docs, covered_through=THROUGH)
    assert exc.value.rule == rule
    assert q(isolated_engine, "SELECT 1 FROM external_document") == []
    assert q(isolated_engine, "SELECT status FROM import_run WHERE id = :i", i=run_id)[0].status == "failed"


def test_refusals_of_the_instance(isolated_engine):
    disabled = make_instance(isolated_engine, disabled=True)
    with pytest.raises(RunRefused) as exc:
        deliver(isolated_engine, [document()], instance_id=disabled)
    assert exc.value.reason == "instance_disabled"
    rates = make_instance(isolated_engine, emits="{transactions}")
    with pytest.raises(RunRefused) as exc:
        deliver(isolated_engine, [document()], instance_id=rates)
    assert exc.value.reason == "not_a_document_source"
    assert q(isolated_engine, "SELECT 1 FROM external_document") == []
    ok = make_instance(isolated_engine)
    assert deliver(isolated_engine, [document()], instance_id=ok).inserted == 1


def test_run_must_be_a_running_documents_run(isolated_engine, make_account):
    result = deliver(isolated_engine, [document()])
    with pytest.raises(IngestError, match="not running"):
        ingest_documents(isolated_engine, result.run_id, [document()], covered_through=THROUGH)
    with isolated_engine.begin() as conn:
        account = make_account(conn)
    tx_run = start_run(isolated_engine, account, "transactions", importer="csv")
    with pytest.raises(IngestError, match="not documents"):
        ingest_documents(isolated_engine, tx_run, [document()], covered_through=THROUGH)


def test_start_run_account_rules(isolated_engine, make_account):
    with isolated_engine.begin() as conn:
        account = make_account(conn)
    with pytest.raises(ValueError):
        start_run(isolated_engine, account, "documents", importer="fake")
    with pytest.raises(ValueError):
        start_run(isolated_engine, None, "transactions", importer="csv")
    with pytest.raises(ValueError):
        start_run(isolated_engine, None, "rates", importer="x")


def test_a_document_run_is_not_revertible(isolated_engine):
    result = deliver(isolated_engine, [document()])
    with pytest.raises(Exception, match="ck_reverted_transactions"):
        with isolated_engine.begin() as conn:
            conn.execute(
                text("UPDATE import_run SET status = 'reverted', reverted_at = now() WHERE id = :i"),
                {"i": result.run_id},
            )
