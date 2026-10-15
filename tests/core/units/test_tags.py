"""Tags are part of the draft: a change relative to the stored tags, applied as membership writes."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.stale import StaleReference
from app.core.units.draft import DraftEntry, DraftError
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import Scene


def stable(scene: Scene, e: int) -> None:
    """Commit once with no change, so the entry is in the state a later commit leaves it in."""
    scene.settle()
    scene.commit(e)


def test_add_and_remove_on_an_existing_entry_preview_commit_and_repeat(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    t1, t2, t3 = scene.tag("a"), scene.tag("b"), scene.tag("c")
    scene.tag_entry(e, t1, t2)
    stable(scene, e)
    change = DraftEntry(e, tags_add=(t3,), tags_remove=(t1,))
    plan, result = preview_then_commit(scene, scene.draft(e, change))
    assert plan.row(e).tag_ids == (t2, t3) and scene.tags_of(e) == (t2, t3)
    (row,) = [r for r in result.entries if r.id == e]
    assert row.tag_ids == (t2, t3)
    again = scene.commit(e, change)  # the same change again: a no-op
    assert scene.tags_of(e) == (t2, t3) and again.entries[0].tag_ids == (t2, t3)


def test_a_tag_only_commit_is_valid_and_bumps_no_version(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    t = scene.tag("a")
    stable(scene, e)
    v = scene.row(e).version
    scene.commit(e, DraftEntry(e, tags_add=(t,)))
    assert scene.row(e).version == v and scene.tags_of(e) == (t,)
    scene.commit(e, DraftEntry(e, tags_remove=(t,)))
    assert scene.row(e).version == v and scene.tags_of(e) == ()
    scene.commit(e)  # no change at all: nothing bumps
    assert scene.row(e).version == v


def test_an_external_tagging_between_load_and_commit_composes(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    ext, mine = scene.tag("ext"), scene.tag("mine")
    stable(scene, e)
    draft = scene.draft(e, DraftEntry(e, tags_add=(mine,)))
    scene.tag_entry(e, ext)  # tagged elsewhere after the client read the unit
    scene.commit_draft(draft)
    assert scene.tags_of(e) == tuple(sorted((ext, mine)))


def test_a_split_row_inherits_then_changes(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    t1, t2, t3 = scene.tag("a"), scene.tag("b"), scene.tag("c")
    scene.tag_entry(e, t1, t2)
    scene.settle()
    draft = scene.draft(
        e,
        DraftEntry(-1, amount=-300, source_entry_id=e, tags_add=(t3,), tags_remove=(t1,)),
        DraftEntry(-2, amount=-100, source_entry_id=e),
    )
    plan, result = preview_then_commit(scene, draft)
    assert plan.row(-1).tag_ids == (t2, t3) and plan.row(-2).tag_ids == (t1, t2)
    assert scene.tags_of(result.created[-1]) == (t2, t3)
    assert scene.tags_of(result.created[-2]) == (t1, t2)
    assert scene.tags_of(e) == (t1, t2)


def test_removing_a_split_drops_its_tags(scene: Scene) -> None:
    _s, (a, b) = scene.movement(-600, -400)
    t = scene.tag("a")
    scene.tag_entry(b, t)
    scene.settle()
    scene.commit(a, removed_entry_ids=[b])
    assert scene.tags_of(b) == ()
    assert scene.q("SELECT count(*) AS n FROM ledger_entry_tag")[0].n == 0


def test_a_tag_in_both_lists_is_an_invalid_draft() -> None:
    with pytest.raises(DraftError) as exc:
        DraftEntry(1, tags_add=(3,), tags_remove=(3,))
    assert exc.value.code == "tag_conflict"


def test_a_tag_on_an_entry_outside_the_unit_is_unknown_entry(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    _s2, (other,) = scene.movement(-500)
    t = scene.tag("a")
    with pytest.raises(DraftError) as exc:
        scene.preview(e, DraftEntry(other, tags_add=(t,)))
    assert exc.value.code == "unknown_entry"


def test_an_unknown_tag_is_stale_in_preview_and_commit(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    scene.settle()
    for call in (scene.preview, scene.commit):
        with pytest.raises(StaleReference) as exc:
            call(e, DraftEntry(e, tags_add=(99_999,)))
        assert (exc.value.field, exc.value.entity, exc.value.entity_id) == (
            "entries[0].tags.add",
            "tag",
            99_999,
        )


def test_a_tag_deleted_between_preview_and_commit_is_stale(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    t = scene.tag("a")
    scene.settle()
    draft = scene.draft(e, DraftEntry(e, tags_add=(t,)))
    scene.preview(e, DraftEntry(e, tags_add=(t,)))
    scene.tx(lambda c: c.execute(text("DELETE FROM tag WHERE id = :t"), {"t": t}))
    with pytest.raises(StaleReference) as exc:
        scene.commit_draft(draft)
    assert exc.value.entity == "tag" and exc.value.entity_id == t


def test_settle_is_untouched_by_tags(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    t = scene.tag("a")
    scene.settle()
    scene.commit(e, DraftEntry(e, tags_add=(t,)))
    assert scene.settle().touched_entry_ids == ()
