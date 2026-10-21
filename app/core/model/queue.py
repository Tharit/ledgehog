"""The list of entries the model still has to look at (architecture §5.4): in memory, never stored.

Settling fills it (`sync`: every settle hands over the whole set of entries whose category falls to the
model, as (entry id, payload fingerprint)); one worker takes the head, one at a time. It is not a review
flag: a restart loses it and the start's settling refills it. It is read from threads (settling, requests)
and from the worker's event loop, so every access takes the lock.

Unavailable: when the model cannot be reached the list empties and what it held is remembered as
`dropped`. Settling hands it new work again only for an item not among them (an entry that was not
waiting when the model failed); otherwise the worker retries after its delay and settles, which refills.
An entry the model had no answer for (no category fits, an invalid reply) is not asked again for the same
payload until a restart.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from app.core.plugins.classifier import EntryInput

Item = tuple[int, str]  # (entry id, payload fingerprint)


class ModelQueue:
    def __init__(self, fingerprint: Callable[[EntryInput], str | None]) -> None:
        self.fingerprint = fingerprint
        # set by the worker: called (from any thread) when work arrives
        self.notify: Callable[[], None] | None = None
        self._lock = threading.Lock()
        self._items: list[Item] = []
        self._unavailable = False
        self._dropped: set[Item] = set()
        self._no_answer: set[Item] = set()

    def sync(self, wanted: Sequence[Item]) -> None:
        """Make the list the `wanted` items: the ones already waiting keep their place, the others follow."""
        want = list(dict.fromkeys(wanted))
        added = False
        with self._lock:
            want_set = set(want)
            self._no_answer &= want_set
            candidates = [w for w in want if w not in self._no_answer]
            if self._unavailable:
                fresh = [w for w in candidates if w not in self._dropped]
                if not fresh:
                    return
                self._unavailable = False
                self._dropped.clear()
            keep = [i for i in self._items if i in want_set]
            have = set(keep)
            new = [w for w in candidates if w not in have]
            self._items = keep + new
            added = bool(new)
            notify = self.notify
        if added and notify is not None:
            notify()

    def pending(self) -> int:
        with self._lock:
            return len(self._items)

    def entry_ids(self) -> frozenset[int]:
        with self._lock:
            return frozenset(i for i, _ in self._items)

    def head(self) -> Item | None:
        with self._lock:
            return self._items[0] if self._items else None

    def finish(self, item: Item, *, answered: bool) -> None:
        """Take the item off; an unanswered one is not asked again for the same payload."""
        with self._lock:
            if item in self._items:
                self._items.remove(item)
            if not answered:
                self._no_answer.add(item)

    @property
    def unavailable(self) -> bool:
        with self._lock:
            return self._unavailable

    def mark_unavailable(self) -> bool:
        """The model cannot be reached: the list empties. True when this is a change (log it once)."""
        with self._lock:
            changed = not self._unavailable
            self._dropped = set(self._items)
            self._items = []
            self._unavailable = True
            return changed

    def retry(self) -> None:
        """Try again: the next `sync` refills the list."""
        with self._lock:
            self._unavailable = False
            self._dropped.clear()


_queue: ModelQueue | None = None


def configure_model_queue(queue: ModelQueue | None) -> None:
    """Install the process's queue (None: no model configured, nothing is listed)."""
    global _queue
    _queue = queue


def current_model_queue() -> ModelQueue | None:
    return _queue
