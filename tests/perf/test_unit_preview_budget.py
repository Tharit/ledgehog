"""Opening a unit and committing it stay inside their budgets on a backfill-sized ledger (spec §6).

Preview: one unit opened with no draft, a draft with a split and a drafted category, and a re-resolve of
the whole unit, each on the 8,000-entry ledger with nothing confirmed and on the ~70% confirmed one (5,600
history voters). Commit: one unit accepted, then the settle that follows (the commit and its settle are
timed together against the settle budget, since that is what the user waits for). Numbers are printed (run
with -s)."""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Callable

import pytest
from sqlalchemy import text

from app.core.settle.settle import settle
from app.core.units.commit import commit_unit
from app.core.units.draft import DraftEntry, FieldDraft, PairingDraft, UnitDraft
from app.core.units.preview import preview_unit
from app.core.units.read import review_queue
from tests.perf.budget import BUDGET_SECONDS, UNIT_PREVIEW_BUDGET_SECONDS
from tests.perf.conftest import Backfill
from tests.perf.test_settle_budget import Stats

pytestmark = pytest.mark.perf
REPEATS = 7


def _anchors(backfill: Backfill, n: int) -> list[int]:
    with backfill.engine.connect() as conn:
        queue = review_queue(conn, limit=n, section="pending_review")
    return [u.anchor_entry_id for u in queue.sections[0].units]


def _drafts(anchor: int) -> dict[str, UnitDraft]:
    return {
        "opened (no draft)": UnitDraft(anchor),
        "a split and a drafted category": UnitDraft(
            anchor,
            [
                DraftEntry(anchor, category=FieldDraft("fixed", None)),
                DraftEntry(-1, amount=-1, source_entry_id=anchor),
            ],
        ),
        "the whole unit re-resolved": UnitDraft(anchor, reresolve_all=True),
    }


def _within_budget(backfill: Backfill, label: str) -> None:
    anchors = _anchors(backfill, 5)
    worst = 0.0
    for name in _drafts(anchors[0]):
        samples: list[float] = []
        for i in range(REPEATS):
            draft = _drafts(anchors[i % len(anchors)])[name]
            started = time.perf_counter()
            plan = preview_unit(backfill.engine, draft)
            samples.append(time.perf_counter() - started)
            assert plan.rows
        stats = Stats.of(samples)
        print(f"[perf] unit preview {label}, {name}: {stats}")
        worst = max(worst, stats.max)
        budget = UNIT_PREVIEW_BUDGET_SECONDS
        assert stats.max <= budget, f"{label}, {name}: {stats}"
    print(f"[perf] unit preview {label}: worst {worst * 1000:.0f} ms (budget {budget} s)")


def test_preview_within_budget_all_unconfirmed(backfill: Backfill) -> None:
    _within_budget(backfill, "all unconfirmed")


def test_preview_within_budget_with_most_entries_confirmed(backfill_settled: Backfill) -> None:
    _within_budget(backfill_settled, "70% confirmed")


def test_commit_then_settle_within_the_settle_budget(backfill_settled: Backfill) -> None:
    settle(backfill_settled.engine)  # the first settle after the load resolves everything: not what is timed
    anchors = _anchors(backfill_settled, REPEATS)
    samples: list[float] = []
    for anchor in anchors:
        with backfill_settled.engine.connect() as conn:
            versions = {
                int(r.id): int(r.version)
                for r in conn.exec_driver_sql("SELECT id, version FROM ledger_entry WHERE id = %s", (anchor,))
            }
        started = time.perf_counter()
        result = commit_unit(backfill_settled.engine, UnitDraft(anchor, versions=versions))
        samples.append(time.perf_counter() - started)
        assert result.settle.error is None
    stats = Stats.of(samples)
    print(f"[perf] unit commit + settle, 70% confirmed: {stats}")
    assert stats.max <= BUDGET_SECONDS, f"{stats} exceeds {BUDGET_SECONDS} s"


__all__: list[Callable[..., object]] = []


# ---- transfer legs: offers and the ledger-wide simulation of settling (spec §5.7, step 8d) ----------------


def _unpaired_legs(backfill: Backfill, n: int, *, with_counter: bool) -> list[int]:
    cond = "IS NOT NULL" if with_counter else "IS NULL"
    with backfill.engine.connect() as conn:
        return [
            int(i)
            for i in conn.exec_driver_sql(
                "SELECT id FROM ledger_entry WHERE type = 'transfer' AND counterpart_entry_id IS NULL"
                f" AND counter_account_id {cond} ORDER BY id LIMIT {int(n)}"
            ).scalars()
        ]


def _measure_offers(backfill: Backfill, label: str, anchors: list[int]) -> float:
    samples: list[float] = []
    offered = 0
    for anchor in anchors:
        started = time.perf_counter()
        plan = preview_unit(backfill.engine, UnitDraft(anchor), window_days=90)
        samples.append(time.perf_counter() - started)
        offered += sum(len(t.offers) for t in plan.transfers.values())
        assert anchor in plan.transfers
    stats = Stats.of(samples)
    print(f"[perf] unit preview with offers, leg {label} ({offered} offers over {len(anchors)}): {stats}")
    assert stats.max <= UNIT_PREVIEW_BUDGET_SECONDS, f"{label}: {stats}"
    return stats.max


