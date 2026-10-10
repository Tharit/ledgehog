"""Settling (architecture §5.2): derived state brought up to date after every write.

Contract shared by every caller:

* ``settle(engine)`` opens **its own** transaction, takes the settle lock exclusively,
  runs rounds until a round confirms nothing new, and commits. It takes no account lock
  and creates no rows. It is idempotent (spec I37): a second call touches nothing.
* A failure after the caller's write committed does not raise: the settle transaction
  rolls back, the write stands, and the failure is reported in ``SettleResult.error``.

One round is the five ordered steps of architecture §5.2. Steps 1-4 are named no-op
hooks for now; later work replaces them with ``register_step(name, fn)``. Step 5 is
the review flags. The settle baseline is a pass over every unconfirmed unit; narrowing
to a dirty set is an optimisation to take only if the time budget is missed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from app.core.settle.flags import recompute_review_flags
from app.utils.db.locks import lock_settle_exclusive

log = logging.getLogger(__name__)

# Rounds terminate because the confirmed set only grows; this guard turns a broken
# hook that "confirms" forever into a reported failure instead of a hang.
MAX_ROUNDS = 100


@dataclass(frozen=True)
class SettleResult:
    """What settling touched; part of every operation's response (architecture §5.2)."""

    touched_entry_ids: tuple[int, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class StepOutcome:
    """What one step did: the entry ids it changed and how many units it newly confirmed."""

    touched: Iterable[int] = ()
    newly_confirmed: int = 0


Step = Callable[[Connection], StepOutcome]


def _noop(conn: Connection) -> StepOutcome:
    return StepOutcome()


def _review_flags_step(conn: Connection) -> StepOutcome:
    # Confirmation is not derived yet (no unit can be confirmed before steps 6-9),
    # so the flags never confirm anything new.
    return StepOutcome(touched=recompute_review_flags(conn))


_STEPS: list[tuple[str, Step]] = [
    ("resolve", _noop),
    ("match_documents", _noop),
    ("resolve_after_link", _noop),
    ("pair_transfers", _noop),
    ("review_flags", _review_flags_step),
]


def registered_steps() -> tuple[str, ...]:
    """Names of the steps of one round, in execution order."""
    return tuple(name for name, _ in _STEPS)


def register_step(name: str, fn: Step) -> None:
    """Replace the hook of the named step, keeping its place in the order."""
    for i, (existing, _) in enumerate(_STEPS):
        if existing == name:
            _STEPS[i] = (name, fn)
            return
    raise ValueError(f"unknown settle step: {name!r}")


def _run_rounds(conn: Connection) -> set[int]:
    touched: set[int] = set()
    for _ in range(MAX_ROUNDS):
        confirmed = 0
        for _name, step in list(_STEPS):
            outcome = step(conn)
            touched.update(outcome.touched)
            confirmed += outcome.newly_confirmed
        if confirmed == 0:
            return touched
    raise RuntimeError(f"settling did not converge within {MAX_ROUNDS} rounds")


def settle(engine: Engine) -> SettleResult:
    """Settle derived state in its own transaction; never raises for a failure of its own."""
    try:
        with engine.begin() as conn:
            lock_settle_exclusive(conn)
            # transaction-local: settling's rewrites must not bump `version` (schema 8.6)
            conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
            touched = _run_rounds(conn)
    except Exception as exc:
        log.exception("settle failed; the committed write stands")
        return SettleResult(error=_short(exc))
    return SettleResult(touched_entry_ids=tuple(sorted(touched)))


def _short(exc: Exception) -> str:
    first_line = (str(exc).strip().splitlines() or [""])[0][:200]
    return f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
