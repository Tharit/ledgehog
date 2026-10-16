"""Committing the document part of a draft (spec §5.8, §6; architecture §4.1, §5.2).

What a commit writes (`document_id` and the `document` key), what it refuses (a pick that is no longer
what the preview saw is a conflict: `UnitMoved`, `StaleReference`), and the locks it takes. Every case that
commits goes through `equality.preview_then_commit`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.domain.errors import VersionConflict
from app.core.importers.providers import reset_document_providers
from app.core.stale import StaleReference
from app.core.units.commit import UnitMoved, commit_unit
from app.core.units.draft import DocumentDraft, DraftEntry
from tests.core.units.doc_helpers import Docs
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, Scene, fixed, no_document


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    reset_document_providers()
    yield
    reset_document_providers()


@pytest.fixture
def docs(scene: Scene) -> Docs:
    return Docs(scene)


def pick(scene: Scene, entry: int, doc: int, **kw: object) -> DraftEntry:
    version = scene.q("SELECT version FROM external_document WHERE id = :i", i=doc)[0].version
    return DraftEntry(entry, document=DocumentDraft("pick", doc, version), **kw)  # type: ignore[arg-type]


def decline(entry: int, **kw: object) -> DraftEntry:
    return DraftEntry(entry, document=DocumentDraft(decline_split=True), **kw)  # type: ignore[arg-type]


# ---- what a commit writes -----------------------------------------------------------------------------


def test_a_proposed_link_of_several_lines_becomes_the_users_once_the_unit_is_committed(
    scene: Scene, docs: Docs
) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    docs.lines(doc, ("USB cable", -400), ("Case", -600))
    scene.settle()
    stored = scene.row(entry)
    assert stored.document_id == doc and stored.derivation["document"]["pass"] == "matcher_proposal"
    assert not scene.preview(entry).anchor_unit.state.confirmed
    cat = scene.category("Gadgets")
    plan, _ = preview_then_commit(scene, scene.draft(entry, decline(entry, category=fixed(cat))))
    assert plan.row(entry).derivation["document"] == {"pass": "user"}
    committed = scene.row(entry)
    assert committed.document_id == doc and committed.derivation["document"] == {"pass": "user"}
    assert committed.review_flags == []  # the unit was reviewed once: it is confirmed


def test_a_link_of_one_line_stays_the_matchers_standing_decision(scene: Scene, docs: Docs) -> None:
    entry, doc = docs.charge(), docs.document(total=-1000)
    scene.settle()
    cat = scene.category("Gadgets")
    plan, _ = preview_then_commit(scene, scene.draft(entry, DraftEntry(entry, category=fixed(cat))))
    assert plan.row(entry).derivation["document"] == {"pass": "matcher_decision", "basis": {}}
    assert scene.row(entry).document_id == doc
    assert scene.row(entry).version == 3  # the link (settling), then the commit; a keep rewrites no link


def test_a_pick_writes_the_link_the_key_and_moves_the_version_once(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    a = docs.document(total=-1000, external_id="a")
    docs.document(total=-1000, external_id="b")
    before = scene.row(entry).version
    preview_then_commit(scene, scene.draft(entry, pick(scene, entry, a)))
    row = scene.row(entry)
    assert (row.document_id, row.derivation["document"], row.version) == (a, {"pass": "user"}, before + 1)


def test_none_writes_the_key_without_a_link(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    docs.document(total=-1000, external_id="a")
    docs.document(total=-1000, external_id="b")
    preview_then_commit(scene, scene.draft(entry, no_document(entry)))
    row = scene.row(entry)
    assert row.document_id is None and row.derivation["document"] == {"pass": "user"}


def test_documents_move_between_the_entries_of_a_unit_in_one_commit(scene: Scene, docs: Docs) -> None:
    (_a, (x,)), (_b, (y,)) = scene.transfer_pair()
    d1, d2 = docs.document(total=-1000, external_id="one"), docs.document(total=-900, external_id="two")
    scene.tx(
        lambda c: [
            c.execute(text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": doc, "e": entry})
            for entry, doc in ((x, d1), (y, d2))
        ]
    )
    plan, _ = preview_then_commit(scene, scene.draft(x, pick(scene, x, d2), pick(scene, y, d1)))
    assert plan.row(x).document_id == d2 and plan.row(y).document_id == d1
    assert (scene.row(x).document_id, scene.row(y).document_id) == (d2, d1)


# ---- what a commit refuses ------------------------------------------------------------------------------


def test_a_document_taken_since_the_preview_is_a_conflict(scene: Scene, docs: Docs) -> None:
    first = docs.charge()
    second = docs.charge(on=D + timedelta(days=1))
    doc = docs.document(total=-1000)
    docs.document(total=-1000, external_id="b")
    docs.document(total=-1000, external_id="c")
    mine = scene.draft(second, pick(scene, second, doc))
    assert not scene.preview(second, pick(scene, second, doc)).problems
    preview_then_commit(scene, scene.draft(first, pick(scene, first, doc)))  # someone else took it
    with pytest.raises(UnitMoved) as raised:
        commit_unit(scene.engine, mine)
    assert (raised.value.document_id, raised.value.reason) == (doc, "taken")
    assert scene.row(second).document_id is None


def test_a_document_at_another_version_than_the_client_saw_is_a_conflict(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    doc = docs.document(total=-1000)
    docs.document(total=-1000, external_id="b")
    draft = scene.draft(entry, pick(scene, entry, doc))
    scene.tx(
        lambda c: c.execute(
            text("UPDATE external_document SET version = version + 1 WHERE id = :d"), {"d": doc}
        )
    )
    with pytest.raises(UnitMoved) as raised:
        commit_unit(scene.engine, draft)
    assert (raised.value.document_id, raised.value.reason) == (doc, "version")
    assert scene.row(entry).version == 1


def test_a_document_that_is_gone_is_a_stale_reference(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    doc = docs.document(total=-1000)
    docs.document(total=-1000, external_id="b")
    draft = scene.draft(entry, pick(scene, entry, doc))
    scene.tx(lambda c: c.execute(text("DELETE FROM external_document WHERE id = :d"), {"d": doc}))
    with pytest.raises(StaleReference) as raised:
        commit_unit(scene.engine, draft)
    assert (raised.value.field, raised.value.entity, raised.value.entity_id) == (
        "document_id",
        "document",
        doc,
    )


def test_a_commit_that_is_refused_for_the_missing_decision_writes_nothing(scene: Scene) -> None:
    from app.core.units.commit import CommitRefused

    waiting = Docs(scene, covered=False)
    entry = waiting.charge()
    cat = scene.category("Gadgets")
    before = scene.fingerprint()
    with pytest.raises(CommitRefused):
        scene.commit(entry, DraftEntry(entry, category=fixed(cat)))
    assert scene.fingerprint() == before


# ---- the locks -------------------------------------------------------------------------------------------


def test_a_commit_locks_the_documents_it_picks(scene: Scene, docs: Docs) -> None:
    entry = docs.charge()
    doc = docs.document(total=-1000)
    docs.document(total=-1000, external_id="b")
    draft = scene.draft(entry, pick(scene, entry, doc))
    finished = threading.Event()
    with scene.engine.begin() as holder:
        holder.execute(text("SELECT id FROM external_document WHERE id = :d FOR UPDATE"), {"d": doc})
        with ThreadPoolExecutor(1) as pool:

            def run() -> None:
                commit_unit(scene.engine, draft)
                finished.set()

            future = pool.submit(run)
            time.sleep(1.0)
            assert not finished.is_set(), "the commit did not wait for the document"
            holder.rollback()
            future.result(timeout=60)
    assert scene.row(entry).document_id == doc


def test_two_commits_racing_for_one_document_leave_it_with_one(scene: Scene, docs: Docs) -> None:
    first = docs.charge()
    second = docs.charge(on=D + timedelta(days=1))
    doc = docs.document(total=-1000)
    docs.document(total=-1000, external_id="b")
    docs.document(total=-1000, external_id="c")
    drafts = [scene.draft(e, pick(scene, e, doc)) for e in (first, second)]
    with scene.engine.begin() as holder:
        holder.execute(text("SELECT id FROM external_document WHERE id = :d FOR UPDATE"), {"d": doc})
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(commit_unit, scene.engine, d) for d in drafts]
            time.sleep(1.0)
            holder.rollback()
            outcomes = []
            for f in futures:
                try:
                    f.result(timeout=60)
                    outcomes.append("committed")
                except UnitMoved as moved:
                    outcomes.append(moved.reason or "moved")
    assert sorted(outcomes) == ["committed", "taken"]
    assert len(scene.q("SELECT 1 FROM ledger_entry WHERE document_id = :d", d=doc)) == 1


def test_a_changed_document_drops_an_unconfirmed_carriers_pick_and_the_panel_sees_it(
    scene: Scene, docs: Docs
) -> None:
    """D8: a document that changes resolves its unconfirmed carrier afresh, the user's pick gone; a draft that
    still names the old version is a consequence the preview lists and a commit refuses as a conflict."""
    from app.core.ingest.documents import reresolve_unconfirmed_carrier

    entry = docs.charge()
    doc = docs.document(total=-1000, external_id="a")
    docs.document(total=-1000, external_id="b")
    preview_then_commit(scene, scene.draft(entry, pick(scene, entry, doc)))
    assert scene.row(entry).document_id == doc
    stale = scene.draft(entry, pick(scene, entry, doc))
    scene.tx(
        lambda c: [
            c.execute(
                text("UPDATE external_document SET total = -999, version = version + 1 WHERE id = :d"),
                {"d": doc},
            ),
            reresolve_unconfirmed_carrier(c, [entry]),
        ]
    )
    assert scene.row(entry).document_id is None and "document" not in scene.row(entry).derivation
    plan = scene.preview(entry, DraftEntry(entry, document=DocumentDraft("pick", doc, 1)))
    assert [p.code for p in plan.problems] == ["document_changed"]
    with pytest.raises(VersionConflict):  # the carrier moved too: its link was dropped
        commit_unit(scene.engine, stale)
    with pytest.raises(
        UnitMoved
    ) as raised:  # a draft that reloaded the unit but kept the old document version
        scene.commit(entry, DraftEntry(entry, document=DocumentDraft("pick", doc, 1)))
    assert (raised.value.document_id, raised.value.reason) == (doc, "version")
