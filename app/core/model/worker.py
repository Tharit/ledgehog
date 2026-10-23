"""The one worker that asks the model, in the background (architecture §5.4).

It takes the head of the `ModelQueue`, one item at a time (an entry, or a document line), reads it afresh,
asks the model for the category and stores the answer with a write that settles like any other
(`settle(before=...)`): the category and its `llm` key (the payload's fingerprint, the model's name and
one-line rationale), the type `flow` keyed the same when none was decided. "No category fits" is stored
too: the `llm` key with `none` and the rationale on the empty category, nothing else touched, which
settling then keeps and does not list again for that payload (the pass-3 classifier proposes the absence
while the payload stands); an invalid reply is not stored. Every entry asked gets one INFO
line saying what came of it and why (stored, dropped, no answer: a reason code). Nothing changes under
the user: the answer is dropped when the entry is confirmed, its payload changed, or its category now has a
value of a user or of a pass of higher authority. Settling never waits for the worker.

An unreachable model (timeout, refused, an HTTP error): the queue is marked unavailable and emptied, one
WARNING is logged, and the worker tries again after `retry_after` seconds by settling, which refills the
list. Never logged: the payload, the model's reply, the key.

A document line's answer is stored on the line (`category_id` and `category_key`, a key of the shape of an
entry's `llm` key, `none` included), dropped when the line is gone or its payload changed, and settles like
any write: the unconfirmed entries with that line are resolved again and take it (spec §5.9, pass 3).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.model.queue import LINE, Item, ModelQueue
from app.core.plugins.classifier import EntryInput
from app.core.plugins.model import (
    CategoryPath,
    LineInput,
    ModelAnswer,
    ModelClient,
    ModelUnavailable,
    NoAnswer,
)
from app.core.resolution.load import UnconfirmedEntry, load_units_of
from app.core.settle import settle
from app.utils.db.changes import DOCUMENTS, note_change

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

_LINE = text(
    """
    SELECT l.id, l.description, d.merchant_name
      FROM external_document_line AS l JOIN external_document AS d ON d.id = l.document_id
     WHERE l.id = :id
    """
)

# a line's answer: the category (NULL for "none") and its key, in an entry's shape
_STORE_LINE = text(
    "UPDATE external_document_line SET category_id = :category, category_key = CAST(:key AS jsonb)"
    " WHERE id = :id"
)
_LINE_ENTRIES = text("SELECT id FROM ledger_entry WHERE document_line_id = :id ORDER BY id")


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


def _line_of(conn: Connection, line_id: int) -> LineInput | None:
    r = conn.execute(_LINE, {"id": line_id}).first()
    return LineInput(int(r.id), r.merchant_name, str(r.description)) if r is not None else None


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
        """Ask the model about one listed entry or line and store what it answers (the loop's one step)."""
        started = loop_time()
        try:
            loaded = await asyncio.to_thread(self._load, item)
            if loaded is None:  # gone, confirmed or its payload changed: settling lists what is left
                self.queue.finish(item, answered=True)
                return
            subject, categories = loaded
            answer = await self.client.ask(subject, categories)
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
        if isinstance(answer, NoAnswer):
            spent = f" after {answer.tokens} tokens" if answer.tokens is not None else ""
            outcome, stored = f"no answer ({answer.reason}{spent})", False
        else:
            outcome = await asyncio.to_thread(self._store, item, answer)
            stored = outcome.startswith("stored")
        self.queue.finish(item, answered=stored)
        # the outcome and its reason only: never the payload, the reply or the key
        log.info("model asked about %s %d: %s in %.1f s", item[0], item[1], outcome, loop_time() - started)

    # ---- reading and writing (threads) ----------------------------------------------------------

    def _load(self, item: Item) -> tuple[EntryInput | LineInput, list[CategoryPath]] | None:
        kind, ident, fingerprint = item
        with self.engine.connect() as conn:
            subject: EntryInput | LineInput
            if kind == LINE:
                line = _line_of(conn, ident)
                if line is None or self.client.fingerprint(line) != fingerprint:
                    return None
                subject = line
            else:
                row = _row_of(conn, ident)
                if (
                    row is None
                    or row.input.document_line is not None  # an entry with a line takes its line's answer
                    or not _may_take_answer(row)
                    or self.client.fingerprint(row.input) != fingerprint
                ):
                    return None
                subject = row.input
            return subject, load_category_paths(conn)

    def _store(self, item: Item, answer: ModelAnswer) -> str:
        """Write the answer inside a settle. The outcome for the log: `stored`, `stored, no fitting
        category`, or `dropped (why)` when nothing is written."""
        kind, entry_id, fingerprint = item
        outcome = "dropped (not written)"

        def key_of() -> dict[str, Any]:
            basis: dict[str, Any] = {
                "model": answer.model,
                "rationale": answer.rationale,
                "fingerprint": fingerprint,
            }
            if answer.category_id is None:
                basis["none"] = True
            return {"pass": "llm", "basis": basis}

        def write_line(conn: Connection) -> list[int] | None:
            nonlocal outcome
            line = _line_of(conn, entry_id)
            if line is None:
                outcome = "dropped (line gone)"
                return None
            if self.client.fingerprint(line) != fingerprint:
                outcome = "dropped (payload changed)"
                return None
            if (
                answer.category_id is not None
                and conn.execute(
                    text("SELECT 1 FROM category WHERE id = :c"), {"c": answer.category_id}
                ).first()
                is None
            ):
                outcome = "dropped (category gone)"
                return None
            conn.execute(
                _STORE_LINE, {"id": entry_id, "category": answer.category_id, "key": json.dumps(key_of())}
            )
            note_change(conn, DOCUMENTS)
            outcome = "stored, no fitting category" if answer.category_id is None else "stored"
            # the unconfirmed entries with that line are resolved again by the settle that follows
            return [int(i) for i in conn.execute(_LINE_ENTRIES, {"id": entry_id}).scalars()]

        def write(conn: Connection) -> list[int] | None:
            nonlocal outcome
            row = _row_of(conn, entry_id)
            if row is None:
                outcome = "dropped (entry gone or confirmed)"
                return None
            if not _may_take_answer(row):
                outcome = "dropped (category decided meanwhile)"
                return None
            if row.input.document_line is not None or self.client.fingerprint(row.input) != fingerprint:
                outcome = "dropped (payload changed)"
                return None
            if (
                answer.category_id is not None
                and conn.execute(
                    text("SELECT 1 FROM category WHERE id = :c"), {"c": answer.category_id}
                ).first()
                is None
            ):
                outcome = "dropped (category gone)"
                return None
            key = key_of()
            if answer.category_id is None:
                conn.execute(_STORE_NONE, {"id": entry_id, "key": json.dumps(key)})
            else:
                conn.execute(_STORE, {"id": entry_id, "category": answer.category_id, "key": json.dumps(key)})
            outcome = "stored, no fitting category" if answer.category_id is None else "stored"
            return [entry_id]

        result = settle(self.engine, before=write_line if kind == LINE else write)
        if result.error is not None:
            log.error("storing the model's answer failed: %s", result.error)
            return "dropped (storing failed)"
        return outcome


def loop_time() -> float:
    return asyncio.get_running_loop().time()
