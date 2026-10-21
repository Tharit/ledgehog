"""The OpenAI chat-completions client for pass 3 (architecture §5.4).

One request per entry, `temperature` 0, structured output: `response_format` of type `json_schema` whose
`category_id` is one of the listed ids or null, plus a one-line rationale. llama.cpp's server accepts the
OpenAI form (`json_schema.schema`) and its own (`schema` beside `type`); servers without constrained
output ignore the field, so the reply is validated whatever the server does: malformed JSON or an id that
is not listed is no answer; null with a rationale is the answer "no category fits". The system message is
the same for every request while the categories do not change (instruction, then the whole tree as
`id | path` in a fixed order), so a server that caches a prompt prefix processes only the entry's own text.

Nothing of the payload, the reply or the key is ever logged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.plugins.classifier import EntryInput
from app.core.plugins.model import CategoryPath, ModelAnswer, ModelUnavailable, NoAnswer
from app.plugins.classifiers.llm.payload import payload_fingerprint, payload_of, user_message

log = logging.getLogger("ledgehog.model")

TIMEOUT_SECONDS = 30.0
RATIONALE_MIN = 3
RATIONALE_MAX = 120

INSTRUCTION = (
    "You categorise one bank transaction of a household's personal finances. "
    "Choose the single best category for the transaction below from the list, by its id. "
    "If no listed category fits, or the text says too little, answer null for category_id; "
    "then the rationale says what the transaction is and what kind of category would fit it, "
    'for example "a Catalan motorway toll; there is no category for tolls". '
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
            "rationale": {"type": "string", "minLength": RATIONALE_MIN, "maxLength": RATIONALE_MAX},
        },
        "required": ["category_id", "rationale"],
        "additionalProperties": False,
    }
    return {"type": "json_schema", "json_schema": {"name": "category", "strict": True, "schema": schema}}


def parse_reply(content: object, categories: Sequence[CategoryPath]) -> tuple[int | None, str] | NoAnswer:
    """The category id (None: the model says no category fits) and rationale of a valid reply, else the
    reason it is no answer: `not_json`, `not_object`, `no_rationale` (missing or not text),
    `empty_rationale` (a "none" without the rationale that is all there is to show of it), `bad_id_type`
    (the string "none", a bool, anything but an integer or null) or `unknown_id`."""
    if not isinstance(content, str):
        return NoAnswer("not_json")
    try:
        data = json.loads(content)
    except ValueError:
        return NoAnswer("not_json")
    if not isinstance(data, dict):
        return NoAnswer("not_object")
    category_id, rationale = data.get("category_id"), data.get("rationale")
    if not isinstance(rationale, str):
        return NoAnswer("no_rationale")
    line = " ".join(rationale.split())[:RATIONALE_MAX]
    if category_id is None:
        return (None, line) if line else NoAnswer("empty_rationale")
    if isinstance(category_id, bool) or not isinstance(category_id, int):
        return NoAnswer("bad_id_type")
    if category_id not in {c.id for c in categories}:
        return NoAnswer("unknown_id")
    return category_id, line


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
        return payload_fingerprint(entry)

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

    async def ask(self, entry: EntryInput, categories: Sequence[CategoryPath]) -> ModelAnswer | NoAnswer:
        payload = payload_of(entry)
        if payload is None:
            return NoAnswer("empty_payload")
        if not categories:
            return NoAnswer("no_categories")
        try:
            response = await self._http.post(self._url, json=self.request_body(payload, categories))
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelUnavailable(f"HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise ModelUnavailable(type(exc).__name__) from None
        except ValueError:
            return NoAnswer("not_json")  # a reply that is not JSON at all
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return NoAnswer("not_json")  # no choices[0].message.content
        if isinstance(choice, dict) and choice.get("finish_reason") == "length":
            return NoAnswer("truncated")  # cut off at max_tokens: whatever is there is not the whole reply
        parsed = parse_reply(content, categories)
        if isinstance(parsed, NoAnswer):
            return parsed
        return ModelAnswer(category_id=parsed[0], rationale=parsed[1], model=self.name)

    async def aclose(self) -> None:
        await self._http.aclose()
