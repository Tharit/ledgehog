"""The document an entry reads, on the entry shape and the preview row (spec §5.8; documents.md §5):
`document` (the transaction's document, whichever entry carries the link) and `document_line` (the entry's
own line)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.importers.providers import reset_document_providers
from app.core.units.doc_draft import proposed_split_id
from tests.api.conftest import login
from tests.core.units.conftest import build_scene
from tests.core.units.doc_helpers import Docs
from tests.core.units.scene import D, Scene

ENTRIES = "/api/ledger/entries"
PREVIEW = "/api/units/preview"
UNIT = "/api/units"
LINES = (("USB cable", -400), ("Case", -300), ("Shipping", -300))


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


def get(client: TestClient, entry: int) -> dict[str, Any]:
    r = client.get(f"{ENTRIES}/{entry}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def linked(scene: Scene, docs: Docs, *lines: tuple[str, int]) -> tuple[int, int]:
    entry = docs.charge(-1000)
    doc = docs.document(total=-1000)
    docs.merchant(doc, "Seeed Studio")
    docs.lines(doc, *lines)
    scene.settle()
    assert scene.row(entry).document_id == doc
    return entry, doc


def test_an_entry_without_a_document_has_neither(anna: TestClient, scene: Scene) -> None:
    _src, (entry,) = scene.movement(-500, counterparty="REWE")
    row = get(anna, entry)
    assert row["document"] is None and row["document_line"] is None and row["document_id"] is None


def test_a_document_of_one_line_gives_the_entry_both(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry, doc = linked(scene, docs, ("USB cable", -1000))
    row = get(anna, entry)
    assert row["document"] == {
        "id": doc,
        "provider": "paypal",
        "merchant_name": "Seeed Studio",
        "line_count": 1,
    }
    assert row["document_line"] == {"line_no": 1, "description": "USB cable"}
    assert row["document_id"] == doc
    listed = anna.get(ENTRIES).json()["entries"]
    assert [(e["document"]["id"], e["document_line"]["line_no"]) for e in listed if e["id"] == entry] == [
        (doc, 1)
    ]


def test_an_unsplit_document_of_several_lines_gives_a_document_and_no_line(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    entry, doc = linked(scene, docs, *LINES)
    row = get(anna, entry)
    assert row["document"]["line_count"] == 3 and row["document"]["id"] == doc
    assert row["document_line"] is None


def test_every_entry_of_a_split_reads_the_one_document_and_its_own_line(
    anna: TestClient, scene: Scene, docs: Docs
) -> None:
    entry, doc = linked(scene, docs, *LINES)
    r = anna.post(
        "/api/units/commit",
        json={
            "anchor_entry_id": entry,
            "entries": [
                {
                    "id": proposed_split_id(entry, n),
                    "amount": -300,
                    "source_entry_id": entry,
                    "document_line": {"document_id": doc, "line_no": n},
                }
                for n in (2, 3)
            ],
            "versions": {str(k): v for k, v in scene.versions(entry).items()},
        },
    )
    assert r.status_code == 200, r.text
    ids = scene.unit_ids(entry)
    assert len(ids) == 3
    rows = {i: get(anna, i) for i in ids}
    assert {i: r["document_id"] for i, r in rows.items()} == {ids[0]: doc, ids[1]: None, ids[2]: None}
    assert all(r["document"]["id"] == doc for r in rows.values())  # the transaction's document, on each
    assert {i: r["document_line"] for i, r in rows.items()} == {
        ids[n]: {"line_no": n + 1, "description": LINES[n][0]} for n in range(3)
    }
    unit = anna.get(f"{UNIT}/{entry}").json()
    assert [e["document_line"]["line_no"] for e in unit["entries"]] == [1, 2, 3]


def test_a_line_of_another_document_is_not_the_entrys(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry, doc = linked(scene, docs, ("USB cable", -1000))
    other = docs.document(total=-4242, external_id="other")
    docs.lines(other, ("Case", -4242))
    stray = scene.q("SELECT id FROM external_document_line WHERE document_id = :d", d=other)[0].id
    scene.tx(
        lambda c: c.exec_driver_sql(f"UPDATE ledger_entry SET document_line_id = {stray} WHERE id = {entry}")
    )
    row = get(anna, entry)
    assert row["document"]["id"] == doc and row["document_line"] is None


def test_the_preview_row_describes_its_line(anna: TestClient, scene: Scene, docs: Docs) -> None:
    entry, doc = linked(scene, docs, *LINES)
    out = anna.post(
        PREVIEW,
        json={
            "anchor_entry_id": entry,
            "entries": [],
            "versions": {str(k): v for k, v in scene.versions(entry).items()},
        },
    ).json()
    assert [r["document_line"] for r in out["rows"]] == [
        {"document_id": doc, "line_no": n, "description": d} for n, (d, _a) in enumerate(LINES, start=1)
    ]
    one, doc_one = linked_one_line(scene, docs)
    out = anna.post(
        PREVIEW,
        json={
            "anchor_entry_id": one,
            "entries": [],
            "versions": {str(k): v for k, v in scene.versions(one).items()},
        },
    ).json()
    assert out["rows"][0]["document_line"] == {
        "document_id": doc_one,
        "line_no": 1,
        "description": "Pro plan",
    }


def linked_one_line(scene: Scene, docs: Docs) -> tuple[int, int]:
    entry = docs.charge(-777, on=D + timedelta(days=1))
    doc = docs.document(total=-777, external_id="one")
    docs.lines(doc, ("Pro plan", -777))
    scene.settle()
    assert scene.row(entry).document_id == doc
    return entry, doc


def test_a_preview_row_without_a_line_says_null(anna: TestClient, scene: Scene) -> None:
    _src, (entry,) = scene.movement(-500, counterparty="REWE")
    out = anna.post(
        PREVIEW,
        json={
            "anchor_entry_id": entry,
            "entries": [],
            "versions": {str(k): v for k, v in scene.versions(entry).items()},
        },
    ).json()
    assert out["rows"][0]["document_line"] is None
