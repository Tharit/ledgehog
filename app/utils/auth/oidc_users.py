"""OIDC sign-in, the rules half (architecture §5.6, decisions D226).

What a verified identity may do: the login claim is the login; a matching user signs in, an unknown
one is created without a password; a configured user's first sign-in hands them to the provider
(`source` becomes `oidc`, the password is dropped); a disabled user, an unverified e-mail and a
missing group are refused. One transaction, supplied by the caller. Logs name logins, never claims
beyond that.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, text

from app.utils.auth.oidc import DISABLED, FAILED, NO_LOGIN, NOT_ALLOWED, UNVERIFIED, OidcError, OidcIdentity
from app.utils.config import OidcConfig

log = logging.getLogger("ledgehog.oidc")


def admit(conn: Connection, cfg: OidcConfig, identity: OidcIdentity) -> int:
    """The id of the user this identity signs in as, creating or handing over as the rules say.

    Raises `OidcError` with the refusal's code.
    """
    login = identity.login
    if login is None:
        raise OidcError(NO_LOGIN, f"the {cfg.login_attribute} claim is missing")
    if cfg.login_attribute == "email" and identity.email_verified is False:
        raise OidcError(UNVERIFIED, "the provider marks the e-mail unverified")
    if cfg.allowed_group is not None:
        if identity.groups is None:
            raise OidcError(NOT_ALLOWED, "the groups claim is absent")
        if cfg.allowed_group not in identity.groups:
            raise OidcError(
                NOT_ALLOWED, f"the allowed group is not among the user's {len(identity.groups)} groups"
            )

    # the claim is compared without regard to case; `app_user.login` is unique per exact spelling only,
    # so two users differing in case make the match ambiguous, and nobody is signed in
    found = conn.execute(
        text(
            "SELECT id, login, display_name, disabled, source FROM app_user "
            "WHERE lower(login) = lower(:l) FOR UPDATE"
        ),
        {"l": login},
    ).all()
    if len(found) > 1:
        raise OidcError(FAILED, "more than one user matches the login without regard to case")
    row = found[0] if found else None
    if row is None:
        # a concurrent first sign-in of the same login must not fail on the unique key
        created = conn.execute(
            text(
                "INSERT INTO app_user (login, pw_hash, display_name, source) "
                "VALUES (:l, NULL, :n, 'oidc') ON CONFLICT (login) DO NOTHING"
            ),
            {"l": login, "n": identity.display_name or login},
        ).rowcount
        row = conn.execute(
            text("SELECT id, display_name, disabled, source FROM app_user WHERE login = :l FOR UPDATE"),
            {"l": login},
        ).one()
        if created:
            log.info("oidc: user created: %s", login)
    if row.disabled:
        raise OidcError(DISABLED, "the user is disabled")
    if row.source == "config":
        conn.execute(text("UPDATE app_user SET source = 'oidc', pw_hash = NULL WHERE id = :i"), {"i": row.id})
        log.info("oidc: user handed over to the provider: %s", login)
    if identity.display_name is not None and identity.display_name != row.display_name:
        conn.execute(
            text("UPDATE app_user SET display_name = :n WHERE id = :i"),
            {"n": identity.display_name, "i": row.id},
        )
    return int(row.id)
