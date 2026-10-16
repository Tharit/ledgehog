"""The preview of a unit mirrors settle steps 2 and 3 (spec §5.8, §5.9, §6; documents.md §1-§5, §7).

A unique candidate document is shown as linked (the key by the number of lines), the transaction's values
are derived again on the enriched input with history off, the unit stays open for a document it awaits or is
offered, a confirmed unit is left alone, and all of it equals the stored state after a real commit and the
settle that follows (`equality.preview_then_commit`). The link itself is settling's to write: a commit writes
none, and records no "none" for a unit that is not confirmed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Connection

from app.core.importers.providers import reset_document_providers
from app.core.units.commit import CommitRefused
from tests.core.units.doc_helpers import CARD, STANDING, Docs, make_payee
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, DraftEntry, Scene, fixed, no_document
from tests.fixtures import rule_seed as rs
from tests.invariants.helpers import make_category


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    reset_document_providers()
    yield
    reset_document_providers()


@pytest.fixture
def docs(scene: Scene) -> Docs:
    return Docs(scene)


# ---- the automatic link -----------------------------------------------------------------------


def test_a_unique_candidate_is_shown_as_linked_with_a_decision(scene: Scene, docs: Docs) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    plan = scene.preview(entry)
    r = plan.row(entry)
    assert r.document_id == doc
    assert r.derivation["document"] == {"pass": "matcher_decision", "basis": {}}
    assert r.fields["payee"].value == docs.provider
    assert "document_suggested" not in r.flags and "waiting" not in r.flags
    assert plan.rows[0].written.derivation.get("document") is None  # a commit writes no link: settling does


def test_the_preview_equals_the_commit_and_settle_that_follow(scene: Scene, docs: Docs) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    plan, result = preview_then_commit(scene, scene.draft(entry))
    assert plan.row(entry).document_id == doc
    assert scene.row(entry).document_id == doc


def test_the_link_is_written_once_by_settling_after_the_commit_wrote_its_values(
    scene: Scene, docs: Docs
) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    before = scene.row(entry).version
    draft = scene.draft(entry)
    plan = scene.preview(entry)
    assert "document" not in plan.row(entry).written.derivation  # the commit writes no link
    scene.commit_draft(draft)
    row = scene.row(entry)
    assert row.document_id == doc
    assert row.version == before + 2  # the commit's own write, then the link: no write twice
    assert scene.settle().touched_entry_ids == ()
    assert scene.row(entry).version == row.version


def test_a_document_of_several_lines_is_a_proposal_the_unit_reviews(scene: Scene, docs: Docs) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -400), ("Case", -600))
    plan = scene.preview(entry)
    r = plan.row(entry)
    assert r.document_id == doc and r.derivation["document"]["pass"] == "matcher_proposal"
    assert "unconfirmed" in r.flags
    assert not plan.anchor_unit.state.confirmed
    preview_then_commit(scene, scene.draft(entry))


def test_one_line_and_no_line_documents_are_decisions(scene: Scene, docs: Docs) -> None:
    one, doc = docs.charge(-300), docs.document(total=-300, external_id="one")
    docs.lines(doc, ("Cable", -300))
    none_, doc2 = docs.charge(-400), docs.document(total=-400, external_id="none")
    for entry in (one, none_):
        assert scene.preview(entry).row(entry).derivation["document"]["pass"] == "matcher_decision"
    preview_then_commit(scene, scene.draft(one))
    preview_then_commit(scene, scene.draft(none_))
    assert (scene.row(one).document_id, scene.row(none_).document_id) == (doc, doc2)


# ---- no automatic link ---------------------------------------------------------------------------


def test_ambiguous_documents_are_suggestions_and_nothing_is_linked(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    docs.document(total=-1000, external_id="a")
    docs.document(total=-1000, external_id="b")
    plan = scene.preview(entry)
    r = plan.row(entry)
    assert r.document_id is None and "document" not in r.derivation  # no "none" either: not confirmed
    assert "document_suggested" in r.flags
    assert not plan.anchor_unit.state.confirmed
    assert "document_suggested" in plan.anchor_unit.state.reasons
    # offered documents and none picked: the commit is refused unless the draft says "none" (spec §6)
    assert [p.code for p in plan.problems] == ["document_decision_required"]
    preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    assert scene.row(entry).derivation["document"] == {"pass": "user"}


def test_a_candidate_a_charge_outside_the_unit_has_too_is_nobodys(scene: Scene, docs: Docs) -> None:
    entry, other = docs.charge(), docs.charge(on=D + timedelta(days=1))
    docs.document(total=-1000)
    scene.settle()  # the other charge has its payee (a settled ledger)
    plan = scene.preview(entry)
    assert plan.row(entry).document_id is None and "document_suggested" in plan.row(entry).flags
    preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    # "none" took the first charge out of the matching: the document is now the other's alone
    assert scene.row(other).document_id is not None and scene.row(entry).document_id is None


def test_a_document_carried_outside_the_unit_is_no_candidate(scene: Scene, docs: Docs) -> None:
    doc = docs.document(total=-1000)
    carrier = docs.charge(document_id=doc, derivation=json.dumps({**STANDING, "document": {"pass": "user"}}))
    entry = docs.charge(on=D + timedelta(days=1))
    plan = scene.preview(entry)
    assert plan.row(entry).document_id is None and "document_suggested" not in plan.row(entry).flags
    assert scene.row(carrier).document_id == doc


def test_a_unit_awaiting_its_document_is_not_confirmed_and_no_none_is_decided(scene: Scene) -> None:
    uncovered = Docs(scene, covered=False)
    entry = uncovered.charge()
    cat = scene.category("Gadgets")
    decided = DraftEntry(entry, payee=fixed(uncovered.provider), category=fixed(cat))
    plan = scene.preview(entry, decided)
    r = plan.row(entry)
    assert "waiting" in r.flags and "document" not in r.derivation
    assert not plan.anchor_unit.state.confirmed
    assert "waiting_for_document" in plan.anchor_unit.state.reasons
    assert [p.code for p in plan.problems] == ["document_decision_required"]  # the wait is skipped explicitly
    with pytest.raises(CommitRefused):
        scene.commit(entry, decided)
    # the explicit decision: no document, which satisfies the wait; the unit is then confirmed
    plan, _result = preview_then_commit(
        scene, scene.draft(entry, no_document(entry, payee=fixed(uncovered.provider), category=fixed(cat)))
    )
    assert plan.row(entry).derivation["document"] == {"pass": "user"} and plan.anchor_unit.state.confirmed
    assert scene.row(entry).review_flags == []


def test_a_unit_waiting_and_offered_shows_both(scene: Scene) -> None:
    uncovered = Docs(scene, covered=False)
    entry = uncovered.charge()
    uncovered.document(total=-1000, external_id="a")
    uncovered.document(total=-1000, external_id="b")
    plan = scene.preview(entry)
    assert {"waiting", "document_suggested"} <= set(plan.row(entry).flags)
    preview_then_commit(scene, scene.draft(entry, no_document(entry)))


# ---- a confirmed unit -------------------------------------------------------------------------------


def test_a_confirmed_unit_is_left_alone(scene: Scene, docs: Docs) -> None:
    cat = scene.category("Gadgets")
    _src, (entry,) = scene.movement(
        -1000,
        counterparty=CARD,
        type="flow",
        category_id=cat,
        payee_id=docs.provider,
        derivation=json.dumps({**STANDING, "document": {"pass": "user"}}),
    )
    docs.document(total=-1000)
    scene.settle()
    plan = scene.preview(entry)
    r = plan.row(entry)
    assert r.document_id is None and r.derivation["document"] == {"pass": "user"}
    assert plan.anchor_unit.state.confirmed
    preview_then_commit(scene, scene.draft(entry))
    assert scene.row(entry).document_id is None


# ---- enrichment and history ------------------------------------------------------------------------


def _seeed_rules(scene: Scene) -> tuple[int, int]:
    def go(c: Connection) -> tuple[int, int]:
        seeed, gadgets = make_payee(c, "Seeed", None), make_category(c, "Gadgets")
        rs.rule(c, "seeed", "payee", seeed, conditions=(rs.name_is("Seeed Studio"),))
        rs.rule(c, "cables", "category", gadgets, conditions=(rs.cond("purpose", "contains", "USB cable"),))
        return int(seeed), int(gadgets)

    return scene.tx(go)  # type: ignore[no-any-return]


def test_enrichment_changes_the_derived_values_the_preview_shows(scene: Scene, docs: Docs) -> None:
    seeed, gadgets = _seeed_rules(scene)
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -1000))
    docs.merchant(doc, "Seeed Studio")
    plan = scene.preview(entry)
    r = plan.row(entry)
    assert r.document_id == doc
    assert (r.fields["type"].value, r.fields["payee"].value, r.fields["category"].value) == (
        "flow",
        seeed,
        gadgets,
    )
    assert r.fields["payee"].value != docs.provider
    preview_then_commit(scene, scene.draft(entry))
    stored = scene.row(entry)
    assert (stored.payee_id, stored.category_id, stored.document_id) == (seeed, gadgets, doc)


def test_a_stored_link_enriches_the_input_of_a_draft_walk(scene: Scene, docs: Docs) -> None:
    seeed, gadgets = _seeed_rules(scene)
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -1000))
    docs.merchant(doc, "Seeed Studio")
    scene.settle()
    assert scene.row(entry).document_id == doc
    stored_before = scene.row(entry)
    plan = scene.preview(entry)
    assert plan.row(entry).fields["payee"].value == stored_before.payee_id == seeed
    preview_then_commit(scene, scene.draft(entry))


def test_history_does_not_run_for_a_documented_transaction(scene: Scene, docs: Docs) -> None:
    scene.confirmed("Seeed Studio", "Gadgets", amount=-4242, on=D - timedelta(days=30))
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.merchant(doc, "Seeed Studio")
    _src, (control,) = scene.movement(-999, counterparty="Seeed Studio", on=D)
    plan = scene.preview(entry)
    r = plan.row(entry)
    assert r.document_id == doc
    assert r.fields["category"].value is None and r.fields["category"].evidence is None
    control_plan = scene.preview(control)
    assert control_plan.row(control).fields["category"].evidence is not None  # history works without one
    preview_then_commit(scene, scene.draft(entry))


# ---- more shapes -------------------------------------------------------------------------------------


def test_a_split_transaction_shares_its_documents_link(scene: Scene, docs: Docs) -> None:
    _src, (first, second) = scene.movement(-600, -400, counterparty=CARD)
    doc = docs.document(total=-1000)
    plan, _result = preview_then_commit(scene, scene.draft(first))
    assert plan.row(first).document_id == doc and plan.row(second).document_id is None
    assert scene.row(second).document_id is None


def test_an_instructed_currency_document_links(scene: Scene, docs: Docs) -> None:
    entry, doc = (
        docs.charge(-1000, instructed=(-1199, "USD")),
        docs.document(total=-1199, currency="USD"),
    )
    plan = scene.preview(entry)
    assert plan.row(entry).document_id == doc
    preview_then_commit(scene, scene.draft(entry))


def test_a_draft_that_decides_values_is_equal_to_commit_and_settle(scene: Scene, docs: Docs) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    cat = scene.category("Shopping")
    draft = scene.draft(entry, DraftEntry(entry, category=fixed(cat)))
    plan, _result = preview_then_commit(scene, draft)
    assert plan.row(entry).document_id == doc
    assert scene.row(entry).document_id == doc


def test_a_draft_that_decides_everything_but_has_a_candidate_is_linked_not_closed_with_none(
    scene: Scene, docs: Docs
) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    cat = scene.category("Shopping")
    draft = scene.draft(entry, DraftEntry(entry, payee=fixed(docs.provider), category=fixed(cat)))
    plan, _result = preview_then_commit(scene, draft)
    key = plan.row(entry).derivation["document"]
    assert key["pass"] == "matcher_decision" and plan.row(entry).document_id == doc


def test_a_preview_without_any_document_machinery_is_what_it_was(scene: Scene) -> None:
    """No provider payee, no source, no document: nothing is loaded, shown or recorded differently."""
    entry = scene.confirmed("REWE", "Food")
    plan = scene.preview(entry)
    assert plan.row(entry).document_id is None and plan.row(entry).flags == ()
