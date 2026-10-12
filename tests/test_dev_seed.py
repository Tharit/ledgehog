"""The development seed (scripts/dev_seed.py): invented data pushed through the real pipeline.

Two layers: the pure generator (scripts/dev_seed_data.py: deterministic, parsed back through the
real CSV importer here) and a full run against a scratch `dev_` database, which the finalizer drops
(the sweeper never does).
"""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Iterator
from contextlib import redirect_stdout
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.integrity import check_integrity
from app.plugins.importers.csv import load_presets
from app.utils.config import Config
from app.utils.db import admin
from app.utils.db.engine import make_engine
from scripts import dev_seed, dev_seed_data
from tests.plugins.importers.csv.helpers import run as parse_csv

END = date(2026, 8, 20)


def _plan(seed: int = 7, months: int = 3) -> dev_seed_data.SeedPlan:
    return dev_seed_data.build_plan(seed=seed, end=END, months=months)


# -- the generator --------------------------------------------------------------------------------


def test_the_generator_is_deterministic_for_a_seed():
    a, b, c = _plan(7), _plan(7), _plan(8)
    assert [f.data for f in a.files()] == [f.data for f in b.files()]
    assert [f.data for f in a.files()] != [f.data for f in c.files()]


def test_the_generated_files_parse_through_the_real_importer_with_the_shipped_presets():
    presets = load_presets()
    for f in _plan().files():
        profile = {**presets[f.preset], "statement_payment": None}
        parsed = parse_csv(f.data, profile=profile, today=END)
        assert len(parsed.rows) == f.importable_rows, f.label
        assert {r.currency for r in parsed.rows} == {"EUR"}
        if f.balance is None:
            assert parsed.reported_balance is None
        else:
            assert parsed.reported_balance == f.balance
            assert parsed.balance_on == f.balance_on
            assert f.balance - sum(r.amount_minor for r in parsed.rows) == f.balance_before_file


def test_files_carry_what_the_importer_must_drop_and_what_the_card_converts():
    plan = _plan()
    giro = next(f for f in plan.files() if f.preset == "giro_with_preamble")
    parsed = parse_csv(giro.data, profile=load_presets()[giro.preset], today=END)
    assert parsed.importer_stats["filtered"] >= 1  # the zero-amount notice
    assert b"vorgemerkt" in giro.data  # the pending row the profile filters
    assert any(t.foreign for t in plan.txns["visa"])


def test_volume_is_a_few_dozen_rows_a_month_per_account_and_recurring_items_repeat():
    plan = _plan(months=4)
    for key in ("giro", "visa", "amex", "paypal"):
        per_month = len(plan.txns[key]) / 4
        assert 20 <= per_month <= 70, (key, per_month)
    rents = [t for t in plan.txns["giro"] if "Hausverwaltung" in t.name]
    salaries = [t for t in plan.txns["giro"] if t.amount > 200_000]
    assert len(rents) >= 4 and len(salaries) >= 3
    assert len({t.name for t in plan.txns["giro"]}) < len(plan.txns["giro"]) / 2  # merchants repeat


def test_classification_rules_cover_most_but_not_all_merchants():
    plan = _plan(months=4)
    flows = [t for k in ("giro", "visa", "amex", "paypal") for t in plan.txns[k]]
    covered = sum(1 for t in flows if dev_seed_data.classify(t.name, t.purpose) is not None)
    assert 0.65 <= covered / len(flows) <= 0.95


def test_the_seed_data_uses_only_the_designs_names():
    colors = {"forest", "sage", "olive", "teal", "slate", "lavender", "plum", "ochre", "brown", "stone"}
    used = [c.color for c in dev_seed_data.CATEGORIES + dev_seed_data.PAYEES + dev_seed_data.TAGS]
    assert {c for c in used if c} <= colors
    assert len(dev_seed_data.CATEGORIES) >= 14
    assert {c.kind for c in dev_seed_data.CATEGORIES} == {"income", "expense"}


# -- the guard ------------------------------------------------------------------------------------


def test_the_script_refuses_a_database_that_is_not_a_dev_one(admin_cfg: Config):
    env = {**os.environ, "POSTGRES_DB": "ledgehog"}
    out = io.StringIO()
    with redirect_stdout(out), pytest.raises(SystemExit) as exc:
        dev_seed.main([], env)
    assert exc.value.code != 0
    assert "dev_" in str(exc.value.code) or "dev_" in out.getvalue()


# -- a full run on a scratch dev_ database ---------------------------------------------------------


