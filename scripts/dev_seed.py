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

Documents (`dev_seed_data.DOC_SCENARIOS`; with classification, `--no-classify` skips them): a `testdocs`
importer instance (`app/plugins/importers/testdocs`, which delivers what its settings list) run through the
real `start_run` + `ingest_documents`: orders of one and of several lines, a refund and one in another
currency, from two providers. Documents are stored only: what they mean for the ledger is a clearance
account's booking. The script's composition root configures the document importers of its process
(`core/importers/providers.py`).

A scripted test bank (`dev_seed_data.testbank_settings`; only where `testfetch` is registered, that is with
`ENABLE_TEST_IMPORTERS=true`): a `testfetch` instance "Testbank [seed]", shared, linked to no account, for
trying refresh accounts, fetching and the prompts by hand. Its login asks for the PIN **1234**; it reaches
three accounts: "Testbank Giro" (EUR, checking, bookings and a balance, ninety days of history), "Testbank
Dollars" (a USD pocket whose fetch asks for the text TAN **123456**) and "Testbank Depot" (nothing to fetch).
`--reset` removes the instance and the accounts that were linked to it.

Named rules (`dev_seed_data.RULES`: a counter-account rule against the cash account, a payee rule, a
category rule by counterparty reference, a regex rule, a category rule with a payee condition) are
written through the real `create_rule`, previewed first, after the classification they name.

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
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, text

from app.core.accounts import create_account
from app.core.balance.derived import recompute_derived
from app.core.balance.records import set_manual_record
from app.core.importers.instances import create_instance, link_account
from app.core.importers.providers import register_document_importers
from app.core.importers.upload import upload
from app.core.ingest.documents import ingest_documents
from app.core.ingest.run import ingest_delivery, start_run
from app.core.integrity import check_integrity
from app.core.ledger.rules import RuleDraft, create_rule
from app.core.plugins.classifier import Condition
from app.core.resolution.registry import configure_classifiers, configure_rule_tools
from app.core.settle.settle import settle
from app.plugins.classifiers import default_classifiers, default_rule_tools
from app.plugins.importers.csv import CsvImporter, load_presets
from app.plugins.importers.testdocs import TestDocumentImporter
from app.plugins.importers.testfetch import TestFetchImporter
from app.utils import clock
from app.utils.config import Config
from app.utils.db.engine import make_engine
from app.utils.db.locks import lock_settle_exclusive
from scripts import dev_seed_data as data

DEFAULT_SEED = 20261011
_NO_CATEGORY_SHARE = 0.10  # of the classified movements: flows left without a category
_TRANSFER_TAIL_DAYS = (
    10  # days after the exports' last booking day that hold the transfer legs (`_TRANSFERS`)
)
_ALWAYS = frozenset({"Rent", "Salary", "Insurance"})  # recurring items are never left unclassified

