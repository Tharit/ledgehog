"""A rule write's preview on a backfill-sized ledger stays inside the budget (spec §5.9, D204).

The ledger is the settled variant of the fixture (8,000 entries, ~70% confirmed: 5,600 history voters,
about 2,400 unconfirmed) in its own database, so the rules written here touch no other perf test.
Timed: the dry run of a create (a merchant's rule, and the worst case, a regex matching every entry,
so every unconfirmed unit is rederived), of an edit and of a delete (list B read through the GIN
index); and the settle after a real rule write, against the settle budget.
The budget is `tests.perf.budget.RULE_PREVIEW_BUDGET_SECONDS`. Numbers are printed (run with -s).
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.core.ledger import rules as rules_mod
from app.core.ledger.rules import RuleDraft, create_rule, delete_rule, update_rule
from app.core.settle.settle import settle
from app.utils.config import Config
from tests.perf.budget import BUDGET_SECONDS, RULE_PREVIEW_BUDGET_SECONDS
from tests.perf.conftest import Backfill, _backfill
from tests.perf.test_settle_budget import Stats

pytestmark = pytest.mark.perf
REPEATS = 5


@pytest.fixture(scope="module", params=["unclassified", "mostly confirmed"])
def settled(request: pytest.FixtureRequest, admin_cfg: Config, template_db: str) -> Iterator[Backfill]:
    """8,000 entries, all unconfirmed (the worst case to rederive) or ~70% confirmed (history voters)."""
    share = 0.7 if request.param == "mostly confirmed" else 0.0
    for ledger in _backfill(admin_cfg, template_db, confirmed_share=share):
        assert settle(ledger.engine).error is None
        print(f"\n[perf] ledger: {request.param}")
        yield ledger


def _category(ledger: Backfill, merchant: str) -> int:
    """The merchant's category (seeded with the confirmed variant of the fixture), made when missing."""
    name = f"Cat {merchant}"
    with ledger.engine.begin() as conn:
        found = conn.execute(
            text("SELECT id FROM category WHERE name = :n"), {"n": name}
        ).scalar_one_or_none()
        if found is not None:
            return int(found)
        return int(
            conn.execute(
                text("INSERT INTO category (name, kind) VALUES (:n, 'expense') RETURNING id"), {"n": name}
            ).scalar_one()
        )


def _timed[T](samples: list[float], call: object) -> T:
    started = time.perf_counter()
    result = call()  # type: ignore[operator]
    samples.append(time.perf_counter() - started)
    return result  # type: ignore[no-any-return]


def test_the_preview_of_a_create_an_edit_and_a_delete_within_budget(settled: Backfill):
    engine = settled.engine
    shell = _category(settled, "Shell")
    merchant = RuleDraft(name="Shell", sets="category", category_id=shell, name_exact="Shell")
    everything = RuleDraft(name="Everything", sets="category", category_id=shell, purpose_regex=".")
    merchant_s: list[float] = []
    everything_s: list[float] = []
    for _ in range(REPEATS):
        m = _timed(merchant_s, lambda: create_rule(engine, merchant, dry_run=True))
        e = _timed(everything_s, lambda: create_rule(engine, everything, dry_run=True))
    entries = settled.summary.entry_count
    print(
        f"\n[perf] preview, create, a merchant's rule ({m.preview.matches.total} matches): "
        f"{Stats.of(merchant_s)}"
    )
    print(
        f"[perf] preview, create, matches all ({e.preview.matches.total} matches, "
        f"{e.preview.would_confirm + e.preview.stay_in_review} unconfirmed): {Stats.of(everything_s)}"
    )
    assert 0 < m.preview.matches.total < entries
    assert e.preview.matches.total == entries
    unconfirmed = e.preview.would_confirm + e.preview.stay_in_review
    assert unconfirmed > 1_000
    if unconfirmed == entries:  # nothing classified: a category rule completes every flow
        assert e.preview.would_confirm == entries
    assert len(e.preview.matches.rows) == 100  # list A holds only what settling leaves: may be empty

    # a real write, then an edit and a delete of the rule that now holds keys
    written = create_rule(engine, merchant, expected_count=m.preview.matches.total)
    assert written.rule is not None
    rid = written.rule.id
    edit_s: list[float] = []
    delete_s: list[float] = []
    narrowed = RuleDraft(
        name="Shell", sets="category", category_id=shell, name_exact="Shell", mandate_ref="x"
    )
    for _ in range(REPEATS):
        u = _timed(edit_s, lambda: update_rule(engine, rid, narrowed, dry_run=True))
        d = _timed(delete_s, lambda: delete_rule(engine, rid, dry_run=True))
    print(
        f"[perf] preview, edit, narrowing ({u.preview.lost_key.total} keyed entries lost): {Stats.of(edit_s)}"
    )
    print(f"[perf] preview, delete ({d.preview.lost_key.total} keyed entries): {Stats.of(delete_s)}")
    assert u.preview.lost_key.total > 0 and d.preview.lost_key.total == u.preview.lost_key.total

    for name, samples in (
        ("create (merchant)", merchant_s),
        ("create (matches all)", everything_s),
        ("edit", edit_s),
        ("delete", delete_s),
    ):
        stats = Stats.of(samples)
        assert stats.max <= RULE_PREVIEW_BUDGET_SECONDS, (
            f"{name}: {stats} exceeds the budget of {RULE_PREVIEW_BUDGET_SECONDS} s"
        )


def test_settle_after_a_rule_write_within_the_settle_budget(
    settled: Backfill, monkeypatch: pytest.MonkeyPatch
):
    engine = settled.engine
    samples: list[float] = []
    real = settle

    def timed(e):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        try:
            return real(e)
        finally:
            samples.append(time.perf_counter() - started)

    monkeypatch.setattr(rules_mod, "settle", timed)
    category = _category(settled, "Amazon")
    ids: list[int] = []
    for i in range(REPEATS):
        draft = RuleDraft(name=f"Amazon {i}", sets="category", category_id=category, name_exact="Amazon")
        dry = create_rule(engine, draft, dry_run=True)
        written = create_rule(engine, draft, expected_count=dry.preview.matches.total)
        assert written.settle is not None and written.settle.error is None
        assert written.rule is not None
        ids.append(written.rule.id)
    for rid in ids:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rule WHERE id = :i"), {"i": rid})
    stats = Stats.of(samples)
    print(f"[perf] settle after a real rule write: {stats}, budget {BUDGET_SECONDS} s")
    assert len(samples) == REPEATS and stats.max <= BUDGET_SECONDS