@pytest.fixture(scope="module")
def dev_cfg(admin_cfg: Config, template_db: str) -> Iterator[Config]:
    name = f"dev_seedtest_{uuid.uuid4().hex[:12]}"
    admin.create_database(admin_cfg, name, template=template_db)
    try:
        yield admin_cfg.with_database(name)
    finally:
        admin.drop_database(admin_cfg, name)


@pytest.fixture(scope="module")
def dev_engine(dev_cfg: Config) -> Iterator[Engine]:
    engine = make_engine(dev_cfg)
    try:
        yield engine
    finally:
        engine.dispose()


def _env(cfg: Config) -> dict[str, str]:
    return {**os.environ, "POSTGRES_DB": cfg.db.name}


def _run(cfg: Config, *argv: str) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        code = dev_seed.main(list(argv), _env(cfg))
    assert code == 0, out.getvalue()
    return out.getvalue()


def _one(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


@pytest.fixture(scope="module")
def seeded(dev_cfg: Config, dev_engine: Engine) -> str:
    return _run(dev_cfg, "--months", "3", "--seed", "11")


def test_a_full_run_fills_every_account_through_the_real_pipeline(seeded: str, dev_engine: Engine):
    with dev_engine.connect() as conn:
        per_account = {
            r[0]: r[1]
            for r in conn.execute(
                text(
                    "SELECT a.name, count(e.id) FROM account a"
                    " LEFT JOIN ledger_entry e ON e.account_id = a.id"
                    " GROUP BY a.name"
                )
            )
        }
    assert len(per_account) == 6 and all(n > 0 for n in per_account.values()), per_account
    assert all(name.endswith("[seed]") for name in per_account)
    assert _one(dev_engine, "SELECT count(*) FROM balance_record WHERE kind = 'reported'") >= 3
    assert _one(dev_engine, "SELECT count(*) FROM balance_record WHERE kind = 'manual'") >= 2
    assert _one(dev_engine, "SELECT count(*) FROM ledger_entry WHERE type = 'opening'") >= 3
    assert _one(dev_engine, "SELECT count(*) FROM account WHERE external_ref IS NOT NULL") >= 1
    # the second, overlapping upload skipped what was already there
    assert (
        _one(dev_engine, "SELECT count(*) FROM import_run WHERE (stats->>'skipped_by_identity')::int > 0")
        >= 1
    )
    assert "PROTOTYPE-ONLY" in seeded


def test_classification_gives_rows_something_to_render(seeded: str, dev_engine: Engine):
    assert _one(dev_engine, "SELECT count(*) FROM category WHERE icon IS NOT NULL AND color IS NOT NULL") >= 5
    assert _one(dev_engine, "SELECT count(*) FROM category WHERE parent_id IS NOT NULL") >= 6
    assert _one(dev_engine, "SELECT count(*) FROM payee") >= 15
    movements = _one(dev_engine, "SELECT count(*) FROM ledger_entry WHERE balance_record_id IS NULL")
    classified = _one(dev_engine, "SELECT count(*) FROM ledger_entry WHERE category_id IS NOT NULL")
    assert 0.5 <= classified / movements <= 0.9
    assert _one(dev_engine, "SELECT count(*) FROM ledger_entry WHERE 'unclassified' = ANY(review_flags)") > 0
    assert _one(dev_engine, "SELECT count(*) FROM ledger_entry WHERE 'unconfirmed' = ANY(review_flags)") > 0
    assert (
        _one(
            dev_engine,
            "SELECT count(*) FROM ledger_entry WHERE category_id IS NOT NULL AND review_flags = '{}'",
        )
        > 0
    )


def test_the_three_states_exist_side_by_side(seeded: str, dev_engine: Engine):
    movements = _one(dev_engine, "SELECT count(*) FROM ledger_entry WHERE balance_record_id IS NULL")
    categorised = _one(
        dev_engine, "SELECT count(*) FROM ledger_entry WHERE type = 'flow' AND category_id IS NOT NULL"
    )
    uncategorised_sql = "SELECT count(*) FROM ledger_entry WHERE type = 'flow' AND category_id IS NULL"
    uncategorised = _one(dev_engine, uncategorised_sql)
    untyped = _one(
        dev_engine, "SELECT count(*) FROM ledger_entry WHERE balance_record_id IS NULL AND type IS NULL"
    )
    # settling resolves by pass 0: a payment to one of the household's own accounts is a transfer
    transfers = _one(dev_engine, "SELECT count(*) FROM ledger_entry WHERE type = 'transfer'")
    assert categorised + uncategorised + untyped + transfers == movements
    # the seed writes flows without a category, but settling now resolves them: history proposes a
    # category where the seeded neighbours agree, so few remain (the seed is prototype-only data)
    assert uncategorised / movements <= 0.14, (uncategorised, movements)
    assert 0.12 <= untyped / movements <= 0.35, (untyped, movements)
    assert categorised / movements >= 0.5
    with dev_engine.connect() as conn:
        # the API's `uncategorised` predicate: only flows, and some of both payee/confirmation kinds
        rows = conn.execute(
            text(
                "SELECT type, payee_id, review_flags FROM ledger_entry"
                " WHERE category_id IS NULL AND type = 'flow'"
            )
        ).all()
        assert all(r[0] == "flow" for r in rows)
        assert all("unclassified" in r[2] for r in rows)  # settle: untyped OR flow without category
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM ledger_entry WHERE balance_record_id IS NULL"
                    " AND ('unclassified' = ANY(review_flags))"
                    " <> (type IS NULL OR (type = 'flow' AND category_id IS NULL))"
                )
            ).scalar_one()
            == 0
        )
    assert "flows without a category" in seeded


