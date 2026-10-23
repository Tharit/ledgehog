"""The document part of `POST /api/units/preview` and `/commit` (architecture §4.1, spec §5.8, §6):
the draft field and its 422s, the preview's document block and split rows, the commit's refusals and
conflicts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.importers.providers import reset_document_providers
from app.core.units.doc_draft import proposed_split_id
from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.core.units.conftest import build_scene
from tests.core.units.doc_helpers import Docs
from tests.core.units.scene import Scene

PREVIEW = "/api/units/preview"
COMMIT = "/api/units/commit"


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    reset_document_providers()
    yield
    reset_document_providers()


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def scene(api_engine: Engine, make_account: Callable[..., int]) -> Scene:
    return build_scene(api_engine, make_account)


@pytest.fixture
def docs(scene: Scene) -> Docs:
    return Docs(scene)


def body(scene: Scene, anchor: int, *entries: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "anchor_entry_id": anchor,
        "entries": list(entries),
        "versions": {str(k): v for k, v in scene.versions(anchor).items()},
        **extra,
    }


def pick(entry: int, doc: int, version: int = 1, **kw: Any) -> dict[str, Any]:
    return {"id": entry, "document": {"mode": "pick", "document_id": doc, "document_version": version}, **kw}


def two_documents(docs: Docs) -> tuple[int, int, int]:
    entry = docs.charge()
    return entry, docs.document(total=-1000, external_id="a"), docs.document(total=-1000, external_id="b")


# ---- the draft field --------------------


def test_the_document_draft_is_validated(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry, a, _b = two_documents(docs)
    invalid = [
        ({"mode": "pick"}, "invalid_document"),
        ({"mode": "pick", "document_id": a}, "invalid_document"),
        ({"mode": "none", "document_id": a}, "invalid_document"),
        ({"mode": "reresolve", "document_version": 1}, "invalid_document"),
    ]
    for document, code in invalid:
        for url in (PREVIEW, COMMIT):
            r = anna.post(url, json=body(scene, entry, {"id": entry, "document": document}))
            assert_envelope(r, 422, "invalid_draft")
            assert r.json()["error"]["details"]["code"] == code
    new = {"id": -1, "amount": -100, "source_entry_id": entry, "document": {"mode": "none"}}
    r = anna.post(PREVIEW, json=body(scene, entry, new))
    assert r.json()["error"]["details"]["code"] == "document_not_original"
    line = {"id": entry, "document_line": {"document_id": a, "line_no": 2}}
    r = anna.post(PREVIEW, json=body(scene, entry, line))
    assert r.json()["error"]["details"]["code"] == "invalid_document_line"


def test_a_client_cannot_mark_a_document_pick_as_a_proposal(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    entry, a, _b = two_documents(docs)
    for url in (PREVIEW, COMMIT):
        forged = {
            "id": entry,
            "document": {"mode": "pick", "document_id": a, "document_version": 1, "is_proposal": True},
        }
        assert anna.post(url, json=body(scene, entry, forged)).status_code == 422
    for url in (PREVIEW, COMMIT):  # there is no decline: the field is gone
        declined = {"id": entry, "document": {"mode": "keep", "decline_split": True}}
        assert anna.post(url, json=body(scene, entry, declined)).status_code == 422
    for bad in (
        {"mode": "maybe"},
        {"mode": "pick", "document_id": 0, "document_version": 1},
        {"surprise": 1},
    ):
        r = anna.post(PREVIEW, json=body(scene, entry, {"id": entry, "document": bad}))
        assert_envelope(r, 422, "validation_error")


def test_a_document_on_an_entry_that_is_not_the_original_is_422(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    _src, (first, second) = scene.movement(-600, -400, counterparty="PAYPAL *X")
    doc = docs.document(total=-1000)
    r = anna.post(PREVIEW, json=body(scene, first, pick(second, doc)))
    assert_envelope(r, 422, "invalid_draft")
    assert r.json()["error"]["details"] == {
        "code": "document_not_original",
        "entry_id": second,
        "field": "document",
    }


# ---- the preview --------------------


def test_the_preview_carries_the_suggestions_and_asks_for_a_decision(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    entry, a, b = two_documents(docs)
    r = anna.post(PREVIEW, json=body(scene, entry))
    assert r.status_code == 200, r.text
    out = r.json()
    row = out["rows"][0]
    assert row["document_line"] is None
    doc = row["document"]
    assert set(doc) == {
        "stored_document_id", "document", "key", "suggestions", "waiting", "decision_required", "split",
    }  # fmt: skip
    assert doc["stored_document_id"] is None and doc["document"] is None and doc["key"] is None
    assert doc["decision_required"] is True and doc["waiting"] is None and doc["split"] is None
    assert sorted(s["id"] for s in doc["suggestions"]) == [a, b]
    first = doc["suggestions"][0]
    assert set(first) == {
        "id", "version", "provider", "external_id", "occurred_on", "total", "merchant_name", "title",
        "line_count",
    }  # fmt: skip
    assert first["total"] == {"amount": -1000, "currency": "EUR"} and first["provider"] == "paypal"
    assert first["version"] == 1 and first["line_count"] == 0
    assert [p["code"] for p in out["problems"]] == ["document_decision_required"]
    assert out["problems"][0]["entry_id"] == entry and out["problems"][0]["field"] == "document"
    assert "document_suggested" in out["state"]["reasons"]


def test_the_preview_carries_the_waiting_line(anna: TestClient, scene: Scene) -> None:
    waiting = Docs(scene, covered=False)
    entry = waiting.charge()
    doc = anna.post(PREVIEW, json=body(scene, entry)).json()["rows"][0]["document"]
    assert doc["waiting"] == {"provider": "paypal", "covered_through": None}
    assert doc["decision_required"] is True and doc["suggestions"] == []


def test_the_preview_carries_the_rest_of_an_order_line(anna: TestClient, scene: Scene, docs: Docs) -> None:
    scene.sync(scene.checking)  # fetched through 2026-03-01: not yet through the order's date plus back
    order = docs.document(total=-5000, external_id="302-1")
    docs.lines(order, ("a", -3000), ("b", -2000))
    entry = docs.charge(-3000)
    scene.settle()
    doc = anna.post(PREVIEW, json=body(scene, entry)).json()["rows"][0]["document"]
    assert doc["waiting"] == {
        "order": "302-1",
        "provider": "paypal",
        "charged": {"amount": -3000, "currency": "EUR"},
        "total": {"amount": -5000, "currency": "EUR"},
    }
    assert doc["decision_required"] is False  # the wait adds no refusal


def test_the_queue_carries_the_rest_of_an_order(anna: TestClient, scene: Scene, docs: Docs) -> None:
    scene.sync(scene.checking)
    order = docs.document(total=-5000, external_id="302-1")
    docs.lines(order, ("a", -3000), ("b", -2000))
    entry = docs.charge(-3000)
    scene.settle()
    sections = {s["kind"]: s for s in anna.get("/api/units/queue").json()["sections"]}
    (unit,) = sections["waiting"]["units"]
    assert unit["anchor_entry_id"] == entry
    assert unit["waiting_order"] == {
        "order": "302-1",
        "provider": "paypal",
        "charged": {"amount": -3000, "currency": "EUR"},
        "total": {"amount": -5000, "currency": "EUR"},
    }
    assert unit["waiting"] is None and unit["waiting_document"] is None


def test_a_pick_previews_as_the_link_with_its_key(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry, a, _b = two_documents(docs)
    r = anna.post(PREVIEW, json=body(scene, entry, pick(entry, a)))
    assert r.status_code == 200, r.text
    out = r.json()
    doc = out["rows"][0]["document"]
    assert doc["document"]["id"] == a and doc["key"] == {"pass": "user", "basis": {}}
    assert doc["suggestions"] == [] and doc["decision_required"] is False
    assert out["problems"] == []


def test_the_problems_of_a_pick_are_codes(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry, a, _b = two_documents(docs)
    out = anna.post(PREVIEW, json=body(scene, entry, pick(entry, 987654))).json()
    assert [(p["code"], p["field"], p["detail"]) for p in out["problems"]] == [
        ("stale_reference", "document_id", {"id": 987654})
    ]
    out = anna.post(PREVIEW, json=body(scene, entry, pick(entry, a, version=9))).json()
    assert [(p["code"], p["detail"]) for p in out["problems"]] == [
        ("document_changed", {"document_id": a, "version": 1, "expected": 9})
    ]


def test_a_pick_on_a_transfer_is_a_problem_code(anna: TestClient, scene: Scene, docs: Docs) -> None:
    (_a, (x,)), _b = scene.transfer_pair()
    doc = docs.document(total=-1000)
    out = anna.post(PREVIEW, json=body(scene, x, pick(x, doc))).json()
    assert [(p["code"], p["entry_id"], p["field"]) for p in out["problems"]] == [
        ("document_not_for_transfer", x, "document")
    ]
    assert_envelope(anna.post(COMMIT, json=body(scene, x, pick(x, doc))), 422, "document_not_for_transfer")


def test_a_pick_brings_the_carriers_in_and_a_transfer_beside_a_document_is_422(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    doc = docs.document(total=-1000, external_id="a")
    carrier = docs.charge(document_id=doc)
    entry = docs.charge()
    both = {**scene.versions(entry), **scene.versions(carrier)}
    request = body(scene, entry, pick(entry, doc), versions={str(k): v for k, v in both.items()})
    out = anna.post(PREVIEW, json=request).json()
    assert out["problems"] == []
    assert {r["id"]: r["in_unit"] for r in out["rows"]} == {carrier: True, entry: True}
    _src, (first, second) = scene.movement(-600, -400, lead={"type": "flow", "document_id": doc})
    to_savings = {
        "id": second,
        "type": {"mode": "fixed", "value": "transfer"},
        "counter_account": {"mode": "fixed", "value": scene.savings},
    }
    out = anna.post(PREVIEW, json=body(scene, first, to_savings)).json()
    assert [(p["code"], p["entry_id"]) for p in out["problems"]] == [("document_with_transfer", second)]
    assert_envelope(anna.post(COMMIT, json=body(scene, first, to_savings)), 422, "document_with_transfer")


def test_the_split_along_the_lines_is_proposed_with_server_issued_ids(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    entry = docs.charge()
    doc = docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -400), ("Case", -300), ("Shipping", -300))
    scene.settle()
    out = anna.post(PREVIEW, json=body(scene, entry)).json()
    ids = [r["id"] for r in out["rows"]]
    assert ids == [entry, proposed_split_id(entry, 2), proposed_split_id(entry, 3)]
    assert [r["document_line"] for r in out["rows"]] == [
        {"document_id": doc, "line_no": n, "description": d}
        for n, d in ((1, "USB cable"), (2, "Case"), (3, "Shipping"))
    ]
    assert [r["amount"]["amount"] for r in out["rows"]] == [-400, -300, -300]
    assert out["rows"][0]["document"]["split"] == {
        "document_id": doc, "proposed": True, "available": True, "replaces_stored_split": False,
    }  # fmt: skip
    assert all(ident >= -(2**53) for ident in ids)  # a client may echo them back


# ---- the commit --------------------


def test_a_commit_without_a_decision_is_refused_with_its_code(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    entry, a, _b = two_documents(docs)
    r = anna.post(COMMIT, json=body(scene, entry))
    assert_envelope(r, 422, "document_decision_required")
    assert r.json()["error"]["details"]["problems"][0]["entry_id"] == entry
    r = anna.post(COMMIT, json=body(scene, entry, {"id": entry, "document": {"mode": "none"}}))
    assert r.status_code == 200, r.text
    assert scene.row(entry).derivation["document"] == {"pass": "user"}


def test_a_pick_commits_and_the_row_carries_the_document(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry, a, _b = two_documents(docs)
    r = anna.post(COMMIT, json=body(scene, entry, pick(entry, a)))
    assert r.status_code == 200, r.text
    row = next(e for e in r.json()["entries"] if e["id"] == entry)
    assert row["document_id"] == a and row["derivation"]["document"] == {"pass": "user"}


def test_a_proposed_split_commits_and_maps_its_ids(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    doc = docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -400), ("Case", -300), ("Shipping", -300))
    scene.settle()
    food = scene.category("Food")
    draft = body(
        scene,
        entry,
        {"id": entry, "category": {"mode": "fixed", "value": food}},
        *[
            {
                "id": proposed_split_id(entry, n),
                "amount": -300,
                "source_entry_id": entry,
                "document_line": {"document_id": doc, "line_no": n},
                "category": {"mode": "fixed", "value": food},
            }
            for n in (2, 3)
        ],
    )
    r = anna.post(COMMIT, json=draft)
    assert r.status_code == 200, r.text
    out = r.json()
    assert sorted(out["created"]) == sorted(str(proposed_split_id(entry, n)) for n in (2, 3))
    assert {e["amount"]["amount"] for e in out["entries"]} == {-400, -300}


def test_a_document_taken_or_moved_is_409_unit_moved_and_a_missing_one_stale(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    first, a, _b = two_documents(docs)
    second = docs.charge()
    docs.document(total=-1000, external_id="c")
    mine = body(scene, second, pick(second, a))
    assert anna.post(COMMIT, json=body(scene, first, pick(first, a))).status_code == 200
    r = anna.post(COMMIT, json=mine)
    assert_envelope(r, 409, "unit_moved")
    assert r.json()["error"]["details"] == {"anchor_entry_id": second, "document_id": a, "reason": "taken"}
    r = anna.post(
        COMMIT, json=body(scene, second, pick(second, docs.document(total=-5, external_id="d"), version=3))
    )
    assert_envelope(r, 409, "unit_moved")
    assert r.json()["error"]["details"]["reason"] == "version"
    r = anna.post(COMMIT, json=body(scene, second, pick(second, 987654)))
    assert_envelope(r, 409, "stale_reference")
