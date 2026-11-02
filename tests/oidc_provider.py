"""A mock OIDC provider for tests: discovery, JWKS, token and userinfo behind `httpx2.MockTransport`.

Nothing here touches the network. Tokens are signed with a key generated per provider; a test
changes what the provider answers by assigning to its attributes before the callback.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
from joserfc import jwt
from joserfc.jwk import RSAKey

ISSUER = "https://idp.test/realms/home"
CLIENT_ID = "ledgehog-client"
CLIENT_SECRET = "client-secret-value-4711"
ACCESS_TOKEN = "access-token-value-0815"
CODE = "authorization-code-value-1234"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class MockProvider:
    def __init__(self, now_ts: float) -> None:
        self.now_ts = now_ts
        self.key = RSAKey.generate_key(2048, {"kid": "k1"})
        self.other_key = RSAKey.generate_key(2048, {"kid": "k1"})  # same kid, another key: a forgery
        self.down = False
        self.nonce: str | None = None  # learnt from the authorization request
        self.challenge: str | None = None
        self.claims: dict[str, Any] = {}  # merged over the defaults of the ID token
        self.drop: set[str] = set()  # ID token claims to leave out
        self.userinfo: dict[str, Any] | None = None  # None: no userinfo endpoint answers
        self.userinfo_status = 200  # what the userinfo endpoint answers, when it has claims to give
        self.sign_with = self.key
        self.token_requests: list[dict[str, str]] = []
        self.token_auth: list[str | None] = []
        self.userinfo_auth: list[str | None] = []
        self.requests: list[str] = []
        self.pkce_ok: bool | None = None

    # -- what a test sets ---------------------------------------------------------------------

    def saw_authorization(self, location: str) -> dict[str, list[str]]:
        query = parse_qs(urlsplit(location).query)
        self.nonce = query["nonce"][0]
        self.challenge = query["code_challenge"][0]
        return query

    def id_token(self) -> str:
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "sub": "sub-1",
            "aud": CLIENT_ID,
            "iat": int(self.now_ts),
            "exp": int(self.now_ts) + 600,
            "nonce": self.nonce,
        }
        claims.update(self.claims)
        for name in self.drop:
            claims.pop(name, None)
        return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, self.sign_with)

    # -- the wire -----------------------------------------------------------------------------

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request.url.path)
        if self.down:
            raise httpx2.ConnectError("provider is down", request=request)
        path = request.url.path
        if path == "/realms/home/.well-known/openid-configuration":
            base = "https://idp.test/realms/home"
            doc: dict[str, Any] = {
                "issuer": ISSUER,
                "authorization_endpoint": f"{base}/auth",
                "token_endpoint": f"{base}/token",
                "jwks_uri": f"{base}/jwks",
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            }
            if self.userinfo is not None:
                doc["userinfo_endpoint"] = f"{base}/userinfo"
            return httpx2.Response(200, json=doc)
        if path == "/realms/home/jwks":
            return httpx2.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if path == "/realms/home/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            self.token_auth.append(request.headers.get("authorization"))
            verifier = form.get("code_verifier", "")
            self.pkce_ok = _b64(hashlib.sha256(verifier.encode()).digest()) == self.challenge
            if form.get("code") != CODE or not self.pkce_ok:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            return httpx2.Response(
                200,
                json={"access_token": ACCESS_TOKEN, "token_type": "Bearer", "id_token": self.id_token()},
            )
        if path == "/realms/home/userinfo":
            self.userinfo_auth.append(request.headers.get("authorization"))
            if request.headers.get("authorization") != f"Bearer {ACCESS_TOKEN}" or self.userinfo is None:
                return httpx2.Response(401)
            if self.userinfo_status != 200:
                return httpx2.Response(self.userinfo_status, text="secret-body")
            return httpx2.Response(200, json=self.userinfo)
        return httpx2.Response(404)