def test_named_rules_exist_for_every_kind_and_the_regex_one(seeded: str, dev_engine: Engine):
    with dev_engine.connect() as conn:
        by_sets = {r[0]: r[1] for r in conn.execute(text("SELECT sets, count(*) FROM rule GROUP BY sets"))}
        assert by_sets.keys() == {"counter_account", "payee", "category"}, by_sets
        assert (
            conn.execute(text("SELECT count(*) FROM rule WHERE purpose_regex IS NOT NULL")).scalar_one() >= 1
        )
        assert (
            conn.execute(text("SELECT count(*) FROM rule WHERE counterparty_ref IS NOT NULL")).scalar_one()
            >= 1
        )
        # the cash rule points at the cash account, and its entries are transfers decided by the rule
        cash = conn.execute(
            text(
                "SELECT count(*) FROM ledger_entry e"
                " JOIN rule r ON r.counter_account_id = e.counter_account_id"
            )
        ).scalar_one()
        assert cash > 0
    assert "named rules" in seeded


def test_tags_span_a_week_and_the_ledger_is_intact(seeded: str, dev_engine: Engine):
    with dev_engine.connect() as conn:
        trip = conn.execute(
            text(
                "SELECT t.color, min(e.booked_on), max(e.booked_on), count(*) FROM tag t"
                " JOIN ledger_entry_tag lt ON lt.tag_id = t.id"
                " JOIN ledger_entry e ON e.id = lt.ledger_entry_id"
                " WHERE t.name = 'Lisbon trip' GROUP BY t.color"
            )
        ).one()
        assert trip[0] is not None and trip[3] >= 5
        assert 3 <= (trip[2] - trip[1]).days <= 7
        assert conn.execute(text("SELECT count(*) FROM tag")).scalar_one() >= 5
        report = check_integrity(conn)
        assert report.ok, {k: v.rows for k, v in report.checks.items() if v.rows}


def test_a_second_run_is_a_no_op(seeded: str, dev_cfg: Config, dev_engine: Engine):
    before = _one(dev_engine, "SELECT count(*) FROM ledger_entry")
    out = _run(dev_cfg, "--months", "3", "--seed", "11")
    assert "already seeded" in out
    assert _one(dev_engine, "SELECT count(*) FROM ledger_entry") == before


def test_reset_removes_everything_it_created_and_a_reseed_works(
    seeded: str, dev_cfg: Config, dev_engine: Engine
):
    _run(dev_cfg, "--reset-only")
    for table in (
        "account",
        "importer_instance",
        "import_run",
        "source_transaction",
        "ledger_entry",
        "balance_record",
        "category",
        "payee",
        "tag",
        "ledger_entry_tag",
        "rule",
    ):
        assert _one(dev_engine, f"SELECT count(*) FROM {table}") == 0, table  # noqa: S608
    out = _run(dev_cfg, "--months", "2", "--seed", "12", "--no-classify")
    assert "PROTOTYPE-ONLY" not in out
    assert _one(dev_engine, "SELECT count(*) FROM ledger_entry") > 0
    assert _one(dev_engine, "SELECT count(*) FROM category") == 0
    _run(dev_cfg, "--reset", "--months", "2")  # reset + seed in one go
    assert _one(dev_engine, "SELECT count(*) FROM category") > 0
    with dev_engine.connect() as conn:
        assert check_integrity(conn).ok
