"""OIDC sign-in, the protocol half (architecture §5.6).

The authorization code flow with PKCE, state and nonce, against the issuer's discovery document, by
Authlib over httpx. The ID token is verified (signature, issuer, audience, expiry, nonce); a claim it
lacks (login, name, groups) is taken from the userinfo endpoint, whose subject must match. What a
verified identity may do in the application is `oidc_users`.

The provider is asked only at sign-in. Discovery and the signing keys are fetched lazily and cached,
so the application starts with the provider down. State, nonce and the PKCE verifier live in memory
(one worker, architecture §5.2) for a few minutes, keyed by `state`; the route binds the browser to
that state with a cookie.

Nothing here logs a token, a code or the client secret; failures carry a stable code, never a payload.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from app.utils.config import OidcConfig

log = logging.getLogger("ledgehog.oidc")

PENDING_TTL = timedelta(minutes=10)
_PENDING_CAP = 500
_DISCOVERY_TTL = timedelta(hours=1)
_LEEWAY = 60  # seconds of clock skew tolerated on exp, nbf and iat
_TIMEOUT = 10.0
# asymmetric algorithms only: a token signed with the client secret, or with `none`, is never accepted
_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]

# the stable codes a refusal returns to the login page (`/login?error=<code>`)
FAILED = "oidc_failed"
UNAVAILABLE = "oidc_unavailable"
NO_LOGIN = "oidc_no_login"
UNVERIFIED = "oidc_unverified"
NOT_ALLOWED = "oidc_not_allowed"
DISABLED = "oidc_disabled"


class OidcError(Exception):
    """A sign-in that does not complete. `code` is stable and safe to show; the message is for the log."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True, slots=True)
class OidcIdentity:
    """What the rules need of a verified sign-in."""

    login: str | None
    display_name: str | None
    groups: tuple[str, ...] | None  # None: the claim is absent
    email_verified: bool | None  # None: not stated


