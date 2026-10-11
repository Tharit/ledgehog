"""Applying a tag to a whole year of a backfill-sized ledger stays inside the budget (plan B13).

Both the dry run (the preview) and the real apply select ~8,000 entries; the real run is timed
without settle (that is `test_settle_budget`). Memberships are removed again after each sample.
The budget is `tests.perf.budget.TAG_APPLY_BUDGET_SECONDS`. Numbers are printed (run with -s).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import text

from app.core.ledger import LedgerFilter
from app.core.ledger import tags as tags_mod
from app.core.ledger.tags import apply_tag, create_tag
from app.core.settle.settle import SettleResult
from tests.fixtures.backfill import END
from tests.perf.budget import TAG_APPLY_BUDGET_SECONDS
from tests.perf.conftest import Backfill
from tests.perf.test_settle_budget import Stats

pytestmark = pytest.mark.perf
REPEATS = 5


@pytest.fixture
def tag_id(backfill: Backfill) -> Iterator[int]:
    made = create_tag(backfill.engine, name="perf-apply")
    yield made.tag.id
    with backfill.engine.begin() as conn:
        conn.execute(text("DELETE FROM tag WHERE id = :t"), {"t": made.tag.id})


def _year() -> LedgerFilter:
    return LedgerFilter(date_from=date(END.year, 1, 1), date_to=date(END.year, 12, 31))


def test_apply_a_whole_year_within_budget(backfill: Backfill, tag_id: int, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tags_mod, "settle", lambda engine: SettleResult())
    flt = _year()
    dry: list[float] = []
    real: list[float] = []
    selected = 0
    for _ in range(REPEATS):
        started = time.perf_counter()
        preview = apply_tag(backfill.engine, tag_id, flt, dry_run=True, expected_count=None, all_=False)
        dry.append(time.perf_counter() - started)
        started = time.perf_counter()
        done = apply_tag(
            backfill.engine, tag_id, flt, dry_run=False, expected_count=preview.newly_tagged, all_=False
        )
        real.append(time.perf_counter() - started)
        selected = done.newly_tagged
        assert done.newly_tagged == preview.newly_tagged
        with backfill.engine.begin() as conn:
            conn.execute(text("DELETE FROM ledger_entry_tag WHERE tag_id = :t"), {"t": tag_id})
    print(f"[perf] tag apply dry run, {selected} entries: {Stats.of(dry)}")
    print(f"[perf] tag apply real run, {selected} entries: {Stats.of(real)}")
    assert selected > 5_000, "the year should select most of the backfill"
    for name, samples in (("dry run", dry), ("real run", real)):
        stats = Stats.of(samples)
        assert stats.max <= TAG_APPLY_BUDGET_SECONDS, (
            f"{name}: {stats} exceeds the budget of {TAG_APPLY_BUDGET_SECONDS} s"
        )
