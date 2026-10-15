"""Waiting and unmatched (spec §5.7, §6), as predicates over one unpaired leg.

Mirrored in SQL by the settle flags; an equivalence test pins the two together.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.matching.leg import Leg


def waiting(leg: Leg, *, counter_synced: bool, synced_through: date | None, window: int) -> bool:
    """An unpaired leg whose counter-account is synced and has not yet synced past the window.

    `counter_synced` and `synced_through` describe the leg's counter-account (ignored where it has none).
    """
    if leg.counter_account_id is None or not counter_synced:
        return False
    return synced_through is None or synced_through < leg.booked_on + timedelta(days=window)


def unmatched(
    leg: Leg, *, paired: bool, counter_synced: bool, synced_through: date | None, window: int
) -> bool:
    """Unpaired and not waiting. A paired leg is neither."""
    return not paired and not waiting(
        leg, counter_synced=counter_synced, synced_through=synced_through, window=window
    )
