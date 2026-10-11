"""Reading a database error without quoting it."""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError


def constraint_name(exc: DBAPIError) -> str | None:
    """The violated constraint's name, when the driver reports one."""
    orig = exc.orig
    return getattr(getattr(orig, "diag", None), "constraint_name", None) if orig is not None else None
