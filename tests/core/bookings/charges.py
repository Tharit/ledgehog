"""Builders for the transfer-booking tests and the units tests that preview them: clearance accounts,
charges on checking, rules that decide them, and reading the bookings back."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.accounts import create_account
from app.core.resolution.confirmed import load_confirmed_ids
from tests.core.units.scene import D, Scene
from tests.invariants.helpers import make_entry, make_source

__all__ = [
    "BOOKING_KEY",
    "IBAN",
    "START",
    "booking_entries",
    "booking_of",
    "charge",
    "clearance",
    "confirmed",
    "rule_to",
]

BOOKING_KEY = {"pass": "booking", "basis": {}}
IBAN = "DE89 3704 0044 0532 0130 00"
START = date(2026, 1, 31)


def clearance(
    scene: Scene, name: str = "Amazon.de", *, currency: str = "EUR", external_ref: str | None = None
) -> int:
    return create_account(
        scene.engine,
        name=name,
        kind="clearance",
        currency=currency,
        start_date=START,
        external_ref=external_ref,
    )


def rule_to(scene: Scene, account: int, counterparty: str = "Amazon") -> None:
    scene.tx(
        lambda c: c.execute(
            text(
                "INSERT INTO rule (sets, counter_account_id, conditions, name)"
                " VALUES ('counter_account', :a, CAST(:cond AS jsonb), :n)"
            ),
            {
                "a": account,
                "cond": json.dumps([{"field": "counterparty_name", "op": "equals", "value": counterparty}]),
                "n": f"to {account} {counterparty}",
            },
        )
    )


def charge(
    scene: Scene,
    amount: int = -4997,
    *,
    counterparty: str | None = "Amazon",
    ref: str | None = None,
    on: date = D,
    purpose: str | None = "AMZN Mktp",
    instructed: tuple[int, str] | None = None,
    currency: str = "EUR",
    account: int | None = None,
    authored: bool = False,
) -> int:
    """An imported (or authored) charge on checking, untyped; its entry id."""
    columns: dict[str, Any] = {"counterparty_name": counterparty, "counterparty_ref": ref}
    if instructed is not None:
        columns.update(instructed_amount=instructed[0], instructed_currency=instructed[1])

    def make(c: Any) -> int:
        acct = account or scene.checking
        src = make_source(
            c,
            acct,
            amount=amount,
            booked_on=on,
            purpose=purpose,
            currency=currency,
            importer=None if authored else "test",
            run_id=None if authored else scene.run if acct == scene.checking else None,
            columns=columns,
        )
        return make_entry(c, src, type=None)

    return int(scene.tx(make))


def booking_of(scene: Scene, entry_id: int) -> Any | None:
    rows = scene.q("SELECT * FROM source_transaction WHERE source_id = :s", s=f"transfer:{entry_id}")
    return rows[0] if rows else None


def booking_entries(scene: Scene, entry_id: int) -> list[Any]:
    return scene.q(
        "SELECT e.* FROM ledger_entry e JOIN source_transaction s ON s.id = e.source_transaction_id"
        " WHERE s.source_id = :s ORDER BY e.id",
        s=f"transfer:{entry_id}",
    )


def confirmed(scene: Scene, *ids: int) -> bool:
    with scene.engine.connect() as conn:
        done = load_confirmed_ids(conn)
    return all(i in done for i in ids)
