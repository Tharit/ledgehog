"""The development seed (scripts/dev_seed.py): invented data pushed through the real pipeline.

Two layers: the pure generator (scripts/dev_seed_data.py: deterministic, parsed back through the
real CSV importer here) and a full run against a scratch `dev_` database, which the finalizer drops
(the sweeper never does).
"""

from __future__ import annotations

import io
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import redirect_stdout
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.accounts import create_account
from app.core.documents import DocumentFilter, get_document, list_documents
from app.core.importers.instances import link_account
from app.core.importers.providers import reset_document_providers
from app.core.integrity import check_integrity
from app.plugins.importers.csv import load_presets
from app.plugins.importers.testfetch import TestFetchImporter
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
    giro = next(f for f in plan.files() if f.preset == "consorsbank_giro")
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


@pytest.fixture(scope="module", autouse=True)
def _document_registry_is_restored() -> Iterator[None]:
    """`dev_seed.main` configures the document providers of its process; later tests start without."""
    yield
    reset_document_providers()


@pytest.fixture(scope="module")
def dev_engine(dev_cfg: Config) -> Iterator[Engine]:
    engine = make_engine(dev_cfg)
    try:
        yield engine
    finally:
        engine.dispose()


def _env(cfg: Config) -> dict[str, str]:
    return {**os.environ, "POSTGRES_DB": cfg.db.name}


def _run(cfg: Config, *argv: str, extra_env: dict[str, str] | None = None) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        code = dev_seed.main(list(argv), {**_env(cfg), **(extra_env or {})})
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
    # the unsynced GBP cash account stays empty on purpose: the cross-currency legs offer to fill it
    empty = {name for name, n in per_account.items() if n == 0}
    assert len(per_account) == 7 and empty == {"Bargeld GBP [seed]"}, per_account
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
        for field, op in (
            ("purpose", "regex"),
            ("counterparty_ref", "equals"),
            ("counterparty_name", "starts_with"),
        ):
            probe = json.dumps([{"field": field, "op": op}])
            assert (
                conn.execute(
                    text("SELECT count(*) FROM rule WHERE conditions @> CAST(:p AS jsonb)"), {"p": probe}
                ).scalar_one()
                >= 1
            ), (field, op)
        assert (  # the payee-conditioned category rule: a payee condition in the list
            conn.execute(
                text(
                    "SELECT count(*) FROM rule WHERE sets = 'category'"
                    ' AND conditions @> CAST(\'[{"field":"payee","op":"is"}]\' AS jsonb)'
                )
            ).scalar_one()
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


def _scenario(engine: Engine, key: str) -> Any:
    index = [c.key for c in dev_seed_data.DOC_CHARGES].index(key)
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT e.id, e.version, e.document_id, d.external_id, e.review_flags,"
                " e.derivation -> 'document' ->> 'pass' AS key"
                " FROM ledger_entry e JOIN source_transaction s ON s.id = e.source_transaction_id"
                " LEFT JOIN external_document d ON d.id = e.document_id WHERE s.source_id = :sid"
            ),
            {"sid": f"seed-document-{index}"},
        ).one()


def test_the_document_scenarios_come_out_as_described(seeded: str, dev_engine: Engine):
    exact = _scenario(dev_engine, "exact")
    assert (exact.external_id, exact.key) == ("PP-1001", "matcher_decision")  # one line: standing
    multi = _scenario(dev_engine, "multi")
    assert (multi.external_id, multi.key) == ("PP-1002", "matcher_proposal")  # several lines: review once
    assert "unconfirmed" in multi.review_flags
    for key in ("twin-a", "twin-b"):  # identical charges and documents: suggestions only
        twin = _scenario(dev_engine, key)
        assert twin.document_id is None and twin.key is None
        assert "document_suggested" in twin.review_flags and "waiting" not in twin.review_flags
    refund = _scenario(dev_engine, "refund")
    assert refund.external_id == "PP-1005"
    instructed = _scenario(dev_engine, "instructed")
    assert instructed.external_id == "PP-1006"
    confirmed = _scenario(dev_engine, "confirmed")
    assert confirmed.document_id is None and confirmed.key == "user" and list(confirmed.review_flags) == []
    late = _scenario(dev_engine, "late")
    assert (
        late.document_id is None
        and "waiting" in late.review_flags
        and "document_suggested" not in late.review_flags
    )
    assert "document scenarios:" in seeded and "charge exact: linked to PP-1001" in seeded


