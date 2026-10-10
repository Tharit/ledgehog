"""`unconfirmed` is judged per unit (spec §6), settling still judges per entry."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.core.settle.settle import settle
from tests.core.ingest.conftest import ledger  # noqa: F401  (fixture)
from tests.core.ingest.dup_helpers import Ledger


@pytest.mark.xfail(
    strict=True,
    reason="spec §6 judges unconfirmed per unit (siblings and transfer partner, transitively); "
    "settling judges per entry until steps 7/8",
)
def test_a_transfer_partner_of_an_unconfirmed_leg_is_unconfirmed_too(ledger: Ledger) -> None:  # noqa: F811
    _, a, _, b = ledger.transfer_pair()
    history = {"category": {"pass": "history", "basis": {"from": "similar"}}}
    pair_key = ledger.one("SELECT derivation FROM ledger_entry WHERE id = :i", i=a).derivation
    ledger.tx(
        lambda c: c.execute(
            text("UPDATE ledger_entry SET derivation = CAST(:d AS jsonb) WHERE id = :i"),
            {"d": json.dumps({**pair_key, **history}), "i": a},
        )
    )
    settle(ledger.engine)
    flags = {r.id: list(r.review_flags) for r in ledger.q("SELECT id, review_flags FROM ledger_entry")}
    assert "unconfirmed" in flags[a]
    assert "unconfirmed" in flags[b]
