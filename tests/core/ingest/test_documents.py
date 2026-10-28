"""The document run (spec §5.5): upsert, version, coverage, refusals. Documents only: no entry is touched."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.domain.errors import ContractViolation, IngestError, RunRefused
from app.core.ingest.documents import DocumentRunResult, ingest_documents
from app.core.ingest.run import start_run
from app.core.plugins.fetch import FetchImporter
from app.core.plugins.importer import IncomingDocument
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


def doc_row(engine: Engine, source_id: str = "D1") -> Any:
    return q(engine, "SELECT * FROM external_document WHERE source_id = :e", e=source_id)[0]


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


def test_fake_satisfies_the_protocol():
    fake = FakeDocumentImporter([document("A"), document("B", occurred_on=date(2026, 1, 1))])
    assert isinstance(fake, FetchImporter)
    out = fake.fetch({}, since=date(2026, 3, 1), today=THROUGH)
    assert [d.source_id for d in out.documents] == ["A"]


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
        {"occurred_on": date(2026, 6, 2)},
        {"lines": (line("Renamed"),)},
        {"lines": (line(), line("More", -5))},
        {"merchant_name": "Somebody"},
        {"title": "Other"},
        {"reference": "ORD-7"},
    ],
)
def test_version_moves_on_a_content_change(isolated_engine, change):
    deliver(isolated_engine, [document()])
    result = deliver(isolated_engine, [document(**change)])
    d = doc_row(isolated_engine)
    assert d.version == 2 and result.changed == (d.id,)


def test_a_delivered_reference_is_stored(isolated_engine):
    deliver(isolated_engine, [document(reference="ORD-7")])
    assert doc_row(isolated_engine).reference == "ORD-7"
    deliver(isolated_engine, [document()])  # a source that names none any more clears it
    assert doc_row(isolated_engine).reference is None


def test_version_stays_on_a_raw_only_change(isolated_engine):
    deliver(isolated_engine, [document()])
    result = deliver(
        isolated_engine,
        [document(raw={"n": 2})],
    )
    d = doc_row(isolated_engine)
    assert d.version == 1 and result.changed == ()
    assert d.raw == {"n": 2}


def test_lines_are_replaced(isolated_engine):
    deliver(isolated_engine, [document(lines=(line("A", -400), line("B", -600)))])
    deliver(isolated_engine, [document(lines=(line("C", -1000),))])
    rows = q(isolated_engine, "SELECT line_no, description FROM external_document_line")
    assert [tuple(r) for r in rows] == [(1, "C")]


def test_a_zero_total_is_a_document_like_any_other(isolated_engine):
    result = deliver(isolated_engine, [document(total_minor=0, lines=())])
    assert result.inserted == 1 and doc_row(isolated_engine).total == 0


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