def test_the_scripted_test_bank_is_seeded_unlinked_with_its_pin_and_tan(seeded: str, dev_engine: Engine):
    with dev_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, emits::text, access, settings FROM importer_instance"
                " WHERE importer = 'testfetch' AND label = 'Testbank [seed]'"
            )
        ).one()
        links = conn.execute(
            text("SELECT count(*) FROM account_source WHERE importer_instance_id = :i"), {"i": row.id}
        ).scalar_one()
    assert row.emits == "{transactions}" and row.access == "shared"
    assert links == 0  # refresh accounts, then add and link: the seed links nothing
    settings = row.settings
    assert settings["open"] == [{"ask": "secret", "subject": "pin", "expect": "1234"}]
    accounts = {a["name"]: a for a in settings["accounts"]}
    assert set(accounts) == {"Testbank Giro", "Testbank Dollars", "Testbank Depot"}
    assert (
        accounts["Testbank Giro"]["currency"] == "EUR"
        and accounts["Testbank Giro"]["kind_hint"] == "checking"
    )
    assert accounts["Testbank Giro"]["capabilities"] == ["transactions", "balance"]
    assert accounts["Testbank Dollars"]["currency"] == "USD"
    assert accounts["Testbank Dollars"]["fetch"] == [{"ask": "tan", "medium": "text", "expect": "123456"}]
    assert accounts["Testbank Depot"]["capabilities"] == []
    # the real importer accepts exactly these settings, and the PIN and the TAN are in the report
    TestFetchImporter().validate_settings(settings)
    assert "PIN 1234" in seeded and "TAN 123456" in seeded


def test_the_documents_are_a_real_importer_instance_and_a_provider_payee(seeded: str, dev_engine: Engine):
    assert (
        _one(dev_engine, "SELECT emits::text FROM importer_instance WHERE importer = 'testdocs'")
        == "{documents}"
    )
    assert (
        _one(dev_engine, "SELECT count(*) FROM import_run WHERE emits = 'documents' AND status = 'ok'") == 1
    )
    assert _one(dev_engine, "SELECT count(*) FROM v_document_coverage") == 1
    assert _one(dev_engine, "SELECT document_provider FROM payee WHERE name = 'PayPal'") == "paypal"
    assert _one(dev_engine, "SELECT count(*) FROM external_document_line") >= 9


def test_the_confirmed_charges_document_is_a_reverse_match_and_the_list_shows_the_rest(
    seeded: str, dev_engine: Engine
):
    with dev_engine.connect() as conn:
        page = list_documents(conn, DocumentFilter(), limit=100, offset=0)
        by_id = {d.external_id: d for d in page.documents}
        assert page.total == len(dev_seed_data.DOC_SCENARIOS) == len(by_id)
        free = {d.external_id for d in page.documents if d.carrier_count == 0}
        assert free == {"PP-1003", "PP-1004", "PP-1007", "PP-1008", "AZ-2001"}
        unlinked_paypal = list_documents(
            conn, DocumentFilter(providers=("paypal",), linked=False), limit=100, offset=0
        )
        assert {d.external_id for d in unlinked_paypal.documents} == free - {"AZ-2001"}
        renewal = get_document(conn, by_id["PP-1007"].id)
        assert renewal is not None
        confirmed = _scenario(dev_engine, "confirmed")
        assert [(m.entry_id, m.confirmed) for m in renewal.matches] == [(confirmed.id, True)]
        twin = get_document(conn, by_id["PP-1003"].id)
        assert twin is not None and len(twin.matches) == 2 and not any(m.confirmed for m in twin.matches)
        assert get_document(conn, by_id["PP-1008"].id).matches == ()  # type: ignore[union-attr]


