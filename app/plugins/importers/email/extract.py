"""Extraction by the model (spec/plugins/importers/email.md §5, §8).

The text is read by the deployment's model with a strict `json_schema`; where it yields no document, each
PDF's page images go to the vision model without a schema (constrained decoding made a vision model loop),
whose reply is parsed tolerantly. The model extracts and never classifies; whether the answer is a document
is the builder's call, handed in as `accept`. Nothing of a message, a reply or a key is ever logged.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2

from app.core.plugins.errors import SourceUnavailable
from app.plugins.chat_completions import auth_headers, chat_url, reasoning_field
from app.plugins.importers.email.extractor import (
    MODEL_REFUSED,
    NO_CONTENT,
    PDF_NOT_READ,
    UNREADABLE,
    AttemptFailed,
    Extraction,
    Skipped,
)
from app.plugins.importers.email.message import PdfPart
from app.plugins.importers.email.pdf import render_pdf

log = logging.getLogger("ledgehog.email")

TEXT_MAX_TOKENS = 8192  # room for a reasoning model's thinking, besides the answer
VISION_MAX_TOKENS = 2048  # an answer is a few hundred tokens: a model that loops fails fast
CONNECT_TIMEOUT_S = 10.0
TEXT_TIMEOUT_S = 120.0
VISION_TIMEOUT_S = 300.0

REFUSED_STATUSES = frozenset({400, 413, 422})  # the model refuses this one request
UNAVAILABLE_STATUSES = frozenset({401, 403, 404, 429})  # the model cannot be used at all

_FIELDS = (
    "merchant is the seller, as the source names it. "
    "order_id is the order, invoice or booking number. "
    "total is the amount the customer pays in total, shipping, fees and taxes included, as a positive number "
    "with a dot as decimal separator. "
    "currency is the total's ISO 4217 code. "
    "refund is true where the amount is returned to the customer or no longer charged (a refund, a credit "
    "note, a cancellation), else false. "
    "items lists every line that makes up the total, so that their amounts add up to it: each article, "
    "shipping, fees, taxes added on top, and discounts and vouchers as negative amounts. Each item has name "
    "(the line's description), quantity (as shown) and amount: the line's total (quantity times unit price), "
    "never the unit price."
)
_SHARED = (
    "Extract the purchase or payment data of the source, whatever kind of document it is: an order "
    "confirmation, an invoice, a rental agreement. Extract, do not classify: do not judge what the document "
    "is; "
    "where it states no purchase or payment, set every field to null (refund false, items null). "
    + _FIELDS
    + " Use null for what the source does not say. Never invent values."
)
TEXT_INSTRUCTION = (
    "You read one email, given as plain text rendered from its HTML: table cells are separated by tabs, "
    "images appear as [alt text], superscript is marked with ^ and subscript with _ (43^55^EUR is 43.55 EUR: "
    "a price whose cents are set in superscript). " + _SHARED
)
VISION_INSTRUCTION = (
    "You are given the page images of a document attached to an email, in page order. "
    + _SHARED
    + " The JSON object has exactly these keys: merchant (string or null), order_id (string or null), total "
    "(number or null), currency (string or null), refund (true or false), items (array or null) of objects "
    "with name (string), quantity (number or null) and amount (number or null). "
    "Answer with the JSON object only, no code fences or other text."
)

_NUMBER = {"type": ["number", "null"]}
_STRING = {"type": ["string", "null"]}
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "merchant": _STRING,
        "order_id": _STRING,
        "total": _NUMBER,
        "currency": _STRING,
        "refund": {"type": "boolean"},
        "items": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "quantity": _NUMBER, "amount": _NUMBER},
                "required": ["name", "quantity", "amount"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["merchant", "order_id", "total", "currency", "refund", "items"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One model endpoint, as plain values (the composition root unwraps the configuration's secrets)."""

    endpoint: str
    name: str
    api_key: str | None = None
    reasoning_effort: str | None = None


# ---- the reply --------------------------------------------------------------------------------------


