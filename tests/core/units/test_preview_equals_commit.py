"""PROPERTY: the preview of a draft equals the stored state after a real commit and a real settle.

Hypothesis draws units (a plain flow, a split, a confirmed pair) and drafts over them (values, splits,
removals, conversions, re-resolving); a draft the preview finds invalid must be refused by the commit with
nothing written, and any other must leave exactly the previewed rows, keys, flags and states.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from app.core.units.commit import CommitRefused
from app.core.units.draft import KEEP, UNSET, DraftEntry, FieldDraft, UnitDraft
from app.core.units.preview import preview_unit
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import RERESOLVE, Scene, fixed

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
    return scene


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
    draw: st.DrawFn, scene: Scene, ids: list[int], originals: set[int], flows_only: bool
) -> UnitDraft:
    payees = [fixed(scene.payees["Landlord"]), fixed(None)]
    accounts = [fixed(scene.savings), fixed(scene.cash), fixed(scene.usd), fixed(scene.checking)]
    edits: list[DraftEntry] = []
    for i in ids:
        if draw(st.booleans()):
            kind = draw(st.sampled_from(["keep", "keep", "flow", "transfer"]))
            edits.append(
                DraftEntry(
                    i,
                    description=draw(st.sampled_from(["x", None, "same"])) if draw(st.booleans()) else UNSET,
                    note=draw(st.sampled_from(["n", None])) if draw(st.booleans()) else UNSET,
                    type=KEEP if kind == "keep" else fixed(kind),
                    payee=draw(st.sampled_from([KEEP, RERESOLVE, *payees])),
                    category=draw(categories(scene)),
                    counter_account=draw(st.sampled_from([KEEP, RERESOLVE, *accounts])),
                )
            )
    removed = [
        i for i in ids if i not in originals and draw(st.booleans()) and not any(e.id == i for e in edits)
    ]
    new: list[DraftEntry] = []
    for n in range(draw(st.integers(0, 2))):
        new.append(
            DraftEntry(
                -(n + 1),
                amount=draw(st.sampled_from([-100, -300, 50, -999, -1000, 700])),
                source_entry_id=draw(st.sampled_from(sorted(originals))),
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
    )


SETTINGS = settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


def _build(scene: Scene, kind: str, who: str, confirmed: bool) -> tuple[list[int], set[int]]:
    if kind == "plain":
        _s, ents = scene.movement(-1000, counterparty=who)
        originals = {ents[0]}
    elif kind == "split":
        _s, ents = scene.movement(-600, -400, counterparty=who)
        originals = {ents[0]}
    else:
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
    outcomes = {"committed": 0, "refused": 0}

    @SETTINGS
    @given(data=st.data(), who=st.sampled_from(COUNTERPARTIES), confirmed=st.booleans())
    def run(data: st.DataObject, who: str, confirmed: bool) -> None:
        ids, originals = _build(scene, kind, who, confirmed)
        ids = scene.unit_ids(ids[0])
        draft = data.draw(entries_draft(scene, list(ids), originals, kind in ("plain", "split")))
        plan = preview_unit(scene.engine, draft)
        if plan.problems:
            before = scene.fingerprint()
            with pytest.raises(CommitRefused) as exc:
                scene.commit_draft(draft)
            assert {p.code for p in exc.value.problems} == {p.code for p in plan.problems}
            assert scene.fingerprint() == before
            outcomes["refused"] += 1
            return
        preview_then_commit(scene, draft)
        outcomes["committed"] += 1

    run()
    print(kind, outcomes)
    assert outcomes["committed"] > 5, outcomes
