"""Migration 0006: every confirmed unit gets "no document" on its original entries (D3a); idempotent."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy import text

from app.utils.config import Config
from app.utils.db import migrate
from app.utils.db.engine import make_engine
from tests.core.units.doc_helpers import make_payee
from tests.invariants.helpers import make_category, make_entry, make_source, pair

NONE = {"pass": "matcher_decision"}
ROOT = Path(__file__).resolve().parents[1]


def _downgrade(cfg: Config, revision: str) -> None:
    engine = make_engine(cfg, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as conn:
            alembic = migrate.alembic_config()
            alembic.attributes["connection"] = conn
            command.downgrade(alembic, revision)
    finally:
        engine.dispose()


def _backfill_sql() -> str:
    spec = importlib.util.spec_from_file_location(
        "m0006", ROOT / "migrations" / "versions" / "0006_document_none.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module._BACKFILL)


def test_the_backfill_marks_exactly_the_confirmed_units(isolated_db: Config, make_account: Any) -> None:
    _downgrade(isolated_db, "0005")
    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    standing = json.dumps({"category": {"pass": "user"}})
    proposal = json.dumps({"category": {"pass": "history"}})
    with engine.begin() as conn:
        a, b = make_account(conn, name="A"), make_account(conn, name="B")
        cat = make_category(conn, "Food")
        payee = make_payee(conn, "PayPal", "paypal")
        done_src = make_source(conn, a, amount=-200)
        done_first = make_entry(
            conn, done_src, amount=-100, category_id=cat, payee_id=payee, derivation=standing
        )
        done_second = make_entry(conn, done_src, amount=-100, category_id=cat, derivation=standing)
        proposed = make_entry(conn, make_source(conn, a), category_id=cat, derivation=proposal)
        incomplete = make_entry(conn, make_source(conn, a))
        keyed = make_entry(
            conn,
            make_source(conn, a),
            category_id=cat,
            derivation=json.dumps({"document": {"pass": "user"}}),
        )
        out = make_entry(conn, make_source(conn, a, amount=-50), type="transfer", derivation=standing)
        into = make_entry(conn, make_source(conn, b, amount=50), type="transfer", derivation=standing)
        conn.execute(
            text("UPDATE ledger_entry SET counter_account_id = :c WHERE id = :i"), {"c": b, "i": out}
        )
        conn.execute(
            text("UPDATE ledger_entry SET counter_account_id = :c WHERE id = :i"), {"c": a, "i": into}
        )
        pair(conn, out, into)
        unpaired = make_entry(conn, make_source(conn, a), type="transfer", derivation=standing)
    engine.dispose()

    migrate.upgrade(isolated_db)

    def derivation(entry: int) -> dict[str, Any]:
        with make_engine(isolated_db, pool_size=1, max_overflow=0).connect() as conn:
            return dict(
                conn.execute(
                    text("SELECT derivation FROM ledger_entry WHERE id = :i"), {"i": entry}
                ).scalar_one()
            )

    assert derivation(done_first)["document"] == NONE
    assert "document" not in derivation(done_second)  # only the original entry of the transaction
    assert derivation(out)["document"] == NONE and derivation(into)["document"] == NONE
    assert derivation(keyed)["document"] == {"pass": "user"}  # a decision is kept
    for untouched in (proposed, incomplete, unpaired):
        assert "document" not in derivation(untouched)

    # idempotent: a second run writes nothing
    sql = _backfill_sql()
    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.begin() as conn:
        assert conn.execute(text(sql)).rowcount == 0
        assert (
            conn.execute(
                text("SELECT count(*) FROM ledger_entry WHERE jsonb_exists(derivation, 'document')")
            ).scalar_one()
            == 4
        )
    engine.dispose()
