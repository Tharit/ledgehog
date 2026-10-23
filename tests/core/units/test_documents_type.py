"""A linked or picked document decides the type `flow`, with the key of its link (spec §5.8, §5.9 field
order, D225): a pick `user`, an automatic link of one line `matcher_decision`, one of several
`matcher_proposal`. Every case that commits goes through `equality.preview_then_commit`: the preview is what a
commit and the settle that follow leave."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from app.core.importers.providers import reset_document_providers
from app.core.units.commit import CommitRefused, commit_unit
from app.core.units.draft import DocumentLineRef, DraftEntry
from tests.core.units.doc_helpers import CARD, STANDING, Docs
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import Scene, fixed, no_document
from tests.core.units.test_documents_draft import pick
from tests.fixtures import rule_seed as rs


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    reset_document_providers()
    yield
    reset_document_providers()


@pytest.fixture
def docs(scene: Scene) -> Docs:
    return Docs(scene)


def type_key(scene: Scene, entry: int) -> dict[str, object]:
    return dict(scene.row(entry).derivation["type"])


def test_a_pick_types_an_untyped_entry_a_flow_keyed_user(scene: Scene, docs: Docs) -> None:
    _src, (entry,) = scene.movement(-1000, counterparty="Mystery")
    doc = docs.document(total=-4242, external_id="by-hand")
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    assert plan.row(entry).fields["type"].value == "flow"
    assert scene.row(entry).type == "flow" and type_key(scene, entry)["pass"] == "user"


def test_a_pick_on_a_confirmed_flow_keeps_flow_keyed_user_and_derives_the_category_again(
    scene: Scene, docs: Docs
) -> None:
    gadgets = scene.category("Gadgets")
    seeed = scene.category("Seeed")

    def rules(c):  # type: ignore[no-untyped-def]
        rs.rule(
            c, "cat", "category", seeed, conditions=(rs.cond("document_merchant", "equals", "Seeed Studio"),)
        )

    scene.tx(rules)
    _src, (entry,) = scene.movement(
        -1000,
        counterparty=CARD,
        type="flow",
        category_id=gadgets,
        payee_id=docs.provider,
        derivation=json.dumps({**STANDING, "document": {"pass": "user"}}),
    )
    doc = docs.document(total=-1000)
    docs.merchant(doc, "Seeed Studio")
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    assert plan.row(entry).fields["type"].value == "flow"
    assert type_key(scene, entry)["pass"] == "user"
    assert scene.row(entry).category_id == seeed  # the link is new input: the category derived again


def test_an_automatic_link_of_one_line_keys_the_type_matcher_decision(scene: Scene, docs: Docs) -> None:
    entry, _doc = docs.charge(), docs.document(total=-1000)
    plan = scene.preview(entry)
    assert plan.row(entry).derivation["type"]["pass"] == "matcher_decision"
    preview_then_commit(scene, scene.draft(entry))
    assert type_key(scene, entry) == {"pass": "matcher_decision", "basis": {}}
    # the key is the final decision's own: a second commit writes the same one (a standing key stays)
    plan, _ = preview_then_commit(scene, scene.draft(entry))
    assert plan.row(entry).fields["type"].evidence is not None
    assert plan.row(entry).fields["type"].evidence.pass_name == "matcher_decision"  # type: ignore[union-attr]
    assert type_key(scene, entry) == {"pass": "matcher_decision", "basis": {}}


def test_a_stored_matcher_proposal_link_shows_its_origin_and_commits_as_the_users(
    scene: Scene, docs: Docs
) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -400), ("Case", -600))
    scene.settle()
    assert type_key(scene, entry) == {"pass": "matcher_proposal", "basis": {}}
    assert not scene.preview(entry).anchor_unit.state.confirmed
    cat = scene.category("Gadgets")
    second = next(r.id for r in scene.preview(entry).rows if r.id != entry)
    draft = scene.draft(
        entry,
        DraftEntry(entry, category=fixed(cat)),
        DraftEntry(
            second,
            category=fixed(cat),
            source_entry_id=entry,
            amount=-600,
            document_line=DocumentLineRef(doc, 2),  # the client echoes the proposed row
        ),
    )
    plan, _ = preview_then_commit(scene, draft)
    assert plan.anchor_unit.state.confirmed  # "after this commit": the unit is confirmed
    field = plan.row(entry).fields["type"]
    # evidence: where the value comes from (the document's proposal); derivation: what is stored afterwards
    assert field.evidence is not None and field.evidence.pass_name == "matcher_proposal"
    assert plan.row(entry).derivation["type"] == {
        "pass": "user",
        "basis": {"pass": "matcher_proposal", "basis": {}},
    }
    assert type_key(scene, entry) == plan.row(entry).derivation["type"]
    assert dict(scene.row(entry).derivation["document"]) == {"pass": "user"}
    assert scene.preview(entry).anchor_unit.state.confirmed


def test_an_automatic_link_of_several_lines_keys_the_type_matcher_proposal_and_the_unit_stays_open(
    scene: Scene, docs: Docs
) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -400), ("Case", -600))
    plan = scene.preview(entry)
    assert plan.row(entry).derivation["type"] == {"pass": "matcher_proposal", "basis": {}}
    assert not plan.anchor_unit.state.confirmed
    scene.settle()  # settling writes it
    assert type_key(scene, entry) == {"pass": "matcher_proposal", "basis": {}}


def test_a_rule_keyed_flow_that_gets_a_document_is_document_decided_when_settling_links_it(
    scene: Scene, docs: Docs
) -> None:
    entry = docs.charge()
    scene.settle()
    assert scene.row(entry).type == "flow" and type_key(scene, entry)["pass"] == "rule"
    docs.document(total=-1000)
    scene.settle()  # step 2 links it, step 3 derives every value again
    assert scene.row(entry).document_id is not None
    assert scene.row(entry).type == "flow"
    assert type_key(scene, entry) == {"pass": "matcher_decision", "basis": {}}
    assert scene.settle().touched_entry_ids == ()


def test_a_counter_account_rule_cannot_make_a_documented_entry_a_transfer(scene: Scene, docs: Docs) -> None:
    def rules(c):  # type: ignore[no-untyped-def]
        rs.rule(
            c,
            "to-savings",
            "counter_account",
            scene.savings,
            conditions=(rs.cond("counterparty_name", "starts_with", "PAYPAL"),),
        )

    scene.tx(rules)
    entry = docs.charge()
    assert scene.preview(entry).row(entry).fields["type"].value == "transfer"  # the control
    doc = docs.document(total=-4242, external_id="by-hand")
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    assert plan.row(entry).fields["type"].value == "flow"
    assert scene.row(entry).type == "flow" and scene.row(entry).counter_account_id is None
    assert type_key(scene, entry)["pass"] == "user"


def test_dropping_the_link_derives_the_type_again(scene: Scene, docs: Docs) -> None:
    entry, _doc = docs.charge(), docs.document(total=-1000)
    scene.settle()
    assert type_key(scene, entry)["pass"] == "matcher_decision"
    plan, _ = preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    assert plan.row(entry).document_id is None
    # derived again as for any entry: the payee rule decides a flow, and the key follows the final decision
    # (`rule`), never the stale `matcher_decision` of the link that was dropped
    assert plan.row(entry).fields["type"].value == "flow"
    assert type_key(scene, entry)["pass"] == "rule"
    assert scene.preview(entry).row(entry).derivation["type"]["pass"] == "rule"


def test_the_pick_replacing_another_link_changes_the_type_key_to_the_picks(scene: Scene, docs: Docs) -> None:
    entry, _auto = docs.charge(), docs.document(total=-1000, external_id="auto")
    scene.settle()
    assert type_key(scene, entry)["pass"] == "matcher_decision"
    other = docs.document(total=-777, external_id="by-hand")
    preview_then_commit(scene, scene.draft(entry, pick(entry, scene, other)))
    assert type_key(scene, entry)["pass"] == "user"


def test_a_draft_that_converts_a_linked_transaction_to_a_transfer_still_drops_the_document_first(
    scene: Scene, docs: Docs
) -> None:
    entry, _doc = docs.charge(), docs.document(total=-1000)
    scene.settle()
    draft = scene.draft(
        entry, DraftEntry(entry, type=fixed("transfer"), counter_account=fixed(scene.savings))
    )
    plan, _ = preview_then_commit(scene, draft)
    assert plan.row(entry).document_id is None and scene.row(entry).type == "transfer"


def test_a_split_that_makes_another_entry_of_a_carrier_a_transfer_is_refused(
    scene: Scene, docs: Docs
) -> None:
    doc = docs.document(total=-1000)
    _src, (first, second) = scene.movement(
        -600,
        -400,
        counterparty=CARD,
        lead={
            "type": "flow",
            "document_id": doc,
            "derivation": json.dumps({**STANDING, "document": {"pass": "user"}}),
        },
    )
    to_savings = DraftEntry(second, type=fixed("transfer"), counter_account=fixed(scene.savings))
    draft = scene.draft(first, to_savings)
    plan = scene.preview(first, to_savings)
    assert [(p.code, p.entry_id, p.field) for p in plan.problems] == [
        ("document_with_transfer", second, "document")
    ]
    before = scene.fingerprint()
    with pytest.raises(CommitRefused) as refused:
        commit_unit(scene.engine, draft)
    assert [p.code for p in refused.value.problems] == ["document_with_transfer"]
    assert scene.fingerprint() == before


def test_a_split_of_a_carrier_that_leaves_no_transfer_is_fine(scene: Scene, docs: Docs) -> None:
    doc = docs.document(total=-1000)
    _src, (first, second) = scene.movement(
        -600,
        -400,
        counterparty=CARD,
        lead={
            "type": "flow",
            "document_id": doc,
            "derivation": json.dumps({**STANDING, "document": {"pass": "user"}}),
        },
    )
    cat = scene.category("Gadgets")
    plan, _ = preview_then_commit(scene, scene.draft(first, DraftEntry(second, category=fixed(cat))))
    assert plan.problems == ()
