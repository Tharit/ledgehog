"""The hand-written multipart/form-data parser of the upload route (RFC 2046 framing)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import pytest

from app.core.plugins.importer import DryRunReport, ParsedFile
from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api, error_of

api = h.api
make_api = h.make_api

B = "XbndX"
PAYLOAD = b"a;b\r\n1;2\r\n"


class Stub:
    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        return None

    def parse(self, data: bytes, profile: Mapping[str, Any], **kw: Any) -> ParsedFile:
        self.seen.append(data)
        return ParsedFile((), None, None, date(2026, 8, 10), None, {}, DryRunReport())


@pytest.fixture
def world(make_api):
    stub = Stub()
    api = make_api(importers={"csv": stub})
    inst, acct = api.world()
    return api, stub, inst, acct


def form(
    acct: int, file_part: bytes, *, boundary: str = B, close: bool = True, pre: bytes = b"", post: bytes = b""
):
    parts = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="account_id"\r\n\r\n{acct}\r\n'.encode()
        + f'--{boundary}\r\nContent-Disposition: form-data; name="dry_run"\r\n\r\ntrue\r\n'.encode()
        + file_part
    )
    return pre + parts + (f"--{boundary}--\r\n".encode() if close else b"") + post


def file_part(content: bytes, *, boundary: str = B, disposition: bytes | None = None) -> bytes:
    cd = (
        disposition
        if disposition is not None
        else b'Content-Disposition: form-data; name="file"; filename="a.csv"'
    )
    return (
        b"--" + boundary.encode() + b"\r\n" + cd + b"\r\nContent-Type: text/csv\r\n\r\n" + content + b"\r\n"
    )


def post(api: Api, inst: int, body: bytes, *, boundary: str = B, quoted: bool = False):
    value = f'"{boundary}"' if quoted else boundary
    return api.client.post(
        f"/api/importers/instances/{inst}/upload",
        content=body,
        headers={"content-type": f"multipart/form-data; boundary={value}"},
    )


def _file_only(acct: int, content: bytes, **kw: Any) -> bytes:
    full = form(acct, b"", **kw)  # the two fields, then (optionally) the closing delimiter
    head, sep, tail = (
        full.rpartition(f"--{kw.get('boundary', B)}--".encode())
        if kw.get("close", True)
        else (full, b"", b"")
    )
    return head + file_part(content, boundary=kw.get("boundary", B)) + sep + tail


def test_a_well_formed_body_is_accepted(world):
    api, stub, inst, acct = world
    r = post(api, inst, _file_only(acct, PAYLOAD))
    assert r.status_code == 200, r.text
    assert stub.seen == [PAYLOAD]


def test_a_quoted_boundary_is_accepted(world):
    api, stub, inst, acct = world
    assert post(api, inst, _file_only(acct, PAYLOAD), quoted=True).status_code == 200
    assert stub.seen == [PAYLOAD]


@pytest.mark.parametrize(
    "name",
    ["my file.csv", 'quo"te.csv', "ümlaut-€.csv"],
)
def test_odd_filenames_are_accepted(world, name: str):
    api, stub, inst, acct = world
    cd = b'Content-Disposition: form-data; name="file"; filename="' + name.replace('"', '\\"').encode() + b'"'
    body = form(acct, file_part(PAYLOAD, disposition=cd))
    assert post(api, inst, body).status_code == 200
    assert stub.seen == [PAYLOAD]


def test_lf_only_framing_is_refused(world):
    api, stub, inst, acct = world
    body = _file_only(acct, PAYLOAD).replace(b"\r\n", b"\n")
    error_of(post(api, inst, body), 422, "validation_error")
    assert stub.seen == []


def test_a_truncated_body_is_refused(world):
    api, stub, inst, acct = world
    whole = _file_only(acct, PAYLOAD * 5)
    cut = whole[: whole.index(b"1;2") + 4]
    err = error_of(post(api, inst, cut), 422, "validation_error")
    assert "malformed multipart body" in str(err["details"])
    assert stub.seen == []


def test_a_body_without_the_closing_delimiter_is_refused(world):
    api, stub, inst, acct = world
    err = error_of(post(api, inst, _file_only(acct, PAYLOAD, close=False)), 422, "validation_error")
    assert "malformed multipart body" in str(err["details"])
    assert stub.seen == []


def test_boundary_text_inside_a_line_of_the_content_is_content(world):
    api, stub, inst, acct = world
    content = f"a;b\r\nx --{B} y\r\n--{B}extra;1\r\nlast".encode()
    assert post(api, inst, _file_only(acct, content)).status_code == 200
    assert stub.seen == [content]


def test_an_epilogue_is_ignored(world):
    api, stub, inst, acct = world
    body = _file_only(acct, PAYLOAD, post=b"epilogue text\r\n--more")
    assert post(api, inst, body).status_code == 200
    assert stub.seen == [PAYLOAD]


def test_a_preamble_is_refused(world):
    # python-multipart does not skip a preamble (RFC 2046 allows one; no browser or client sends it)
    api, stub, inst, acct = world
    body = _file_only(acct, PAYLOAD, pre=b"this is a preamble\r\n")
    error_of(post(api, inst, body), 422, "validation_error")
    assert stub.seen == []


def test_an_empty_file_part_reaches_the_importer_as_empty_bytes(world):
    api, stub, inst, acct = world
    assert post(api, inst, _file_only(acct, b"")).status_code == 200
    assert stub.seen == [b""]


def test_a_part_without_content_disposition_is_refused(world):
    api, stub, inst, acct = world
    body = form(acct, b"--" + B.encode() + b"\r\nContent-Type: text/csv\r\n\r\nabc\r\n")
    error_of(post(api, inst, body), 422, "validation_error")
    assert stub.seen == []


# ---- field handling and the cap, pinned before the parser was swapped for the library ---------


def _text_part(name: str, value: str) -> bytes:
    return f'--{B}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()


def _msg(response) -> str:
    return str(response.json()["error"]["details"])


def test_a_field_given_twice_is_refused(world):
    api, stub, inst, acct = world
    body = form(acct, _text_part("account_id", str(acct)) + file_part(PAYLOAD))
    err = error_of(post(api, inst, body), 422, "validation_error")
    assert "given twice" in str(err["details"]) and stub.seen == []


def test_an_unknown_field_is_refused(world):
    api, stub, inst, acct = world
    body = form(acct, _text_part("extra", "1") + file_part(PAYLOAD))
    err = error_of(post(api, inst, body), 422, "validation_error")
    assert "unknown field" in str(err["details"]) and stub.seen == []


def test_a_missing_file_and_a_bad_dry_run_are_refused(world):
    api, stub, inst, acct = world
    error_of(post(api, inst, form(acct, b"")), 422, "validation_error")
    body = form(acct, _text_part("dry_run", "maybe") + file_part(PAYLOAD)).replace(
        b'name="dry_run"\r\n\r\ntrue', b'name="dry_run"\r\n\r\nmaybe', 1
    )
    error_of(post(api, inst, body), 422, "validation_error")
    assert stub.seen == []


@pytest.mark.parametrize("content_type", ["application/json", "multipart/form-data", "text/plain"])
def test_a_non_multipart_body_or_a_missing_boundary_is_refused(world, content_type: str):
    api, stub, inst, acct = world
    r = api.client.post(
        f"/api/importers/instances/{inst}/upload", content=b"{}", headers={"content-type": content_type}
    )
    err = error_of(r, 422, "validation_error")
    assert "send the upload as multipart/form-data" in str(err["details"]) and stub.seen == []


def test_an_oversized_body_without_a_content_length_is_refused(world):
    api, stub, inst, acct = world
    chunk = b"x" * (1024 * 1024)
    head = (
        form(acct, b"", close=False)
        + b"--"
        + B.encode()
        + b'\r\nContent-Disposition: form-data; name="file"; filename="a"\r\n\r\n'
    )

    def body():
        yield head
        for _ in range(40):  # 40 MiB offered; the cap is 10 MiB plus slack
            yield chunk

    r = api.client.post(
        f"/api/importers/instances/{inst}/upload",
        content=body(),
        headers={"content-type": f"multipart/form-data; boundary={B}"},
    )
    error_of(r, 413, "file_too_large")
    assert stub.seen == []  # (the test client buffers the body; the cap itself acts on each chunk)
