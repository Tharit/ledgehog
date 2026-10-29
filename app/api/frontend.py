"""Serving the SPA bundle and the security headers every response carries (architecture §6.7).

`Frontend.load` reads `index.html` once, at app creation: it finds the one inline script SvelteKit
boots the SPA with and hashes it for the Content-Security-Policy; no inline script, or more than one,
refuses the start. The bundle is optional in development: without an `index.html` the app serves the API only.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)

_POLICY = (
    "default-src 'none'; script-src {script_src}; style-src 'self'; "
    "style-src-attr 'unsafe-inline'; img-src 'self'; font-src 'self'; "
    "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'; require-trusted-types-for 'script'; trusted-types svelte-trusted-html"
)
_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
)


class FrontendError(Exception):
    """The bundle cannot be served safely; the message says why. Refuses the start."""


class _InlineScripts(HTMLParser):
    """Collects the text of every `<script>` without a `src`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._open: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and not any(name == "src" for name, _ in attrs):
            self._open = []

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._open is not None:
            self.scripts.append("".join(self._open))
            self._open = None


def script_hash(html: str) -> str:
    """The CSP source (`'sha256-…'`) of the one inline script of `html`."""
    parser = _InlineScripts()
    parser.feed(html)
    parser.close()
    if len(parser.scripts) != 1:
        raise FrontendError(
            f"index.html holds {len(parser.scripts)} inline scripts; the Content-Security-Policy "
            "allows exactly one (SvelteKit's bootstrap)"
        )
    digest = hashlib.sha256(parser.scripts[0].encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


def _is_api(path: str) -> bool:
    return path == "api" or path.startswith("api/")


class _Bundle(StaticFiles):
    """The static files, with `index.html` for any unknown path that is not the API's."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or _is_api(path):
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not _is_api(path):
            return await super().get_response("index.html", scope)
        return response


@dataclass(frozen=True, slots=True)
class Frontend:
    """What `create_app` needs to serve the bundle; `directory` is None when it is not served."""

    directory: Path | None
    script_src: str

    @classmethod
    def load(cls, directory: Path | None) -> Frontend:
        if directory is None or not (directory / "index.html").is_file():
            log.info("frontend not served: no index.html in %s (the API only)", directory)
            return cls(None, "'self'")
        html = (directory / "index.html").read_text(encoding="utf-8")
        return cls(directory, f"'self' {script_hash(html)}")

    @property
    def policy(self) -> str:
        return _POLICY.format(script_src=self.script_src)

    def mount(self, app: FastAPI) -> None:
        """Called after every API route is registered, so `/api` is never shadowed."""
        if self.directory is not None:
            app.mount("/", _Bundle(directory=self.directory), name="frontend")


class SecurityHeaders:
    """Pure ASGI middleware: the policy and its companions on every HTTP response, streams included."""

    def __init__(self, app: ASGIApp, policy: str) -> None:
        self.app = app
        self._headers = [(b"content-security-policy", policy.encode()), *_HEADERS]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *self._headers]
            await send(message)

        await self.app(scope, receive, send_with_headers)
