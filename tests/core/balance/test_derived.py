"""`core/balance` is the only writer of derived entries (architecture §5.1): the hook lives there."""

from __future__ import annotations

from app.core.balance import derived
from app.core.ingest import duplicates, removal, run


def test_the_recompute_hook_lives_in_core_balance_and_is_the_one_callers_use() -> None:
    assert callable(derived.recompute_derived)
    assert run.recompute_derived is derived.recompute_derived
    assert removal.recompute_derived is derived.recompute_derived
    assert duplicates.recompute_derived is derived.recompute_derived
