"""The model extractor against fake endpoints (never a real model): request shapes, tolerant parse, error
mapping, text first then each PDF."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.core.plugins.errors import SourceUnavailable
from app.plugins.importers.email.extract import (
    ANSWER_SCHEMA,
    ModelExtractor,
    ModelSpec,
    parse_reply,
    validate_answer,
)
from app.plugins.importers.email.extractor import AttemptFailed, Extraction, Skipped
from app.plugins.importers.email.message import PdfPart

ANSWER = {
    "merchant": "Shop",
    "order_id": "A-1",
    "total": 10.5,
    "currency": "EUR",
    "refund": False,
    "items": [{"name": "Thing", "quantity": 1, "amount": 10.5}],
}
PNG = b"\x89PNG\r\n\x1a\nfake"


class Endpoint:
    """A fake chat-completions server: records requests; answers `reply` (an object, or content text), a
    status, or raises."""

    def __init__(self, reply: object = ANSWER, status: int = 200, finish: str = "stop") -> None:
        self.requests: list[httpx2.Request] = []
        self.reply = reply
        self.status = status
        self.finish = finish
        self.raises: Exception | None = None
        self.replies: list[object] = []  # one per request, before `reply` applies

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        if self.status != 200:
            return httpx2.Response(self.status, text="nope: secret text")
        reply = self.replies.pop(0) if self.replies else self.reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        body = {"choices": [{"message": {"content": content}, "finish_reason": self.finish}]}
        return httpx2.Response(200, json=body)

    def body(self, i: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def fake_render(data: bytes) -> list[bytes]:
    return [PNG, PNG]


def extractor(
    text: Endpoint,
    vision: Endpoint | None = None,
    *,
    render: Callable[[bytes], list[bytes]] = fake_render,
    effort: str | None = "low",
) -> ModelExtractor:
    return ModelExtractor(
        ModelSpec("http://text.test/v1/", "text-1", "tkey", effort),
        ModelSpec("http://vision.test/v1", "vision-1", "vkey") if vision else None,
        transport=httpx2.MockTransport(text),
        vision_transport=httpx2.MockTransport(vision) if vision else None,
        render=render,
    )


PDFS = (PdfPart("a.pdf", b"A"), PdfPart("b.pdf", b"B"))


def never(_: Extraction) -> bool:
    return False


# ---- the requests -----------------------------------------------------------------------------------


def test_the_text_request_carries_the_strict_schema_the_effort_and_the_timeouts():
    endpoint = Endpoint()
    result = extractor(endpoint).extract("Order 1\t10,50", ())
    assert isinstance(result, Extraction) and result.answer == ANSWER
    assert (result.source, result.pdf, result.model) == ("text", None, "text-1")
    request = endpoint.requests[0]
    assert str(request.url) == "http://text.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer tkey"
    body = endpoint.body()
    assert (body["model"], body["temperature"], body["max_tokens"], body["stream"]) == (
        "text-1",
        0,
        8192,
        False,
    )
    assert body["reasoning_effort"] == "low"
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "receipt", "strict": True, "schema": ANSWER_SCHEMA},
    }
    system, user = body["messages"]
    assert system["role"] == "system" and "^" in system["content"] and "tab" in system["content"]
    assert "never invent" in system["content"].lower() and "do not classify" in system["content"].lower()
    assert user == {"role": "user", "content": "Order 1\t10,50"}
    assert request.extensions["timeout"] == {"connect": 10.0, "read": 120.0, "write": 120.0, "pool": 120.0}


def test_no_effort_is_not_sent():
    endpoint = Endpoint()
    extractor(endpoint, effort=None).extract("x", ())
    assert "reasoning_effort" not in endpoint.body()


def test_the_schema_holds_exactly_the_fields_of_the_spec_and_no_date_or_receipt_flag():
    props = ANSWER_SCHEMA["properties"]
    assert set(props) == {"merchant", "order_id", "total", "currency", "refund", "items"}
    assert set(ANSWER_SCHEMA["required"]) == set(props)
    assert set(props["items"]["items"]["properties"]) == {"name", "quantity", "amount"}


def test_the_vision_request_has_images_and_no_schema_no_effort_and_a_small_budget():
    text, vision = Endpoint(), Endpoint()
    result = extractor(text, vision).extract(None, PDFS[:1])
    assert isinstance(result, Extraction) and (result.source, result.pdf, result.model) == (
        "pdf",
        "a.pdf",
        "vision-1",
    )
    assert text.requests == []
    request = vision.requests[0]
    assert str(request.url) == "http://vision.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer vkey"
    body = vision.body()
    assert "response_format" not in body and "reasoning_effort" not in body
    assert (body["model"], body["temperature"], body["max_tokens"]) == ("vision-1", 0, 2048)
    system, user = body["messages"]
    for key in ("merchant", "order_id", "total", "currency", "refund", "items", "quantity", "amount"):
        assert key in system["content"]
    assert "no code fences" in system["content"]
    images = [p["image_url"]["url"] for p in user["content"] if p["type"] == "image_url"]
    assert len(images) == 2
    assert all(base64.b64decode(u.removeprefix("data:image/png;base64,")) == PNG for u in images)
    assert request.extensions["timeout"]["read"] == 300.0 and request.extensions["timeout"]["connect"] == 10.0


def test_the_vision_model_without_its_own_key_sends_no_authorization():
    vision = Endpoint()
    ModelExtractor(
        ModelSpec("http://t/v1", "t"),
        ModelSpec("http://v/v1", "v"),
        transport=httpx2.MockTransport(Endpoint()),
        vision_transport=httpx2.MockTransport(vision),
        render=fake_render,
    ).extract(None, PDFS[:1])
    assert "authorization" not in vision.requests[0].headers


# ---- the reply --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        "```json\n" + json.dumps(ANSWER) + "\n```",
        "```\n" + json.dumps(ANSWER) + "\n```",
        "Here you go: " + json.dumps(ANSWER) + " Hope that helps.",
        "  " + json.dumps(ANSWER) + "  ",
    ],
)
def test_a_reply_is_parsed_tolerantly(content: str):
    result = extractor(Endpoint(content)).extract("x", ())
    assert isinstance(result, Extraction) and result.answer == ANSWER


@pytest.mark.parametrize(
    "reply",
    [
        "no json here",
        "{broken",
        "[1, 2]",
        json.dumps("a string"),
        {**ANSWER, "total": "10.50"},  # a number as text
        {**ANSWER, "total": True},
        {**ANSWER, "refund": "no"},
        {**ANSWER, "merchant": 7},
        {**ANSWER, "items": "none"},
        {**ANSWER, "items": [{"name": None, "quantity": 1, "amount": 1}]},
        {**ANSWER, "items": [{"name": "x", "quantity": "1", "amount": 1}]},
        {**ANSWER, "items": [{"name": "x", "quantity": 1, "amount": "1"}]},
        {**ANSWER, "items": ["x"]},
        '{"total": NaN}',
    ],
)
def test_a_reply_that_is_not_the_shape_is_unreadable(reply: object):
    assert extractor(Endpoint(reply)).extract("x", ()) == Skipped("unreadable")


def test_a_reply_cut_off_at_max_tokens_is_unreadable_even_where_it_parses():
    assert extractor(Endpoint(ANSWER, finish="length")).extract("x", ()) == Skipped("unreadable")


def test_a_body_without_content_or_not_json_is_unreadable():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>")

    model = ModelExtractor(ModelSpec("http://t/v1", "t"), transport=httpx2.MockTransport(handler))
    assert model.extract("x", ()) == Skipped("unreadable")
    assert parse_reply({"choices": []}) is None
    assert parse_reply({"choices": [{"message": {"content": None}}]}) is None
    assert parse_reply("nope") is None


def test_an_unreadable_reply_is_never_retried():
    endpoint = Endpoint("nonsense")
    extractor(endpoint).extract("x", ())
    assert len(endpoint.requests) == 1


def test_a_missing_key_is_null_and_a_quoted_number_order_id_is_a_string():
    answer = validate_answer({"merchant": "Shop", "total": 3, "order_id": 12345})
    assert answer == {
        "merchant": "Shop",
        "order_id": "12345",
        "total": 3,
        "currency": None,
        "refund": False,
        "items": None,
    }
    assert validate_answer({"order_id": 1.5}) is None


# ---- errors -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_a_model_that_refuses_us_fails_the_run_and_counts_no_attempt(status: int):
    endpoint = Endpoint(status=status)
    with pytest.raises(SourceUnavailable) as caught:
        extractor(endpoint).extract("secret receipt text", ())
    assert type(caught.value) is SourceUnavailable  # not AttemptFailed: `stuck` counts nothing
    assert f"HTTP {status}" in str(caught.value)
    assert "secret" not in str(caught.value) and "tkey" not in str(caught.value)


@pytest.mark.parametrize("error", [httpx2.ConnectError("refused"), httpx2.ConnectTimeout("slow")])
def test_a_model_that_cannot_be_reached_fails_the_run_and_counts_no_attempt(error: Exception):
    endpoint = Endpoint()
    endpoint.raises = error
    with pytest.raises(SourceUnavailable) as caught:
        extractor(endpoint).extract("x", ())
    assert type(caught.value) is SourceUnavailable and "could not be reached" in str(caught.value)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_5xx_after_the_request_was_sent_is_an_attempt_that_failed(status: int):
    with pytest.raises(AttemptFailed):
        extractor(Endpoint(status=status)).extract("x", ())


@pytest.mark.parametrize(
    "error",
    [
        httpx2.ReadTimeout("t"),
        httpx2.WriteTimeout("t"),
        httpx2.RemoteProtocolError("dropped"),
        httpx2.ReadError("r"),
    ],
)
def test_a_time_out_or_a_dropped_connection_after_sending_is_an_attempt_that_failed(error: Exception):
    endpoint = Endpoint()
    endpoint.raises = error
    with pytest.raises(AttemptFailed):
        extractor(endpoint).extract("x", ())


@pytest.mark.parametrize("status", [400, 413, 422])
def test_a_request_the_model_refuses_skips_the_message(status: int):
    assert extractor(Endpoint(status=status)).extract("x", ()) == Skipped("model_refused")


def test_another_4xx_is_a_model_that_refuses_us():
    with pytest.raises(SourceUnavailable) as caught:
        extractor(Endpoint(status=418)).extract("x", ())
    assert type(caught.value) is SourceUnavailable


def test_a_failing_vision_request_maps_the_same_way():
    vision = Endpoint(status=503)
    with pytest.raises(AttemptFailed):
        extractor(Endpoint(), vision).extract(None, PDFS[:1])
    assert extractor(Endpoint(), Endpoint(status=422)).extract(None, PDFS[:1]) == Skipped("model_refused")


# ---- text first, then each PDF ----------------------------------------------------------------------


def test_an_accepted_text_answer_never_reaches_the_vision_model():
    vision = Endpoint()
    result = extractor(Endpoint(), vision).extract("x", PDFS)
    assert isinstance(result, Extraction) and result.source == "text"
    assert vision.requests == []


def test_where_the_text_yields_no_document_each_pdf_is_asked_in_turn_until_one_does():
    text, vision = Endpoint(), Endpoint()
    vision.replies = [{**ANSWER, "total": None}, ANSWER]
    rendered: list[bytes] = []

    def render(data: bytes) -> list[bytes]:
        rendered.append(data)
        return [PNG]

    def accept(extraction: Extraction) -> bool:
        return extraction.answer["total"] is not None and extraction.source == "pdf"

    result = extractor(text, vision, render=render).extract(
        "x", (*PDFS, PdfPart("c.pdf", b"C")), accept=accept
    )
    assert isinstance(result, Extraction) and (result.source, result.pdf) == ("pdf", "b.pdf")
    assert len(text.requests) == 1 and len(vision.requests) == 2 and rendered == [b"A", b"B"]


def test_where_nothing_yields_a_document_the_first_answer_read_goes_to_the_builder_for_its_reason():
    result = extractor(Endpoint(), Endpoint({**ANSWER, "merchant": "Other"})).extract("x", PDFS, accept=never)
    assert isinstance(result, Extraction) and result.source == "text" and result.answer["merchant"] == "Shop"


def test_without_a_text_answer_the_first_pdf_answer_is_returned_when_none_is_accepted():
    vision = Endpoint()
    vision.replies = [{**ANSWER, "merchant": "First"}, {**ANSWER, "merchant": "Second"}]
    result = extractor(Endpoint(), vision).extract(None, PDFS, accept=never)
    assert isinstance(result, Extraction) and result.answer["merchant"] == "First"


def test_without_a_vision_model_a_pdf_is_never_read_and_the_message_counts_as_pdf_not_read():
    text = Endpoint({**ANSWER, "total": None})
    assert extractor(text).extract("x", PDFS, accept=never) == Skipped("pdf_not_read")
    assert extractor(text).extract(None, PDFS) == Skipped("pdf_not_read")
    # an accepted text answer wins, whatever PDFs there are
    assert isinstance(extractor(Endpoint()).extract("x", PDFS), Extraction)


def test_text_that_is_unreadable_falls_back_to_the_pdf():
    text = Endpoint("nonsense")
    result = extractor(text, Endpoint()).extract("x", PDFS[:1])
    assert isinstance(result, Extraction) and result.source == "pdf"


def test_a_pdf_that_does_not_render_is_passed_over():
    vision = Endpoint()

    def render(data: bytes) -> list[bytes]:
        if data == b"A":
            raise ValueError("broken pdf")
        return [PNG]

    result = extractor(Endpoint(), vision, render=render).extract(None, PDFS)
    assert isinstance(result, Extraction) and result.pdf == "b.pdf" and len(vision.requests) == 1
    assert extractor(Endpoint(), vision, render=lambda d: []).extract(None, PDFS) == Skipped("no_content")


def test_unreadable_pdf_answers_with_nothing_else_are_unreadable():
    assert extractor(Endpoint(), Endpoint("nonsense")).extract(None, PDFS[:1]) == Skipped("unreadable")


def test_nothing_to_read_is_no_content():
    assert extractor(Endpoint()).extract(None, ()) == Skipped("no_content")


# ---- a real rendering -------------------------------------------------------------------------------


def test_a_generated_pdf_is_rendered_to_grayscale_png_pages_within_the_limits():
    import io
    import struct
    import zlib

    pypdfium2 = pytest.importorskip("pypdfium2")
    from app.plugins.importers.email.pdf import MAX_PAGES, MAX_SIDE, render_pdf, render_scale

    pdf = pypdfium2.PdfDocument.new()
    for _ in range(6):
        pdf.new_page(595, 842)  # A4 in points: 150 DPI would be 1754 px high
    pdf.new_page(1500, 100)  # not reached: only four pages are read
    buffer = io.BytesIO()
    pdf.save(buffer)
    pdf.close()
    images = render_pdf(buffer.getvalue())
    assert len(images) == MAX_PAGES
    first = images[0]
    assert first.startswith(b"\x89PNG\r\n\x1a\n")
    width, height, depth, colour = struct.unpack(">IIBB", first[16:26])
    assert (depth, colour) == (8, 0)  # 8-bit grayscale
    assert (width, abs(height - 842 * 150 / 72) < 2) == (round(595 * 150 / 72), True)
    assert max(width, height) <= MAX_SIDE
    # the stream decodes to height rows of a filter byte and `width` pixels
    idat = first.index(b"IDAT")
    length = struct.unpack(">I", first[idat - 4 : idat])[0]
    assert len(zlib.decompress(first[idat + 4 : idat + 4 + length])) == height * (width + 1)
    assert render_scale(595, 3000) == MAX_SIDE / 3000  # a long page is scaled down to the limit
    assert render_scale(100, 100) == 150 / 72
