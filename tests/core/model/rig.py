"""A fake chat-completions endpoint and the model wired as startup wires it, for the worker's tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import Engine, text

from app.core.model.queue import ModelQueue, configure_model_queue
from app.core.model.worker import ModelWorker
from app.core.resolution.registry import configure_classifiers
from app.plugins.classifiers import default_classifiers
from app.plugins.classifiers.llm import OpenAIModelClient


class Endpoint:
    """Answers every request with `reply` (a category id and rationale), or `status`; `during` runs inside
    the request, as the user acting while the model thinks."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.category_id: int | None = None
        self.rationale = "a short reason"
        self.status = 200
        self.during: Callable[[], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.during is not None:
            self.during()
        if self.status != 200:
            return httpx.Response(self.status, text="down")
        content = json.dumps({"category_id": self.category_id, "rationale": self.rationale})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@dataclass
class Rig:
    endpoint: Endpoint
    queue: ModelQueue
    worker: ModelWorker
    engine: Engine
    client: OpenAIModelClient = field(repr=False, default=None)  # type: ignore[assignment]


def make_rig(engine: Engine, retry_after: float = 600.0) -> Rig:
    endpoint = Endpoint()
    client = OpenAIModelClient("http://model.test/v1", "m-1", None, transport=httpx.MockTransport(endpoint))
    queue = ModelQueue(client.fingerprint)
    configure_model_queue(queue)
    configure_classifiers(lambda rules: default_classifiers(rules, model=True))
    return Rig(endpoint, queue, ModelWorker(queue, client, engine, retry_after=retry_after), engine, client)


def entry_row(engine: Engine, entry_id: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT type, category_id, derivation, version FROM ledger_entry WHERE id = :i"),
            {"i": entry_id},
        ).one()
