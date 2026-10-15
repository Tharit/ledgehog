"""Settle step 4, pairing transfer legs (architecture §5.2, spec §5.7, I10, I18, I33, I37).

Every unpaired transfer leg (a movement entry typed `transfer` with no counterpart, its source not a
duplicate) goes to the pure matcher (`core/matching`), which pairs them in date order. Each pair is
written in ONE set-based statement, under `ledger.settling`:

* `counterpart_entry_id` on both legs (structural, so versions move);
* `counter_account_id` = the partner's account on a leg that had none, and ONLY there (I10);
* the `counterpart` key `{"pass": "matcher_decision", "basis": {}}` on both legs, and on a leg that got
  its counter-account from the pair the key `{"pass": "matcher_decision", "basis": {"from": "counterpart"}}`.

The type is never touched. Pairing runs unnarrowed in every round (the work is proportional to the
unpaired legs) and is idempotent: legs left unpaired find no partner the second time (I37). A pair
stands once made: only unpaired legs are loaded. Whether the unit is then confirmed is decided by the
legs' other keys, in step 5. No lock is taken (a settle holds the settle lock exclusively).
"""

from __future__ import annotations

import json

from sqlalchemy import Connection, text

from app.core.ingest.identity import canonical_text
from app.core.matching import PAIR_BASIS, Leg, Pair, pair_all
from app.core.resolution.load import load_accounts
from app.core.settle.run import StepOutcome
from app.core.settle.window import matching_window_days

PAIR_KEY_VALUE: dict[str, object] = {"pass": "matcher_decision", "basis": {}}
PAIR_COUNTER_KEY_VALUE: dict[str, object] = {"pass": "matcher_decision", "basis": dict(PAIR_BASIS)}
PAIR_KEY = json.dumps(PAIR_KEY_VALUE)
PAIR_COUNTER_KEY = json.dumps(PAIR_COUNTER_KEY_VALUE)

_UNPAIRED = text(
    """
    SELECT e.id, e.account_id, e.currency, e.amount, e.booked_on, e.counter_account_id,
           s.end_to_end_id, s.instructed_amount, s.instructed_currency, s.purpose
      FROM ledger_entry AS e
      JOIN source_transaction AS s ON s.id = e.source_transaction_id
     WHERE e.type = 'transfer' AND e.counterpart_entry_id IS NULL AND s.duplicate_of IS NULL
     ORDER BY e.booked_on, e.id
    """
)

_WRITE = text(
    """
    UPDATE ledger_entry AS e
       SET counterpart_entry_id = v.partner,
           counter_account_id = COALESCE(e.counter_account_id, v.counter),
           derivation = e.derivation
                        || jsonb_build_object('counterpart', CAST(:pair_key AS jsonb))
                        || CASE WHEN e.counter_account_id IS NULL AND v.counter IS NOT NULL
                                THEN jsonb_build_object('counter_account', CAST(:counter_key AS jsonb))
                                ELSE '{}'::jsonb END
      FROM unnest(CAST(:ids AS bigint[]), CAST(:partners AS bigint[]), CAST(:counters AS bigint[]))
           AS v(id, partner, counter)
     WHERE e.id = v.id
    RETURNING e.id
    """
)


def load_unpaired_legs(conn: Connection) -> list[Leg]:
    """The unpaired transfer legs, in (booked_on, id) order, as the matcher reads them."""
    return [
        Leg(
            entry_id=r.id,
            account_id=r.account_id,
            currency=r.currency,
            amount=r.amount,
            booked_on=r.booked_on,
            counter_account_id=r.counter_account_id,
            end_to_end_id=r.end_to_end_id,
            instructed_amount=r.instructed_amount,
            instructed_currency=r.instructed_currency,
            purpose=canonical_text(r.purpose),
        )
        for r in conn.execute(_UNPAIRED)
    ]


def write_pairs(conn: Connection, pairs: list[Pair]) -> list[int]:
    """Both legs of every pair, in one statement; returns the ids written, ascending."""
    ids: list[int] = []
    partners: list[int] = []
    counters: list[int | None] = []
    for p in pairs:
        ids += [p.leg_id, p.partner_id]
        partners += [p.partner_id, p.leg_id]
        counters += [p.leg_counter_account, p.partner_counter_account]
    written = conn.execute(
        _WRITE,
        {
            "ids": ids,
            "partners": partners,
            "counters": counters,
            "pair_key": PAIR_KEY,
            "counter_key": PAIR_COUNTER_KEY,
        },
    ).scalars()
    return sorted(int(i) for i in written)


def pair_transfers_step(conn: Connection) -> StepOutcome:
    legs = load_unpaired_legs(conn)
    if len(legs) < 2:
        return StepOutcome()
    pairs = pair_all(legs, matching_window_days(conn), {a.id: a for a in load_accounts(conn)})
    if not pairs:
        return StepOutcome()
    return StepOutcome(touched=write_pairs(conn, pairs))
