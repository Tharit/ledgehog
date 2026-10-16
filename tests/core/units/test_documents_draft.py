"""The document field of a draft (spec §5.8, §6; documents.md §8): validation, what each mode makes of the
preview, the problems, and the explicit decision to commit without a document.

Every case that commits goes through `equality.preview_then_commit`: the preview is what a commit and the
settle that follows leave.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Connection

from app.core.importers.providers import reset_document_providers
from app.core.units.draft import DocumentDraft, DocumentLineRef, DraftEntry, DraftError
from tests.core.units.doc_helpers import CARD, STANDING, Docs, make_payee
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, Scene, no_document
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


def pick(entry: int, scene: Scene, doc: int, **kw: object) -> DraftEntry:
    version = scene.q("SELECT version FROM external_document WHERE id = :i", i=doc)[0].version
    return DraftEntry(entry, document=DocumentDraft("pick", doc, version), **kw)  # type: ignore[arg-type]


def codes(plan: object) -> list[str]:
    return [p.code for p in plan.problems]  # type: ignore[attr-defined]


# ---- the draft field ----------------------------------------------------------------------------------


def test_the_document_draft_is_validated_like_a_pairing() -> None:
    assert DocumentDraft().mode == "keep"
    for bad in (
        lambda: DocumentDraft("pick"),
        lambda: DocumentDraft("pick", 3),
        lambda: DocumentDraft("pick", 0, 1),
        lambda: DocumentDraft("none", 3, 1),
        lambda: DocumentDraft("reresolve", document_version=1),
        lambda: DocumentDraft("split_along_lines", 3, 1, decline_split=True),
        lambda: DocumentDraft("maybe"),  # type: ignore[arg-type]
        lambda: DocumentLineRef(0, 1),
        lambda: DocumentLineRef(1, 0),
        lambda: DraftEntry(-1, amount=-5, source_entry_id=1, document=DocumentDraft("none")),
        lambda: DraftEntry(1, document_line=DocumentLineRef(1, 2)),
    ):
        with pytest.raises(DraftError):
            bad()


def test_a_document_on_an_entry_that_is_not_the_original_is_refused(scene: Scene, docs: Docs) -> None:
    _src, (first, second) = scene.movement(-600, -400, counterparty=CARD)
    doc = docs.document(total=-1000)
    with pytest.raises(DraftError) as raised:
        scene.preview(first, pick(second, scene, doc))
    assert raised.value.code == "document_not_original" and raised.value.entry_id == second


# ---- picking ------------------------------------------------------------------------------------------


def test_a_suggestion_picked_is_linked_as_the_users_decision(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    a, b = docs.document(total=-1000, external_id="a"), docs.document(total=-1000, external_id="b")
    shown = scene.preview(entry).row(entry).document_view
    assert shown is not None and sorted(d.id for d in shown.suggestions) == [a, b]
    assert shown.decision_required and shown.document is None
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, b)))
    row = plan.row(entry)
    assert row.document_id == b and row.derivation["document"] == {"pass": "user"}
    assert row.document_view is not None and row.document_view.document is not None
    assert row.document_view.document.id == b and not row.document_view.suggestions
    stored = scene.row(entry)
    assert stored.document_id == b and stored.derivation["document"] == {"pass": "user"}
    assert plan.anchor_unit.state.reasons == (
        "incomplete",
    )  # the document is decided: only the category is open


def test_a_pick_replaces_an_automatic_link_and_frees_it(scene: Scene, docs: Docs) -> None:
    entry, auto = docs.charge(), docs.document(total=-1000, external_id="auto")
    scene.settle()
    assert scene.row(entry).document_id == auto
    other = docs.document(total=-777, external_id="by-hand")  # found by hand: it need not match the amount
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, other)))
    assert plan.row(entry).document_id == other
    assert scene.row(entry).document_id == other
    assert scene.q("SELECT 1 FROM ledger_entry WHERE document_id = :d", d=auto) == []  # free again
    assert (
        scene.row(entry).version == 3
    )  # the pick is a structural change; the link settling made was one too


def test_a_pick_derives_every_standing_value_again_from_the_document_fields(scene: Scene, docs: Docs) -> None:
    def rules(c: Connection) -> tuple[int, int]:
        seeed, gadgets = make_payee(c, "Seeed", None), make_category(c, "Gadgets")
        merchant = rs.cond("document_merchant", "equals", "Seeed Studio")
        rs.rule(c, "seeed", "payee", seeed, conditions=(merchant,), priority=50)
        rs.rule(c, "cables", "category", gadgets, conditions=(rs.cond("document_line", "contains", "USB"),))
        return int(seeed), int(gadgets)

    seeed, gadgets = scene.tx(rules)
    entry = docs.charge()
    scene.settle()
    assert scene.row(entry).payee_id == docs.provider  # the card text: PayPal
    ambiguous = (docs.document(total=-1000, external_id="a"), docs.document(total=-1000, external_id="b"))
    docs.merchant(ambiguous[0], "Seeed Studio")
    docs.lines(ambiguous[0], ("USB cable", -1000))
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, ambiguous[0])))
    r = plan.row(entry)
    assert (r.fields["payee"].value, r.fields["category"].value) == (seeed, gadgets)
    assert r.fields["payee"].stored_value == docs.provider
    stored = scene.row(entry)
    assert (stored.payee_id, stored.category_id, stored.document_id) == (seeed, gadgets, ambiguous[0])


def test_a_pick_on_a_confirmed_unit_shows_what_it_would_change(scene: Scene, docs: Docs) -> None:
    cat = scene.category("Gadgets")
    _src, (entry,) = scene.movement(
        -1000,
        counterparty=CARD,
        type="flow",
        category_id=cat,
        payee_id=docs.provider,
        derivation=json.dumps({**STANDING, "document": {"pass": "user"}}),
    )
    doc = docs.document(total=-1000)
    docs.merchant(doc, "Elsewhere")
    assert scene.preview(entry).anchor_unit.state.confirmed  # a document arriving never reopens it
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    assert plan.row(entry).document_id == doc
    assert scene.row(entry).document_id == doc


def test_a_pick_by_hand_of_a_document_that_matches_nothing(scene: Scene, docs: Docs) -> None:
    """documents.md §9: a transaction whose payee has no provider takes any document, found by hand."""
    entry = scene.confirmed("REWE", "Food")
    doc = docs.document(total=-4242, external_id="far")
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    assert plan.row(entry).document_id == doc and scene.row(entry).document_id == doc


# ---- the problems of a pick ----------------------------------------------------------------------------


def test_a_document_that_is_gone_is_a_stale_reference(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("pick", 987654, 1)))
    assert [(p.code, p.field, dict(p.detail)) for p in plan.problems] == [
        ("stale_reference", "document_id", {"id": 987654})
    ]


def test_a_document_another_entry_carries_is_taken(scene: Scene, docs: Docs) -> None:
    doc = docs.document(total=-1000)
    carrier = docs.charge(document_id=doc, derivation=json.dumps({**STANDING, "document": {"pass": "user"}}))
    entry = docs.charge(on=D + timedelta(days=1))
    plan = scene.preview(entry, pick(entry, scene, doc))
    assert [(p.code, p.entry_id, dict(p.detail)) for p in plan.problems] == [
        ("document_taken", entry, {"document_id": doc, "carrier": carrier})
    ]


def test_a_document_of_another_provider_than_the_payees_is_refused(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    scene.settle()
    amazon = docs.document(provider="amazon", total=-1000)
    assert scene.row(entry).payee_id == docs.provider
    plan = scene.preview(entry, pick(entry, scene, amazon))
    assert [(p.code, dict(p.detail)) for p in plan.problems] == [
        ("document_provider_mismatch", {"provider": "amazon", "payee_provider": "paypal"})
    ]


def test_a_document_at_another_version_than_the_client_saw_is_changed(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    doc = docs.document(total=-1000)
    scene.tx(lambda c: c.exec_driver_sql("UPDATE external_document SET version = 5"))
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("pick", doc, 1)))
    assert [(p.code, dict(p.detail)) for p in plan.problems] == [
        ("document_changed", {"document_id": doc, "version": 5, "expected": 1})
    ]


# ---- "none" ----------------------------------------------------------------------------------------------


def test_none_drops_a_link_and_derives_again_where_history_may_run(scene: Scene, docs: Docs) -> None:
    scene.confirmed("Seeed Studio", "Gadgets", amount=-4242, on=D - timedelta(days=30))
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.merchant(doc, "Seeed Studio")
    scene.settle()
    assert scene.row(entry).document_id == doc and scene.row(entry).category_id is None  # history is off
    plan, _ = preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    r = plan.row(entry)
    assert r.document_id is None and r.derivation["document"] == {"pass": "user"}
    assert scene.row(entry).document_id is None
    assert r.fields["payee"].value == docs.provider  # the card text again, not the merchant


def test_none_stops_the_suggestions_for_as_long_as_it_stands(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    docs.document(total=-1000, external_id="a")
    docs.document(total=-1000, external_id="b")
    preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    again = scene.preview(entry)
    assert again.row(entry).document_view is not None
    assert (
        not again.row(entry).document_view.suggestions
        and not again.row(entry).document_view.decision_required
    )
    assert "document_suggested" not in scene.row(entry).review_flags


# ---- re-resolving ----------------------------------------------------------------------------------------


def test_reresolve_drops_the_decision_and_matching_decides_afresh(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    a, _b = docs.document(total=-1000, external_id="a"), docs.document(total=-1000, external_id="b")
    preview_then_commit(scene, scene.draft(entry, pick(entry, scene, a)))
    assert scene.row(entry).derivation["document"] == {"pass": "user"}
    scene.settle()
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("reresolve")))
    r = plan.row(entry)
    assert r.document_id is None and "document" not in r.derivation
    assert r.document_view is not None and len(r.document_view.suggestions) == 2  # offered again
    assert r.document_view.stored_document_id == a and codes(plan) == ["document_decision_required"]
    preview_then_commit(scene, scene.draft(entry, DraftEntry(entry, document=DocumentDraft("none"))))


def test_reresolve_of_a_link_the_matcher_makes_again_is_the_matchers(scene: Scene, docs: Docs) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    other = docs.document(total=-999, external_id="by-hand")
    preview_then_commit(scene, scene.draft(entry, pick(entry, scene, other)))
    plan, _ = preview_then_commit(
        scene, scene.draft(entry, DraftEntry(entry, document=DocumentDraft("reresolve")))
    )
    assert plan.row(entry).document_id == doc  # the unique candidate is linked afresh, by the matcher
    assert scene.row(entry).derivation["document"]["pass"] == "matcher_decision"


def test_re_resolving_the_whole_unit_resolves_its_document_afresh_too(scene: Scene, docs: Docs) -> None:
    cat = scene.category("Gadgets")
    _src, (entry,) = scene.movement(
        -1000,
        counterparty=CARD,
        type="flow",
        category_id=cat,
        payee_id=docs.provider,
        derivation=json.dumps({**STANDING, "document": {"pass": "user"}}),
    )
    doc = docs.document(total=-1000)  # arrived after the charge was confirmed
    plan = scene.preview(entry, reresolve_all=True)
    assert plan.row(entry).document_id == doc  # what re-resolving would link, shown to keep or adjust
    preview_then_commit(scene, scene.draft(entry, reresolve_all=True))


# ---- the explicit decision to commit without a document ----------------------------------------------------


def test_a_commit_without_a_pick_where_documents_are_offered_is_refused_unless_it_says_none(
    scene: Scene, docs: Docs
) -> None:
    from app.core.units.commit import CommitRefused

    entry = docs.charge()
    docs.document(total=-1000, external_id="a")
    docs.document(total=-1000, external_id="b")
    plan = scene.preview(entry)
    assert codes(plan) == ["document_decision_required"]
    with pytest.raises(CommitRefused) as raised:
        scene.commit(entry)
    assert [p.code for p in raised.value.problems] == ["document_decision_required"]
    assert scene.row(entry).version == 1  # nothing written
    plan, _ = preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    assert not plan.problems


def test_a_unit_with_neither_suggestion_nor_wait_commits_as_before(scene: Scene) -> None:
    entry = scene.confirmed("REWE", "Food")
    plan, _ = preview_then_commit(scene, scene.draft(entry))
    view = plan.row(entry).document_view
    assert view is not None and not view.suggestions and view.waiting is None and not view.decision_required
    assert scene.row(entry).derivation["document"] == {"pass": "matcher_decision"}  # settling recorded "none"


def test_the_waiting_line_and_the_suggestions_are_in_the_preview(scene: Scene) -> None:
    waiting = Docs(scene, covered=False)
    entry = waiting.charge()
    a = waiting.document(total=-1000, external_id="a")
    waiting.document(total=-1000, external_id="b")
    view = scene.preview(entry).row(entry).document_view
    assert view is not None and view.waiting is not None
    assert (view.waiting.provider, view.waiting.covered_through) == ("paypal", None)  # not synced yet
    assert view.decision_required and a in {d.id for d in view.suggestions}
    s = next(d for d in view.suggestions if d.id == a)
    assert (s.provider, s.occurred_on, s.total, s.currency, s.line_count, s.version) == (
        "paypal",
        D,
        -1000,
        "EUR",
        0,
        1,
    )


def test_a_document_only_reresolve_keeps_the_users_values_where_reresolve_all_clears_them(
    scene: Scene, docs: Docs
) -> None:
    """A confirmed charge (type, category, payee the user's) with the recorded "none" and candidates that
    arrived later. The document-only re-resolve offers them and leaves the other fields be, as long as it
    links nothing; a link it makes (a unique candidate) is a change of the first value in field order and
    derives the rest again (spec §5.9), and the panel-wide re-resolve does that for every value."""
    cat = scene.category("Gadgets")

    def confirmed_charge() -> int:
        _src, (e,) = scene.movement(
            -1000,
            counterparty=CARD,
            type="flow",
            category_id=cat,
            payee_id=docs.provider,
            derivation=json.dumps({**STANDING, "document": {"pass": "matcher_decision"}}),  # the "none"
        )
        return e

    entry = confirmed_charge()
    a, b = docs.document(total=-1000, external_id="a"), docs.document(total=-1000, external_id="b")
    before = scene.row(entry)
    assert not scene.preview(entry).row(entry).document_view.suggestions  # the "none" stands: no suggestion

    # several candidates: the suggestion appears, nothing is linked, no value moves
    row = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("reresolve"))).row(entry)
    assert row.document_view is not None and sorted(d.id for d in row.document_view.suggestions) == [a, b]
    assert row.document_id is None and "document" not in row.derivation  # only the "none" is dropped
    assert (row.fields["type"].value, row.fields["category"].value, row.fields["payee"].value) == (
        "flow",
        cat,
        docs.provider,
    )
    assert {k: v for k, v in row.derivation.items() if k != "document"} == {
        k: before.derivation[k] for k in STANDING
    }  # type, category and payee are still the user's
    assert (row.amount, row.note, tuple(row.tag_ids)) == (before.amount, before.note, ())

    # the panel-wide re-resolve derives every value afresh: the user's category has no evidence to come back
    every = scene.preview(entry, reresolve_all=True).row(entry)
    assert every.fields["category"].value is None and every.derivation.get("category") is None
    assert every.document_view is not None and sorted(d.id for d in every.document_view.suggestions) == [a, b]
