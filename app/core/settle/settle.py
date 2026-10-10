"""Settling (architecture §5.2): derived state brought up to date after every write.

Contract shared by every caller, fixed ahead of the implementation:

* ``settle(engine)`` opens **its own** transaction, takes the settle lock exclusively,
  runs rounds until nothing newly confirms, and commits. It is idempotent (spec I37).
* A failure after the caller's write committed does not raise: the write stands and
  the failure is reported in ``SettleResult.error``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine


@dataclass(frozen=True)
class SettleResult:
    """What settling touched; part of every operation's response (architecture §5.2)."""

    touched_entry_ids: tuple[int, ...] = ()
    error: str | None = None


def settle(engine: Engine) -> SettleResult:
    """Stub: replaced by Task 3b. Callers depend only on this signature."""
    return SettleResult()
