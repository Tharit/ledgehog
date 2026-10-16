"""An entry's line of its transaction's document (spec §5.8, §6; documents.md §4, §6, §8): read from the
stored reference, written with the link (a pick of a document of one line, the split along the lines), cleared
with it, and the rules that keep a document to a flow (a pick on a transfer is refused, converting to a
transfer drops it, a pick on an untyped entry types it a flow).

Every case that commits goes through `equality.preview_then_commit`, which compares each row's line too.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection

from app.core.importers.providers import reset_document_providers
from app.core.units.doc_draft import proposed_split_id
from app.core.units.draft import DocumentDraft, DocumentLineRef, DraftEntry, PairingDraft
from app.core.units.preview import preview_unit
from tests.core.units.doc_helpers import Docs, make_payee
from tests.core.units.equality import preview_then_commit, stored_lines
from tests.core.units.scene import Scene, fixed, no_document
from tests.core.units.test_documents_draft import pick
from tests.core.units.test_documents_split import LINES, echo, order
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


class Shop:
    """A rule that reads an entry's line: `USB cable` is Gadgets; the merchant `Seeed Studio` is the payee."""

    def __init__(self, scene: Scene) -> None:
        def build(c: Connection) -> tuple[int, int]:
            seeed = make_payee(c, "Seeed", None)
            gadgets = make_category(c, "Gadgets")
            rs.rule(
                c,
                "seeed",
                "payee",
                seeed,
                conditions=(rs.cond("document_merchant", "equals", "Seeed Studio"),),
                priority=50,
            )
            rs.rule(
                c,
                "cables",
                "category",
                gadgets,
                conditions=(rs.cond("document_line", "contains", "USB cable"),),
            )
            return int(seeed), int(gadgets)

        self.seeed, self.gadgets = scene.tx(build)


@pytest.fixture
def shop(scene: Scene) -> Shop:
    return Shop(scene)


def lines_of(scene: Scene, *entries: int) -> dict[int, tuple[int, int]]:
    return stored_lines(scene, list(entries))


# ---- reading the stored line -----------------------------------------------------------------------------


def test_a_one_line_link_settling_made_is_read_as_the_entrys_line(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, ("USB cable", -1000))
    assert lines_of(scene, entry) == {entry: (doc, 1)}  # settling wrote it with the link
    plan = scene.preview(entry)
    r = plan.row(entry)
    assert r.document_line == (doc, 1) and r.document_line_description == "USB cable"
    assert r.fields["category"].value == shop.gadgets  # resolved with its line, as settling did
    assert not plan.problems


