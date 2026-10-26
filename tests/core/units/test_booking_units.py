"""Bookings in the preview and the commit (spec §5.7, §5.8, §6): the counter-leg of a charge decided to a
clearance account, shown as a row settling will make; a booking's entries fixed to their source."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine

from app.core.ledger.sources import NotUserAuthored, delete_source, update_source
from app.core.settle.settle import SettleResult
from app.core.units import commit as commit_module
from app.core.units.commit import CommitRefused
from app.core.units.draft import CounterLegDraft, DraftEntry, DraftError, PairingDraft
from app.core.units.overlay import booking_temp_id
from app.core.units.plan import Plan
from app.core.units.preview import preview_unit
from app.core.units.read import get_unit, review_queue
from tests.core.bookings.charges import (
    BOOKING_KEY,
    booking_entries,
    booking_of,
    charge,
    clearance,
    confirmed,
    rule_to,
)
from tests.core.bookings.scene import Scene as DocScene
from tests.core.bookings.scene import doc, line
from tests.core.units.conftest import build_scene
from tests.core.units.scene import D, Scene, fixed


@pytest.fixture
def scene(isolated_engine: Engine, make_account: Callable[..., int]) -> Scene:
    return build_scene(isolated_engine, make_account)


def codes(plan: Plan) -> list[str]:
    return sorted(p.code for p in plan.problems)


def no_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit that is not followed by its settle: what the commit itself writes."""
    monkeypatch.setattr(commit_module, "settle", lambda _engine: SettleResult())


# ---- a charge decided to a clearance account: the booking settling will make ------------------------------


def test_the_preview_shows_the_counter_leg_booking_settling_will_make(scene: Scene) -> None:
    account = clearance(scene)
    e = charge(scene, -4997, purpose="AMZN Mktp")
    plan = scene.preview(e, DraftEntry(e, counter_account=fixed(account)))
    ghost = booking_temp_id(e)
    b = plan.row(ghost)
    assert b.booking_for == e and b.counter_leg_for is None
    assert (b.booking, b.booking_key) == ("transfer", e)
    assert b.version is None and b.stored is None and b.in_unit and b.original
    assert (b.account_id, b.amount, b.currency, b.booked_on) == (account, 4997, "EUR", D)
    assert (b.purpose, b.counterpart_entry_id, b.description) == ("AMZN Mktp", e, None)
    assert b.fields["type"].value == "transfer" and b.fields["counter_account"].value == scene.checking
    assert b.derivation == {"type": BOOKING_KEY, "counter_account": BOOKING_KEY, "counterpart": BOOKING_KEY}
    c = plan.row(e)
    assert c.counterpart_entry_id == ghost and c.derivation["counterpart"] == BOOKING_KEY
    assert c.derivation["counter_account"]["pass"] == "user"
    assert plan.transfers[e].state == "paired" and plan.transfers[e].partner is not None
    assert plan.transfers[e].partner.entry_id == ghost
    assert plan.transfers[e].offers == () and plan.transfers[e].proposal is None
    assert plan.anchor_unit.state.confirmed and plan.anchor_unit.entry_ids == (e, ghost)
    assert not plan.problems and plan.created_ids == () and plan.booking_dropped == ()
    assert ghost not in {c.entry_id for c in plan.consequences}


def test_a_proposed_counter_account_is_shown_with_the_booking_the_commit_leads_to(scene: Scene) -> None:
    account = clearance(scene)
    cat = scene.category("Books")  # only so history has a flow vote to compare against
    old = charge(scene, on=date(2026, 2, 1))
    scene.commit(old, DraftEntry(old, counter_account=fixed(account)))
    new = charge(scene, on=date(2026, 2, 5))
    scene.settle()
    row = scene.row(new)
    assert cat and row.counter_account_id == account  # history proposes the account the charges went to
    assert row.derivation["counter_account"]["pass"] == "history"
    assert booking_of(scene, new) is None and not confirmed(scene, new)
    plan = scene.preview(new)
    assert plan.row(booking_temp_id(new)).booking_for == new  # a commit takes the proposal as the user's
    assert plan.anchor_unit.state.confirmed


