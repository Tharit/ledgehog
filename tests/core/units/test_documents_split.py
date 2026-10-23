"""Splitting along a document's lines (documents.md §6; spec §5.8, §6): proposed for a transaction that is not
split, resolved line by line in the preview, an existing split replaced only by the explicit choice, and all
of it equal to the stored state after a commit and the settle that follows."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Connection, text

from app.core.importers.providers import reset_document_providers
from app.core.units.doc_draft import proposed_split_id
from app.core.units.draft import DocumentDraft, DocumentLineRef, DraftEntry
from tests.core.units.doc_helpers import CARD, Docs, make_payee, matcher_link, users_link, users_link_to
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, Scene, fixed
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
    """Rules that read an entry's line each: `USB cable` is Gadgets, `Case` is Accessories, the merchant is
    Seeed (ordered before the card rule)."""

    def __init__(self, scene: Scene) -> None:
        def build(c: Connection) -> tuple[int, int, int]:
            seeed = make_payee(c, "Seeed", None)
            gadgets, accessories = make_category(c, "Gadgets"), make_category(c, "Accessories")
            merchant = rs.cond("document_merchant", "equals", "Seeed Studio")
            rs.rule(c, "seeed", "payee", seeed, conditions=(merchant,), priority=50)
            line = "document_line"
            rs.rule(c, "cables", "category", gadgets, conditions=(rs.cond(line, "contains", "USB cable"),))
            rs.rule(c, "cases", "category", accessories, conditions=(rs.cond(line, "contains", "Case"),))
            return int(seeed), int(gadgets), int(accessories)

        self.seeed, self.gadgets, self.accessories = scene.tx(build)


@pytest.fixture
def shop(scene: Scene) -> Shop:
    return Shop(scene)


def echo(entry: int, doc: int, line_no: int, amount: int, **kw: object) -> DraftEntry:
    """A row the preview made from `line_no`, as the client sends it back."""
    return DraftEntry(
        proposed_split_id(entry, line_no),
        amount=amount,
        source_entry_id=entry,
        document_line=DocumentLineRef(doc, line_no),
        **kw,  # type: ignore[arg-type]
    )


def order(
    scene: Scene, docs: Docs, *lines: tuple[str, int], total: int = -1000, **kw: object
) -> tuple[int, int]:
    """A PayPal charge of `total` and its document of `lines` from Seeed, linked by settling."""
    entry = docs.charge(total)
    doc = docs.document(total=total, **kw)  # type: ignore[arg-type]
    docs.merchant(doc, "Seeed Studio")
    docs.lines(doc, *lines)
    scene.settle()
    assert scene.row(entry).document_id == doc
    return entry, doc


LINES = (("USB cable", -400), ("Case", -300), ("Shipping", -300))


# ---- the proposal -----------------------------------------------------------------------------------------


def test_an_unsplit_linked_transaction_is_proposed_split_along_the_lines(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, *LINES)
    plan = scene.preview(entry)
    second, third = proposed_split_id(entry, 2), proposed_split_id(entry, 3)
    assert [r.id for r in plan.rows] == [entry, second, third]
    # the original takes the first line and the remainder: nothing of the entry is lost
    assert [r.amount for r in plan.rows] == [-400, -300, -300]
    assert plan.splits[0].residual_amount == -400
    assert [r.document_line for r in plan.rows] == [(doc, 1), (doc, 2), (doc, 3)]
    assert {(c.entry_id, c.kind) for c in plan.consequences} >= {(second, "created"), (third, "created")}
    view = plan.row(entry).document_view
    assert view is not None and view.split is not None
    assert (view.split.proposed, view.split.available, view.split.replaces_stored_split) == (
        True,
        True,
        False,
    )
    # each row is resolved with its own line, the original with its first
    assert plan.row(entry).fields["category"].value == shop.gadgets
    assert plan.row(second).fields["category"].value == shop.accessories
    # "Shipping": no rule reads that line, and an entry has its own line only (never all of them): no category
    assert plan.row(third).fields["category"].value is None
    assert all(r.fields["payee"].value == shop.seeed for r in plan.rows)


def test_a_commit_performs_the_split_and_equals_the_preview(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, doc = order(scene, docs, *LINES)
    cat = scene.category("Shipping")
    third = proposed_split_id(entry, 3)
    draft = scene.draft(entry, echo(entry, doc, 2, -300), echo(entry, doc, 3, -300, category=fixed(cat)))
    plan, result = preview_then_commit(scene, draft)
    assert set(result.created) == {proposed_split_id(entry, 2), third}
    real = {t: result.created[t] for t in result.created}
    assert [scene.row(i).amount for i in (entry, real[proposed_split_id(entry, 2)], real[third])] == [
        -400,
        -300,
        -300,
    ]
    stored = scene.row(entry)
    assert stored.category_id == shop.gadgets and stored.derivation["document"] == {"pass": "user"}
    assert scene.row(real[proposed_split_id(entry, 2)]).category_id == shop.accessories
    assert scene.row(real[third]).category_id == cat
    assert (
        scene.q(
            "SELECT count(*) AS n FROM ledger_entry WHERE source_transaction_id = :s",
            s=stored.source_transaction_id,
        )[0].n
        == 3
    )
    assert plan.anchor_unit.state.confirmed and scene.row(entry).review_flags == []


def test_the_client_echoes_the_proposal_and_its_edits_stick_to_the_line(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, *LINES)
    second = proposed_split_id(entry, 2)
    other = scene.category("Other")
    edited = echo(entry, doc, 2, -250, category=fixed(other))
    plan = scene.preview(entry, edited)
    # not regenerated: the draft holds the user's split now, and a row it leaves out is removed
    assert [r.id for r in plan.rows] == [entry, second]
    assert plan.row(second).amount == -250 and plan.row(entry).amount == -750
    assert plan.row(second).fields["category"].value == other


def test_a_split_the_draft_makes_by_hand_is_replaced_by_the_proposal(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, _doc = order(scene, docs, *LINES)
    plan = scene.preview(entry, DraftEntry(-1, amount=-100, source_entry_id=entry))
    # the link is the matcher's: the proposal replaces the client's own row
    assert [r.id for r in plan.rows] == [entry, proposed_split_id(entry, 2), proposed_split_id(entry, 3)]
    view = plan.row(entry).document_view
    assert view is not None and view.split is not None and view.split.proposed and view.split.available


def test_once_every_link_is_the_users_nothing_is_proposed(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, doc = order(scene, docs, *LINES)
    users_link(scene, entry)
    plan = scene.preview(entry)
    assert [r.id for r in plan.rows] == [entry]
    view = plan.row(entry).document_view
    assert view is not None and view.split is not None
    assert (view.split.proposed, view.split.available) == (False, True)
    # a split by hand stands
    plan = scene.preview(entry, DraftEntry(-1, amount=-100, source_entry_id=entry))
    assert [r.id for r in plan.rows] == [entry, -1]
    # the explicit choice stays available
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("split_along_lines", doc, 1)))
    assert len(plan.rows) == 3 and not plan.problems


def test_there_is_no_decline_the_proposal_is_edited_like_any_split(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, *LINES)
    # one proposed row removed (the client echoes the other only): the split is the client's
    plan = scene.preview(entry, echo(entry, doc, 3, -300))
    assert [r.id for r in plan.rows] == [entry, proposed_split_id(entry, 3)]
    assert [r.amount for r in plan.rows] == [-700, -300]


def test_no_proposal_where_there_is_nothing_to_split(scene: Scene, docs: Docs, shop: Shop) -> None:
    one, _ = order(scene, docs, ("USB cable", -1000))  # one line
    assert [r.id for r in scene.preview(one).rows] == [one]
    assert scene.preview(one).row(one).document_view.split is None  # type: ignore[union-attr]
    # a total that does not match the transaction exactly: documents of the transaction's currency only
    entry = docs.charge(-2000, on=scene.q("SELECT DATE '2026-04-01' AS d")[0].d)
    doc = docs.document(total=-1999, external_id="off")
    docs.lines(doc, ("USB cable", -999), ("Case", -1000))
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("pick", doc, 1)))
    assert [r.id for r in plan.rows] == [entry]
    view = plan.row(entry).document_view
    assert view is not None and view.split is not None and not view.split.available


def test_the_original_never_ends_with_nothing(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry = docs.charge(-300)
    doc = docs.document(total=-300)
    docs.lines(doc, ("USB cable", -100), ("Case", -300))  # the rest takes more than the entry
    scene.settle()
    assert scene.row(entry).document_id == doc
    plan = scene.preview(entry)
    assert [r.id for r in plan.rows] == [entry]
    assert not plan.problems


def test_a_foreign_currency_document_is_converted_proportionally(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry = docs.charge(-1000, instructed=(-1200, "USD"))
    doc = docs.document(total=-1200, currency="USD")
    docs.lines(doc, ("USB cable", -600), ("Case", -300), ("Shipping", -300))
    scene.settle()
    assert scene.row(entry).document_id == doc
    plan = scene.preview(entry)
    # lines convert by 1000 / 1200 and round half-even; the original takes the rest
    assert [r.amount for r in plan.rows] == [-500, -250, -250]
    preview_then_commit(
        scene,
        scene.draft(
            entry, echo(entry, doc, 2, -250), echo(entry, doc, 3, -250, category=fixed(shop.gadgets))
        ),
    )


# ---- picking another document, an existing split -----------------------------------------------------------


def test_picking_another_document_regenerates_the_proposal(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, a = order(scene, docs, *LINES)
    b = docs.document(total=-1000, external_id="b")
    docs.lines(b, ("Case", -600), ("USB cable", -400))
    # the client still echoes the row it made from the first document's third line
    stale = DraftEntry(
        proposed_split_id(entry, 3), amount=-300, source_entry_id=entry, document_line=DocumentLineRef(a, 3)
    )
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("pick", b, 1)), stale)
    assert [r.id for r in plan.rows] == [entry, proposed_split_id(entry, 2)]
    assert [r.amount for r in plan.rows] == [-600, -400]
    assert plan.row(entry).document_line == (b, 1)
    # the first line of the new document: "Case"; the second: "USB cable"
    assert plan.row(entry).fields["category"].value == shop.accessories
    assert plan.row(proposed_split_id(entry, 2)).fields["category"].value == shop.gadgets
    preview_then_commit(
        scene, scene.draft(entry, DraftEntry(entry, document=DocumentDraft("pick", b, 1)), stale)
    )


def test_the_proposal_replaces_an_existing_split_and_lists_what_it_deletes(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    _src, (first, second) = scene.movement(-600, -400, counterparty=CARD)
    doc = docs.document(total=-1000)
    docs.merchant(doc, "Seeed Studio")
    docs.lines(doc, *LINES)
    scene.settle()
    assert scene.row(first).document_id == doc
    tag = scene.tag("gift")
    scene.tag_entry(second, tag)
    plan = scene.preview(first)
    assert [r.id for r in plan.rows if r.stored is not None] == [first]
    view = plan.row(first).document_view
    assert view is not None and view.split is not None
    assert (view.split.proposed, view.split.available, view.split.replaces_stored_split) == (True, True, True)
    deleted = [c for c in plan.consequences if c.kind == "deleted"]
    assert [c.entry_id for c in deleted] == [second]
    assert {r.id for r in plan.removed} == {second}
    assert plan.removed[0].tag_ids == (tag,)  # the tags it deletes are shown
    assert [r.amount for r in plan.rows] == [-400, -300, -300]
    plan, result = preview_then_commit(scene, scene.draft(first))
    assert result.removed_entry_ids == (second,)
    assert scene.q("SELECT 1 FROM ledger_entry WHERE id = :i", i=second) == []
    assert len(result.created) == 2
    assert scene.preview(first).row(first).document_view.split.proposed is False  # type: ignore[union-attr]


def test_a_stored_split_that_is_the_proposal_shows_no_change(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, _doc = order(scene, docs, *LINES)
    preview_then_commit(scene, scene.draft(entry))
    matcher_link(scene, entry)  # the link is the matcher's again: something is still to be reviewed
    plan = scene.preview(entry)
    assert [r.id for r in plan.rows] == list(scene.unit_ids(entry))
    assert not [c for c in plan.consequences if c.kind in ("created", "deleted")]


def test_the_explicit_choice_replaces_a_split_by_hand_once_the_link_is_the_users(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    _src, (first, second) = scene.movement(-600, -400, counterparty=CARD)
    doc = docs.document(total=-1000)
    docs.lines(doc, *LINES)
    scene.settle()
    users_link(scene, first)
    assert [r.id for r in scene.preview(first).rows] == [first, second]  # it stands
    choice = DraftEntry(first, document=DocumentDraft("split_along_lines", doc, 1))
    plan = scene.preview(first, choice)
    assert [c.entry_id for c in plan.consequences if c.kind == "deleted"] == [second]
    plan, result = preview_then_commit(scene, scene.draft(first, choice))
    assert result.removed_entry_ids == (second,) and len(result.created) == 2


def test_two_charges_of_one_order_are_each_proposed_their_own_line(scene: Scene, docs: Docs) -> None:
    first = docs.charge(-3000)
    second = docs.charge(-2000, on=D + timedelta(days=1))
    doc = docs.document(total=-5000)
    docs.lines(doc, ("USB cable", -3000), ("Case", -2000))
    scene.settle()
    assert scene.row(first).document_id == scene.row(second).document_id == doc
    plan = scene.preview(first)
    assert {r.id for r in plan.rows} == {first, second}
    for carrier, line in ((first, 1), (second, 2)):
        row = plan.row(carrier)
        assert row.document_line == (doc, line)  # one line each: the original takes it, no extra entry
        view = row.document_view
        assert view is not None and view.split is not None and view.split.available
    assert [plan.row(first).amount, plan.row(second).amount] == [-3000, -2000]
    _plan, result = preview_then_commit(scene, scene.draft(first, versions=scene.versions(first)))
    assert not result.created
    refs = scene.q(
        "SELECT e.id, l.line_no FROM ledger_entry e"
        " JOIN external_document_line l ON l.id = e.document_line_id WHERE e.id = ANY(:ids) ORDER BY e.id",
        ids=[first, second],
    )
    assert [(r.id, r.line_no) for r in refs] == [(first, 1), (second, 2)]


def test_two_charges_of_one_order_with_several_lines_in_one(scene: Scene, docs: Docs) -> None:
    first = docs.charge(-1000)
    second = docs.charge(-500, on=D + timedelta(days=1))
    doc = docs.document(total=-1500)
    docs.lines(doc, ("a", -600), ("b", -500), ("c", -400))
    scene.settle()
    plan = scene.preview(first)
    # the earliest charge takes a and c (-1000), the next takes b
    assert [r.id for r in plan.rows] == [first, second, proposed_split_id(first, 3)]
    assert [r.amount for r in plan.rows] == [-600, -500, -400]
    assert plan.row(proposed_split_id(first, 3)).document_line == (doc, 3)
    assert plan.row(second).document_line == (doc, 2)
    _plan, result = preview_then_commit(scene, scene.draft(first, versions=scene.versions(first)))
    assert len(result.created) == 1


def test_a_coupon_line_folds_into_the_originals_remainder(scene: Scene, docs: Docs, shop: Shop) -> None:
    # items -400 -300 -400, a coupon of +100: the order's total is -1000
    entry, doc = order(scene, docs, ("USB cable", -400), ("Case", -300), ("Cable", -400), ("Coupon", 100))
    plan = scene.preview(entry)
    assert [r.id for r in plan.rows] == [entry, proposed_split_id(entry, 2), proposed_split_id(entry, 3)]
    assert [r.amount for r in plan.rows] == [-300, -300, -400]  # the original: -400 plus the coupon
    assert [r.document_line for r in plan.rows] == [(doc, 1), (doc, 2), (doc, 3)]


def test_a_wrongly_split_charge_is_corrected_when_a_new_charge_is_picked_in(scene: Scene, docs: Docs) -> None:
    _src, (original, extra) = scene.movement(-1000, -2000, counterparty=CARD)  # one charge of -3000
    doc = docs.document(total=-5000)
    docs.lines(doc, ("a", -2000), ("b", -3000))
    line_a = scene.q("SELECT id FROM external_document_line WHERE document_id = :d AND line_no = 1", d=doc)[
        0
    ].id
    users_link_to(scene, original, doc)
    scene.tx(
        lambda c: c.execute(
            text("UPDATE ledger_entry SET document_line_id = :l WHERE id = :e"), {"l": line_a, "e": extra}
        )
    )
    new = docs.charge(-2000, on=D + timedelta(days=1))
    version = scene.q("SELECT version FROM external_document WHERE id = :i", i=doc)[0].version
    plan = scene.preview(new, DraftEntry(new, document=DocumentDraft("pick", doc, version)))
    # the committed split referenced line a (-2000), which the new charge takes: the split is replaced
    assert [c.entry_id for c in plan.consequences if c.kind == "deleted"] == [extra]
    assert plan.row(original).amount == -3000 and plan.row(original).document_line == (doc, 2)
    assert plan.row(new).document_line == (doc, 1)
    _plan, result = preview_then_commit(
        scene, scene.draft(new, DraftEntry(new, document=DocumentDraft("pick", doc, version)))
    )
    assert result.removed_entry_ids == (extra,)


def test_the_explicit_choice_where_the_lines_do_not_fit_is_a_problem(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry = docs.charge(-1000)
    doc = docs.document(total=-999, external_id="off")
    docs.lines(doc, ("USB cable", -500), ("Case", -499))
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("split_along_lines", doc, 1)))
    assert [(p.code, p.entry_id) for p in plan.problems] == [("document_split_unavailable", entry)]
    assert [r.id for r in plan.rows] == [entry]


def test_picking_a_suggestion_with_several_lines_proposes_the_split(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry = docs.charge()
    a = docs.document(total=-1000, external_id="a")
    docs.document(total=-1000, external_id="b")
    docs.lines(a, *LINES)
    docs.merchant(a, "Seeed Studio")
    chosen = DraftEntry(entry, document=DocumentDraft("pick", a, 1))
    plan = scene.preview(entry, chosen)
    assert len(plan.rows) == 3 and plan.row(entry).document_id == a
    draft = scene.draft(
        entry, chosen, echo(entry, a, 2, -300), echo(entry, a, 3, -300, category=fixed(shop.gadgets))
    )
    plan, result = preview_then_commit(scene, draft)
    assert len(result.created) == 2


def test_a_commit_of_a_draft_that_never_echoed_the_proposal_performs_it(
    scene: Scene, docs: Docs, shop: Shop
) -> None:
    entry, doc = order(scene, docs, *LINES)
    plan, result = preview_then_commit(scene, scene.draft(entry))  # the same draft for both: no echo
    assert len(plan.rows) == 3 and len(result.created) == 2
    assert [r.amount for r in plan.rows] == [-400, -300, -300]
    stored = scene.row(entry)
    assert stored.document_id == doc and stored.derivation["document"] == {"pass": "user"}
    assert scene.preview(entry).row(entry).document_view.split.proposed is False  # type: ignore[union-attr]


def test_the_rows_of_a_split_inherit_the_originals_tags(scene: Scene, docs: Docs, shop: Shop) -> None:
    entry, _doc = order(scene, docs, *LINES)
    tag = scene.tag("gift")
    scene.tag_entry(entry, tag)
    plan, result = preview_then_commit(scene, scene.draft(entry))
    assert all(r.tag_ids == (tag,) for r in plan.rows)
    assert all(scene.tags_of(i) == (tag,) for i in result.created.values())
