"""The start of a clearance account decides only where a charge not yet booked goes (spec §5.8): an existing
transfer booking stays when the start changes, and follows its charge otherwise."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, text

from app.core.ledger.sources import update_source
from tests.core.bookings.charges import booking_of, charge, clearance, rule_to
from tests.core.units.conftest import build_scene
from tests.core.units.scene import D, Scene


@pytest.fixture
def scene(isolated_engine: Engine, make_account: Callable[..., int]) -> Scene:
    return build_scene(isolated_engine, make_account)


def move_start(scene: Scene, account: int, to: date) -> None:
    scene.tx(
        lambda c: c.execute(
            text("UPDATE balance_record SET balance_on = :d WHERE account_id = :a"), {"d": to, "a": account}
        )
    )


def test_a_later_start_keeps_an_existing_transfer_booking(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene)
    scene.settle()
    before = booking_of(scene, e)
    assert before is not None
    move_start(scene, account, D + timedelta(days=30))
    assert scene.settle().error is None
    after = booking_of(scene, e)
    assert after is not None and after.id == before.id
    assert scene.row(e).counterpart_entry_id is not None
    scene.assert_checks_clean()


def test_an_earlier_start_books_the_charges_it_now_covers(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, on=date(2026, 1, 20))
    scene.settle()
    assert booking_of(scene, e) is None
    move_start(scene, account, date(2026, 1, 10))
    assert scene.settle().error is None
    assert booking_of(scene, e) is not None
    scene.assert_checks_clean()


def test_a_charge_not_yet_booked_and_dated_before_the_start_books_nothing(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, on=date(2026, 1, 20))
    assert scene.settle().error is None
    assert booking_of(scene, e) is None


def test_a_booked_charge_whose_date_moves_before_the_start_keeps_its_booking(scene: Scene) -> None:
    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene, authored=True)  # a user-authored charge: its date is the user's to edit
    scene.settle()
    before = booking_of(scene, e)
    assert before is not None
    early = date(2026, 1, 20)
    source_id = scene.q("SELECT source_transaction_id AS s FROM ledger_entry WHERE id = :e", e=e)[0].s
    probe = update_source(scene.engine, source_id, booked_on=early, dry_run=True)
    edited = update_source(
        scene.engine, source_id, booked_on=early, expected_versions=dict(probe.effects.versions)
    )
    assert edited.settle is not None and edited.settle.error is None
    after = booking_of(scene, e)
    assert after is not None and after.id == before.id and after.booked_on == early
    scene.assert_checks_clean()
