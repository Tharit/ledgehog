"""Booking entries whose category falls to the model are listed in the settle that books them (§5.9)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from app.core.accounts import set_clearance_providers
from app.core.model.queue import ModelQueue, configure_model_queue
from app.core.settle import settle
from tests.core.bookings.scene import Scene, doc, line
from tests.core.model.rig import make_rig


@pytest.fixture
def scene(isolated_engine: Engine) -> Scene:
    return Scene(isolated_engine)


@pytest.fixture
def queue(isolated_engine: Engine) -> Iterator[ModelQueue]:
    rig = make_rig(isolated_engine)
    try:
        yield rig.queue
    finally:
        configure_model_queue(None)


def _ids(scene: Scene, external_id: str = "A1") -> set[int]:
    return {int(e.id) for e in scene.entries(external_id)}


def test_a_booking_ingest_lists_its_entries(scene: Scene, queue: ModelQueue) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("Cable", -1000), line("Book", -500)))
    assert len(_ids(scene)) == 2
    assert queue.entry_ids() == _ids(scene)
    assert queue.pending() == 2


def test_writing_the_providers_lists_the_entries_it_books(scene: Scene, queue: ModelQueue) -> None:
    account = scene.clearance(providers=())
    scene.deliver(doc("A1", line("Cable", -1000)))
    assert scene.booking() is None
    assert queue.entry_ids() == frozenset()
    set_clearance_providers(scene.engine, account, ["Amazon"])
    assert len(_ids(scene)) == 1
    assert queue.entry_ids() == _ids(scene)


def test_a_changed_source_text_is_listed_again(scene: Scene, queue: ModelQueue) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("Cable", -1000)))
    (entry,) = _ids(scene)
    queue.sync([])  # the model answered, the list is empty
    scene.deliver(doc("A1", line("Cable USB-C", -1000)), redelivery="replace")
    assert queue.entry_ids() == {entry}


def test_an_entry_decided_by_a_rule_is_not_listed(scene: Scene, queue: ModelQueue) -> None:
    scene.clearance()
    cables = scene.category("Cables")
    scene.exec(
        "INSERT INTO rule (sets, category_id, conditions, name) VALUES ('category', :t,"
        " CAST(:c AS jsonb), 'usb')",
        t=cables,
        c=json.dumps([{"field": "source_text", "op": "contains", "value": "cable"}]),
    )
    scene.deliver(doc("A1", line("Cable", -1000), line("Book", -500)))
    book = next(e for e in scene.entries() if e.source_text == "Book")
    assert queue.entry_ids() == {int(book.id)}


def test_settle_alone_keeps_the_list(scene: Scene, queue: ModelQueue) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("Cable", -1000)))
    assert settle(scene.engine).error is None
    assert queue.entry_ids() == _ids(scene)