def test_a_commit_does_not_write_the_booking_settling_makes_it(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = clearance(scene)
    e = charge(scene, -4997)
    draft = scene.draft(e, DraftEntry(e, counter_account=fixed(account)))
    plan = preview_unit(scene.engine, draft)
    no_settle(monkeypatch)
    result = scene.commit_draft(dataclasses.replace(draft, versions={**draft.versions, **plan.versions}))
    assert booking_of(scene, e) is None and result.created == {}
    assert scene.q("SELECT id FROM ledger_entry WHERE account_id = :a", a=account) == []
    assert scene.row(e).counterpart_entry_id is None
    assert plan.row(booking_temp_id(e)).booking_for == e and booking_temp_id(e) not in result.created
    monkeypatch.undo()
    assert scene.settle().error is None  # settling books it, as the preview showed
    (leg,) = booking_entries(scene, e)
    b = plan.row(booking_temp_id(e))
    assert (leg.account_id, leg.amount, leg.booked_on, leg.type) == (
        b.account_id,
        b.amount,
        b.booked_on,
        "transfer",
    )
    assert (leg.counter_account_id, leg.counterpart_entry_id) == (b.fields["counter_account"].value, e)
    assert dict(leg.derivation) == dict(b.derivation) and list(leg.review_flags) == list(b.flags)
    row = scene.row(e)
    assert row.counterpart_entry_id == leg.id
    assert dict(row.derivation) == dict(plan.row(e).derivation)
    assert list(row.review_flags) == list(plan.row(e).flags)
    assert confirmed(scene, e, leg.id)
    scene.assert_checks_clean()


def test_a_commit_result_carries_the_charge_and_the_settled_booking(scene: Scene) -> None:
    account = clearance(scene)
    e = charge(scene, -4997)
    result = scene.commit(e, DraftEntry(e, counter_account=fixed(account)))
    assert result.settle.error is None
    (leg,) = booking_entries(scene, e)
    assert e in {r.id for r in result.entries}
    assert leg.id in set(result.settle.touched_entry_ids)
    assert not any(i < 0 for i in result.created)


def test_a_rule_decided_charge_shows_its_stored_booking_as_a_booking_row(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    plan = scene.preview(e)
    b = plan.row(leg.id)
    assert (b.booking, b.booking_key, b.booking_for) == ("transfer", e, None)
    assert b.stored is not None and b.counterpart_entry_id == e
    assert plan.anchor_unit.state.confirmed and not plan.problems and not plan.consequences
    assert plan.row(e).booking is None
    # opened from the booking entry the unit is the same
    assert preview_unit(scene.engine, scene.draft(leg.id)).anchor_unit.entry_ids == (e, leg.id)


def test_re_typing_the_charge_shows_the_booking_it_removes_and_the_commit_lets_settling_remove_it(
    scene: Scene,
) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    cat = scene.category("Books")
    draft = scene.draft(e, DraftEntry(e, type=fixed("flow"), category=fixed(cat)))
    plan = preview_unit(scene.engine, draft)
    assert not plan.problems
    assert leg.id not in {r.id for r in plan.rows}  # the row disappears with its booking
    assert (leg.id, "deleted") in {(c.entry_id, c.kind) for c in plan.consequences}
    assert [d.entry.id for d in plan.booking_dropped] == [leg.id] and plan.removed == ()
    assert plan.row(e).fields["type"].value == "flow" and plan.row(e).counterpart_entry_id is None
    result = scene.commit_draft(dataclasses.replace(draft, versions={**draft.versions, **plan.versions}))
    assert result.settle.error is None and result.removed_entry_ids == ()
    assert (
        booking_of(scene, e) is None and scene.q("SELECT id FROM ledger_entry WHERE id = :i", i=leg.id) == []
    )
    row = scene.row(e)
    assert (row.type, row.category_id, row.counterpart_entry_id) == ("flow", cat, None)
    scene.assert_checks_clean()
    assert scene.settle().touched_entry_ids == ()


def test_a_draft_anchored_on_the_booking_that_removes_it_keeps_a_unit(scene: Scene) -> None:
    e, leg = booked_charge(scene)
    cat = scene.category("Books")
    draft = scene.draft(leg, DraftEntry(e, type=fixed("flow"), category=fixed(cat)))
    plan = preview_unit(scene.engine, draft)
    assert not plan.problems and leg not in {r.id for r in plan.rows}
    assert plan.anchor_unit.entry_ids == (e,) and (leg, "deleted") in {
        (c.entry_id, c.kind) for c in plan.consequences
    }
    scene.commit_draft(dataclasses.replace(draft, versions={**draft.versions, **plan.versions}))
    assert booking_of(scene, e) is None and scene.row(e).type == "flow"


def test_moving_the_charge_to_another_clearance_account_shows_the_old_booking_gone_and_the_new_one(
    scene: Scene,
) -> None:
    first = clearance(scene, "Amazon.de")
    second = clearance(scene, "Zalando")
    rule_to(scene, first)
    e = charge(scene)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    draft = scene.draft(e, DraftEntry(e, counter_account=fixed(second)))
    plan = preview_unit(scene.engine, draft)
    assert not plan.problems
    assert leg.id not in {r.id for r in plan.rows} and (leg.id, "deleted") in {
        (c.entry_id, c.kind) for c in plan.consequences
    }
    new = plan.row(booking_temp_id(e))
    assert new.account_id == second and new.booking_for == e and plan.row(e).counterpart_entry_id == new.id
    scene.commit_draft(dataclasses.replace(draft, versions={**draft.versions, **plan.versions}))
    (moved,) = booking_entries(scene, e)
    assert moved.account_id == second and moved.id != leg.id
    assert scene.row(e).counterpart_entry_id == moved.id
    scene.assert_checks_clean()
    assert scene.settle().touched_entry_ids == ()


def test_a_split_of_the_charge_makes_the_booking_follow_its_amount(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, -4997)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    cat = scene.category("Food")
    split = DraftEntry(-5, amount=-1997, source_entry_id=e, category=fixed(cat))
    draft = scene.draft(e, split, DraftEntry(e))
    plan = preview_unit(scene.engine, draft)
    assert not plan.problems, plan.problems
    b = plan.row(leg.id)
    assert b.amount == 3000 and plan.row(e).amount == -3000
    draft = dataclasses.replace(draft, versions={**draft.versions, **plan.versions})
    result = scene.commit_draft(draft)
    assert result.settle.error is None
    (after,) = booking_entries(scene, e)
    assert after.id == leg.id and after.amount == 3000 and booking_of(scene, e).amount == 3000
    assert scene.row(e).amount == -3000 and scene.row(e).counterpart_entry_id == leg.id
    (bal,) = scene.q("SELECT balance FROM v_account_balance WHERE account_id = :a", a=account)
    assert bal.balance == 3000
    scene.assert_checks_clean()
    assert scene.settle().touched_entry_ids == ()


def test_a_cross_currency_charge_is_booked_by_its_instructed_amount(scene: Scene) -> None:
    usd = clearance(scene, "Amazon.com", currency="USD")
    e = charge(scene, -4997, instructed=(-5500, "USD"))
    plan = scene.preview(e, DraftEntry(e, counter_account=fixed(usd)))
    b = plan.row(booking_temp_id(e))
    assert (b.amount, b.currency, b.account_id) == (5500, "USD", usd)
    assert not plan.problems
    scene.commit(e, DraftEntry(e, counter_account=fixed(usd)))
    (leg,) = booking_entries(scene, e)
    assert (leg.amount, leg.currency) == (5500, "USD")


def test_a_charge_without_an_instructed_amount_cannot_go_to_a_foreign_currency_clearance_account(
    scene: Scene,
) -> None:
    usd = clearance(scene, "Amazon.com", currency="USD")
    e = charge(scene, -4997)
    plan = scene.preview(e, DraftEntry(e, counter_account=fixed(usd)))
    assert "currency_rule" in codes(plan)
    assert not any(r.booking_for for r in plan.rows)
    with pytest.raises(CommitRefused) as refused:
        scene.commit(e, DraftEntry(e, counter_account=fixed(usd)))
    assert refused.value.problems[0].code == "currency_rule"
    assert booking_of(scene, e) is None


def test_a_flow_charge_has_no_booking(scene: Scene) -> None:
    clearance(scene)
    e = charge(scene)
    cat = scene.category("Books")
    plan = scene.preview(e, DraftEntry(e, category=fixed(cat)))
    assert not any(r.booking_for for r in plan.rows) and plan.booking_dropped == ()


# ---- clearance accounts stay off the transfer matcher -----------------------------------------------------


def hand_made(scene: Scene, account: int, amount: int = 4997, **kw: Any) -> int:
    _src, (e,) = scene.movement(amount, account=account, authored=True, **kw)
    return e


def test_a_leg_toward_a_clearance_account_has_no_offers_and_no_counter_leg(scene: Scene) -> None:
    account = clearance(scene)
    hand_made(scene, account, 4997)  # an entry on the clearance account that would match by amount
    e = charge(scene, -4997)
    plan = scene.preview(e, DraftEntry(e, counter_account=fixed(account)))
    t = plan.transfers[e]
    assert t.offers == () and t.proposal is None
    assert t.state == "paired" and t.partner is not None and t.partner.entry_id == booking_temp_id(e)


def test_an_entry_on_a_clearance_account_is_not_an_offer_for_another_leg(scene: Scene) -> None:
    account = clearance(scene)
    other = hand_made(scene, account, 4997)
    e = charge(scene, -4997)
    plan = scene.preview(e, DraftEntry(e, type=fixed("transfer")))
    assert other not in {o.entry_id for o in plan.transfers[e].offers}


def test_a_pick_toward_or_from_a_clearance_account_is_refused(scene: Scene) -> None:
    account = clearance(scene)
    other = hand_made(scene, account, 4997)
    e = charge(scene, -4997)
    plan = scene.preview(e, DraftEntry(e, type=fixed("transfer"), pairing=PairingDraft("pick", other)))
    assert "partner_not_offered" in codes(plan)


def test_a_counter_leg_for_a_clearance_account_is_refused(scene: Scene) -> None:
    account = clearance(scene)
    e = charge(scene, -4997)
    entry = DraftEntry(
        e,
        counter_account=fixed(account),
        pairing=PairingDraft("counter_leg", counter_leg=CounterLegDraft(-3)),
    )
    plan = scene.preview(e, entry)
    assert "counter_leg_not_offered" in codes(plan)


def test_converting_an_entry_on_a_clearance_account_to_a_transfer_is_refused(scene: Scene) -> None:
    account = clearance(scene)
    e = hand_made(scene, account, -100, on=D)
    plan = scene.preview(e, DraftEntry(e, counter_account=fixed(scene.savings)))
    assert "clearance_transfer" in codes(plan)
    with pytest.raises(CommitRefused) as refused:
        scene.commit(e, DraftEntry(e, counter_account=fixed(scene.savings)))
    assert refused.value.problems[0].code == "clearance_transfer"
    assert scene.row(e).type != "transfer"


def test_a_correction_on_a_clearance_account_is_an_ordinary_flow(scene: Scene) -> None:
    account = clearance(scene)
    e = hand_made(scene, account, -100)
    cat = scene.category("Books")
    plan = scene.preview(e, DraftEntry(e, category=fixed(cat)))
    assert not plan.problems and plan.row(e).fields["type"].value == "flow"
    scene.commit(e, DraftEntry(e, category=fixed(cat)))
    assert scene.row(e).category_id == cat


# ---- a booking's entries are fixed to their source --------------------------------------------------------


def refused(scene: Scene, anchor: int, *entries: DraftEntry, **kw: Any) -> DraftError:
    with pytest.raises(DraftError) as err:
        preview_unit(scene.engine, scene.draft(anchor, *entries, **kw))
    assert err.value.code == "booking_fixed"
    with pytest.raises(DraftError) as err2:
        scene.commit(anchor, *entries, **kw)
    assert err2.value.code == "booking_fixed"
    return err.value


def booked_charge(scene: Scene) -> tuple[int, int]:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    return e, leg.id


def test_a_draft_that_changes_a_transfer_bookings_type_amount_or_pair_is_refused(scene: Scene) -> None:
    e, leg = booked_charge(scene)
    refused(scene, e, DraftEntry(leg, type=fixed("flow")))
    refused(scene, e, DraftEntry(leg, counter_account=fixed(scene.savings)))
    refused(scene, e, DraftEntry(leg, amount=123))
    refused(scene, e, DraftEntry(leg, pairing=PairingDraft("reresolve")))
    refused(scene, e, DraftEntry(leg, pairing=PairingDraft("pick", e)))
    refused(scene, e, DraftEntry(-9, amount=-100, source_entry_id=leg))
    refused(scene, e, removed_entry_ids=[leg])
    assert scene.row(leg).counterpart_entry_id == e


def test_the_refusal_names_the_entry_and_the_field(scene: Scene) -> None:
    e, leg = booked_charge(scene)
    err = refused(scene, e, DraftEntry(leg, type=fixed("flow")))
    assert (err.entry_id, err.field) == (leg, "type")


def test_a_transfer_bookings_unchanged_values_are_not_a_change(scene: Scene) -> None:
    e, leg = booked_charge(scene)
    row = scene.row(leg)
    same = DraftEntry(leg, type=fixed("transfer"), counter_account=fixed(row.counter_account_id))
    plan = preview_unit(scene.engine, scene.draft(e, same))
    assert not plan.problems and plan.row(leg).counterpart_entry_id == e


def test_the_description_note_and_tags_of_a_transfer_booking_stay_editable(scene: Scene) -> None:
    e, leg = booked_charge(scene)
    tag = scene.tag("Amazon")
    entry = DraftEntry(leg, description="Order", note="n", tags_add=(tag,))
    plan = preview_unit(scene.engine, scene.draft(e, entry))
    assert not plan.problems
    assert (plan.row(leg).description, plan.row(leg).note) == ("Order", "n")
    scene.commit(e, entry)
    row = scene.row(leg)
    assert (row.description, row.note) == ("Order", "n") and scene.tags_of(leg) == (tag,)
    assert row.counterpart_entry_id == e and row.derivation["type"] == BOOKING_KEY
    assert confirmed(scene, e, leg)


@pytest.fixture
def documents(scene: Scene) -> DocScene:
    return DocScene(scene.engine)


def test_a_document_bookings_structure_is_fixed_but_its_values_are_editable(
    scene: Scene, documents: DocScene
) -> None:
    documents.clearance()
    documents.deliver(doc("A1", line("Cable", -1299), line("Book", -3499)))
    first, second = (e.id for e in documents.entries())
    refused(scene, first, DraftEntry(first, type=fixed("transfer")))
    refused(scene, first, DraftEntry(second, amount=-1000))
    refused(scene, first, DraftEntry(first, pairing=PairingDraft("reresolve")))
    refused(scene, first, DraftEntry(-4, amount=-100, source_entry_id=first))
    refused(scene, first, removed_entry_ids=[second])
    cat = scene.category("Books")
    entry = DraftEntry(second, category=fixed(cat), note="gift")
    plan = preview_unit(scene.engine, scene.draft(first, entry))
    assert not plan.problems
    assert (plan.row(second).booking, plan.row(second).booking_key) == (
        "document",
        documents.document_id("A1"),
    )
    scene.commit(first, entry)
    row = scene.row(second)
    assert (row.category_id, row.note, row.type) == (cat, "gift", "flow")
    assert row.derivation["type"] == BOOKING_KEY and row.derivation["category"]["pass"] == "user"


# ---- the entry form, the queue ----------------------------------------------------------------------------


def test_the_entry_form_refuses_a_booking(scene: Scene) -> None:
    e, leg = booked_charge(scene)
    src = scene.row(leg).source_transaction_id
    with pytest.raises(NotUserAuthored):
        update_source(scene.engine, src, amount=1, dry_run=True)
    with pytest.raises(NotUserAuthored):
        delete_source(scene.engine, src, dry_run=True)
    assert e


def test_the_queue_and_the_unit_mark_a_booking_with_its_source_kind(
    scene: Scene, documents: DocScene
) -> None:
    documents.clearance()
    documents.deliver(doc("A1", line("Cable", -1299), line("Book", -3499)))
    e = charge(scene, -4997)
    with scene.engine.connect() as conn:
        queue = review_queue(conn, section="pending_review")
        (booked,) = (u for u in queue.sections[0].units if u.booking is not None)
        plain = [u for u in queue.sections[0].units if u.booking is None]
        assert booked.booking == "document" and {r.origin for r in booked.entries} == {"booking"}
        assert [u.anchor_entry_id for u in plain] == [e]
        assert get_unit(conn, booked.anchor_entry_id).booking == "document"  # type: ignore[union-attr]
        assert get_unit(conn, e).booking is None  # type: ignore[union-attr]


def test_a_transfer_bookings_unit_is_marked_transfer(scene: Scene) -> None:
    e, leg = booked_charge(scene)
    with scene.engine.connect() as conn:
        for entry in (e, leg):
            view = get_unit(conn, entry)
            assert view is not None and view.booking == "transfer" and view.state.confirmed
            assert {r.booking for r in view.entries if r.booking} == {("transfer", e)}


# ---- locks --------------------------------------------------------------------------------------------


def test_the_commit_locks_no_clearance_account_it_does_not_write_and_settling_locks_only_those(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.bookings import write
    from app.utils.db import locks

    account = clearance(scene)
    e = charge(scene, -4997)
    seen: dict[str, list[list[int]]] = {"commit": [], "step": []}

    def recording(where: str) -> Callable[..., Any]:
        def lock(conn: Any, ids: Any) -> Any:
            ids = sorted(ids)
            seen[where].append(ids)
            return locks.lock_accounts(conn, ids)

        return lock

    monkeypatch.setattr(commit_module, "lock_accounts", recording("commit"))
    monkeypatch.setattr(write, "lock_accounts", recording("step"))
    scene.commit(e, DraftEntry(e, counter_account=fixed(account)))
    assert seen["commit"] == [[scene.checking]]  # the commit writes the charge's account only
    assert seen["step"] == [[account]]  # settling writes, and locks, the clearance account only
    assert booking_of(scene, e) is not None
