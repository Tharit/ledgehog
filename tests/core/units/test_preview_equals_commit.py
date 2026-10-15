"""PROPERTY: the preview of a draft equals the stored state after a real commit and a real settle.

Hypothesis draws units (a plain flow, a split, a confirmed pair) and drafts over them (values, splits,
removals, conversions, re-resolving); a draft the preview finds invalid must be refused by the commit with
nothing written, and any other must leave exactly the previewed rows, keys, flags and states.
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from app.core.units.commit import CommitRefused
from app.core.units.draft import (
    KEEP,
    UNSET,
    CounterLegDraft,
    DraftEntry,
    DraftError,
    FieldDraft,
    PairingDraft,
    UnitDraft,
)
from app.core.units.preview import preview_unit
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import RERESOLVE, D, Scene, fixed

COUNTERPARTIES = ["REWE", "ALDI", "RENT", "NEWCO", "ATM"]


@pytest.fixture
def world(scene: Scene) -> Scene:
    for name, cat in (("REWE", "Food"), ("REWE", "Food"), ("ALDI", "Groceries"), ("NEWCO", "Misc")):
        scene.confirmed(name, cat)
    payee = scene.payee("Landlord")
    scene.tag("t1"), scene.tag("t2"), scene.tag("t3")
    for name in ("Fun", "Rent"):
        scene.category(name)

    def rules(conn: Any) -> None:
        conn.execute(
            text(
                "INSERT INTO rule (name, sets, category_id, conditions) VALUES ('rent', 'category', :c,"
                " CAST(:k AS jsonb))"
            ),
            {
                "c": scene.cats["Rent"],
                "k": json.dumps([{"field": "counterparty_name", "op": "equals", "value": "RENT"}]),
            },
        )
        conn.execute(
            text(
                "INSERT INTO rule (name, sets, payee_id, conditions) VALUES ('landlord', 'payee', :p,"
                " CAST(:k AS jsonb))"
            ),
            {"p": payee, "k": json.dumps([{"field": "counterparty_name", "op": "equals", "value": "RENT"}])},
        )
        conn.execute(
            text(
                "INSERT INTO rule (name, sets, counter_account_id, conditions)"
                " VALUES ('atm', 'counter_account', :a, CAST(:k AS jsonb))"
            ),
            {
                "a": scene.cash,
                "k": json.dumps([{"field": "counterparty_name", "op": "equals", "value": "ATM"}]),
            },
        )

    scene.tx(rules)
    spares(scene)
    return scene


def spares(scene: Scene) -> None:
    """Partners to pick: open legs (no counter-account) of several amounts and dates, untyped entries (an
    original, and a split's second entry), and a pair elsewhere. None matches an amount the examples use on a
    counter-account a rule sets (the cash), so that settling alone never pairs them with an example's unit:
    the draws must not depend on what earlier examples left."""
    user = json.dumps({"type": {"pass": "user"}})
    for account, amount, day in (
        (scene.savings, 1000, 0),
        (scene.savings, 500, 1),
        (scene.cash, 650, 2),
        (scene.savings, 400, 3),
        (scene.cash, 1050, 20),
    ):
        scene.movement(
            amount,
            account=account,
            on=D + timedelta(days=day),
            type="transfer",
            derivation=user,
            authored=True,
        )
    scene.movement(1000, account=scene.savings, authored=True)
    scene.movement(300, 200, account=scene.cash, authored=True)
    scene.transfer_pair(-500)


def field_drafts(scene: Scene) -> st.SearchStrategy[FieldDraft]:
    return st.one_of(
        st.just(KEEP),
        st.just(KEEP),
        st.just(RERESOLVE),
    )


def categories(scene: Scene) -> st.SearchStrategy[FieldDraft]:
    ids = [scene.cats[n] for n in ("Food", "Groceries", "Misc", "Fun", "Rent")]
    return st.one_of(
        st.just(KEEP),
        st.just(RERESOLVE),
        st.sampled_from([fixed(i) for i in ids]),
        st.just(fixed(None)),
        st.sampled_from([fixed(ids[0], ("history", {"matches": 3}))]),
    )


def tag_sets(scene: Scene) -> st.SearchStrategy[tuple[int, ...]]:
    ids = [r.id for r in scene.q("SELECT id FROM tag ORDER BY id")]
    return st.lists(st.sampled_from(ids), max_size=2, unique=True).map(tuple)


@st.composite
def entries_draft(
    draw: st.DrawFn, scene: Scene, ids: list[int], originals: set[int], flows_only: bool, spare_ids: list[int]
) -> UnitDraft:
    # a pick names a spare leg, an id that does not exist, or an entry of the unit itself: an index, so that
    # the draws do not depend on the ledger
    in_unit = st.integers(0, len(spare_ids) + 1).map(
        lambda n: spare_ids[n] if n < len(spare_ids) else 987_654 if n == len(spare_ids) else ids[0]
    )
    payees = [fixed(scene.payees["Landlord"]), fixed(None)]
    accounts = [fixed(scene.savings), fixed(scene.cash), fixed(scene.usd), fixed(scene.checking)]
    edits: list[DraftEntry] = []
    for i in ids:
        if draw(st.booleans()):
            kind = draw(st.sampled_from(["keep", "keep", "flow", "transfer"]))
            # a counter-leg is for a leg without a partner: drawn for the kinds of unpaired legs only (on a
            # paired leg it is the deliberate `counter_leg_not_offered`, pinned in test_counter_legs.py)
            hows = ["keep", "keep", "keep", "reresolve", "pick"] + (["counter_leg"] * 2 if flows_only else [])
            how = draw(st.sampled_from(hows))
            partner = draw(in_unit)
            # a counter-leg is drafted with or without an amount received (a magnitude): the plan says whether
            # it is needed
            received = draw(st.sampled_from([None, None, 500, 1000, 1234]))
            pairing = (
                PairingDraft()
                if how == "keep" or i not in originals
                else PairingDraft("reresolve")
                if how == "reresolve"
                else PairingDraft("counter_leg", counter_leg=CounterLegDraft(-(50 + i), received))
                if how == "counter_leg"
                else PairingDraft("pick", partner)
            )
            if pairing.mode != "keep" and draw(st.sampled_from([True, True, True, False])):
                kind = "transfer"  # most picks are of a transfer leg: the rest are 422s
            counter = draw(st.sampled_from([KEEP, KEEP, KEEP, KEEP, RERESOLVE, RERESOLVE, *accounts]))
            if pairing.mode == "counter_leg":  # its counter-account is the cash or the dollar account
                kind = "transfer"
                counter = draw(st.sampled_from([fixed(scene.cash), fixed(scene.usd)]))
                # the amount received is needed across currencies only (now and then given wrongly)
                dollars = counter.value == scene.usd
                given = draw(st.sampled_from([1234, 1234, 1234, None] if dollars else [None] * 7 + [500]))
                pairing = PairingDraft("counter_leg", counter_leg=CounterLegDraft(-(50 + i), given))
            edits.append(
                DraftEntry(
                    i,
                    pairing=pairing,
                    description=draw(st.sampled_from(["x", None, "same"])) if draw(st.booleans()) else UNSET,
                    note=draw(st.sampled_from(["n", None])) if draw(st.booleans()) else UNSET,
                    type=KEEP if kind == "keep" else fixed(kind),
                    payee=draw(st.sampled_from([KEEP, RERESOLVE, *payees])),
                    category=draw(categories(scene)),
                    counter_account=counter,
                )
            )
    removed = [
        i for i in ids if i not in originals and draw(st.booleans()) and not any(e.id == i for e in edits)
    ]
    new: list[DraftEntry] = []
    for n in range(draw(st.integers(0, 2))):
        # an amount of the source's own sign (a pair's second original is the incoming leg); now and then a
        # large one, which flips the residual's sign: a deliberate refusal
        srcs = sorted(originals)
        which = draw(st.integers(0, len(srcs) - 1))
        incoming = not flows_only and which == 1
        amount = draw(st.sampled_from([50, 20, 30, 50, 700] if incoming else [-100, -300, -50, -20, -999]))
        new.append(
            DraftEntry(
                -(n + 1),
                amount=amount,
                source_entry_id=srcs[which],
                category=draw(categories(scene)),
                payee=draw(st.sampled_from([KEEP, *payees])),
            )
        )
    versions = scene.versions(ids[0])
    entries = []
    for e in [*edits, *new]:  # a tag change on top of whatever else the entry carries
        add, remove = draw(tag_sets(scene)), draw(tag_sets(scene))
        entries.append(
            dataclasses.replace(e, tags_add=add, tags_remove=tuple(t for t in remove if t not in add))
        )
    for i in ids:  # and tag-only entries
        if not any(e.id == i for e in entries) and i not in removed and draw(st.booleans()):
            add, remove = draw(tag_sets(scene)), draw(tag_sets(scene))
            entries.append(DraftEntry(i, tags_add=add, tags_remove=tuple(t for t in remove if t not in add)))
    return UnitDraft(
        ids[0],
        entries,
        removed_entry_ids=removed,
        reresolve_all=draw(st.booleans()),
        versions=versions,
        # a commit checks a pick against the cap: the preview is made with a widened window, as the picker's
        # "load more" does, so that what it refuses the commit refuses too
        window_days=draw(st.sampled_from([30, 90])),
    )


SETTINGS = settings(
    max_examples=int(os.environ.get("PEC_EXAMPLES", "40")),
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _build(scene: Scene, kind: str, who: str, confirmed: bool) -> tuple[list[int], set[int]]:
    if kind == "plain":
        _s, ents = scene.movement(-1000, counterparty=who)
        originals = {ents[0]}
    elif kind == "split":
        _s, ents = scene.movement(-600, -400, counterparty=who)
        originals = {ents[0]}
    else:
        # the examples share one ledger and the same amounts: a leg an earlier example left behind is a
        # candidate
        # of this one, and the preview must pair with it exactly as settling will
        (_sa, a), (_sb, b) = scene.transfer_pair(-500, out_extra=[-100] if kind == "pair_split" else ())
        ents = [*a, *b]
        originals = {a[0], b[0]}
    for i in ents:  # some stored tags to inherit, keep or remove
        scene.tag_entry(i, *[r.id for r in scene.q("SELECT id FROM tag ORDER BY id")][: i % 3])
    scene.settle()
    if confirmed:
        try:
            scene.commit(ents[0])
        except CommitRefused:
            pass
    return sorted(ents), originals


@pytest.mark.parametrize("kind", ["plain", "split", "pair", "pair_split"])
def test_preview_equals_commit_and_settle(world: Scene, kind: str) -> None:
    scene = world
    # the partners a draft may pick, fixed before the examples (a strategy must not read the database)
    spare_ids = [
        r.id
        for r in scene.q("SELECT id FROM ledger_entry WHERE account_id <> :c ORDER BY id", c=scene.checking)
    ]
    reasons: dict[str, int] = {}
    outcomes = {
        "committed": 0,
        "refused": 0,
        "pulled": 0,
        "invalid": 0,
        "picked": 0,
        "counter_legs": 0,
        "followed": 0,
    }

    @SETTINGS
    @given(data=st.data(), who=st.sampled_from(COUNTERPARTIES), confirmed=st.booleans())
    def run(data: st.DataObject, who: str, confirmed: bool) -> None:
        ids, originals = _build(scene, kind, who, confirmed)
        ids = scene.unit_ids(ids[0])
        draft = data.draw(entries_draft(scene, list(ids), originals, kind in ("plain", "split"), spare_ids))
        before = scene.fingerprint()
        try:
            plan = preview_unit(scene.engine, draft)
        except DraftError as err:  # a pairing on something that is no transfer leg: the commit says the same
            with pytest.raises(DraftError) as exc_draft:
                scene.commit_draft(draft)
            assert exc_draft.value.code == err.code
            assert scene.fingerprint() == before
            outcomes["invalid"] += 1
            return
        pulled = set(plan.versions) != set(draft.versions)  # a leg outside the unit was paired or picked
        # a commit carries the versions of everything the preview shows (partners and proposals included)
        carrying = dataclasses.replace(draft, versions={**draft.versions, **plan.versions})
        if plan.problems:
            with pytest.raises(CommitRefused) as exc:
                scene.commit_draft(carrying)
            assert {p.code for p in exc.value.problems} == {p.code for p in plan.problems}
            for p in plan.problems:
                reasons[p.code] = reasons.get(p.code, 0) + 1
            assert scene.fingerprint() == before
            outcomes["refused"] += 1
            return
        preview_then_commit(scene, draft)
        outcomes["committed"] += 1
        outcomes["pulled"] += pulled
        outcomes["followed"] += bool(plan.followed_sources)
        outcomes["counter_legs"] += any(r.counter_leg_for is not None for r in plan.rows)
        outcomes["picked"] += any(
            r.counterpart_entry_id is not None
            and r.stored is not None
            and r.stored.counterpart_entry_id != r.counterpart_entry_id
            for r in plan.rows
        )

    run()
    print(kind, outcomes, reasons)
    # the draws are fixed (`derandomize`): this is the coverage of the strategy, not of a lucky run
    assert outcomes["committed"] >= 1, outcomes
    # `pulled` counts the examples where settling paired a leg of the unit with one outside it (legs the
    # earlier examples left behind); how often depends on the draw, test_preview_pairing_ledger_wide pins it
