"""Development seed: months of SYNTHETIC, realistic ledger data in a `dev_*` database.

    . ./test.env && POSTGRES_DB=$(uv run --no-sync python scripts/dev_db.py name) \
        uv run --no-sync python scripts/dev_seed.py [--months 6] [--seed 20261011] [--no-classify] \
        [--reset | --reset-only]

Everything the domain owns goes through the real core operations: `create_account`,
`create_instance` + `link_account`, `upload()` with `CsvImporter` for generated files in the three
preset formats (giro with preamble, card with footer balance, card with inverted signs), a second
overlapping giro upload (dedup), `set_manual_record` for the cash account, and `settle`. All data
is invented (scripts/dev_seed_data.py); the script refuses any database whose name does not start
with `dev_`, and it is idempotent: a second run says it is already seeded and does nothing.

PROTOTYPE-ONLY: categories, payees and tags have no create/edit API yet (step 6), so
`classify` writes them, and assigns them to ~75% of the imported movements, with direct SQL in ONE
transaction. That part, and the SQL cleanup in `reset`, is dev data plumbing, not a pattern for
application code; it goes when step 6 lands (use its operations then). `--no-classify` skips it.

`--reset` removes what the seed created (accounts and importer instances carrying the `[seed]`
marker with everything they hold, and the seed's categories, payees and tags by name) and seeds
again; `--reset-only` just removes. The removal is a documented SQL cleanup: a revert keeps the
run rows, and an account holding runs cannot be deleted through `delete_account`.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections.abc import Mapping
from datetime import date
from typing import Any

from sqlalchemy import Engine, text

from app.core.accounts import create_account
from app.core.balance.records import set_manual_record
from app.core.importers.instances import create_instance, link_account
from app.core.importers.upload import upload
from app.core.integrity import check_integrity
from app.core.settle.settle import settle
from app.plugins.importers.csv import CsvImporter, load_presets
from app.utils import clock
from app.utils.config import Config
from app.utils.db.engine import make_engine
from app.utils.db.locks import lock_settle_exclusive
from scripts import dev_seed_data as data

DEFAULT_SEED = 20261011
_ALWAYS = frozenset({"Rent", "Salary", "Insurance"})  # recurring items are never left unclassified

# preset -> (accounts it feeds: (account key, reference at the login))
_LINKS: dict[str, tuple[tuple[str, str], ...]] = {
    "giro_with_preamble": (("giro", data.IBAN["giro"]), ("savings", data.IBAN["savings"])),
    "card_footer_balance": (("visa", "visa-0000"),),
    "card_inverted_signs": (("amex", "amex-0000"), ("paypal", "paypal-login")),
}


def _env_config(environ: Mapping[str, str] | None) -> Config:
    env = dict(os.environ if environ is None else environ)
    name = env.get("POSTGRES_DB", "")
    if not name.startswith("dev_"):
        raise SystemExit(
            f"refusing to seed {name or '(POSTGRES_DB unset)'!r}: the seed only runs against a "
            "database whose name starts with 'dev_' (scripts/dev_db.py name)"
        )
    env.setdefault("BASE_CURRENCY", "EUR")
    env.setdefault("TIMEZONE", "UTC")
    return Config.from_env(env)


def is_seeded(engine: Engine) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT 1 FROM account WHERE right(name, :n) = :m LIMIT 1"),
                {"n": len(data.SUFFIX), "m": data.SUFFIX},
            ).first()
            is not None
        )


# -- the real pipeline ----------------------------------------------------------------------------


def run_pipeline(engine: Engine, plan: data.SeedPlan, today: date, out: list[str]) -> dict[str, int]:
    """Accounts, instances, links, uploads and manual records through the core operations."""
    accounts = {
        key: create_account(
            engine, name=name + data.SUFFIX, kind=kind, currency="EUR", external_ref=ref, sort_order=i
        )
        for i, (key, name, kind, ref) in enumerate(data.ACCOUNTS)
    }
    presets = load_presets()
    importer = CsvImporter()
    instance_of: dict[str, int] = {}
    for preset, links in _LINKS.items():
        settings = {**presets[preset], "statement_payment": None}  # no paying account to point at
        instance_id = create_instance(
            engine,
            importer="csv",
            label=f"{preset}{data.SUFFIX}",
            settings=settings,
            emits=["transactions"],
            access="shared",
            validate=importer.validate_settings,
        )
        instance_of[preset] = instance_id
        for key, ref in links:
            link_account(engine, instance_id, accounts[key], ref)
    counts: dict[str, int] = {}
    for f in plan.files():
        result = upload(
            engine,
            instance_id=instance_of[f.preset],
            account_id=accounts[f.account],
            data=f.data,
            importer=importer,
            user_id=None,
            today=today,
        )
        if result.failure is not None:
            raise SystemExit(f"upload {f.label!r} failed: {result.failure.kind}: {result.failure.message}")
        inserted = int(result.summary.get("inserted", 0))
        skipped = int(result.summary.get("skipped_by_identity", 0))
        counts[f.account] = counts.get(f.account, 0) + inserted
        out.append(f"  upload {f.label}: {inserted} new, {skipped} already known")
    for on, balance in plan.cash_records:
        set_manual_record(engine, accounts["cash"], on, balance)
    return counts


# -- PROTOTYPE-ONLY: classification written with direct SQL ----------------------------------------


def classify(engine: Engine, seed: int, out: list[str]) -> None:
    """PROTOTYPE-ONLY dev data: categories, payees, tags and their assignments, one transaction.

    No create/edit API exists yet (step 6). Entries get `type='flow'` with a category (and a
    payee where a rule names one); each value carries a derivation key, `user` (standing, so the
    unit reads as confirmed) for ~70%, `history` (a proposal, so `unconfirmed`) for the rest.
    Movements no rule matches, and ~8% that do, stay untyped: the `unclassified` state.
    """
    rng = random.Random(f"{seed}:classify")
    with engine.begin() as conn:
        lock_settle_exclusive(conn)
        held = sum(
            int(conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one())  # noqa: S608
            for t in ("category", "payee", "tag")
        )
        if held:
            out.append("PROTOTYPE-ONLY classification skipped: categories, payees or tags already exist")
            return
        category_id: dict[str, int] = {}
        for c in data.CATEGORIES:  # parents are listed before their children
            category_id[c.name] = int(
                conn.execute(
                    text(
                        "INSERT INTO category (name, kind, parent_id, sort_order, icon, color)"
                        " VALUES (:n, :k, :p, :o, :i, :c) RETURNING id"
                    ),
                    {
                        "n": c.name,
                        "k": c.kind,
                        "p": category_id[c.parent] if c.parent else None,
                        "o": len(category_id),
                        "i": c.icon,
                        "c": c.color,
                    },
                ).scalar_one()
            )
        payee_id = {
            p.name: int(
                conn.execute(
                    text("INSERT INTO payee (name, icon, color) VALUES (:n, :i, :c) RETURNING id"),
                    {"n": p.name, "i": p.icon, "c": p.color},
                ).scalar_one()
            )
            for p in data.PAYEES
        }
        tag_id = {
            t.name: int(
                conn.execute(
                    text("INSERT INTO tag (name, color) VALUES (:n, :c) RETURNING id"),
                    {"n": t.name, "c": t.color},
                ).scalar_one()
            )
            for t in data.TAGS
        }
        movements = conn.execute(
            text(
                "SELECT e.id, s.counterparty_name, s.purpose FROM ledger_entry e"
                " JOIN source_transaction s ON s.id = e.source_transaction_id"
                " WHERE e.balance_record_id IS NULL ORDER BY e.id"
            )
        ).all()
        updates: list[dict[str, Any]] = []
        tagged: list[dict[str, int]] = []
        for entry_id, name, purpose in movements:
            rule = data.classify(name, purpose)
            if rule is not None and (rule.category in _ALWAYS or rng.random() < 0.92):
                key = "user" if rng.random() < 0.7 else "history"
                derivation = {"type": {"pass": key}, "category": {"pass": key}}
                if rule.payee:
                    derivation["payee"] = {"pass": key}
                updates.append(
                    {
                        "id": entry_id,
                        "c": category_id[rule.category],
                        "p": payee_id[rule.payee] if rule.payee else None,
                        "d": json.dumps(derivation),
                    }
                )
            tagged.extend(
                {"e": entry_id, "t": tag_id[t]} for t in data.tags_for(name, purpose) if t in tag_id
            )
        if updates:
            conn.execute(
                text(
                    "UPDATE ledger_entry SET type = 'flow', category_id = :c, payee_id = :p,"
                    " derivation = CAST(:d AS jsonb) WHERE id = :id"
                ),
                updates,
            )
        if tagged:
            conn.execute(
                text("INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:e, :t)"), tagged
            )
    out.append(
        f"PROTOTYPE-ONLY dev data (direct SQL, no API yet): {len(category_id)} categories, "
        f"{len(payee_id)} payees, {len(tag_id)} tags; {len(updates)} of {len(movements)} movements "
        f"classified, {len(tagged)} tag assignments"
    )


def reset(engine: Engine) -> None:
    """Remove everything the seed created. Documented SQL cleanup (see the module docstring)."""
    marker = {"n": len(data.SUFFIX), "m": data.SUFFIX}
    with engine.begin() as conn:
        lock_settle_exclusive(conn)
        ids = [
            int(r)
            for r in conn.execute(text("SELECT id FROM account WHERE right(name, :n) = :m"), marker).scalars()
        ]
        if ids:
            for sql in (
                "DELETE FROM ledger_entry_tag WHERE ledger_entry_id IN"
                " (SELECT id FROM ledger_entry WHERE account_id = ANY(:ids))",
                "DELETE FROM ledger_entry WHERE account_id = ANY(:ids)",
                "DELETE FROM source_transaction WHERE account_id = ANY(:ids)",
                "DELETE FROM balance_record WHERE account_id = ANY(:ids)",
                "DELETE FROM import_run WHERE account_id = ANY(:ids)",
                "DELETE FROM account_source WHERE account_id = ANY(:ids)",
                "DELETE FROM account WHERE id = ANY(:ids)",
            ):
                conn.execute(text(sql), {"ids": ids})  # noqa: S608
        conn.execute(text("DELETE FROM importer_instance WHERE right(label, :n) = :m"), marker)
        conn.execute(text("DELETE FROM payee WHERE name = ANY(:n)"), {"n": [p.name for p in data.PAYEES]})
        conn.execute(text("DELETE FROM tag WHERE name = ANY(:n)"), {"n": [t.name for t in data.TAGS]})
        for children in (True, False):  # the tree has two levels: children, then roots
            names = [c.name for c in data.CATEGORIES if (c.parent is not None) == children]
            conn.execute(text("DELETE FROM category WHERE name = ANY(:n)"), {"n": names})
    settle(engine)


# -- the report -----------------------------------------------------------------------------------


def summary(engine: Engine) -> list[str]:
    lines: list[str] = []
    with engine.connect() as conn:
        lo, hi = conn.execute(
            text("SELECT min(booked_on), max(booked_on) FROM ledger_entry WHERE balance_record_id IS NULL")
        ).one()
        lines.append(f"date range {lo} .. {hi}")
        lines.append("entries per account (movements + derived):")
        for name, movements, derived in conn.execute(
            text(
                "SELECT a.name, count(e.id) FILTER (WHERE e.balance_record_id IS NULL),"
                " count(e.id) FILTER (WHERE e.balance_record_id IS NOT NULL)"
                " FROM account a LEFT JOIN ledger_entry e ON e.account_id = a.id"
                " WHERE right(a.name, :n) = :m GROUP BY a.id, a.name ORDER BY a.sort_order, a.id"
            ),
            {"n": len(data.SUFFIX), "m": data.SUFFIX},
        ):
            lines.append(f"  {name}: {movements} + {derived}")
        flags = {
            r[0]: r[1]
            for r in conn.execute(
                text("SELECT f, count(*) FROM ledger_entry, unnest(review_flags) AS f GROUP BY f ORDER BY f")
            )
        }
        lines.append(f"review flags: {flags or 'none'}")
        cats = conn.execute(
            text(
                "SELECT c.name, count(e.id) FROM category c LEFT JOIN ledger_entry e ON e.category_id = c.id"
                " GROUP BY c.id, c.name ORDER BY count(e.id) DESC, c.name"
            )
        ).all()
        if cats:
            lines.append("entries per category: " + ", ".join(f"{n} {c}" for n, c in cats))
        for name, n, first, last in conn.execute(
            text(
                "SELECT t.name, count(*), min(e.booked_on), max(e.booked_on) FROM tag t"
                " JOIN ledger_entry_tag lt ON lt.tag_id = t.id"
                " JOIN ledger_entry e ON e.id = lt.ledger_entry_id"
                " GROUP BY t.id, t.name ORDER BY t.name"
            )
        ):
            lines.append(f"tag {name}: {n} entries, {first} .. {last}")
    return lines


def seed(engine: Engine, *, months: int, seed_value: int, do_classify: bool, today: date) -> list[str]:
    out: list[str] = ["seeding SYNTHETIC data through the real pipeline"]
    plan = data.build_plan(seed=seed_value, end=today, months=months)
    run_pipeline(engine, plan, today, out)
    if do_classify:
        classify(engine, seed_value, out)
    settle(engine)  # review flags recomputed once, at the end
    with engine.connect() as conn:
        report = check_integrity(conn)
    if not report.ok:
        bad = {name: check.rows[:3] for name, check in report.checks.items() if check.rows}
        raise SystemExit(f"integrity check failed after seeding: {bad}")
    out.append("integrity check: clean")
    out.extend(summary(engine))
    return out


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--no-classify", action="store_true", help="skip the PROTOTYPE-ONLY categories/payees/tags"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reset", action="store_true", help="remove the seeded data, then seed again")
    group.add_argument("--reset-only", action="store_true", help="remove the seeded data and stop")
    args = parser.parse_args(argv)
    if not 1 <= args.months <= 36:
        parser.error("--months must be between 1 and 36")
    cfg = _env_config(environ)  # refuses a database that is not a dev_ one, before connecting
    engine = make_engine(cfg)
    try:
        if args.reset or args.reset_only:
            reset(engine)
            print(f"removed the seeded data from {cfg.db.name}")
            if args.reset_only:
                return 0
        elif is_seeded(engine):
            print(f"{cfg.db.name} is already seeded: nothing to do (--reset to start over)")
            return 0
        today = clock.today(cfg.timezone)
        for line in seed(
            engine,
            months=args.months,
            seed_value=args.seed,
            do_classify=not args.no_classify,
            today=today,
        ):
            print(line)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