def _loads_tolerant(content: str) -> Any:
    """The JSON of the content minus a surrounding code fence; else of the first `{` to the last `}`."""
    text = content.strip()
    if fenced := re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.S | re.I):
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def validate_answer(data: object) -> dict[str, Any] | None:
    """The answer in the shape of §5, or None where it is not of that shape. A missing key is null (`refund`:
    false), so a model that leaves out what it has not got is not refused; a wrong type is no answer."""
    if not isinstance(data, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("merchant", "currency"):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            return None
        out[key] = value
    order_id = data.get("order_id")
    if isinstance(order_id, int) and not isinstance(order_id, bool):
        order_id = str(order_id)  # a number the model did not quote
    if order_id is not None and not isinstance(order_id, str):
        return None
    out["order_id"] = order_id
    total = data.get("total")
    if total is not None and not _number(total):
        return None
    out["total"] = total
    refund = data.get("refund", False)
    if not isinstance(refund, bool):
        return None
    out["refund"] = refund
    items = data.get("items")
    if items is not None:
        if not isinstance(items, list):
            return None
        checked: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                return None
            quantity, amount = item.get("quantity"), item.get("amount")
            for number in (quantity, amount):
                if number is not None and not _number(number):
                    return None
            checked.append({"name": item["name"], "quantity": quantity, "amount": amount})
        items = checked
    out["items"] = items
    return out


def parse_reply(body: object) -> dict[str, Any] | None:
    """The validated answer of a chat-completions reply; None where there is none: no content, cut off at
    `max_tokens`, not JSON, not an object, not of the shape."""
    try:
        choice = body["choices"][0]  # type: ignore[index]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(content, str) or choice.get("finish_reason") == "length":
        return None
    try:
        return validate_answer(_loads_tolerant(content))
    except ValueError:
        return None


# ---- the extractor ----------------------------------------------------------------------------------


class _Endpoint:
    def __init__(self, spec: ModelSpec, timeout_s: float, transport: httpx2.BaseTransport | None) -> None:
        self.spec = spec
        self.url = chat_url(spec.endpoint)
        self.timeout = httpx2.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        self.http = httpx2.Client(headers=auth_headers(spec.api_key), transport=transport)


class ModelExtractor:
    """Satisfies `Extractor`: the text model, and the vision model where one is configured."""

    def __init__(
        self,
        text_model: ModelSpec,
        vision_model: ModelSpec | None = None,
        *,
        transport: httpx2.BaseTransport | None = None,
        vision_transport: httpx2.BaseTransport | None = None,
        render: Callable[[bytes], list[bytes]] = render_pdf,
    ) -> None:
        self._text = _Endpoint(text_model, TEXT_TIMEOUT_S, transport)
        self._vision = (
            _Endpoint(vision_model, VISION_TIMEOUT_S, vision_transport or transport) if vision_model else None
        )
        self._render = render

    def close(self) -> None:
        self._text.http.close()
        if self._vision is not None:
            self._vision.http.close()

    # -- requests -----------------------------------------------------------------------------------

    def text_request(self, text: str) -> dict[str, Any]:
        return {
            "model": self._text.spec.name,
            "temperature": 0,
            "max_tokens": TEXT_MAX_TOKENS,
            "stream": False,
            "messages": [
                {"role": "system", "content": TEXT_INSTRUCTION},
                {"role": "user", "content": text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "receipt", "strict": True, "schema": ANSWER_SCHEMA},
            },
            **reasoning_field(self._text.spec.reasoning_effort),
        }

    def vision_request(self, images: Sequence[bytes]) -> dict[str, Any]:
        assert self._vision is not None
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": f"Extract the purchase data from these {len(images)} page image(s)."}
        ]
        for image in images:
            url = f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
        return {  # no schema, and no reasoning effort
            "model": self._vision.spec.name,
            "temperature": 0,
            "max_tokens": VISION_MAX_TOKENS,
            "stream": False,
            "messages": [
                {"role": "system", "content": VISION_INSTRUCTION},
                {"role": "user", "content": parts},
            ],
        }

    # -- asking -------------------------------------------------------------------------------------

    def _ask(self, endpoint: _Endpoint, request: dict[str, Any], model: str) -> Extraction | Skipped:
        """One request, never retried. Errors are mapped per §8; nothing of the request or reply is logged."""
        try:
            response = endpoint.http.post(endpoint.url, json=request, timeout=endpoint.timeout)
        except (httpx2.ConnectError, httpx2.ConnectTimeout) as exc:  # nothing was sent
            raise SourceUnavailable("the model could not be reached") from exc
        except httpx2.TransportError as exc:  # sent, and no reply: a time-out, a dropped connection
            raise AttemptFailed(f"the model did not answer ({type(exc).__name__})") from None
        status = response.status_code
        if status in UNAVAILABLE_STATUSES:
            raise SourceUnavailable(f"the model refused the request: HTTP {status}")
        if status in REFUSED_STATUSES:
            log.info("the model refused a request: HTTP %s", status)
            return Skipped(MODEL_REFUSED)
        if status >= 500:
            raise AttemptFailed(f"the model failed: HTTP {status}")
        if status >= 400:
            raise SourceUnavailable(f"the model refused the request: HTTP {status}")
        try:
            body = response.json()
        except ValueError:
            return Skipped(UNREADABLE)
        answer = parse_reply(body)
        return Skipped(UNREADABLE) if answer is None else Extraction(answer, "text", None, model)

    def _ask_text(self, text: str) -> Extraction | Skipped:
        return self._ask(self._text, self.text_request(text), self._text.spec.name)

    def _ask_pdf(self, pdf: PdfPart) -> Extraction | Skipped | None:
        """None where the PDF does not render: it is passed over."""
        assert self._vision is not None
        try:
            images = self._render(pdf.data)
        except Exception as exc:  # whatever the renderer raises for a PDF it cannot read
            log.info("a PDF did not render: %s", type(exc).__name__)
            return None
        if not images:
            return None
        result = self._ask(self._vision, self.vision_request(images), self._vision.spec.name)
        if isinstance(result, Extraction):
            return Extraction(result.answer, "pdf", pdf.name, result.model)
        return result

    def extract(
        self,
        text: str | None,
        pdfs: Sequence[PdfPart],
        *,
        accept: Callable[[Extraction], bool] = lambda extraction: True,
    ) -> Extraction | Skipped:
        first: Extraction | None = None  # the first answer read, for the builder to say why it is no document
        failure: Skipped | None = None
        if text is not None:
            result = self._ask_text(text)
            if isinstance(result, Extraction):
                if accept(result):
                    return result
                first = result
            else:
                failure = result
        if pdfs:
            if self._vision is None:
                return Skipped(PDF_NOT_READ)
            for pdf in pdfs:
                result_pdf = self._ask_pdf(pdf)
                if isinstance(result_pdf, Extraction):
                    if accept(result_pdf):
                        return result_pdf
                    first = first or result_pdf
                elif result_pdf is not None:
                    failure = failure or result_pdf
        return first or failure or Skipped(NO_CONTENT)