# preset -> (accounts it feeds: (account key, reference at the login))
_LINKS: dict[str, tuple[tuple[str, str], ...]] = {
    "consorsbank_giro": (("giro", data.IBAN["giro"]), ("savings", data.IBAN["savings"])),
    "deutschebank_card": (("visa", "visa-0000"),),
    "amex_card": (("amex", "amex-0000"), ("paypal", "paypal-login")),
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
    About 8% of all movements become flows with NO category (some with a payee); movements no
    rule matches, and ~8% that do, stay untyped (type NULL, as the importer leaves them). Both
    carry the `unclassified` flag.
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
                # ~10% of the classified (~8% of all movements) are flows the user has typed but
                # not yet categorised: type flow, no category, a payee for about half of them
                no_category = rule.category not in _ALWAYS and rng.random() < _NO_CATEGORY_SHARE
                payee = rule.payee if rule.payee and not (no_category and rng.random() < 0.5) else None
                derivation = {"type": {"pass": key}}
                if not no_category:
                    derivation["category"] = {"pass": key}
                if payee:
                    derivation["payee"] = {"pass": key}
                updates.append(
                    {
                        "id": entry_id,
                        "c": None if no_category else category_id[rule.category],
                        "p": payee_id[payee] if payee else None,
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
    uncategorised = sum(1 for u in updates if u["c"] is None)
    out.append(
        f"PROTOTYPE-ONLY dev data (direct SQL, no API yet): {len(category_id)} categories, "
        f"{len(payee_id)} payees, {len(tag_id)} tags; of {len(movements)} movements "
        f"{len(updates) - uncategorised} categorised flows, {uncategorised} flows without a category, "
        f"{len(movements) - len(updates)} without a type; {len(tagged)} tag assignments"
    )


@dataclass(frozen=True, slots=True)
class _Leg:
    """One transfer leg of `transfer_cases`: `ago` days before the giro's last day, `counter` the account key
    the user named (or None); `proposal` leaves it untyped, for settling to
    type from the history of `name` (the counterparty; a proposal, so the unit is unconfirmed) instead of
    the standing `user` one; `instructed` is (minor units, currency)."""

    account: str
    amount: int
    purpose: str
    ago: int = 0
    counter: str | None = None
    proposal: bool = False
    name: str | None = None
    instructed: tuple[int, str] | None = None


# the accounts whose legs are imported (the others are entered by hand), by `dev_seed_data.ACCOUNTS` key
_SYNCED = ("giro", "savings", "paypal", "visa")
# key, name, kind, currency: created for the cross-currency legs
_CASH_GBP = ("gbp", "Bargeld GBP", "cash", "GBP")

# counterparties the history learns the transfer from (the confirmed pair below votes for them)
_TO_SAVINGS, _FROM_GIRO = "Tagesgeld Urlaub", "Girokonto Urlaub"

# Every scenario of the review queue and the partner popover (spec §5.7), by what settling makes of it
_TRANSFERS: tuple[_Leg, ...] = (
    # needs an account in USD: no USD account exists
    _Leg("giro", -9_200, "ATM WITHDRAWAL NEW YORK USD 100.00 [seed]", instructed=(-10_000, "USD")),
    # waiting: the partner on the (synced) giro has not arrived yet
    _Leg("cash", -4_711, "Cash given to a friend [seed]", counter="giro"),
    # an exact pair of two synced accounts, paired by settling, both legs unconfirmed (a proposed type)
    _Leg("giro", -30_000, "Umbuchung Reisekasse [seed]", ago=4, proposal=True, name=_TO_SAVINGS),
    _Leg("savings", 30_000, "Umbuchung Reisekasse [seed]", ago=4, proposal=True, name=_FROM_GIRO),
    # an exact match with no counter-account on either leg: not paired (I33), each offers the other, proposed
    _Leg("giro", -8_500, "Guthaben auf PayPal laden [seed]", ago=2),
    _Leg("paypal", 8_500, "Aufladung vom Girokonto [seed]", ago=1),
    # inexact: a fee of 1.50 sits between the legs, so they are not paired; the offer carries the fee
    _Leg("giro", -15_000, "Auszahlung Verkaufserloes [seed]", ago=5, counter="paypal"),
    _Leg("paypal", 14_850, "Auszahlung auf Girokonto [seed]", ago=5),
    # a counter-leg proposal: the cash account is unsynced and holds nothing to pair with
    _Leg("giro", -6_000, "Cash for the weekend [seed]", ago=1, counter="cash"),
    # across currencies: with an instructed amount in the account's currency the counter-leg has an amount,
    # without it the user types the amount received
    _Leg(
        "giro",
        -23_000,
        "Wechsel Reisekasse GBP 200.00 [seed]",
        ago=2,
        counter="gbp",
        instructed=(-20_000, "GBP"),
    ),
    _Leg("giro", -11_500, "Wechsel Reisekasse GBP [seed]", ago=3, counter="gbp"),
    # a confirmed pair (standing keys), whose savings leg then shows as paired elsewhere under the unpaired
    # duplicate booking one day later on the giro
    _Leg("giro", -4_000, "Sparrate Urlaub [seed]", ago=7, counter="savings", name=_TO_SAVINGS),
    _Leg("savings", 4_000, "Sparrate Urlaub [seed]", ago=7, name=_FROM_GIRO),
    _Leg("giro", -4_000, "Sparrate Urlaub doppelt gebucht [seed]", ago=6, counter="savings"),
)


def transfer_cases(engine: Engine, out: list[str]) -> None:
    """PROTOTYPE-ONLY dev data: transfer legs for the review queue and the partner popover (spec §5.7),
    written with direct SQL in the days after the synced accounts' last reported balance (`_TRANSFERS`;
    it says what each is). Each synced account's legs belong to a new run, closed through the real
    `ingest_delivery` with the balance the legs lead to, so the ledger holds no reconciliation and no
    difference; derived entries are recomputed for every touched account. The legs:
    needs account, waiting, an exact pair (unconfirmed), exact open legs, an inexact pair, a counter-leg
    proposal, a counter-leg that needs the amount received and one that has it, a confirmed pair, and a
    leg whose partner candidate is paired elsewhere. Settling then pairs what it can.
    """
    gbp = create_account(engine, name=_CASH_GBP[1] + data.SUFFIX, kind=_CASH_GBP[2], currency=_CASH_GBP[3])
    with engine.connect() as conn:
        ids = {
            key: int(
                conn.execute(
                    text("SELECT id FROM account WHERE name = :n"), {"n": name + data.SUFFIX}
                ).scalar_one()
            )
            for key, name, _kind, _ref in data.ACCOUNTS
        }
        # the latest counting record of each synced account: the legs come after all of them
        latest = {
            key: conn.execute(
                text(
                    "SELECT balance_on, balance FROM v_balance_record WHERE account_id = :a"
                    " ORDER BY balance_on DESC, id DESC LIMIT 1"
                ),
                {"a": ids[key]},
            ).first()
            for key in _SYNCED
        }
    ids[_CASH_GBP[0]] = gbp
    currency = {ids[k]: "EUR" for k in ids} | {gbp: _CASH_GBP[3]}
    # `ago` counts back from the last leg day; the earliest leg lies after every reported balance
    last = max(r.balance_on for r in latest.values() if r is not None) + timedelta(
        days=max(leg.ago for leg in _TRANSFERS) + 1
    )
    legs_of = {leg.account for leg in _TRANSFERS if leg.account in _SYNCED}
    run = {key: start_run(engine, ids[key], "transactions", importer="csv") for key in legs_of}
    with engine.begin() as conn:
        lock_settle_exclusive(conn)
        for n, leg in enumerate(_TRANSFERS):
            account, day, imported = ids[leg.account], last - timedelta(days=leg.ago), leg.account in _SYNCED
            counter = ids[leg.counter] if leg.counter else None
            sid = conn.execute(
                text(
                    "INSERT INTO source_transaction (origin, importer, import_run_id, account_id, source_id,"
                    " content_hash, source_format, amount, currency, booked_on, purpose, raw,"
                    " counterparty_name, instructed_amount, instructed_currency)"
                    " VALUES (:origin, :importer, :run, :account, :source_id, :content_hash, :source_format,"
                    " :amount, :currency, :day, :purpose, '{}', :name, :instructed_amount,"
                    " :instructed_currency)"
                    " RETURNING id"
                ),
                {
                    "origin": "import" if imported else "user",
                    "importer": "csv" if imported else None,
                    "run": run[leg.account] if imported else None,
                    "account": account,
                    "source_id": f"seed-transfer-{n}" if imported else None,
                    "content_hash": None if imported else f"seed-transfer-{n}",
                    "source_format": "csv" if imported else None,
                    "amount": leg.amount,
                    "currency": currency[account],
                    "day": day,
                    "purpose": leg.purpose,
                    "name": leg.name,
                    "instructed_amount": leg.instructed[0] if leg.instructed else None,
                    "instructed_currency": leg.instructed[1] if leg.instructed else None,
                },
            ).scalar_one()
            derivation: dict[str, Any] = {}
            if not leg.proposal:
                derivation["type"] = {"pass": "user"}
            if counter:
                derivation["counter_account"] = {"pass": "user"}
            conn.execute(
                text(
                    "INSERT INTO ledger_entry (source_transaction_id, account_id, currency, booked_on,"
                    " amount, type, counter_account_id, derivation)"
                    " VALUES (:s, :account, :currency, :day, :amount, :type, :counter,"
                    " CAST(:d AS jsonb))"
                ),
                {
                    "s": sid,
                    "account": account,
                    "currency": currency[account],
                    "day": day,
                    "amount": leg.amount,
                    "type": None if leg.proposal else "transfer",
                    "counter": counter,
                    "d": json.dumps(derivation),
                },
            )
        for account_id in {ids[leg.account] for leg in _TRANSFERS}:  # direct SQL bypasses the derived entries
            recompute_derived(conn, account_id)
    for key in sorted(legs_of):  # the real delivery closes each run with the balance the legs lead to
        total = sum(leg.amount for leg in _TRANSFERS if leg.account == key)
        before = latest[key]  # an account that never reported a balance has none to lead on from
        ingest_delivery(
            engine,
            run[key],
            [],
            reported_balance=None if before is None else int(before.balance) + total,
            reported_balance_on=None if before is None else last,
            covered_from=None if before is None else before.balance_on + timedelta(days=1),
            covered_through=last,
        )
    out.append(f"PROTOTYPE-ONLY dev data (direct SQL): {len(_TRANSFERS)} transfer legs for the review queue")


def document_cases(engine: Engine, today: date, out: list[str]) -> None:
    """Documents for the document list (spec §5.5, §5.8, documents.md): a document importer instance
    (`TestDocumentImporter`, which delivers what its settings list) run through the real `start_run` +
    `ingest_documents`, which settles. The documents are stored only."""
    last_on = _last_booking(engine)
    covered = last_on - timedelta(days=3)
    start = last_on - timedelta(days=60)
    importer = TestDocumentImporter()
    settings: dict[str, Any] = {
        "start_date": start.isoformat(),
        "covered_through": covered.isoformat(),
        "documents": [_document_json(d, last_on) for d in data.DOC_SCENARIOS],
    }
    instance = create_instance(
        engine,
        importer=data.DOC_IMPORTER,
        label=f"{data.DOC_IMPORTER}{data.SUFFIX}",
        settings=settings,
        emits=["documents"],
        access="shared",
        validate=importer.validate_settings,
    )
    delivery = importer.fetch(settings, since=start, today=today)
    run = start_run(engine, None, "documents", importer=data.DOC_IMPORTER, importer_instance_id=instance)
    result = ingest_documents(
        engine,
        run,
        delivery.documents,
        covered_through=delivery.covered_through,
        covered_from=delivery.covered_from,
    )
    out.append(
        f"{result.inserted} documents (importer instance, covered through {delivery.covered_through}), "
        "through the real ingest"
    )


def testbank_instance(engine: Engine, today: date, out: list[str]) -> None:
    """The scripted test bank: a `testfetch` instance "Testbank [seed]" to try the sync pages against.

    Through the real `create_instance` (its settings validated by the importer). It is not linked to
    any account: refresh its accounts (`/settings/importers/<id>/accounts`), then add and link them.
    Only seeded where `testfetch` is registered (`ENABLE_TEST_IMPORTERS`), like the document importer
    it mirrors; the [seed] marker lets `--reset` remove it, and the accounts linked to it.
    """
    importer = TestFetchImporter()
    create_instance(
        engine,
        importer=data.TESTBANK_IMPORTER,
        label=data.TESTBANK_LABEL + data.SUFFIX,
        settings=data.testbank_settings(today),
        emits=["transactions"],
        access="shared",
        validate=importer.validate_settings,
    )
    out.append(
        f"importer instance {data.TESTBANK_LABEL + data.SUFFIX!r} (testfetch): PIN {data.TESTBANK_PIN}, "
        f"TAN {data.TESTBANK_TAN} for the dollar pocket; three accounts, none linked"
    )


def _last_booking(engine: Engine) -> date:
    with engine.connect() as conn:
        visa = int(
            conn.execute(
                text("SELECT id FROM account WHERE name = :n"), {"n": "Visa Karte" + data.SUFFIX}
            ).scalar_one()
        )
        last_on: date = conn.execute(
            text(
                "SELECT max(booked_on) FROM ledger_entry WHERE account_id = :a AND balance_record_id IS NULL"
            ),
            {"a": visa},
        ).scalar_one()
    return last_on


def _document_json(d: data.DocScenario, last_on: date) -> dict[str, Any]:
    return {
        "provider": d.provider,
        "external_id": d.external_id,
        "occurred_on": (last_on - timedelta(days=d.ago)).isoformat(),
        "total_minor": d.total,
        "currency": d.currency,
        "merchant_name": d.merchant,
        "title": d.title,
        "lines": [{"description": x.description, "amount_minor": x.amount, "qty": x.qty} for x in d.lines],
    }


def make_rules(engine: Engine, out: list[str]) -> None:
    """The named rules of `dev_seed_data.RULES`, through the real operation: previewed first, then
    written with the preview's count (spec §5.9). Needs the categories and payees `classify` made."""
    with engine.connect() as conn:
        account = {
            key: int(
                conn.execute(
                    text("SELECT id FROM account WHERE name = :n"), {"n": name + data.SUFFIX}
                ).scalar_one()
            )
            for key, name, _kind, _ref in data.ACCOUNTS
        }
        payee = {str(n): int(i) for n, i in conn.execute(text("SELECT name, id FROM payee"))}
        category = {str(n): int(i) for n, i in conn.execute(text("SELECT name, id FROM category"))}
    made = 0
    for r in data.RULES:
        target = {"counter_account": account, "payee": payee, "category": category}[r.sets].get(r.target)
        if target is None:
            continue  # the vocabulary it names is not there (--no-classify, or already changed)
        # a payee condition names its payee; the rule stores the id
        conditions = [(f, o, str(payee.get(v)) if f == "payee" else v) for f, o, v in r.conditions]
        if any(f == "payee" and v == "None" for f, _o, v in conditions):
            continue  # the payee it names is not there
        draft = RuleDraft(
            name=r.name,
            sets=r.sets,
            counter_account_id=target if r.sets == "counter_account" else None,
            payee_id=target if r.sets == "payee" else None,
            category_id=target if r.sets == "category" else None,
            conditions=tuple(Condition(f, o, v) for f, o, v in conditions),  # type: ignore[arg-type]
            priority=r.priority,
        )
        preview = create_rule(engine, draft, dry_run=True, limit=1).preview
        create_rule(engine, draft, expected_count=preview.matches.total, limit=1)
        made += 1
    out.append(f"{made} named rules (through the rule operation, previewed first)")


def reset(engine: Engine) -> None:
    """Remove everything the seed created. Documented SQL cleanup (see the module docstring)."""
    marker = {"n": len(data.SUFFIX), "m": data.SUFFIX}
    with engine.begin() as conn:
        lock_settle_exclusive(conn)
        ids = [
            int(r)
            for r in conn.execute(text("SELECT id FROM account WHERE right(name, :n) = :m"), marker).scalars()
        ]
        # the accounts a seeded login was linked to by hand (the Testbank's, added from its discovery)
        # carry no marker but are its test data: they go with it
        linked = conn.execute(
            text(
                "SELECT account_id FROM account_source WHERE importer_instance_id IN"
                " (SELECT id FROM importer_instance WHERE right(label, :n) = :m)"
            ),
            marker,
        ).scalars()
        ids = sorted({*ids, *(int(r) for r in linked)})
        conn.execute(
            text("DELETE FROM rule WHERE name = ANY(:n)"),
            {"n": [r.name for r in data.RULES]},
        )
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
        # documents belong to no account: their entries are gone, so they, their runs and instance can go
        instances = "SELECT id FROM importer_instance WHERE right(label, :n) = :m"
        conn.execute(
            text(f"DELETE FROM external_document WHERE importer_instance_id IN ({instances})"), marker
        )  # noqa: S608
        conn.execute(text(f"DELETE FROM import_run WHERE importer_instance_id IN ({instances})"), marker)  # noqa: S608
        conn.execute(text("DELETE FROM importer_instance WHERE right(label, :n) = :m"), marker)
        conn.execute(
            text("DELETE FROM payee WHERE name = ANY(:n)"),
            {"n": [p.name for p in data.PAYEES]},
        )
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


def seed(
    engine: Engine,
    *,
    months: int,
    seed_value: int,
    do_classify: bool,
    today: date,
    test_importers: bool = False,
) -> list[str]:
    out: list[str] = ["seeding SYNTHETIC data through the real pipeline"]
    # With the transfer cases the exports end a few days early: those legs are a later delivery, after
    # every reported balance, and still booked before today.
    export_day = today - timedelta(days=_TRANSFER_TAIL_DAYS) if do_classify else today
    plan = data.build_plan(seed=seed_value, end=export_day, months=months)
    run_pipeline(engine, plan, export_day, out)
    if do_classify:
        classify(engine, seed_value, out)
        make_rules(engine, out)
        transfer_cases(engine, out)
        document_cases(engine, today, out)
    if test_importers:
        testbank_instance(engine, today, out)
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
    configure_classifiers(default_classifiers)  # the composition root of this script
    configure_rule_tools(default_rule_tools())
    register_document_importers({data.DOC_IMPORTER: TestDocumentImporter()})
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
            test_importers=cfg.enable_test_importers,
        ):
            print(line)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
