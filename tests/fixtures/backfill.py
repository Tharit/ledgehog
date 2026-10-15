"""A backfill-sized ledger: a year of history, thousands of unconfirmed entries.

Generated deterministically from a seed (`random.Random`, no global state, no clock),
and loaded through legal SQL in ONE transaction per call: per account an `ok` import
run, its source transactions (bulk `executemany`) and then one entry per source row
(`INSERT ... SELECT`), so the deferred triggers pass at commit. Identity comes from
`app.core.ingest.identity`, exactly as ingest would assign it: checking and card rows
carry a source-assigned id, the others a content hash with its ordinal.

By default nothing is classified: every entry is a plain movement with no type, category or
derivation, i.e. `unclassified` once settled (no voters for history, no rules). The text
vocabulary is small and repeats, so a history key has something to group.

`confirmed_share > 0` is the settled-ledger variant: that share of the entries (chosen by the
seeded stream) is a confirmed flow of its merchant's category and payee with `user` keys, so
history has voters; the rest stay unconfirmed, and a few merchants also get rules (a payee and a
category rule each), so settling has standing decisions to make too.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, text

from app.core.ingest.identity import ContentHash, SourceId, assign_ordinals, identity_of
from app.core.plugins.importer import IncomingRow

END = date(2025, 12, 31)

# (name, kind, currency, identity by: "source_id" | "hash")
ACCOUNT_PLAN: tuple[tuple[str, str, str, str], ...] = (
    ("Checking", "checking", "EUR", "source_id"),
    ("Credit card", "card", "EUR", "source_id"),
    ("PayPal", "paypal", "EUR", "hash"),
    ("Travel card", "card", "USD", "hash"),
    ("Savings", "savings", "EUR", "hash"),
    ("Cash", "cash", "EUR", "hash"),
)

# counterparty name, typical expense in minor units (low, high), purpose variants
_MERCHANTS: tuple[tuple[str, int, int, tuple[str, ...]], ...] = (
    ("REWE Markt", 800, 9500, ("Kartenzahlung REWE", "REWE SAGT DANKE")),
    ("Lidl", 500, 6500, ("Kartenzahlung LIDL", "LIDL DIENSTLEISTUNG")),
    ("Aldi Sued", 600, 7000, ("ALDI SUED Einkauf",)),
    ("dm drogerie", 300, 4500, ("DM FIL 1234", "dm-drogerie markt")),
    ("Deutsche Bahn", 1500, 12000, ("Fahrkarte DB", "Bahn Ticket Online")),
    ("Shell", 3000, 9000, ("SHELL TANKSTELLE", "Tanken Shell")),
    ("Amazon", 500, 15000, ("AMZN Mktp DE", "Amazon.de Bestellung")),
    ("Netflix", 1299, 1299, ("NETFLIX.COM",)),
    ("Spotify", 1099, 1099, ("Spotify AB",)),
    ("Vodafone", 3999, 3999, ("Vodafone Mobilfunk Rechnung",)),
    ("Stadtwerke", 8500, 8500, ("Abschlag Strom",)),
    ("Hausverwaltung", 95000, 95000, ("Miete Wohnung",)),
    ("Restaurant Roma", 1800, 9000, ("Kartenzahlung Roma", "RISTORANTE ROMA")),
    ("Baeckerei Mueller", 200, 1800, ("Kartenzahlung Baeckerei",)),
    ("Apotheke am Markt", 400, 5500, ("APOTHEKE", "Apotheke am Markt Kartenzahlung")),
    ("IKEA", 1500, 40000, ("IKEA Deutschland",)),
    ("Zalando", 2500, 18000, ("Zalando Payments",)),
    ("Fitnessstudio", 2990, 2990, ("Mitgliedsbeitrag",)),
    ("Versicherung", 4500, 4500, ("Haftpflicht Beitrag",)),
    ("Cafe Central", 300, 2200, ("Kartenzahlung Cafe",)),
)
_INCOME: tuple[tuple[str, int, int, tuple[str, ...]], ...] = (
    ("Arbeitgeber GmbH", 280000, 280000, ("Gehalt",)),
    ("Finanzamt", 5000, 90000, ("Erstattung",)),
    ("Marktplatz Verkauf", 1000, 12000, ("Verkauf Artikel",)),
)


# `transfers > 0` adds that many transfer legs (about) on top of the plain rows, across the EUR accounts:
# 40% of them in pairs that settling will still make (one leg decided with a counter-account, the other
# only typed), 25% in pairs already made and confirmed, and 35% unpaired legs, half of them waiting on a
# counter-account that is synced (an import instance linked to it, covered through the end of the year,
# so a leg of the last days has not yet been delivered its partner) and half unmatched.
_PAIR_TO_MAKE, _PAIR_MADE = 0.40, 0.25
_USER = {"type": {"pass": "user"}, "counter_account": {"pass": "user"}}
_USER_PAIR = {**_USER, "counterpart": {"pass": "user"}}


@dataclass(frozen=True)
class BackfillSummary:
    seed: int
    account_ids: tuple[int, ...]
    account_currencies: tuple[str, ...]
    source_count: int
    entry_count: int
    first_booked: date
    last_booked: date
    run_ids: tuple[int, ...]
    transfer_count: int = 0  # the transfer legs `transfers` added (part of source_count and entry_count)


def _fake_ref(name: str) -> str:
    # stable per merchant within a build: derived from the name, not from the stream
    digits = sum(ord(c) * (i + 1) for i, c in enumerate(name)) % 10**10
    return f"DE89370400{digits:010d}"


def _rows_for(
    rng: random.Random, currency: str, count: int, first: date, days: int, by: str
) -> list[IncomingRow]:
    rows: list[IncomingRow] = []
    for n in range(count):
        income = rng.random() < 0.07
        name, low, high, purposes = rng.choice(_INCOME if income else _MERCHANTS)
        minor = rng.randint(low, high)
        amount = minor if income else -minor
        rows.append(
            IncomingRow(
                amount_minor=amount,
                currency=currency,
                booked_on=first + timedelta(days=rng.randrange(days)),
                source_format="csv:backfill",
                raw={"n": n},
                counterparty_ref=_fake_ref(name),
                counterparty_name=name,
                purpose=rng.choice(purposes),
                source_id=f"ref-{rng.getrandbits(48):012x}-{n}" if by == "source_id" else None,
            )
        )
    rows.sort(key=lambda r: r.booked_on)
    return rows


RULE_MERCHANTS = ("REWE Markt", "Netflix", "Deutsche Bahn", "Arbeitgeber GmbH")


def _equals_name(name: str) -> str:
    return json.dumps([{"field": "counterparty_name", "op": "equals", "value": name}])


def _seed_dimensions(conn: Any) -> tuple[dict[str, int], dict[str, int]]:
    """A category and a payee per merchant, and a payee and category rule for `RULE_MERCHANTS`."""
    category: dict[str, int] = {}
    payee: dict[str, int] = {}
    for names, kind in ((_MERCHANTS, "expense"), (_INCOME, "income")):
        for name, *_ in names:
            category[name] = conn.execute(
                text("INSERT INTO category (name, kind) VALUES (:n, :k) RETURNING id"),
                {"n": f"Cat {name}", "k": kind},
            ).scalar_one()
            payee[name] = conn.execute(
                text("INSERT INTO payee (name) VALUES (:n) RETURNING id"), {"n": name}
            ).scalar_one()
    for name in RULE_MERCHANTS:
        conn.execute(
            text(
                "INSERT INTO rule (name, sets, payee_id, conditions)"
                " VALUES (:n, 'payee', :p, CAST(:m AS jsonb))"
            ),
            {"n": f"{name} payee", "p": payee[name], "m": _equals_name(name)},
        )
        conn.execute(
            text(
                "INSERT INTO rule (name, sets, category_id, conditions)"
                " VALUES (:n, 'category', :c, CAST(:m AS jsonb))"
            ),
            {"n": f"{name} category", "c": category[name], "m": _equals_name(name)},
        )
    return category, payee


_CONFIRM = text(
    "UPDATE ledger_entry AS e SET type = 'flow', category_id = v.c, payee_id = v.p,"
    " derivation = CAST(v.d AS jsonb)"
    " FROM unnest(CAST(:ids AS bigint[]), CAST(:cats AS bigint[]), CAST(:payees AS bigint[]),"
    " CAST(:ds AS text[])) AS v(id, c, p, d) WHERE e.id = v.id"
)
_USER_KEYS = json.dumps({k: {"pass": "user"} for k in ("type", "payee", "category")})


_INSERT_SOURCE = text(
    "INSERT INTO source_transaction (importer, import_run_id, account_id, source_id, content_hash,"
    " source_format, amount, currency, booked_on, counterparty_ref, counterparty_name, purpose, raw)"
    " VALUES ('csv', :run, :account, :source_id, :content_hash, :source_format, :amount, :currency,"
    " :booked_on, :cp_ref, :cp_name, :purpose, CAST(:raw AS jsonb))"
)


_TRANSFER_SOURCE = text(
    "INSERT INTO source_transaction (importer, import_run_id, account_id, source_id, source_format,"
    " amount, currency, booked_on, counterparty_name, purpose, raw)"
    " VALUES ('csv', :run, :account, :source_id, 'csv:backfill', :amount, 'EUR', :booked_on,"
    " 'Umbuchung', :purpose, CAST('{}' AS jsonb))"
)
_TRANSFER_ENTRY = text(
    "INSERT INTO ledger_entry (source_transaction_id, account_id, amount, currency, booked_on, type,"
    " counter_account_id, derivation)"
    " SELECT s.id, s.account_id, s.amount, s.currency, s.booked_on, 'transfer', v.counter,"
    " CAST(v.derivation AS jsonb)"
    " FROM unnest(CAST(:sids AS text[]), CAST(:counters AS bigint[]), CAST(:derivations AS text[]))"
    " AS v(sid, counter, derivation) JOIN source_transaction s ON s.source_id = v.sid"
)
_PAIRED_LEGS = (
    "SELECT ea.id AS ea, eb.id AS eb FROM unnest(CAST(:a AS text[]), CAST(:b AS text[])) AS v(a, b)"
    " JOIN source_transaction sa ON sa.source_id = v.a"
    " JOIN ledger_entry ea ON ea.source_transaction_id = sa.id"
    " JOIN source_transaction sb ON sb.source_id = v.b"
    " JOIN ledger_entry eb ON eb.source_transaction_id = sb.id"
)
_TRANSFER_PAIRS = text(
    "UPDATE ledger_entry AS e SET counterpart_entry_id = m.partner FROM ("
    f" SELECT ea AS id, eb AS partner FROM ({_PAIRED_LEGS}) AS p"
    f" UNION ALL SELECT eb, ea FROM ({_PAIRED_LEGS}) AS q) AS m WHERE e.id = m.id"
)


def _add_transfers(
    conn: Any,
    rng: random.Random,
    count: int,
    accounts: list[int],
    runs: list[int],
    currencies: list[str],
    first: date,
    days: int,
) -> int:
    """Add about `count` transfer legs (see the comment above `BackfillSummary`); returns how many."""
    eur = [i for i, c in enumerate(currencies) if c == "EUR"]
    if len(eur) < 3:
        raise ValueError("transfers need three EUR accounts (two to pair, one synced to wait on)")
    synced = eur[-1]  # the account whose coverage legs wait on
    instance = conn.execute(
        text(
            "INSERT INTO importer_instance (importer, label, access)"
            " VALUES ('csv', 'Backfill sync', 'shared') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO account_source (account_id, importer_instance_id, external_ref)"
            " VALUES (:a, :i, 'backfill')"
        ),
        {"a": accounts[synced], "i": instance},
    )
    others = [i for i in eur if i != synced]
    sources: list[dict[str, Any]] = []
    entries: list[tuple[str, int | None, str]] = []  # (source id, counter-account, derivation)
    made: list[tuple[str, str]] = []
    n = 0

    def leg(account: int, amount: int, on: date, counter: int | None, keys: dict[str, Any]) -> str:
        nonlocal n
        n += 1
        sid = f"xfer-{n}"
        sources.append(
            {
                "run": runs[account],
                "account": accounts[account],
                "source_id": sid,
                "amount": amount,
                "booked_on": on,
                "purpose": f"Umbuchung {n}",
            }
        )
        entries.append((sid, None if counter is None else accounts[counter], json.dumps(keys)))
        return sid

    def day() -> date:
        return first + timedelta(days=rng.randrange(days))

    to_make, already = round(count * _PAIR_TO_MAKE / 2), round(count * _PAIR_MADE / 2)
    for k in range(to_make + already):
        a, b = rng.sample(others, 2)
        amount, on = rng.randint(1000, 500_000), day()
        partner_on = on + timedelta(days=rng.randrange(4))
        if k < to_make:
            leg(a, -amount, on, b, _USER)  # decided; its partner is only typed, settling pairs them
            leg(b, amount, partner_on, None, {"type": {"pass": "user"}})
        else:
            x = leg(a, -amount, on, b, _USER_PAIR)
            y = leg(b, amount, partner_on, a, _USER_PAIR)
            made.append((x, y))
    for k in range(count - 2 * (to_make + already)):
        a = rng.choice(others)
        amount = rng.randint(1000, 500_000) + 7  # an amount no other leg has
        if k % 2 == 0:  # waiting: its counter-account is synced and not yet past the leg's window
            leg(a, -amount, END - timedelta(days=rng.randrange(5)), synced, _USER)
        else:  # unmatched: the counter-account is unsynced, or there is none
            counter = rng.choice([*others, None])
            if counter is None or counter == a:
                leg(a, -amount, day(), None, {"type": {"pass": "user"}})
            else:
                leg(a, -amount, day(), counter, _USER)
    conn.execute(_TRANSFER_SOURCE, sources)
    conn.execute(
        _TRANSFER_ENTRY,
        {
            "sids": [e[0] for e in entries],
            "counters": [e[1] for e in entries],
            "derivations": [e[2] for e in entries],
        },
    )
    if made:
        conn.execute(_TRANSFER_PAIRS, {"a": [x for x, _ in made], "b": [y for _, y in made]})
    return len(sources)


def build_backfill(
    engine: Engine,
    *,
    seed: int = 20260101,
    accounts: int = 4,
    months: int = 12,
    rows_per_account: int = 2000,
    confirmed_share: float = 0.0,
    transfers: int = 0,
) -> BackfillSummary:
    """Load the fixture into an empty ledger in one transaction and return what was built."""
    if not 1 <= accounts <= len(ACCOUNT_PLAN):
        raise ValueError(f"accounts must be 1..{len(ACCOUNT_PLAN)}, got {accounts}")
    rng = random.Random(seed)
    days = months * 30
    first = END - timedelta(days=days - 1)
    account_ids: list[int] = []
    run_ids: list[int] = []
    currencies: list[str] = []
    total = 0
    with engine.begin() as conn:
        category, payee = _seed_dimensions(conn) if confirmed_share > 0 else ({}, {})
        for name, kind, currency, by in ACCOUNT_PLAN[:accounts]:
            account = conn.execute(
                text("INSERT INTO account (name, kind, currency) VALUES (:n, :k, :c) RETURNING id"),
                {"n": name, "k": kind, "c": currency},
            ).scalar_one()
            run = conn.execute(
                text(
                    "INSERT INTO import_run (importer, emits, account_id, status, finished_at,"
                    " covered_from, covered_through) VALUES ('csv', 'transactions', :a, 'ok',"
                    " clock_timestamp(), :f, :t) RETURNING id"
                ),
                {"a": account, "f": first, "t": END},
            ).scalar_one()
            rows = _rows_for(rng, currency, rows_per_account, first, days, by)
            params: list[dict[str, Any]] = []
            for row, ordinal in zip(rows, assign_ordinals(rows), strict=True):
                ident = identity_of(row, ordinal)
                params.append(
                    {
                        "run": run,
                        "account": account,
                        "source_id": ident.value if isinstance(ident, SourceId) else None,
                        "content_hash": ident.hex() if isinstance(ident, ContentHash) else None,
                        "source_format": row.source_format,
                        "amount": row.amount_minor,
                        "currency": row.currency,
                        "booked_on": row.booked_on,
                        "cp_ref": row.counterparty_ref,
                        "cp_name": row.counterparty_name,
                        "purpose": row.purpose,
                        "raw": json.dumps(row.raw),
                    }
                )
            conn.execute(_INSERT_SOURCE, params)
            conn.execute(
                text(
                    "INSERT INTO ledger_entry (source_transaction_id, account_id, amount, currency,"
                    " booked_on, value_on) SELECT id, account_id, amount, currency, booked_on, value_on"
                    " FROM source_transaction WHERE account_id = :a ORDER BY id"
                ),
                {"a": account},
            )
            if confirmed_share > 0:
                picked = [
                    (r.id, r.counterparty_name)
                    for r in conn.execute(
                        text(
                            "SELECT e.id, s.counterparty_name FROM ledger_entry e"
                            " JOIN source_transaction s ON s.id = e.source_transaction_id"
                            " WHERE e.account_id = :a ORDER BY e.id"
                        ),
                        {"a": account},
                    )
                    if rng.random() < confirmed_share
                ]
                conn.execute(
                    _CONFIRM,
                    {
                        "ids": [i for i, _ in picked],
                        "cats": [category[n] for _, n in picked],
                        "payees": [payee[n] for _, n in picked],
                        "ds": [_USER_KEYS] * len(picked),
                    },
                )
            account_ids.append(account)
            run_ids.append(run)
            currencies.append(currency)
            total += len(rows)
        added = (
            _add_transfers(conn, rng, transfers, account_ids, run_ids, currencies, first, days)
            if transfers
            else 0
        )
        total += added
    return BackfillSummary(
        seed=seed,
        account_ids=tuple(account_ids),
        account_currencies=tuple(currencies),
        source_count=total,
        entry_count=total,
        first_booked=first,
        last_booked=END,
        run_ids=tuple(run_ids),
        transfer_count=added,
    )
