"""Pass 3's client and classifier against a mock endpoint (never a real model)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest

from app.core.plugins.classifier import ClassifierContext, EntryInput
from app.core.plugins.model import CategoryPath, ModelUnavailable, NoAnswer
from app.core.resolution import Decided
from app.plugins.classifiers.llm import LlmClassifier, OpenAIModelClient
from app.plugins.classifiers.llm.client import RATIONALE_MAX, RATIONALE_MIN, parse_reply, system_message
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_of

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


CATEGORIES = [
    CategoryPath(3, "Expense > Travel > Tolls"),
    CategoryPath(1, "Expense > Food"),
    CategoryPath(2, "Income > Salary"),
]


def _entry(entry_id: int = 1, **kw: Any) -> EntryInput:
    return EntryInput(
        entry_id=entry_id,
        account_id=1,
        currency="EUR",
        booked_on=date(2026, 2, 10),
        amount=-500,
        **kw,
    )


class Endpoint:
    """A fake chat-completions server: records requests, answers with `reply` (content) or `status`."""

    def __init__(self, reply: object = None, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.reply = reply if reply is not None else {"category_id": 3, "rationale": "motorway toll"}
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, text="nope")
        content = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def body(self, i: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def _client(endpoint: Endpoint, key: str | None = None) -> OpenAIModelClient:
    return OpenAIModelClient(
        "http://model.test/v1/", "m-1", key, transport=httpx.MockTransport(endpoint), timeout=5
    )


async def test_the_request_has_a_stable_system_message_and_the_schema() -> None:
    endpoint = Endpoint()
    client = _client(endpoint, key="sekret")
    a = await client.ask(_entry(1, counterparty_name="AUCAT BAR"), CATEGORIES)
    await client.ask(_entry(2, counterparty_name="Other", purpose="x"), list(reversed(CATEGORIES)))
    assert a is not None and (a.category_id, a.rationale, a.model) == (3, "motorway toll", "m-1")

    first, second = endpoint.body(0), endpoint.body(1)
    assert str(endpoint.requests[0].url) == "http://model.test/v1/chat/completions"
    assert endpoint.requests[0].headers["authorization"] == "Bearer sekret"
    sys0, user0 = first["messages"]
    assert sys0["role"] == "system" and user0 == {"role": "user", "content": "counterparty: AUCAT BAR"}
    assert sys0 == second["messages"][0]  # identical for every entry: the server reuses its prefix
    assert sys0["content"] == system_message(CATEGORIES)
    lines = sys0["content"].splitlines()[-3:]
    assert lines == ["1 | Expense > Food", "3 | Expense > Travel > Tolls", "2 | Income > Salary"]

    fmt = first["response_format"]
    assert fmt["type"] == "json_schema"
    schema = fmt["json_schema"]["schema"]
    assert schema["properties"]["category_id"]["enum"] == [1, 3, 2, None]
    assert schema["properties"]["rationale"]["minLength"] == RATIONALE_MIN  # a reason is always required
    assert schema["properties"]["rationale"]["maxLength"] == RATIONALE_MAX
    assert first["model"] == "m-1" and first["temperature"] == 0 and first["stream"] is False
    await client.aclose()


async def test_no_authorization_header_without_a_key_and_a_full_url_is_kept() -> None:
    endpoint = Endpoint()
    client = OpenAIModelClient(
        "http://model.test/v1/chat/completions", "m", None, transport=httpx.MockTransport(endpoint)
    )
    await client.ask(_entry(counterparty_name="x"), CATEGORIES)
    assert "authorization" not in endpoint.requests[0].headers
    assert endpoint.requests[0].url.path == "/v1/chat/completions"
    await client.aclose()


async def test_an_empty_payload_is_not_asked() -> None:
    endpoint = Endpoint()
    client = _client(endpoint)
    assert await client.ask(_entry(counterparty_ref="DE89370400440532013000"), CATEGORIES) == NoAnswer(
        "empty_payload"
    )
    assert endpoint.requests == []
    await client.aclose()


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ("not json at all", "not_json"),
        ('["a"]', "not_object"),
        ({"category_id": 99, "rationale": "invented id"}, "unknown_id"),
        ({"category_id": None, "rationale": "  "}, "empty_rationale"),  # a "none" without what to show of it
        ({"category_id": None}, "no_rationale"),
        ({"category_id": "none", "rationale": "none fits"}, "bad_id_type"),
        ({"category_id": True, "rationale": "bool is not an id"}, "bad_id_type"),
        ({"category_id": 3}, "no_rationale"),
        ({"category_id": 3, "rationale": 7}, "no_rationale"),
    ],
)
async def test_an_invalid_reply_is_no_answer_with_its_reason(reply: object, reason: str) -> None:
    client = _client(Endpoint(reply))
    assert await client.ask(_entry(counterparty_name="x"), CATEGORIES) == NoAnswer(reason)
    await client.aclose()


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({"choices": []}, "not_json"),
        ({"choices": [{"message": {}}]}, "not_json"),
        ({"choices": [{"message": {"content": None}}]}, "not_json"),
        ({"error": "x"}, "not_json"),
        (
            {
                "choices": [
                    {
                        "message": {"content": '{"category_id": 3, "rationale": "mot'},
                        "finish_reason": "length",
                    }
                ]
            },
            "truncated",
        ),
    ],
)
async def test_a_reply_without_content_or_cut_off_is_no_answer(body: dict[str, Any], reason: str) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    client = OpenAIModelClient("http://model.test/v1", "m", None, transport=transport)
    assert await client.ask(_entry(counterparty_name="x"), CATEGORIES) == NoAnswer(reason)
    await client.aclose()


async def test_a_body_that_is_not_json_is_no_answer() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
    client = OpenAIModelClient("http://model.test/v1", "m", None, transport=transport)
    assert await client.ask(_entry(counterparty_name="x"), CATEGORIES) == NoAnswer("not_json")
    await client.aclose()


async def test_null_with_a_rationale_is_the_answer_that_no_category_fits() -> None:
    reply = {"category_id": None, "rationale": "a Catalan motorway toll; no category for tolls"}
    client = _client(Endpoint(reply))
    answer = await client.ask(_entry(counterparty_name="x"), CATEGORIES)
    assert answer is not None and answer.category_id is None
    assert answer.rationale == reply["rationale"] and answer.model == "m-1"
    await client.aclose()


def test_the_instruction_asks_for_what_would_fit_when_nothing_does() -> None:
    text = system_message(CATEGORIES)
    assert "answer null for category_id" in text and "what kind of category would fit" in text


def test_the_rationale_is_one_capped_line() -> None:
    parsed = parse_reply(json.dumps({"category_id": 1, "rationale": "a\nb  " + "x" * 500}), CATEGORIES)
    assert isinstance(parsed, tuple) and parsed[0] == 1
    assert "\n" not in parsed[1] and len(parsed[1]) == RATIONALE_MAX and parsed[1].startswith("a b ")


@pytest.mark.parametrize("status", [500, 401, 404])
async def test_an_http_error_is_unavailable(status: int) -> None:
    client = _client(Endpoint(status=status))
    with pytest.raises(ModelUnavailable):
        await client.ask(_entry(counterparty_name="x"), CATEGORIES)
    await client.aclose()


async def test_a_timeout_or_refused_connection_is_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    client = OpenAIModelClient("http://model.test/v1", "m", None, transport=httpx.MockTransport(boom))
    with pytest.raises(ModelUnavailable):
        await client.ask(_entry(counterparty_name="x"), CATEGORIES)
    await client.aclose()


# ---- the classifier reads the stored answer --------------------------------------------------------


def _stored(entry: EntryInput, value: int | None = 3) -> Decided:
    payload = payload_of(entry)
    assert payload is not None
    return Decided(value, "llm", {"model": "m", "rationale": "r", "fingerprint": fingerprint_of(payload)})


def test_the_classifier_proposes_the_stored_answer_while_the_payload_stands() -> None:
    entry = _entry(counterparty_name="AUCAT")
    stored = _stored(entry)
    p = LlmClassifier().propose("category", entry, ClassifierContext(stored={"category": stored}))
    assert p is not None and p.value == 3 and dict(p.basis) == dict(stored.basis)


def test_the_body_has_room_for_thinking_and_sends_the_reasoning_effort_only_when_set() -> None:
    plain = OpenAIModelClient("http://model.test/v1", "m")
    body = plain.request_body({"counterparty": "x"}, CATEGORIES)
    assert body["max_tokens"] == 1024 and "reasoning_effort" not in body
    effort = OpenAIModelClient("http://model.test/v1", "m", reasoning_effort="low")
    assert effort.request_body({"counterparty": "x"}, CATEGORIES)["reasoning_effort"] == "low"


def test_the_classifier_proposes_the_stored_absence_while_the_payload_stands() -> None:
    entry = _entry(counterparty_name="AUCAT")
    stored = _stored(entry, None)
    ctx = ClassifierContext(stored={"category": stored})
    p = LlmClassifier().propose("category", entry, ctx)
    assert p is not None and p.value is None and p.basis["fingerprint"] == stored.basis["fingerprint"]
    assert LlmClassifier().propose("category", _entry(counterparty_name="AUCAT", purpose="new"), ctx) is None


def test_the_classifier_proposes_nothing_otherwise() -> None:
    clf = LlmClassifier()
    entry = _entry(counterparty_name="AUCAT")
    stored = _stored(entry)
    ctx = ClassifierContext(stored={"category": stored})
    assert clf.propose("payee", entry, ctx) is None
    assert clf.propose("type", entry, ctx) is None
    assert clf.propose("category", entry, ClassifierContext()) is None  # nothing stored
    changed = _entry(counterparty_name="AUCAT", purpose="new")
    assert clf.propose("category", changed, ctx) is None  # the payload changed
    other = ClassifierContext(stored={"category": Decided(3, "history", dict(stored.basis))})
    assert clf.propose("category", entry, other) is None  # not the model's key
