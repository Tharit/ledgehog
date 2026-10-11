"""`apply_tag`: tag everything a ledger filter selects, previewed and all-or-nothing (architecture §4.1)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.ledger import LedgerFilter
from app.core.ledger import tags as tags_mod
from app.core.ledger.tags import (
    EmptyFilter,
    FilterResultChanged,
    Span,
    TagMissing,
    apply_tag,
    create_tag,
    tag_entry,
)
from app.core.settle.settle import SettleResult
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import make_source

MAR = LedgerFilter(date_from=date(2026, 3, 1), date_to=date(2026, 3, 31))


@pytest.fixture
def two_accounts(isolated_engine: Engine) -> tuple[int, int]:
    with isolated_engine.begin() as conn:
        return seed.account(conn, "A"), seed.account(conn, "B")


@pytest.fixture
def tag(isolated_engine: Engine) -> int:
    return create_tag(isolated_engine, name="Trip").tag.id


def add(engine: Engine, account_id: int, **kw: Any) -> int:
    with engine.begin() as conn:
        return seed.entry(conn, account_id, **kw)


def memberships(engine: Engine) -> list[tuple[int, int]]:
    with engine.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text("SELECT ledger_entry_id, tag_id FROM ledger_entry_tag ORDER BY 1, 2")
            ).all()
        ]


def versions(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text("SELECT id, version FROM ledger_entry ORDER BY id")).all())


def go(engine: Engine, tag: int, flt: LedgerFilter = MAR, **kw: Any):
    kw.setdefault("dry_run", False)
    kw.setdefault("expected_count", None)
    kw.setdefault("all_", False)
    return apply_tag(engine, tag, flt, **kw)


def test_real_apply_tags_exactly_the_filters_entries(isolated_engine: Engine, two_accounts, tag):
    a, b = two_accounts
    in1 = add(isolated_engine, a, on=date(2026, 3, 2))
    in2 = add(isolated_engine, b, on=date(2026, 3, 30))
    out_before = add(isolated_engine, a, on=date(2026, 2, 28))
    out_after = add(isolated_engine, b, on=date(2026, 4, 1))
    r = go(isolated_engine, tag)
    assert memberships(isolated_engine) == [(in1, tag), (in2, tag)]
    assert (r.selected, r.newly_tagged, r.already_tagged, r.skipped_derived) == (2, 2, 0, 0)
    assert r.per_account == {a: 1, b: 1}
    assert r.span_before == Span(None, None, 0)
    assert r.span_after == Span(date(2026, 3, 2), date(2026, 3, 30), 2)
    assert r.entries == ((in1, (tag,)), (in2, (tag,)))
    assert r.settle is not None and r.settle.error is None
    assert {out_before, out_after}.isdisjoint(e for e, _ in memberships(isolated_engine))


def test_dry_run_writes_nothing_and_has_the_same_counts(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    add(isolated_engine, a, on=date(2026, 3, 2))
    add(isolated_engine, a, on=date(2026, 3, 9))
    preview = go(isolated_engine, tag, dry_run=True)
    assert memberships(isolated_engine) == []
    assert (preview.selected, preview.newly_tagged) == (2, 2)
    assert preview.span_after == Span(date(2026, 3, 2), date(2026, 3, 9), 2)
    assert preview.span_before == Span(None, None, 0)
    assert preview.entries == () and preview.settle is None
    real = go(isolated_engine, tag)
    assert (real.selected, real.newly_tagged, real.per_account, real.span_after) == (
        preview.selected,
        preview.newly_tagged,
        preview.per_account,
        preview.span_after,
    )


def test_dry_run_does_not_settle(isolated_engine: Engine, two_accounts, tag, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(tags_mod, "settle", lambda e: calls.append(1) or SettleResult())
    add(isolated_engine, two_accounts[0], on=date(2026, 3, 2))
    go(isolated_engine, tag, dry_run=True)
    assert calls == []


def test_derived_entries_are_skipped_and_counted(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    e = add(isolated_engine, a, on=date(2026, 3, 2))
    with isolated_engine.begin() as conn:
        seed.derived(conn, a, type="opening", on=date(2026, 3, 1))
    r = go(isolated_engine, tag)
    assert (r.selected, r.newly_tagged, r.skipped_derived) == (2, 1, 1)
    assert memberships(isolated_engine) == [(e, tag)]


def test_reapplying_is_idempotent(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    add(isolated_engine, a, on=date(2026, 3, 2))
    add(isolated_engine, a, on=date(2026, 3, 3))
    go(isolated_engine, tag)
    again = go(isolated_engine, tag)
    assert (again.selected, again.newly_tagged, again.already_tagged) == (2, 0, 2)
    assert again.per_account == {} and again.entries == ()
    assert again.span_before == again.span_after == Span(date(2026, 3, 2), date(2026, 3, 3), 2)


def test_partly_tagged_counts_only_the_new(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    first = add(isolated_engine, a, on=date(2026, 3, 2))
    second = add(isolated_engine, a, on=date(2026, 3, 3))
    tag_entry(isolated_engine, first, tag)
    r = go(isolated_engine, tag)
    assert (r.selected, r.newly_tagged, r.already_tagged) == (2, 1, 1)
    assert r.entries == ((second, (tag,)),)
    assert r.span_before == Span(date(2026, 3, 2), date(2026, 3, 2), 1)


def test_entries_report_all_their_tags(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    other = create_tag(isolated_engine, name="Other").tag.id
    e = add(isolated_engine, a, on=date(2026, 3, 2))
    tag_entry(isolated_engine, e, other)
    r = go(isolated_engine, tag)
    assert r.entries == ((e, tuple(sorted((tag, other)))),)


def test_split_children_are_each_tagged(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    with isolated_engine.begin() as conn:
        src = make_source(conn, a, amount=-1000, booked_on=date(2026, 3, 2))
        first = seed.entry(conn, a, on=date(2026, 3, 2), amount=-600, source_id=src)
        second = seed.entry(conn, a, on=date(2026, 3, 2), amount=-400, source_id=src)
    r = go(isolated_engine, tag)
    assert r.newly_tagged == 2
    assert memberships(isolated_engine) == [(first, tag), (second, tag)]


def test_no_version_moves_and_reviewed_and_unreviewed_are_tagged(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    add(isolated_engine, a, on=date(2026, 3, 2), flags=("unconfirmed",))
    add(isolated_engine, a, on=date(2026, 3, 3))
    before = versions(isolated_engine)
    assert go(isolated_engine, tag).newly_tagged == 2
    assert versions(isolated_engine) == before


def test_an_empty_filter_is_refused_without_all_and_allowed_with_it(
    isolated_engine: Engine, two_accounts, tag
):
    a, _ = two_accounts
    add(isolated_engine, a, on=date(2026, 1, 2))
    add(isolated_engine, a, on=date(2026, 5, 2))
    for dry in (True, False):
        with pytest.raises(EmptyFilter):
            go(isolated_engine, tag, LedgerFilter(), dry_run=dry)
    assert memberships(isolated_engine) == []
    assert go(isolated_engine, tag, LedgerFilter(), all_=True).newly_tagged == 2
    # `all` with a real filter is simply allowed
    assert go(isolated_engine, tag, MAR, all_=True).newly_tagged == 0


def test_expected_count_match_and_mismatch(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    add(isolated_engine, a, on=date(2026, 3, 2))
    add(isolated_engine, a, on=date(2026, 3, 3))
    with pytest.raises(FilterResultChanged) as e:
        go(isolated_engine, tag, expected_count=3)
    assert (e.value.expected, e.value.actual) == (3, 2)
    assert memberships(isolated_engine) == []
    assert go(isolated_engine, tag, expected_count=2).newly_tagged == 2


def test_expected_count_after_the_set_changed(isolated_engine: Engine, two_accounts, tag):
    a, _ = two_accounts
    add(isolated_engine, a, on=date(2026, 3, 2))
    preview = go(isolated_engine, tag, dry_run=True)
    add(isolated_engine, a, on=date(2026, 3, 5))  # an entry arrives after the preview
    with pytest.raises(FilterResultChanged) as e:
        go(isolated_engine, tag, expected_count=preview.newly_tagged)
    assert (e.value.expected, e.value.actual) == (1, 2)
    assert memberships(isolated_engine) == []


def test_expected_count_zero_is_checked_too(isolated_engine: Engine, two_accounts, tag):
    add(isolated_engine, two_accounts[0], on=date(2026, 3, 2))
    with pytest.raises(FilterResultChanged):
        go(isolated_engine, tag, expected_count=0)


def test_unknown_tag(isolated_engine: Engine, two_accounts):
    with pytest.raises(TagMissing):
        go(isolated_engine, 999)
    with pytest.raises(TagMissing):
        go(isolated_engine, 999, dry_run=True)


def test_a_failure_midway_writes_nothing(isolated_engine: Engine, two_accounts, tag, monkeypatch):
    a, _ = two_accounts
    add(isolated_engine, a, on=date(2026, 3, 2))
    add(isolated_engine, a, on=date(2026, 3, 3))

    def boom(*args: Any, **kw: Any):
        raise RuntimeError("injected")

    monkeypatch.setattr(tags_mod, "_span", boom)  # runs after the insert, inside the transaction
    with pytest.raises(RuntimeError):
        go(isolated_engine, tag)
    assert memberships(isolated_engine) == []


def test_settle_runs_once_after_commit_and_its_error_is_returned(
    isolated_engine: Engine, two_accounts, tag, monkeypatch
):
    seen: list[int] = []

    def fake(engine: Engine) -> SettleResult:
        seen.append(len(memberships(engine)))
        return SettleResult((), "boom")

    monkeypatch.setattr(tags_mod, "settle", fake)
    add(isolated_engine, two_accounts[0], on=date(2026, 3, 2))
    r = go(isolated_engine, tag)
    assert seen == [1]  # one call, seeing the committed memberships
    assert r.settle == SettleResult((), "boom") and r.newly_tagged == 1


def test_the_filter_validation_is_the_lists(isolated_engine: Engine, two_accounts, tag):
    """A LedgerFilter cannot be built invalid, so apply can never see one (shared rules)."""
    from app.core.ledger import InvalidFilter

    with pytest.raises(InvalidFilter):
        go(isolated_engine, tag, LedgerFilter(amount_min=1))


def test_other_dimensions_select_through_the_shared_filter(isolated_engine: Engine, two_accounts, tag):
    a, b = two_accounts
    keep = add(isolated_engine, b, on=date(2026, 3, 2), amount=-4000)
    add(isolated_engine, a, on=date(2026, 3, 2), amount=-4000)
    add(isolated_engine, b, on=date(2026, 3, 2), amount=500)
    r = go(isolated_engine, tag, LedgerFilter(account_ids=(b,), direction="out"))
    assert memberships(isolated_engine) == [(keep, tag)] and r.per_account == {b: 1}