def test_the_late_charge_waits_in_the_review_queue_for_its_document(seeded: str, dev_engine: Engine):
    from app.core.units.read import review_queue

    late = _scenario(dev_engine, "late")
    with dev_engine.connect() as conn:
        waiting = {s.kind: s for s in review_queue(conn).sections}["waiting"]
    unit = next(u for u in waiting.units if u.anchor_entry_id == late.id)
    assert unit.waiting_document is not None and unit.waiting_document.provider == "paypal"


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
        "external_document",
        "external_document_line",
    ):
        assert _one(dev_engine, f"SELECT count(*) FROM {table}") == 0, table  # noqa: S608
    # without the test importers registered the scripted bank is not seeded (nothing could run it)
    out = _run(
        dev_cfg,
        "--months",
        "2",
        "--seed",
        "12",
        "--no-classify",
        extra_env={"ENABLE_TEST_IMPORTERS": "false"},
    )
    assert "PROTOTYPE-ONLY" not in out and "Testbank" not in out
    assert _one(dev_engine, "SELECT count(*) FROM importer_instance WHERE importer = 'testfetch'") == 0
    assert _one(dev_engine, "SELECT count(*) FROM ledger_entry") > 0
    assert _one(dev_engine, "SELECT count(*) FROM category") == 0
    assert (
        _one(dev_engine, "SELECT count(*) FROM external_document") == 0
    )  # documents come with the vocabulary
    _run(dev_cfg, "--reset", "--months", "2")  # reset + seed in one go
    assert _one(dev_engine, "SELECT count(*) FROM category") > 0
    assert _one(dev_engine, "SELECT count(*) FROM importer_instance WHERE importer = 'testfetch'") == 1
    with dev_engine.connect() as conn:
        assert check_integrity(conn).ok


def test_reset_also_removes_the_accounts_linked_by_hand_to_the_test_bank(
    seeded: str, dev_cfg: Config, dev_engine: Engine
):
    # what "Add and link" leaves behind: an account without the marker, linked to the seeded login
    instance = _one(dev_engine, "SELECT id FROM importer_instance WHERE importer = 'testfetch'")
    added = create_account(dev_engine, name="Testbank Giro", kind="checking", currency="EUR")
    link_account(dev_engine, instance, added, "TESTBANK-GIRO")

    _run(dev_cfg, "--reset", "--months", "2")

    assert _one(dev_engine, "SELECT count(*) FROM account WHERE name = 'Testbank Giro'") == 0
    assert _one(dev_engine, "SELECT count(*) FROM importer_instance WHERE importer = 'testfetch'") == 1
    with dev_engine.connect() as conn:
        assert check_integrity(conn).ok


def test_transfer_legs_fill_the_needs_account_and_waiting_sections(seeded: str, dev_engine: Engine):
    from app.core.units.read import review_queue

    with dev_engine.connect() as conn:
        queue = review_queue(conn)
    by_kind = {s.kind: s for s in queue.sections}
    needs, waiting = by_kind["needs_account"], by_kind["waiting"]
    assert needs.total >= 1 and [(g.currency, g.count) for g in needs.groups] == [("USD", needs.total)]
    # a partner (a leg) or a document (a charge): each waiting unit says what it waits for
    assert waiting.total >= 1 and all((u.waiting or u.waiting_document) is not None for u in waiting.units)
    assert any(u.waiting is not None for u in waiting.units)


def test_the_seeds_direct_sql_leaves_every_accounts_derived_entries_current(seeded: str, dev_engine: Engine):
    from app.core.balance.derived import recompute_derived

    snapshot = (
        "SELECT id, account_id, type, booked_on, amount FROM ledger_entry"
        " WHERE balance_record_id IS NOT NULL ORDER BY id"
    )
    with dev_engine.begin() as conn:
        before = conn.execute(text(snapshot)).all()
        for account_id in conn.execute(text("SELECT id FROM account")).scalars().all():
            recompute_derived(conn, account_id)
        assert conn.execute(text(snapshot)).all() == before  # recomputing finds nothing to change
        # the transfer legs are a later, balance-reporting delivery: the giro shows no difference
        giro = conn.execute(
            text("SELECT id FROM account WHERE name = 'Girokonto [seed]'")
        ).scalar_one_or_none()
        if giro is not None:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM v_unexplained_difference"
                        " WHERE account_id = :a AND difference <> 0"
                    ),
                    {"a": giro},
                ).scalar_one()
                == 0
            )