def test_a_stored_split_is_read_line_by_line(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, doc = order(scene, docs, *LINES)
    _plan, result = preview_then_commit(
        scene, scene.draft(entry, echo(entry, doc, 2, -300), echo(entry, doc, 3, -300))
    )
    second, third = (result.created[proposed_split_id(entry, n)] for n in (2, 3))
    plan = scene.preview(entry)  # nothing drafted: every stored entry keeps the line it references
    assert {r.id: r.document_line for r in plan.rows} == {entry: (doc, 1), second: (doc, 2), third: (doc, 3)}
    assert {r.id: r.document_line_description for r in plan.rows} == {
        entry: "USB cable",
        second: "Case",
        third: "Shipping",
    }
    assert plan.row(entry).fields["category"].value == shop.gadgets
    assert not plan.problems and [c for c in plan.consequences if c.kind != "created"] == []


def test_an_entry_of_a_hand_made_split_has_no_line(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, doc = order(scene, docs, *LINES)
    new = DraftEntry(-1, amount=-300, source_entry_id=entry)
    plan = scene.preview(entry, new, DraftEntry(entry, document=DocumentDraft("keep"), note="x"))
    # a split made by hand: the new entry has none; the original, of a document of several lines, has none
    assert plan.row(-1).document_line is None
    assert plan.row(entry).document_line is None or plan.row(entry).document_line == (doc, 1)
    assert plan.row(-1).fields["category"].value is None


def test_a_line_of_another_document_is_ignored_and_cleared_by_a_commit(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, ("USB cable", -1000))
    other = docs.document(total=-4242, external_id="other")
    docs.lines(other, ("Case", -4242))
    stray = scene.q("SELECT id FROM external_document_line WHERE document_id = :d", d=other)[0].id
    scene.tx(
        lambda c: c.exec_driver_sql(f"UPDATE ledger_entry SET document_line_id = {stray} WHERE id = {entry}")
    )
    plan = scene.preview(entry)
    assert plan.row(entry).document_line is None  # not a line of the transaction's document
    plan, _ = preview_then_commit(scene, scene.draft(entry, DraftEntry(entry, note="x")))
    assert plan.row(entry).document_line is None
    assert lines_of(scene, entry) == {}  # the reference is gone with the commit


# ---- a pick of a document of one line --------------------------------------------------------------------


def test_a_pick_of_a_document_of_one_line_writes_the_line_with_the_link(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry = docs.charge(-1000)
    doc = docs.document(total=-4242, external_id="by-hand")
    docs.merchant(doc, "Seeed Studio")
    docs.lines(doc, ("USB cable", -4242))
    plan = scene.preview(entry, pick(entry, scene, doc))
    r = plan.row(entry)
    assert r.document_line == (doc, 1) and r.document_line_description == "USB cable"
    assert r.fields["category"].value == shop.gadgets and r.fields["payee"].value == shop.seeed
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    assert lines_of(scene, entry) == {entry: (doc, 1)}
    assert scene.row(entry).document_id == doc and scene.row(entry).category_id == shop.gadgets


def test_a_pick_of_a_document_of_several_lines_gives_the_original_none(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry = docs.charge(-1000)
    doc = docs.document(total=-4242, external_id="by-hand")
    docs.lines(doc, ("USB cable", -4242), ("Case", 0))
    plan = scene.preview(entry, pick(entry, scene, doc))
    assert plan.row(entry).document_line is None  # unsplit: a line matched would be any of the items
    assert plan.row(entry).fields["category"].value is None


def test_picking_another_document_replaces_the_line(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, doc = order(scene, docs, ("USB cable", -1000))
    other = docs.document(total=-4242, external_id="other")
    docs.lines(other, ("Case", -4242))
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, other)))
    assert plan.row(entry).document_line == (other, 1)
    assert lines_of(scene, entry) == {entry: (other, 1)}  # the old line is free again, the new one taken


# ---- the split along the lines ---------------------------------------------------------------------------


def test_a_split_along_the_lines_writes_each_entrys_line_the_original_the_first(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, *LINES)
    _plan, result = preview_then_commit(scene, scene.draft(entry))  # the proposal, taken as it is
    created = {n: result.created[proposed_split_id(entry, n)] for n in (2, 3)}
    assert lines_of(scene, entry, *created.values()) == {
        entry: (doc, 1),
        created[2]: (doc, 2),
        created[3]: (doc, 3),
    }


def test_an_explicit_split_replacing_a_stored_split_keeps_one_line_each(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, *LINES)
    preview_then_commit(scene, scene.draft(entry))
    version = scene.q("SELECT version FROM external_document WHERE id = :i", i=doc)[0].version
    again = DraftEntry(entry, document=DocumentDraft("split_along_lines", doc, version))
    _plan, result = preview_then_commit(scene, scene.draft(entry, again))
    ids = [entry, *(result.created[proposed_split_id(entry, n)] for n in (2, 3))]
    assert lines_of(scene, *ids) == {ids[0]: (doc, 1), ids[1]: (doc, 2), ids[2]: (doc, 3)}


def test_a_new_row_for_a_line_a_stored_entry_holds_is_a_problem(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, doc = order(scene, docs, *LINES)
    preview_then_commit(scene, scene.draft(entry))
    plan = scene.preview(
        entry, DraftEntry(-5, amount=-100, source_entry_id=entry, document_line=DocumentLineRef(doc, 2))
    )
    assert [
        (p.code, p.field, dict(p.detail)["line_no"]) for p in plan.problems if p.field == "document_line"
    ] == [("document_taken", "document_line", 2)]


# ---- clearing --------------------------------------------------------------------------------------------


def test_none_clears_every_line_of_a_split(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, doc = order(scene, docs, *LINES)
    preview_then_commit(scene, scene.draft(entry))
    assert len(lines_of(scene, *scene.unit_ids(entry))) == 3
    plan, _ = preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    assert all(r.document_line is None for r in plan.rows)
    assert lines_of(scene, *scene.unit_ids(entry)) == {}
    assert scene.row(entry).document_id is None


def test_none_clears_the_line_of_a_one_line_document(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, _doc = order(scene, docs, ("USB cable", -1000))
    plan, _ = preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    assert plan.row(entry).document_line is None and plan.row(entry).fields["category"].value is None
    assert lines_of(scene, entry) == {}


def test_reresolve_clears_the_line_and_settling_gives_the_matchers_back(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, ("USB cable", -1000))
    reresolve = DraftEntry(entry, document=DocumentDraft("reresolve"))
    plan, _ = preview_then_commit(scene, scene.draft(entry, reresolve))
    # the matcher links the same document again (a document of one line: with its line, in the same write)
    assert plan.row(entry).document_id == doc and plan.row(entry).document_line == (doc, 1)
    assert lines_of(scene, entry) == {entry: (doc, 1)}


# ---- a document explains a flow --------------------------------------------------------------------------


def test_a_pick_on_a_transfer_is_refused(scene: Scene, docs: Docs) -> None:
    (_a, (x,)), (_b, (y,)) = scene.transfer_pair()
    doc = docs.document(total=-1000)
    plan = scene.preview(x, pick(x, scene, doc))
    assert [(p.code, p.entry_id, p.field) for p in plan.problems] == [
        ("document_not_for_transfer", x, "document")
    ]
    other = docs.document(total=500, external_id="b")
    both = scene.preview(x, pick(x, scene, doc), pick(y, scene, other))
    assert sorted((p.code, p.entry_id) for p in both.problems) == [
        ("document_not_for_transfer", x),
        ("document_not_for_transfer", y),
    ]


def test_a_pick_on_an_entry_the_draft_makes_a_transfer_is_refused(scene: Scene, docs: Docs) -> None:
    entry = docs.charge(-1000)
    doc = docs.document(total=-4242, external_id="by-hand")
    plan = scene.preview(
        entry,
        pick(entry, scene, doc, type=fixed("transfer"), counter_account=fixed(scene.savings)),
    )
    assert "document_not_for_transfer" in [p.code for p in plan.problems]


def test_converting_a_linked_transaction_to_a_transfer_drops_its_document(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, ("USB cable", -1000))
    draft = scene.draft(
        entry, DraftEntry(entry, type=fixed("transfer"), counter_account=fixed(scene.savings))
    )
    plan, _ = preview_then_commit(scene, draft)
    r = plan.row(entry)
    # key, link and line are gone, as the payee is (I9)
    assert r.document_id is None and r.document_line is None
    assert r.derivation["document"] == {
        "pass": "matcher_decision"
    }  # the "none" settling records at confirming
    assert r.fields["payee"].value is None and r.fields["type"].value == "transfer"
    view = r.document_view
    assert view is not None and view.stored_document_id == doc and view.document is None
    assert (entry, "changed") in [(c.entry_id, c.kind) for c in plan.consequences]
    row = scene.row(entry)
    assert row.document_id is None and row.document_line_id is None and row.type == "transfer"


def test_a_pick_on_an_untyped_entry_types_it_a_flow_as_the_users_decision(scene: Scene, docs: Docs) -> None:
    _src, (entry,) = scene.movement(-1000, counterparty="Mystery")
    assert scene.row(entry).type is None
    doc = docs.document(total=-4242, external_id="by-hand")
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    r = plan.row(entry)
    assert r.fields["type"].value == "flow" and r.fields["type"].key == {"pass": "user"}
    assert scene.row(entry).type == "flow" and scene.row(entry).derivation["type"] == {"pass": "user"}


def test_a_pick_does_not_retype_an_entry_that_is_a_flow_already(scene: Scene, docs: Docs) -> None:
    entry = scene.confirmed("REWE", "Food")
    doc = docs.document(total=-4242, external_id="by-hand")
    plan, _ = preview_then_commit(scene, scene.draft(entry, pick(entry, scene, doc)))
    assert plan.row(entry).fields["type"].value == "flow"
    assert scene.row(entry).derivation["type"] == {"pass": "user"}


def test_a_linked_untyped_entry_picked_as_a_partner_loses_its_document(scene: Scene, docs: Docs) -> None:
    """Pairing makes the partner a transfer: converting a linked transaction drops its document (I9)."""
    doc = docs.document(total=500, external_id="refund")
    docs.lines(doc, ("Refund", 500))
    _src, (leg,) = scene.movement(
        -500, authored=True, type="transfer", derivation=json.dumps({"type": {"pass": "user"}})
    )
    _src, (other,) = scene.movement(
        500,
        account=scene.savings,
        authored=True,
        document_id=doc,
        derivation=json.dumps({"document": {"pass": "user"}}),
    )
    scene.tx(
        lambda c: c.exec_driver_sql(
            f"UPDATE ledger_entry SET document_line_id = (SELECT id FROM external_document_line"
            f" WHERE document_id = {doc}) WHERE id = {other}"
        )
    )
    draft = scene.draft(leg, DraftEntry(leg, pairing=PairingDraft("pick", other)))
    plan = preview_unit(scene.engine, draft)
    r = plan.row(other)
    assert r.document_id is None and r.document_line is None and r.fields["type"].value == "transfer"
    assert "document" not in r.derivation or r.derivation["document"] == {"pass": "matcher_decision"}
    assert (other, "changed") in [(c.entry_id, c.kind) for c in plan.consequences]
    preview_then_commit(scene, draft)
    row = scene.row(other)
    assert row.document_id is None and row.document_line_id is None and row.type == "transfer"
