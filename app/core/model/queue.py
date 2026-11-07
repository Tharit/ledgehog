"""The list the model still has to look at (architecture §5.4): in memory, never stored.

Its items are entries, each as (entry id, payload fingerprint); beside each the ids of the categories
history counted for it, which the payload carries (the fingerprint covers them). Settling fills it (`sync`:
every settle hands over the whole set: the entries whose category falls to the model); one worker takes the
head, one at a time. It is not a review flag: a restart loses it and the start's settling refills it. It
is read from threads (settling, requests) and from the worker's event loop, so every access takes the lock.

Unavailable: when the model cannot be reached the list empties and what it held is remembered as
`dropped`. Settling hands it new work again only for an item not among them (an entry that was not
waiting when the model failed); otherwise the worker retries after its delay and settles, which refills.
An entry the model gave no valid reply for is not asked again for the same payload until a restart; one it
answered "no category fits" is not listed again at all: its stored key is a proposal for the category, so
nothing falls to the model.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence

from app.core.plugins.classifier import EntryInput

Item = tuple[int, str]  # (entry id, payload fingerprint)


class ModelQueue:
    def __init__(self, fingerprint: Callable[[EntryInput, Sequence[int]], str | None]) -> None:
        self.fingerprint = fingerprint
        # set by the worker: called (from any thread) when work arrives
        self.notify: Callable[[], None] | None = None
        self._lock = threading.Lock()
        self._items: list[Item] = []
        self._unavailable = False
        self._dropped: set[Item] = set()
        self._no_answer: set[Item] = set()
        self._categories: dict[Item, tuple[int, ...]] = {}

    def sync(self, wanted: Sequence[Item], categories: Mapping[Item, tuple[int, ...]] | None = None) -> None:
        """Make the list the `wanted` items: the ones already waiting keep their place, the others follow.
        `categories` are the ids history counted for an item (none: not given)."""
        want = list(dict.fromkeys(wanted))
        added = False
        with self._lock:
            self._categories = {w: tuple((categories or {}).get(w, ())) for w in want}
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

    def categories_of(self, item: Item) -> tuple[int, ...]:
        """The ids of the categories history counted for the item when it was listed."""
        with self._lock:
            return self._categories.get(item, ())

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
