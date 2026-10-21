"""The one worker that asks the model, in the background (architecture §5.4).

It takes the head of the `ModelQueue`, one entry at a time, reads the entry afresh, asks the model for the
category and stores the answer with a write that settles like any other (`settle(before=...)`): the
category and its `llm` key (the payload's fingerprint, the model's name and one-line rationale), the type
`flow` keyed the same when none was decided. "No category fits" is stored too: the `llm` key with `none`
and the rationale on the empty category, nothing else touched, which settling then keeps and does not
list again for that payload (`answer.py`); an invalid reply is not stored. Nothing changes under the user:
the answer is dropped when the entry is confirmed, its payload changed, or its category now has a value of
a user or of a pass of higher authority. Settling never waits for the worker.

An unreachable model (timeout, refused, an HTTP error): the queue is marked unavailable and emptied, one
WARNING is logged, and the worker tries again after `retry_after` seconds by settling, which refills the
list. Never logged: the payload, the model's reply, the key.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.model.queue import Item, ModelQueue
from app.core.plugins.classifier import EntryInput
from app.core.plugins.model import CategoryPath, ModelAnswer, ModelClient, ModelUnavailable
from app.core.resolution.load import UnconfirmedEntry, load_units_of
from app.core.settle import settle

log = logging.getLogger("ledgehog.model")

RETRY_AFTER_SECONDS = 600.0

_STORE = text(
    """
    UPDATE ledger_entry
       SET category_id = :category,
           type = COALESCE(type, 'flow'),
           derivation = (derivation - 'category')
                        || jsonb_build_object('category', CAST(:key AS jsonb))
                        || CASE WHEN type IS NULL THEN jsonb_build_object('type', CAST(:key AS jsonb))
                                ELSE '{}'::jsonb END
     WHERE id = :id
    """
)

# the "none" answer (no category fits): the key alone, the category left empty and the type as it is
_STORE_NONE = text(
    """
    UPDATE ledger_entry
       SET derivation = (derivation - 'category') || jsonb_build_object('category', CAST(:key AS jsonb))
     WHERE id = :id
    """
)


def load_category_paths(conn: Connection) -> list[CategoryPath]:
    """The whole category tree as paths (`Expense > Food > Groceries`; the roots are the kinds)."""
    rows = {
        int(r.id): (str(r.name), str(r.kind), int(r.parent_id) if r.parent_id is not None else None)
        for r in conn.execute(text("SELECT id, name, kind, parent_id FROM category"))
    }

    def path(category_id: int) -> str:
        name, kind, parent = rows[category_id]
        names = [name]
        while parent is not None:
            name, _, parent = rows[parent]
            names.append(name)
        names.append(kind.capitalize())
        return " > ".join(reversed(names))

    return sorted((CategoryPath(i, path(i)) for i in rows), key=lambda c: (c.path, c.id))


def _row_of(conn: Connection, entry_id: int) -> UnconfirmedEntry | None:
    for row in load_units_of(conn, [entry_id]):
        if row.input.entry_id == entry_id:
            return None if row.confirmed else row
    return None


def _may_take_answer(row: UnconfirmedEntry) -> bool:
    """The category is still the model's to fill: empty, or held by an earlier answer of its own."""
    if row.type not in (None, "flow"):
        return False
    if row.category_id is None:
        return True
    key = row.derivation.get("category")
    return isinstance(key, Mapping) and key.get("pass") == "llm"


class ModelWorker:
    def __init__(
        self,
        queue: ModelQueue,
        client: ModelClient,
        engine: Engine,
        *,
        retry_after: float = RETRY_AFTER_SECONDS,
    ) -> None:
        self.queue = queue
        self.client = client
        self.engine = engine
        self.retry_after = retry_after
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    # ---- lifecycle ------------------------------------------------------------------------------

    def start(self) -> None:
        """Start the worker on the running loop (the app's lifespan)."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.run(), name="model-worker")

    async def stop(self) -> None:
        task, self._task = self._task, None
        self.queue.notify = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.client.aclose()

    # ---- the loop -------------------------------------------------------------------------------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        wake = self._wake = asyncio.Event()

        def notify() -> None:
            loop.call_soon_threadsafe(wake.set)

        self.queue.notify = notify
        while True:
            item = self.queue.head()
            if item is not None:
                await self.process(item)
                continue
            wake.clear()
            if self.queue.head() is not None:  # work arrived between the look and the clear
                continue
            try:
                await asyncio.wait_for(wake.wait(), self.retry_after if self.queue.unavailable else None)
            except TimeoutError:
                await self._retry()

    async def _retry(self) -> None:
        self.queue.retry()
        log.info("trying the model again")
        await asyncio.to_thread(settle, self.engine)  # the settle's sync refills the list

    async def process(self, item: Item) -> None:
        """Ask the model about one listed entry and store what it answers (the loop's one step)."""
        started = loop_time()
        try:
            loaded = await asyncio.to_thread(self._load, item)
            if loaded is None:  # gone, confirmed or its payload changed: settling lists what is left
                self.queue.finish(item, answered=True)
                return
            entry, categories = loaded
            answer = await self.client.ask(entry, categories)
        except ModelUnavailable as exc:
            if self.queue.mark_unavailable():
                log.warning(
                    "the model is unavailable (%s): its entries stay unclassified, trying again in %d s",
                    exc,
                    int(self.retry_after),
                )
            return
        except Exception as exc:
            log.error("asking the model failed: %s", type(exc).__name__)
            self.queue.finish(item, answered=False)
            return
        stored = answer is not None and await asyncio.to_thread(self._store, item, answer)
        self.queue.finish(item, answered=stored)
        log.debug(
            "model asked about entry %d: %s in %.1f s",
            item[0],
            "stored" if stored else "no answer",
            loop_time() - started,
        )

    # ---- reading and writing (threads) ----------------------------------------------------------

    def _load(self, item: Item) -> tuple[EntryInput, list[CategoryPath]] | None:
        entry_id, fingerprint = item
        with self.engine.connect() as conn:
            row = _row_of(conn, entry_id)
            if row is None or not _may_take_answer(row) or self.client.fingerprint(row.input) != fingerprint:
                return None
            return row.input, load_category_paths(conn)

    def _store(self, item: Item, answer: ModelAnswer) -> bool:
        """Write the answer inside a settle; False when it is dropped (nothing is written)."""
        entry_id, fingerprint = item
        written = False

        def write(conn: Connection) -> list[int] | None:
            nonlocal written
            row = _row_of(conn, entry_id)
            if (
                row is None
                or not _may_take_answer(row)
                or self.client.fingerprint(row.input) != fingerprint
                or (
                    answer.category_id is not None
                    and conn.execute(
                        text("SELECT 1 FROM category WHERE id = :c"), {"c": answer.category_id}
                    ).first()
                    is None
                )
            ):
                return None
            basis: dict[str, Any] = {
                "model": answer.model,
                "rationale": answer.rationale,
                "fingerprint": fingerprint,
            }
            if answer.category_id is None:
                basis["none"] = True
            key: dict[str, Any] = {"pass": "llm", "basis": basis}
            if answer.category_id is None:
                conn.execute(_STORE_NONE, {"id": entry_id, "key": json.dumps(key)})
            else:
                conn.execute(_STORE, {"id": entry_id, "category": answer.category_id, "key": json.dumps(key)})
            written = True
            return [entry_id]

        result = settle(self.engine, before=write)
        if result.error is not None:
            log.error("storing the model's answer failed: %s", result.error)
            return False
        return written


def loop_time() -> float:
    return asyncio.get_running_loop().time()
