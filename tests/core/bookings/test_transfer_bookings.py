"""Settle's booking step for charges (spec §5.7 'Transfers to a clearance account', §5.8): a charge decided as
a transfer to a clearance account books its counter-leg, paired with it and confirmed with it."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, text

from app.core.settle import settle
from tests.core.bookings.charges import (
    BOOKING_KEY,
    IBAN,
    START,
    booking_entries,
    booking_of,
    charge,
    clearance,
    confirmed,
    rule_to,
)
from tests.core.units.conftest import build_scene
from tests.core.units.scene import D, DraftEntry, Scene, fixed
from tests.invariants.helpers import make_entry, make_source


@pytest.fixture
def scene(isolated_engine: Engine, make_account: Callable[..., int]) -> Scene:
    return build_scene(isolated_engine, make_account)


# ---- a charge decided by a rule -------------------------------------------------------------------------


def test_a_rule_decided_charge_books_its_counter_leg_and_the_unit_is_confirmed(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene)
    assert scene.settle().error is None
    row = scene.row(e)
    assert (row.type, row.counter_account_id) == ("transfer", account)
    assert row.derivation["counter_account"]["pass"] == "rule"
    b = booking_of(scene, e)
    assert b is not None
    assert (b.origin, b.account_id, b.currency) == ("booking", account, "EUR")
    assert (b.importer, b.import_run_id, b.source_format) == (None, None, None)
    assert (b.booked_on, b.amount, b.purpose, b.counterparty_name) == (D, 4997, "AMZN Mktp", None)
    assert b.duplicate_of is None and b.raw
    (leg,) = booking_entries(scene, e)
    assert (leg.type, leg.account_id, leg.amount, leg.booked_on) == ("transfer", account, 4997, D)
    assert (leg.counter_account_id, leg.counterpart_entry_id) == (scene.checking, e)
    assert row.counterpart_entry_id == leg.id
    assert leg.derivation == {"type": BOOKING_KEY, "counter_account": BOOKING_KEY, "counterpart": BOOKING_KEY}
    assert row.derivation["counterpart"] == BOOKING_KEY
    assert (leg.review_flags, row.review_flags) == ([], [])
    assert confirmed(scene, e, leg.id)  # I22: confirmed as a pair
    scene.assert_checks_clean()


def test_a_decision_by_a_rule_on_an_existing_unit_books_at_the_next_settle(scene: Scene) -> None:
    account = clearance(scene)
    e = charge(scene)
    scene.settle()
    assert booking_of(scene, e) is None
    rule_to(scene, account)
    scene.settle()
    assert booking_of(scene, e) is not None


def test_pass_0_decides_a_transfer_by_the_clearance_accounts_iban_and_it_is_booked(scene: Scene) -> None:
    account = clearance(scene, external_ref=IBAN)
    e = charge(scene, counterparty="Amazon Payments", ref="DE89370400440532013000")
    scene.settle()
    row = scene.row(e)
    assert (row.type, row.counter_account_id) == ("transfer", account)
    assert row.derivation["counter_account"]["pass"] == "own_account"
    assert booking_of(scene, e) is not None
    assert confirmed(scene, e)


def test_a_charge_whose_counter_account_is_only_proposed_has_no_booking(scene: Scene) -> None:
    account = clearance(scene)
    old = charge(scene, on=date(2026, 2, 1))
    # history proposes the clearance account for the next charge from the same counterparty: a proposal
    scene.tx(
        lambda c: c.execute(
            text(
                "UPDATE ledger_entry SET type = 'transfer', counter_account_id = :a,"
                " derivation = CAST(:d AS jsonb) WHERE id = :i"
            ),
            {
                "a": account,
                "i": old,
                "d": json.dumps({"type": {"pass": "user"}, "counter_account": {"pass": "user"}}),
            },
        )
    )
    scene.settle()  # the first one is the user's decision: booked
    assert booking_of(scene, old) is not None
    new = charge(scene, on=date(2026, 2, 5))
    scene.settle()
    row = scene.row(new)
    assert row.counter_account_id == account  # history proposed it
    assert row.derivation["counter_account"]["pass"] == "history"
    assert booking_of(scene, new) is None and row.counterpart_entry_id is None
    assert not confirmed(scene, new)


def test_the_booking_step_is_idempotent_for_charges(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    charge(scene)
    charge(scene, -1500, on=date(2026, 3, 11))
    scene.settle()
    before = scene.q(
        "SELECT id, version, derivation, review_flags, counterpart_entry_id FROM ledger_entry ORDER BY id"
    )
    sources = scene.q("SELECT id FROM source_transaction ORDER BY id")
    again = settle(scene.engine)
    assert again.error is None and again.touched_entry_ids == ()
    assert (
        scene.q(
            "SELECT id, version, derivation, review_flags, counterpart_entry_id FROM ledger_entry ORDER BY id"
        )
        == before
    )
    assert scene.q("SELECT id FROM source_transaction ORDER BY id") == sources


def test_the_clearance_balance_follows_the_bookings(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    charge(scene, -4997)
    scene.settle()
    (bal,) = scene.q("SELECT balance FROM v_account_balance WHERE account_id = :a", a=account)
    assert bal.balance == 4997


# ---- matching stays off clearance accounts --------------------------------------------------------------


def test_a_leg_toward_a_clearance_account_is_never_paired_with_a_hand_made_entry(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, -4997, on=D)
    # a hand-made opposite entry on the clearance account, an untyped one a pass cannot type as a transfer
    other = scene.tx(
        lambda c: make_entry(
            c,
            make_source(c, account, amount=4997, booked_on=D, importer=None, source_id="hand", origin="user"),
            type="transfer",
            counter_account_id=scene.checking,
            derivation=json.dumps({"type": {"pass": "user"}}),
        )
    )
    scene.settle()
    row = scene.row(e)
    assert row.counterpart_entry_id != other
    assert scene.row(other).counterpart_entry_id is None
    assert booking_of(scene, e) is not None  # the booking is its pair


def test_no_pass_types_a_hand_made_entry_on_a_clearance_account_as_a_transfer(scene: Scene) -> None:
    account = clearance(scene, external_ref=IBAN)
    other = scene.tx(
        lambda c: make_entry(
            c,
            make_source(
                c,
                account,
                amount=-100,
                booked_on=D,
                importer=None,
                source_id="hand",
                origin="user",
                columns={"counterparty_ref": "DE02120300000000202051", "counterparty_name": "hand"},
            ),
            type=None,
        )
    )
    scene.tx(
        lambda c: c.execute(
            text("UPDATE account SET external_ref = 'de02120300000000202051' WHERE id = :i"),
            {"i": scene.savings},
        )
    )
    rule_to(scene, scene.savings, "hand")  # pass 0 (the reference) and a rule would both say transfer
    scene.settle()
    row = scene.row(other)
    assert (row.type, row.counter_account_id, row.counterpart_entry_id) == (None, None, None)


# ---- the booking follows its charge ---------------------------------------------------------------------


def unpair(scene: Scene, *ids: int) -> None:
    scene.tx(
        lambda c: c.execute(
            text("UPDATE ledger_entry SET counterpart_entry_id = NULL WHERE id = ANY(:i)"), {"i": list(ids)}
        )
    )


def test_retyping_the_charge_removes_the_booking(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    unpair(scene, e, leg.id)
    cat = scene.category("Books")
    scene.tx(
        lambda c: c.execute(
            text(
                "UPDATE ledger_entry SET type = 'flow', counter_account_id = NULL, category_id = :c,"
                " derivation = CAST(:d AS jsonb) WHERE id = :i"
            ),
            {"c": cat, "i": e, "d": json.dumps({"type": {"pass": "user"}, "category": {"pass": "user"}})},
        )
    )
    assert scene.settle().error is None
    assert booking_of(scene, e) is None and booking_entries(scene, e) == []
    assert scene.q("SELECT id FROM ledger_entry WHERE account_id = :a", a=account) == []
    row = scene.row(e)
    assert (row.type, row.counterpart_entry_id) == ("flow", None) and "counterpart" not in row.derivation
    (bal,) = scene.q("SELECT balance FROM v_account_balance WHERE account_id = :a", a=account)
    assert bal.balance == 0


def test_moving_the_charge_to_another_clearance_account_moves_the_booking(scene: Scene) -> None:
    first = clearance(scene, "Amazon.de")
    second = clearance(scene, "Zalando")
    rule_to(scene, first)
    e = charge(scene)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    unpair(scene, e, leg.id)
    scene.tx(
        lambda c: c.execute(
            text(
                "UPDATE ledger_entry SET counter_account_id = :a,"
                " derivation = derivation || CAST(:d AS jsonb) WHERE id = :i"
            ),
            {"a": second, "i": e, "d": json.dumps({"counter_account": {"pass": "user"}})},
        )
    )
    assert scene.settle().error is None
    (moved,) = booking_entries(scene, e)
    assert (moved.account_id, moved.amount, moved.counter_account_id) == (second, 4997, scene.checking)
    assert booking_of(scene, e).account_id == second
    assert scene.q("SELECT id FROM ledger_entry WHERE account_id = :a", a=first) == []
    row = scene.row(e)
    assert row.counterpart_entry_id == moved.id and row.counter_account_id == second
    assert confirmed(scene, e, moved.id)


def test_a_changed_amount_date_and_purpose_rederive_the_booking(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, -4997, authored=True)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    src = scene.row(e).source_transaction_id
    unpair(scene, e, leg.id)  # what the entry form does when an edit moves the amount of a paired leg
    scene.tx(
        lambda c: (
            c.execute(
                text(
                    "UPDATE source_transaction SET amount = -5100, booked_on = :on, purpose = 'new'"
                    " WHERE id = :s"
                ),
                {"s": src, "on": date(2026, 3, 12)},
            ),
            c.execute(
                text("UPDATE ledger_entry SET amount = -5100, booked_on = :on WHERE id = :i"),
                {"i": e, "on": date(2026, 3, 12)},
            ),
        )
    )
    assert scene.settle().error is None
    (again,) = booking_entries(scene, e)
    assert again.id == leg.id  # re-derived, not made again
    assert (again.amount, again.booked_on) == (5100, date(2026, 3, 12))
    b = booking_of(scene, e)
    assert (b.amount, b.booked_on, b.purpose) == (5100, date(2026, 3, 12), "new")
    assert scene.row(e).counterpart_entry_id == leg.id and again.counterpart_entry_id == e
    assert confirmed(scene, e, leg.id)


def test_a_split_charge_books_the_residual_the_transfer_entry_holds(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, -4997, authored=True)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    src = scene.row(e).source_transaction_id
    unpair(scene, e, leg.id)
    scene.tx(
        lambda c: (
            c.execute(text("UPDATE ledger_entry SET amount = -3000 WHERE id = :i"), {"i": e}),
            make_entry(c, src, amount=-1997, type="flow", category_id=scene.category("Food")),
        )
    )
    assert scene.settle().error is None
    (again,) = booking_entries(scene, e)
    assert again.amount == 3000 and booking_of(scene, e).amount == 3000


def test_a_cross_currency_charge_books_its_instructed_amount_on_the_account_in_that_currency(
    scene: Scene,
) -> None:
    usd = clearance(scene, "Amazon.com", currency="USD")
    rule_to(scene, usd)
    e = charge(scene, -4997, instructed=(-5500, "USD"))
    scene.settle()
    (leg,) = booking_entries(scene, e)
    assert (leg.account_id, leg.amount, leg.currency) == (usd, 5500, "USD")
    assert scene.row(e).counterpart_entry_id == leg.id
    assert booking_of(scene, e).amount == 5500


def test_a_charge_without_an_instructed_amount_is_not_booked_on_a_foreign_currency_account(
    scene: Scene,
) -> None:
    usd = clearance(scene, "Amazon.com", currency="USD")
    e = charge(scene, -4997)
    scene.tx(
        lambda c: c.execute(
            text(
                "UPDATE ledger_entry SET type = 'transfer', counter_account_id = :a,"
                " derivation = CAST(:d AS jsonb) WHERE id = :i"
            ),
            {
                "a": usd,
                "i": e,
                "d": json.dumps({"type": {"pass": "user"}, "counter_account": {"pass": "user"}}),
            },
        )
    )
    assert scene.settle().error is None
    assert booking_of(scene, e) is None
    assert scene.row(e).counterpart_entry_id is None


def test_a_charge_booked_in_the_wrong_currency_loses_its_booking(scene: Scene) -> None:
    eur = clearance(scene, "Amazon.de")
    usd = clearance(scene, "Amazon.com", currency="USD")
    rule_to(scene, eur)
    e = charge(scene, -4997, authored=True)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    unpair(scene, e, leg.id)
    scene.tx(
        lambda c: c.execute(
            text(
                "UPDATE ledger_entry SET counter_account_id = :a,"
                " derivation = derivation || CAST(:d AS jsonb) WHERE id = :i"
            ),
            {"a": usd, "i": e, "d": json.dumps({"counter_account": {"pass": "user"}})},
        )
    )
    scene.settle()
    assert (
        booking_of(scene, e) is None
    )  # a USD account does not take a EUR charge without an instructed amount
    assert scene.q("SELECT id FROM ledger_entry WHERE account_id = ANY(:a)", a=[eur, usd]) == []


def test_deleting_the_charge_removes_the_booking(scene: Scene) -> None:
    from app.core.ledger.sources import delete_source

    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, authored=True)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    src = scene.row(e).source_transaction_id
    versions = {i: scene.row(i).version for i in (e, leg.id)}
    delete_source(scene.engine, src, expected_versions=versions)
    assert booking_of(scene, e) is None
    assert scene.q("SELECT id FROM ledger_entry WHERE account_id = :a", a=account) == []


def test_a_committed_transfer_books_the_counter_leg(scene: Scene) -> None:
    account = clearance(scene)
    e = charge(scene)
    scene.settle()
    assert booking_of(scene, e) is None
    result = scene.commit(e, DraftEntry(e, counter_account=fixed(account)))
    assert result.settle.error is None
    (leg,) = booking_entries(scene, e)
    assert (leg.account_id, leg.amount, leg.counterpart_entry_id) == (account, 4997, e)
    row = scene.row(e)
    assert (row.type, row.counter_account_id, row.counterpart_entry_id) == ("transfer", account, leg.id)
    assert row.derivation["counter_account"]["pass"] == "user"
    assert row.derivation["counterpart"] == BOOKING_KEY
    assert confirmed(scene, e, leg.id)


def test_an_entry_form_edit_of_an_authored_charge_re_derives_its_booking_and_pairs_it_again(
    scene: Scene,
) -> None:
    from app.core.ledger.sources import update_source

    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, -4997, authored=True)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    src = scene.row(e).source_transaction_id
    versions = {i: scene.row(i).version for i in (e, leg.id)}
    done = update_source(
        scene.engine,
        src,
        amount=-5100,
        purpose="new",
        booked_on=date(2026, 3, 12),
        expected_versions=versions,
    )
    assert done.settle is not None and done.settle.error is None
    (after,) = booking_entries(scene, e)
    assert after.id == leg.id and (after.amount, after.booked_on) == (5100, date(2026, 3, 12))
    b = booking_of(scene, e)
    assert (b.amount, b.purpose, b.booked_on) == (5100, "new", date(2026, 3, 12))
    row = scene.row(e)
    assert row.counterpart_entry_id == leg.id and after.counterpart_entry_id == e
    assert row.derivation["counterpart"] == BOOKING_KEY and after.derivation["counterpart"] == BOOKING_KEY
    assert confirmed(scene, e, leg.id)
    scene.assert_checks_clean()


# ---- the start of the clearance account: a leg on or before it is the source of no booking --------------


@pytest.mark.parametrize(
    ("on", "booked"),
    [(START - timedelta(days=1), False), (START, False), (START + timedelta(days=1), True)],
)
def test_a_charge_dated_on_or_before_the_start_books_no_counter_leg(
    scene: Scene, on: date, booked: bool
) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, on=on)
    assert scene.settle().error is None
    assert (booking_of(scene, e) is not None) is booked
    assert (scene.row(e).counterpart_entry_id is not None) is booked
    if not booked:
        assert scene.row(e).review_flags != []  # an unpaired transfer leg, in review


def test_a_charge_toward_a_clearance_account_without_a_start_books_nothing(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    scene.tx(lambda c: c.execute(text("DELETE FROM balance_record WHERE account_id = :a"), {"a": account}))
    e = charge(scene)
    assert scene.settle().error is None
    assert booking_of(scene, e) is None
    assert scene.row(e).counterpart_entry_id is None
