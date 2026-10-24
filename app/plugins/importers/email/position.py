"""The position and the memory of a run (spec/plugins/importers/email.md §1, §2, §8).

`position_for`, `uidvalidity`, `last_uid`, `fetched_on` and `seen` are the delivery's position, kept only once
the run's documents are written; `stuck` is plain state, written as it is learned.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.plugins.importers.email.settings import EmailSettings

SEEN_DAYS = 14
GIVE_UP_AFTER = 3  # runs in a row that fail at the same message


def _digest16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def position_for(settings: EmailSettings) -> str:
    """What the position was built for: another server, login, folder or start date discards it."""
    parts = (
        settings.host.lower(),
        str(settings.port),
        settings.username,
        settings.mailbox,
        settings.start_date.isoformat(),
    )
    return _digest16("\x1f".join(parts))


def fingerprint(identity: str) -> str:
    """How `seen` remembers a Message-ID: the first 16 hex digits of its SHA-256."""
    return _digest16(identity)


@dataclass(frozen=True, slots=True)
class Position:
    uidvalidity: int
    last_uid: int
    fetched_on: date
    seen: Mapping[str, date] = field(default_factory=dict)


def read_position(state: Mapping[str, Any], settings: EmailSettings) -> Position | None:
    """The stored position; None on a first run, where it was built for other settings, or if malformed."""
    if state.get("position_for") != position_for(settings):
        return None
    try:
        uidvalidity, last_uid = state["uidvalidity"], state["last_uid"]
        if type(uidvalidity) is not int or type(last_uid) is not int or last_uid < 0:
            return None
        fetched_on = date.fromisoformat(state["fetched_on"])
        seen_raw = state.get("seen", {})
        seen = {str(k): date.fromisoformat(v) for k, v in seen_raw.items()}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return Position(uidvalidity, last_uid, fetched_on, seen)


def prune_seen(seen: Mapping[str, date], today: date) -> dict[str, date]:
    """Fingerprints kept for 14 days after their fetch day, then dropped."""
    horizon = today - timedelta(days=SEEN_DAYS)
    return {fp: day for fp, day in seen.items() if day >= horizon}


def position_update(
    settings: EmailSettings,
    *,
    uidvalidity: int,
    last_uid: int,
    today: date,
    seen: Mapping[str, date],
) -> dict[str, Any]:
    """The delivery's `position`: the keys of §1, JSON-able, `seen` pruned."""
    return {
        "position_for": position_for(settings),
        "uidvalidity": uidvalidity,
        "last_uid": last_uid,
        "fetched_on": today.isoformat(),
        "seen": {fp: day.isoformat() for fp, day in sorted(prune_seen(seen, today).items())},
    }


# ---- stuck: the message at which runs failed in a row on the model --------------------------------


def stuck_attempts(state: Mapping[str, Any], uid: int, uidvalidity: int) -> int:
    """How many runs in a row already failed at this message."""
    stuck = state.get("stuck")
    if isinstance(stuck, Mapping) and stuck.get("uid") == uid and stuck.get("uidvalidity") == uidvalidity:
        attempts = stuck.get("attempts")
        if type(attempts) is int and attempts > 0:
            return attempts
    return 0


def record_failure(state: MutableMapping[str, Any], uid: int, uidvalidity: int) -> bool:
    """Count a failed attempt at this message. True where it was the third in a row: the message is then
    given up (and `stuck` cleared); otherwise `stuck` is written for the next run to find."""
    attempts = stuck_attempts(state, uid, uidvalidity) + 1
    if attempts >= GIVE_UP_AFTER:
        state.pop("stuck", None)
        return True
    state["stuck"] = {"uid": uid, "uidvalidity": uidvalidity, "attempts": attempts}
    return False