def test_preview_of_transfer_legs_with_offers_within_budget(backfill_transfers: Backfill) -> None:
    """The transfer ledger (800 legs: unpaired ones waiting and unmatched): a preview loads every unpaired
    leg of the ledger, simulates pairing over them and reads the pool of offers around the unit's legs, the
    widest window (90 days) included. Once for legs that know their counter-account, once for legs that do
    not (offers on every account the currency rule allows: the widest pool); the latter are made by
    clearing the counter-account of a few legs for the duration of the test."""
    settle(backfill_transfers.engine)  # the fixture as a settled ledger: what the user opens units in
    known = _unpaired_legs(backfill_transfers, REPEATS, with_counter=True)
    assert known
    worst = _measure_offers(backfill_transfers, "with a counter-account", known)
    engine = backfill_transfers.engine
    with engine.begin() as conn:
        saved = conn.execute(
            text("SELECT id, counter_account_id, derivation FROM ledger_entry WHERE id = ANY(:i)"),
            {"i": known},
        ).all()
        conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
        conn.execute(
            text(
                "UPDATE ledger_entry SET counter_account_id = NULL,"
                " derivation = derivation - 'counter_account' WHERE id = ANY(:i)"
            ),
            {"i": known},
        )
    try:
        worst = max(worst, _measure_offers(backfill_transfers, "without a counter-account", known))
    finally:
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
            for r in saved:
                conn.execute(
                    text(
                        "UPDATE ledger_entry SET counter_account_id = :c, derivation = CAST(:d AS jsonb)"
                        " WHERE id = :i"
                    ),
                    {"c": r.counter_account_id, "d": json.dumps(r.derivation), "i": r.id},
                )
    print(
        f"[perf] unit preview with offers: worst {worst * 1000:.0f} ms"
        f" (budget {UNIT_PREVIEW_BUDGET_SECONDS} s)"
    )


def test_the_offers_pool_is_served_by_the_date_indexes(backfill_transfers: Backfill) -> None:
    """EXPLAIN of the pool statement: no sequential scan of the ledger (ix_le_date, ix_le_account_date)."""
    from app.core.units.stored import _POOL

    with backfill_transfers.engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT booked_on, amount, account_id, counter_account_id FROM ledger_entry"
            " WHERE type = 'transfer' AND counterpart_entry_id IS NULL ORDER BY id LIMIT 1"
        ).one()
        params = {
            "dates": [row.booked_on, row.booked_on],
            "signs": [-1 if row.amount < 0 else 1, 1],
            "accounts": [row.account_id, row.account_id],
            "counters": [row.counter_account_id, None],  # one leg with a counter-account, one without
            "cap": 90,
            "skip": [0],
        }
        plan = "\n".join(
            str(r[0])
            for r in conn.execute(text("EXPLAIN " + str(_POOL)), params).all()  # noqa: S608
        )
    print(f"[perf] pool plan:\n{plan}")
    assert "Seq Scan on ledger_entry" not in plan, plan


# ---- picking a partner (spec §5.7, step 8e) ----------------------------------------------------------------


def test_preview_and_commit_of_a_pick_within_budget(backfill_transfers: Backfill) -> None:
    """A pick brings the partner's closure into the unit (and the former partners'): the preview of a draft
    that picks the first open offer, with the widest window, then the commit of one pick plus the settle."""
    settle(backfill_transfers.engine)
    engine = backfill_transfers.engine
    legs = _unpaired_legs(backfill_transfers, 40, with_counter=True)
    drafts: list[UnitDraft] = []
    for anchor in legs:
        opened = preview_unit(engine, UnitDraft(anchor), window_days=90)
        offers = [o for o in opened.transfers[anchor].offers if o.entry_id is not None]
        if opened.transfers[anchor].state != "unmatched" or not offers:
            continue
        drafts.append(
            UnitDraft(
                anchor,
                [DraftEntry(anchor, pairing=PairingDraft("pick", offers[0].entry_id))],
                window_days=90,
            )
        )
        if len(drafts) == REPEATS:
            break
    assert drafts, "no unpaired leg with an offer in the fixture"
    samples: list[float] = []
    for draft in drafts:
        started = time.perf_counter()
        plan = preview_unit(engine, draft)
        samples.append(time.perf_counter() - started)
        assert plan.row(draft.anchor_entry_id).counterpart_entry_id is not None
    stats = Stats.of(samples)
    print(f"[perf] unit preview of a pick ({len(drafts)} legs): {stats}")
    assert stats.max <= UNIT_PREVIEW_BUDGET_SECONDS, f"{stats}"
    # an open offer of another amount is the usual pick here (exact ones are paired by settling): the split
    # the preview suggests makes the pair equal
    draft = drafts[0]
    plan = preview_unit(engine, draft)
    for problem in plan.problems:
        assert problem.code == "pair_unequal" and problem.suggested_split is not None
        split = DraftEntry(
            -1, amount=problem.suggested_split.amount, source_entry_id=problem.suggested_split.source_entry_id
        )
        draft = dataclasses.replace(draft, entries=[*draft.entries, split])
        plan = preview_unit(engine, draft)
    assert not plan.problems
    started = time.perf_counter()
    result = commit_unit(engine, dataclasses.replace(draft, versions=dict(plan.versions)))
    took = time.perf_counter() - started
    print(f"[perf] unit commit of a pick + settle: {took * 1000:.0f} ms")
    assert result.settle.error is None and took <= BUDGET_SECONDS
