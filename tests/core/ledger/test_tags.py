"""Tag CRUD and tagging one entry (spec §3.7; architecture §4.1). Real commits: `isolated_engine`."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.ledger import tags as tags_mod
from app.core.ledger.tags import (
    DerivedEntryRefused,
    DuplicateTagName,
    EntryMissing,
    InvalidTagValue,
    TagMissing,
    create_tag,
    delete_tag,
    list_tags,
    tag_entry,
    untag_entry,
    update_tag,
)
from app.core.settle.settle import SettleResult
from tests.fixtures import ledger_seed as seed


@pytest.fixture
def acct(isolated_engine: Engine) -> int:
    with isolated_engine.begin() as conn:
        return seed.account(conn)


def add(engine: Engine, account_id: int, **kw: Any) -> int:
    with engine.begin() as conn:
        return seed.entry(conn, account_id, **kw)


def rows(engine: Engine, sql: str, **p: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), p).all())


def listed(engine: Engine):
    with engine.connect() as conn:
        return list_tags(conn)


# ---- CRUD ------------------------------------------------------------------------------------


def test_create_trims_the_name_and_stores_the_colour_as_given(isolated_engine: Engine):
    made = create_tag(isolated_engine, name="  Trip  ", color="teal")
    assert (made.tag.name, made.tag.color) == ("Trip", "teal")
    assert made.settle == SettleResult()
    assert made.tag.entry_count == 0 and made.tag.starts_on is None and made.tag.ends_on is None


def test_colour_defaults_to_none(isolated_engine: Engine):
    assert create_tag(isolated_engine, name="x").tag.color is None


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_blank_name_is_refused(isolated_engine: Engine, name: str):
    with pytest.raises(InvalidTagValue) as e:
        create_tag(isolated_engine, name=name)
    assert e.value.parameter == "name"
    assert listed(isolated_engine) == []


def test_blank_colour_is_refused(isolated_engine: Engine):
    with pytest.raises(InvalidTagValue) as e:
        create_tag(isolated_engine, name="x", color="  ")
    assert e.value.parameter == "color"


def test_duplicate_names_are_refused_case_insensitively(isolated_engine: Engine):
    create_tag(isolated_engine, name="Trip")
    with pytest.raises(DuplicateTagName):
        create_tag(isolated_engine, name=" tRIP ")
    assert [t.name for t in listed(isolated_engine)] == ["Trip"]


def test_update_name_and_colour_and_the_sentinel_keeps(isolated_engine: Engine):
    t = create_tag(isolated_engine, name="Trip", color="teal").tag
    assert update_tag(isolated_engine, t.id).tag.name == "Trip"  # nothing given: unchanged
    r = update_tag(isolated_engine, t.id, name=" Holiday ")
    assert (r.tag.name, r.tag.color) == ("Holiday", "teal")
    assert update_tag(isolated_engine, t.id, color="red").tag.color == "red"
    assert update_tag(isolated_engine, t.id, color=None).tag.color is None
    assert update_tag(isolated_engine, t.id, name="holiday").tag.name == "holiday"  # own name, other case


def test_update_to_another_tags_name_is_refused(isolated_engine: Engine):
    create_tag(isolated_engine, name="A")
    b = create_tag(isolated_engine, name="B").tag
    with pytest.raises(DuplicateTagName):
        update_tag(isolated_engine, b.id, name="a")
    with pytest.raises(InvalidTagValue):
        update_tag(isolated_engine, b.id, name=" ")
    assert [t.name for t in listed(isolated_engine)] == ["A", "B"]


def test_update_and_delete_unknown_tag(isolated_engine: Engine):
    with pytest.raises(TagMissing):
        update_tag(isolated_engine, 999, name="x")
    with pytest.raises(TagMissing):
        delete_tag(isolated_engine, 999)


def test_delete_reports_removed_memberships_and_keeps_entries(isolated_engine: Engine, acct: int):
    t = create_tag(isolated_engine, name="Trip").tag
    keep = create_tag(isolated_engine, name="Keep").tag
    e1, e2 = add(isolated_engine, acct), add(isolated_engine, acct)
    for e in (e1, e2):
        tag_entry(isolated_engine, e, t.id)
    tag_entry(isolated_engine, e1, keep.id)
    gone = delete_tag(isolated_engine, t.id)
    assert gone.removed_memberships == 2
    assert [x.id for x in listed(isolated_engine)] == [keep.id]
    assert len(rows(isolated_engine, "SELECT 1 FROM ledger_entry")) == 2
    assert rows(isolated_engine, "SELECT tag_id FROM ledger_entry_tag") == [(keep.id,)]


def test_delete_an_unused_tag_removes_zero(isolated_engine: Engine):
    t = create_tag(isolated_engine, name="x").tag
    assert delete_tag(isolated_engine, t.id).removed_memberships == 0


# ---- list ------------------------------------------------------------------------------------


def test_list_shows_unused_tags_and_spans_follow_min_max_booked_on(isolated_engine: Engine, acct: int):
    t = create_tag(isolated_engine, name="Trip", color="blue").tag
    unused = listed(isolated_engine)[0]
    assert (unused.starts_on, unused.ends_on, unused.entry_count) == (None, None, 0)
    early = add(isolated_engine, acct, on=date(2026, 1, 5))
    late = add(isolated_engine, acct, on=date(2026, 2, 9))
    mid = add(isolated_engine, acct, on=date(2026, 1, 20))
    for e in (early, late, mid):
        tag_entry(isolated_engine, e, t.id)
    (row,) = listed(isolated_engine)
    assert (row.id, row.name, row.color) == (t.id, "Trip", "blue")
    assert (row.starts_on, row.ends_on, row.entry_count) == (date(2026, 1, 5), date(2026, 2, 9), 3)
    untag_entry(isolated_engine, early, t.id)
    untag_entry(isolated_engine, late, t.id)
    (row,) = listed(isolated_engine)
    assert (row.starts_on, row.ends_on, row.entry_count) == (date(2026, 1, 20), date(2026, 1, 20), 1)
    untag_entry(isolated_engine, mid, t.id)
    (row,) = listed(isolated_engine)
    assert (row.starts_on, row.ends_on, row.entry_count) == (None, None, 0)


def test_list_is_ordered_by_name(isolated_engine: Engine):
    for n in ("b", "A", "c"):
        create_tag(isolated_engine, name=n)
    assert [t.name for t in listed(isolated_engine)] == ["A", "b", "c"]


# ---- tag / untag one entry --------------------------------------------------------------------


def test_tag_is_idempotent_and_returns_sorted_tag_ids(isolated_engine: Engine, acct: int):
    a, b = (create_tag(isolated_engine, name=n).tag.id for n in ("a", "b"))
    e = add(isolated_engine, acct)
    first = tag_entry(isolated_engine, e, b)
    assert (first.changed, first.entry_id, first.tag_ids) == (True, e, (b,))
    second = tag_entry(isolated_engine, e, b)
    assert (second.changed, second.tag_ids) == (False, (b,))
    assert tag_entry(isolated_engine, e, a).tag_ids == (a, b)


def test_untag_is_idempotent(isolated_engine: Engine, acct: int):
    t = create_tag(isolated_engine, name="a").tag.id
    e = add(isolated_engine, acct, tags=())
    assert untag_entry(isolated_engine, e, t).changed is False
    tag_entry(isolated_engine, e, t)
    first = untag_entry(isolated_engine, e, t)
    assert (first.changed, first.tag_ids) == (True, ())
    assert untag_entry(isolated_engine, e, t).changed is False


def test_a_derived_entry_is_refused(isolated_engine: Engine, acct: int):
    t = create_tag(isolated_engine, name="a").tag.id
    with isolated_engine.begin() as conn:
        d = seed.derived(conn, acct)
    with pytest.raises(DerivedEntryRefused) as e:
        tag_entry(isolated_engine, d, t)
    assert e.value.entry_id == d
    with pytest.raises(DerivedEntryRefused):
        untag_entry(isolated_engine, d, t)
    assert rows(isolated_engine, "SELECT 1 FROM ledger_entry_tag") == []


def test_unknown_entry_and_unknown_tag(isolated_engine: Engine, acct: int):
    t = create_tag(isolated_engine, name="a").tag.id
    e = add(isolated_engine, acct)
    with pytest.raises(EntryMissing):
        tag_entry(isolated_engine, 999, t)
    with pytest.raises(TagMissing):
        tag_entry(isolated_engine, e, 999)
    with pytest.raises(EntryMissing):
        untag_entry(isolated_engine, 999, t)
    with pytest.raises(TagMissing):
        untag_entry(isolated_engine, e, 999)


def test_tagging_bumps_no_version_and_works_for_reviewed_and_unreviewed(isolated_engine: Engine, acct: int):
    t = create_tag(isolated_engine, name="a").tag.id
    unreviewed = add(isolated_engine, acct, flags=("unconfirmed",))
    reviewed = add(isolated_engine, acct)
    before = rows(isolated_engine, "SELECT id, version FROM ledger_entry ORDER BY id")
    for e in (unreviewed, reviewed):
        assert tag_entry(isolated_engine, e, t).changed
    untag_entry(isolated_engine, reviewed, t)
    assert rows(isolated_engine, "SELECT id, version FROM ledger_entry ORDER BY id") == before


def test_each_write_settles_once_after_commit_and_returns_the_result(
    isolated_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch
):
    seen: list[int] = []

    def fake(engine: Engine) -> SettleResult:
        seen.append(len(rows(engine, "SELECT 1 FROM tag")))  # sees the committed write
        return SettleResult((7,), "boom")

    monkeypatch.setattr(tags_mod, "settle", fake)
    made = create_tag(isolated_engine, name="a")
    assert made.settle == SettleResult((7,), "boom") and seen == [1]
    e = add(isolated_engine, acct)
    assert tag_entry(isolated_engine, e, made.tag.id).settle.error == "boom"
    assert untag_entry(isolated_engine, e, made.tag.id).settle.error == "boom"
    assert update_tag(isolated_engine, made.tag.id, color="x").settle.error == "boom"
    assert delete_tag(isolated_engine, made.tag.id).settle.error == "boom"
    assert len(seen) == 5