def _claim_text(claims: Mapping[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def identity_from(claims: Mapping[str, Any], cfg: OidcConfig) -> OidcIdentity:
    groups_raw = claims.get("groups")
    groups: tuple[str, ...] | None = None
    if isinstance(groups_raw, str):
        groups = (groups_raw,)
    elif isinstance(groups_raw, list):
        groups = tuple(g for g in groups_raw if isinstance(g, str))
    verified = claims.get("email_verified")
    if isinstance(verified, str):  # some providers send the strings "true" and "false"
        verified = {"true": True, "false": False}.get(verified.lower())
    return OidcIdentity(
        login=_claim_text(claims, cfg.login_attribute),
        display_name=_claim_text(claims, cfg.displayname_attribute),
        groups=groups,
        email_verified=verified if isinstance(verified, bool) else None,
    )


@dataclass(frozen=True, slots=True)
class _Pending:
    nonce: str
    verifier: str
    expires_at: datetime


class _PendingSignIns:
    """The sign-ins begun and not yet returned: state -> nonce and PKCE verifier. Single use, short life."""

    def __init__(self) -> None:
        self._items: dict[str, _Pending] = {}
        self._lock = threading.Lock()

    def begin(self, now: datetime) -> tuple[str, _Pending]:
        state = secrets.token_urlsafe(32)
        pending = _Pending(secrets.token_urlsafe(32), secrets.token_urlsafe(48), now + PENDING_TTL)
        with self._lock:
            for key in [k for k, p in self._items.items() if p.expires_at <= now]:
                del self._items[key]
            while len(self._items) >= _PENDING_CAP:  # a flood of starts cannot grow memory without bound
                del self._items[next(iter(self._items))]
            self._items[state] = pending
        return state, pending

    def take(self, state: str, now: datetime) -> _Pending | None:
        with self._lock:
            pending = self._items.pop(state, None)
        if pending is None or pending.expires_at <= now:
            return None
        return pending


class OidcFlow:
    """The provider, as the routes use it: `start` to send the browser off, `finish` when it returns."""

    def __init__(self, cfg: OidcConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = cfg
        self._transport = transport
        self._pending = _PendingSignIns()
        self._lock = threading.Lock()
        self._discovery: dict[str, Any] | None = None
        self._discovery_at: datetime | None = None
        self._keys: KeySet | None = None
        self._keys_at: datetime | None = None

    # -- HTTP ---------------------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=_TIMEOUT, follow_redirects=False)

    def _get_json(self, url: str, *, bearer: str | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        try:
            with self._client() as http:
                response = http.get(url, headers=headers)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise OidcError(UNAVAILABLE, f"{type(exc).__name__} fetching {_where(url)}") from None
        except ValueError:
            raise OidcError(FAILED, f"{_where(url)} did not answer JSON") from None
        if not isinstance(body, dict):
            raise OidcError(FAILED, f"{_where(url)} did not answer a JSON object")
        return body

    # -- discovery and keys -------------------------------------------------------------------

    def discovery(self, now: datetime) -> dict[str, Any]:
        with self._lock:
            if (
                self._discovery is not None
                and self._discovery_at
                and now - self._discovery_at < _DISCOVERY_TTL
            ):
                return self._discovery
        doc = self._get_json(f"{self.cfg.issuer}/.well-known/openid-configuration")
        issuer = doc.get("issuer")
        if not isinstance(issuer, str) or issuer.rstrip("/") != self.cfg.issuer:
            raise OidcError(FAILED, "the discovery document names another issuer")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            value = doc.get(key)
            if not isinstance(value, str) or not value.startswith(("http://", "https://")):
                raise OidcError(FAILED, f"the discovery document lacks {key}")
        with self._lock:
            self._discovery, self._discovery_at = doc, now
        return doc

    def _key_set(self, now: datetime, *, refresh: bool = False) -> KeySet:
        with self._lock:
            if (
                not refresh
                and self._keys is not None
                and self._keys_at
                and now - self._keys_at < _DISCOVERY_TTL
            ):
                return self._keys
        jwks = self._get_json(self.discovery(now)["jwks_uri"])
        try:
            keys = KeySet.import_key_set(cast(Any, jwks))
        except (JoseError, ValueError, TypeError, KeyError):
            raise OidcError(FAILED, "the signing keys are unreadable") from None
        with self._lock:
            self._keys, self._keys_at = keys, now
        return keys

    # -- the two halves of the flow -----------------------------------------------------------

    def _oauth(self, doc: Mapping[str, Any]) -> OAuth2Client:
        methods = doc.get("token_endpoint_auth_methods_supported")
        method = "client_secret_basic"
        if (
            isinstance(methods, list)
            and "client_secret_basic" not in methods
            and "client_secret_post" in methods
        ):
            method = "client_secret_post"
        return OAuth2Client(
            client_id=self.cfg.client_id,
            client_secret=self.cfg.client_secret.reveal(),
            scope=" ".join(self.cfg.scopes),
            redirect_uri=self.cfg.redirect_uri,
            code_challenge_method="S256",
            token_endpoint_auth_method=method,
            transport=self._transport,
            timeout=_TIMEOUT,
            follow_redirects=False,
        )

    def start(self, now: datetime) -> tuple[str, str]:
        """The provider's authorization address and the `state` that binds the browser to this sign-in."""
        doc = self.discovery(now)
        state, pending = self._pending.begin(now)
        with self._oauth(doc) as oauth:
            url, _ = oauth.create_authorization_url(
                doc["authorization_endpoint"],
                state=state,
                code_verifier=pending.verifier,
                nonce=pending.nonce,
            )
        return str(url), state

    def finish(self, state: str, code: str, now: datetime) -> OidcIdentity:
        """Exchange the code, verify the ID token, complete its claims; the verified identity."""
        pending = self._pending.take(state, now)
        if pending is None:
            raise OidcError(FAILED, "unknown or expired state")
        doc = self.discovery(now)
        try:
            with self._oauth(doc) as oauth:
                token = oauth.fetch_token(
                    doc["token_endpoint"],
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=pending.verifier,
                )
        except Exception as exc:  # authlib raises its own errors and httpx's; neither is shown on
            raise OidcError(FAILED, f"the code exchange failed ({type(exc).__name__})") from None
        id_token = token.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise OidcError(FAILED, "the token response carries no id_token")
        claims = self._verified_claims(id_token, pending.nonce, doc, now)
        claims = self._complete_claims(claims, doc, token.get("access_token"))
        if "groups" in claims:
            log.info("oidc: groups claim: %s", _groups_shape(claims["groups"]))
        return identity_from(claims, self.cfg)

    # -- verification -------------------------------------------------------------------------

    def _verified_claims(
        self, id_token: str, nonce: str, doc: Mapping[str, Any], now: datetime
    ) -> dict[str, Any]:
        try:
            try:
                claims = dict(jwt.decode(id_token, self._key_set(now), algorithms=_ALGORITHMS).claims)
            except JoseError:  # a rotated key: look again once before refusing
                claims = dict(
                    jwt.decode(id_token, self._key_set(now, refresh=True), algorithms=_ALGORITHMS).claims
                )
        except JoseError as exc:
            raise OidcError(FAILED, f"the id_token does not verify ({type(exc).__name__})") from None
        issuer = doc["issuer"]
        if not isinstance(claims.get("iss"), str) or claims["iss"].rstrip("/") != issuer.rstrip("/"):
            raise OidcError(FAILED, "the id_token has another issuer")
        aud = claims.get("aud")
        audiences = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        if self.cfg.client_id not in audiences:
            raise OidcError(FAILED, "the id_token is for another audience")
        if len(audiences) > 1 and claims.get("azp") != self.cfg.client_id:
            raise OidcError(FAILED, "the id_token's authorized party is another client")
        moment = now.timestamp()
        exp = claims.get("exp")
        if not isinstance(exp, int | float) or exp + _LEEWAY <= moment:
            raise OidcError(FAILED, "the id_token has expired")
        for early in ("nbf", "iat"):
            value = claims.get(early)
            if value is not None and (not isinstance(value, int | float) or value - _LEEWAY > moment):
                raise OidcError(FAILED, f"the id_token's {early} is in the future")
        sent = claims.get("nonce")
        if not isinstance(sent, str) or not hmac.compare_digest(sent.encode(), nonce.encode()):
            raise OidcError(FAILED, "the id_token's nonce does not match")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise OidcError(FAILED, "the id_token has no subject")
        log.info("oidc: id_token claims: %s", _names(claims))
        return claims

    def _complete_claims(
        self, claims: dict[str, Any], doc: Mapping[str, Any], access_token: object
    ) -> dict[str, Any]:
        """Claims the ID token lacks (login, name, groups) come from userinfo, whose `sub` must match."""
        needed = {self.cfg.login_attribute: True, self.cfg.displayname_attribute: False}
        if self.cfg.allowed_group is not None:
            needed["groups"] = True
        missing = [name for name in needed if claims.get(name) in (None, "", [])]
        if not missing:
            return claims
        log.info("oidc: claims missing from the id_token: %s", ", ".join(sorted(missing)))
        required = any(needed[name] for name in missing)
        endpoint = doc.get("userinfo_endpoint")
        if not isinstance(endpoint, str):
            log.info("oidc: userinfo not asked: the provider has no userinfo endpoint")
            return claims  # nothing to ask: the rules refuse what is still missing (fail closed)
        if not isinstance(access_token, str) or not access_token:
            log.info("oidc: userinfo not asked: the token response carries no access token")
            return claims
        try:
            info = self._get_json(endpoint, bearer=access_token)
        except OidcError as exc:
            log.info("oidc: the userinfo request failed: %s", exc)
            if required:
                raise
            return claims
        log.info("oidc: userinfo claims: %s", _names(info))
        if info.get("sub") != claims["sub"]:
            raise OidcError(FAILED, "the userinfo subject does not match the id_token")
        merged = dict(claims)
        for name, value in info.items():
            if name not in merged or merged[name] in (None, "", []):
                merged[name] = value
        return merged


def _names(claims: Mapping[str, Any]) -> str:
    """The claim names, sorted: what arrived, never what it said."""
    return ", ".join(sorted(str(name) for name in claims))


def _groups_shape(value: object) -> str:
    """How the groups claim is built (type, size, separators), never what a group is called."""
    if isinstance(value, str):
        parts = [f"str, {len(value)} chars"]
        parts += [
            f"contains {label}"
            for label, mark in (("comma", ","), ("space", " "), ("semicolon", ";"))
            if mark in value
        ]
        if "@" in value:
            parts.append("contains @")
        return ", ".join(parts)
    if isinstance(value, list):
        kinds = ", ".join(sorted({type(item).__name__ for item in value}))
        parts = [f"list, {len(value)} entries"]
        if kinds:
            parts.append(f"item types {kinds}")
        if any(isinstance(item, str) and "@" in item for item in value):
            parts.append("an entry contains @")
        return ", ".join(parts)
    return type(value).__name__


def _where(url: str) -> str:
    """The address without its query: enough to tell which endpoint, never a code or token."""
    return url.split("?", 1)[0]
