"""The OpenAI chat-completions client for pass 3 (architecture §5.4).

One request per entry, `temperature` 0, structured output: `response_format` of type `json_schema` whose
`category_id` is one of the listed ids or null, plus a one-line rationale. llama.cpp's server accepts the
OpenAI form (`json_schema.schema`) and its own (`schema` beside `type`); servers without constrained
output ignore the field, so the reply is validated whatever the server does: malformed JSON or an id that
is not listed is no answer. The system message is the same for every request while the categories do not
change (instruction, then the whole tree as `id | path` in a fixed order), so a server that caches a
prompt prefix processes only the entry's own text.

Nothing of the payload, the reply or the key is ever logged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.plugins.classifier import EntryInput
from app.core.plugins.model import CategoryPath, ModelAnswer, ModelUnavailable
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_of, user_message

log = logging.getLogger("ledgehog.model")

TIMEOUT_SECONDS = 30.0
RATIONALE_MAX = 120

INSTRUCTION = (
    "You categorise one bank transaction of a household's personal finances. "
    "Choose the single best category for the transaction below from the list, by its id. "
    "If none fits, or the text says too little, answer null for category_id. "
    "Never invent an id. "
    "Answer with a JSON object: category_id (the id, or null) and rationale "
    f"(one short line, at most {RATIONALE_MAX} characters, saying why)."
)


def system_message(categories: Sequence[CategoryPath]) -> str:
    """The same text for the same categories: sorted by path, then id."""
    ordered = sorted(categories, key=lambda c: (c.path, c.id))
    lines = "\n".join(f"{c.id} | {c.path}" for c in ordered)
    return f"{INSTRUCTION}\n\nCategories (id | path):\n{lines}"


def response_format(categories: Sequence[CategoryPath]) -> dict[str, Any]:
    ids: list[int | None] = [c.id for c in sorted(categories, key=lambda c: (c.path, c.id))]
    schema = {
        "type": "object",
        "properties": {
            "category_id": {"enum": [*ids, None]},
            "rationale": {"type": "string", "maxLength": RATIONALE_MAX},
        },
        "required": ["category_id", "rationale"],
        "additionalProperties": False,
    }
    return {"type": "json_schema", "json_schema": {"name": "category", "strict": True, "schema": schema}}


def parse_reply(content: object, categories: Sequence[CategoryPath]) -> tuple[int, str] | None:
    """The category id and rationale of a valid reply, else None (malformed, unknown id, or no category)."""
    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    category_id, rationale = data.get("category_id"), data.get("rationale")
    if not isinstance(rationale, str):
        return None
    if isinstance(category_id, bool) or not isinstance(category_id, int):
        return None  # null, "none", anything else: no answer
    if category_id not in {c.id for c in categories}:
        return None
    return category_id, " ".join(rationale.split())[:RATIONALE_MAX]


class OpenAIModelClient:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        base = endpoint.rstrip("/")
        self._url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        self.name = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(timeout=timeout, headers=headers, transport=transport)

    def fingerprint(self, entry: EntryInput) -> str | None:
        payload = payload_of(entry)
        return fingerprint_of(payload) if payload is not None else None

    def request_body(self, payload: dict[str, str], categories: Sequence[CategoryPath]) -> dict[str, Any]:
        return {
            "model": self.name,
            "temperature": 0,
            "max_tokens": 200,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_message(categories)},
                {"role": "user", "content": user_message(payload)},
            ],
            "response_format": response_format(categories),
        }

    async def ask(self, entry: EntryInput, categories: Sequence[CategoryPath]) -> ModelAnswer | None:
        payload = payload_of(entry)
        if payload is None or not categories:
            return None
        try:
            response = await self._http.post(self._url, json=self.request_body(payload, categories))
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelUnavailable(f"HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise ModelUnavailable(type(exc).__name__) from None
        except ValueError:
            return None  # a reply that is not JSON at all
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        parsed = parse_reply(content, categories)
        if parsed is None:
            return None
        return ModelAnswer(category_id=parsed[0], rationale=parsed[1], model=self.name)

    async def aclose(self) -> None:
        await self._http.aclose()
