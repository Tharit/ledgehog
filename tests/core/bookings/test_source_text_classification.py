"""A booking entry's source text and account are inputs of resolution (spec §5.9, D230): rules read them,
history learns by source text, the model's payload carries them, and booking entries never vote."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import Engine

from app.core.resolution import snapshot
from app.core.resolution.load import load_movements
from app.core.resolution.snapshot import load_votes
from app.plugins.classifiers.llm.payload import payload_of
from tests.core.bookings.scene import Scene, doc, line


@pytest.fixture
def scene(isolated_engine: Engine) -> Scene:
    return Scene(isolated_engine)


def _rule(scene: Scene, sets: str, target: int, conditions: list[dict[str, str]], name: str) -> None:
    column = {"category": "category_id", "payee": "payee_id", "counter_account": "counter_account_id"}[sets]
    scene.exec(
        f"INSERT INTO rule (sets, {column}, conditions, name) VALUES (:s, :t, CAST(:c AS jsonb), :n)",  # noqa: S608
        s=sets,
        t=target,
        c=json.dumps(conditions),
        n=name,
    )


def _by_text(scene: Scene, external_id: str = "A1") -> dict[str | None, object]:
    return {e.source_text: e for e in scene.entries(external_id)}


def test_a_source_text_rule_decides_one_line_of_a_booking(scene: Scene) -> None:
    scene.clearance()
    cables = scene.category("Cables")
    _rule(scene, "category", cables, [{"field": "source_text", "op": "contains", "value": "usb-c"}], "usb")
    scene.deliver(doc("A1", line("USB-C cable", -1000), line("Paperback", -500)))
    got = _by_text(scene)
    assert got["USB-C cable"].category_id == cables  # type: ignore[attr-defined]
    assert got["USB-C cable"].derivation["category"] == {"pass": "rule", "basis": {"rule_id": 1}}  # type: ignore[attr-defined]
    assert got["Paperback"].category_id is None  # type: ignore[attr-defined]


def test_an_account_rule_decides_the_entries_of_that_account_only(scene: Scene) -> None:
    amazon = scene.clearance()
    scene.clearance("Other", providers=("Other",))
    books = scene.category("Books")
    _rule(scene, "category", books, [{"field": "account", "op": "is", "value": str(amazon)}], "acct")
    scene.deliver(doc("A1", line("Paperback", -500)), doc("B1", line("Paperback", -500), provider="Other"))
    assert [e.category_id for e in scene.entries("A1")] == [books]
    assert [e.category_id for e in scene.entries("B1")] == [None]


def test_an_account_rule_for_a_deleted_account_never_matches(scene: Scene) -> None:
    scene.clearance()
    books = scene.category("Books")
    _rule(scene, "category", books, [{"field": "account", "op": "is", "value": "987654"}], "gone")
    scene.deliver(doc("A1", line("Paperback", -500)))
    assert [e.category_id for e in scene.entries()] == [None]


def test_resolution_reads_the_source_text_and_the_accounts_name(scene: Scene) -> None:
    scene.clearance("Amazon.de")
    scene.deliver(doc("A1", line("USB-C cable", -1000), line("Paperback", -500)))
    with scene.engine.connect() as conn:
        inputs = [r.input for r in load_movements(conn)]
    assert sorted(i.source_text or "" for i in inputs) == ["Paperback", "USB-C cable"]
    assert {i.account_name for i in inputs} == {"Amazon.de"}
    payload = payload_of(next(i for i in inputs if i.source_text == "Paperback"))
    assert payload is not None
    assert payload["source text"] == "Paperback" and payload["account"] == "Amazon.de"
    assert payload["counterparty"] == "Amazon" and payload["purpose"] == "Order A1"


def test_booking_entries_never_vote(scene: Scene) -> None:
    scene.clearance()
    books = scene.category("Books")
    _rule(scene, "category", books, [{"field": "counterparty_name", "op": "equals", "value": "Amazon"}], "a")
    scene.deliver(doc("A1", line("Paperback", -500)))
    assert scene.entries()[0].review_flags == []  # confirmed, as a rule decided it
    with scene.engine.connect() as conn:
        assert load_votes(conn) == []


def test_history_learns_by_source_text_where_bookings_may_vote(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot, "BOOKING_ENTRIES_VOTE", True)
    scene.clearance()
    cables = scene.category("Cables")
    _rule(scene, "category", cables, [{"field": "source_text", "op": "equals", "value": "USB-C cable"}], "u")
    scene.deliver(doc("A1", line("USB-C cable", -1000)))
    with scene.engine.connect() as conn:
        votes = load_votes(conn)
    assert [v.source_text for v in votes] == ["USB-C cable"]
    scene.exec("DELETE FROM rule")
    scene.deliver(doc("A2", line("usb-c  Cable", -900), line("Paperback", -500)))
    entry = _by_text(scene, "A2")
    cable = entry["usb-c  Cable"]
    assert cable.category_id == cables  # type: ignore[attr-defined]
    key = cable.derivation["category"]  # type: ignore[attr-defined]
    assert key["pass"] == "history" and key["basis"]["matched_on"] == "source_text"
    assert key["basis"]["agree"] == 1 and key["basis"]["of"] == 1
    assert entry["Paperback"].category_id is None  # type: ignore[attr-defined]


def test_the_statement_marks_a_booking_with_its_origin_and_source(scene: Scene) -> None:
    from app.core.balance.statement import SourceItem, get_statement

    account = scene.clearance()
    scene.deliver(doc("A1", line("USB-C cable", -1000)))
    with scene.engine.connect() as conn:
        st = get_statement(conn, account)
    (item,) = [i for i in st.items if isinstance(i, SourceItem)]
    assert item.origin == "booking" and item.booking is not None
    assert (item.booking.kind, item.booking.provider, item.booking.external_id) == (
        "document",
        "Amazon",
        "A1",
    )
