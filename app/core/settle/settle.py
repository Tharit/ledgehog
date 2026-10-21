"""Settling (architecture §5.2): derived state brought up to date after every write.

Contract shared by every caller:

* ``settle(engine)`` opens **its own** transaction, takes the settle lock exclusively,
  runs rounds until a round confirms nothing new, and commits. It takes no account lock
  and creates no rows. It is idempotent (spec I37): a second call touches nothing.
* A failure after the caller's write committed does not raise: the settle transaction
  rolls back, the write stands, and the failure is reported in ``SettleResult.error``.

One round is the five ordered steps of architecture §5.2. Before the first round, "none" is recorded for the
document of every confirmed unit that has none (step 5 does it for what each round newly confirms).
Step 1 resolves every unconfirmed entry (core/settle/resolution.py), step 4 pairs the unpaired transfer legs
(core/settle/pairing.py) and step 5 is the review flags, which also report what the round
newly confirmed; steps 2 and 3 are document matching and the resolution after a link
(core/settle/documents.py); a step can be replaced with ``register_step(name, fn)``. The steps of one
settle share a `SettleRun` (core/settle/run.py). The settle baseline is a pass over every unconfirmed
unit; narrowing to a dirty set is an optimisation to take only if the time budget is missed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from app.core.resolution.confirmed import load_confirmed_ids
from app.core.settle.documents import match_documents_step, resolve_after_link_step
from app.core.settle.flags import record_none_documents, review_flags_step
from app.core.settle.pairing import pair_transfers_step
from app.core.settle.resolution import resolve_step
from app.core.settle.run import StepOutcome, settle_run
from app.utils.db.changes import DOCUMENTS, LEDGER, note_change
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


Step = Callable[[Connection], StepOutcome]


_STEPS: list[tuple[str, Step]] = [
    ("resolve", resolve_step),
    ("match_documents", match_documents_step),
    ("resolve_after_link", resolve_after_link_step),
    ("pair_transfers", pair_transfers_step),
    ("review_flags", review_flags_step),
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


def _run_rounds(conn: Connection) -> tuple[set[int], bool]:
    """The entries touched, and whether a document was linked."""
    touched: set[int] = set()
    with settle_run() as run:
        run.confirmed = load_confirmed_ids(conn)
        # a unit confirmed before this settle (written complete and standing, such as an entry form's) has
        # no document key yet either: "none" is recorded for it too, so no later document source reopens it
        touched.update(record_none_documents(conn, sorted(run.confirmed)))
        for _ in range(MAX_ROUNDS):
            confirmed = 0
            for _name, step in list(_STEPS):
                outcome = step(conn)
                touched.update(outcome.touched)
                confirmed += outcome.newly_confirmed
            if confirmed == 0:
                return touched, run.document_linked
    raise RuntimeError(f"settling did not converge within {MAX_ROUNDS} rounds")


def settle(
    engine: Engine, *, before: Callable[[Connection], Sequence[int] | None] | None = None
) -> SettleResult:
    """Settle derived state in its own transaction; never raises for a failure of its own.

    `before(conn)` runs first, under the lock, in the same transaction: a write that settles like any other
    (the model's answer, architecture §5.4). It returns the entry ids it wrote, or None for nothing written,
    which ends the settle without a round."""
    try:
        with engine.begin() as conn:
            lock_settle_exclusive(conn)
            # transaction-local: settling's rewrites must not bump `version` (schema 8.6)
            conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
            written: set[int] = set()
            if before is not None:
                wrote = before(conn)
                if wrote is None:
                    return SettleResult()
                written.update(wrote)
            touched, document_linked = _run_rounds(conn)
            touched |= written
            # the change values move when this transaction commits (architecture §5.2)
            if touched:
                note_change(conn, LEDGER)
            if document_linked:
                note_change(conn, DOCUMENTS)
    except Exception as exc:
        log.exception("settle failed; the committed write stands")
        return SettleResult(error=_short(exc))
    return SettleResult(touched_entry_ids=tuple(sorted(touched)))


def _short(exc: Exception) -> str:
    first_line = (str(exc).strip().splitlines() or [""])[0][:200]
    return f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
