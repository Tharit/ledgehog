"""Logging backstop for secret redaction (architecture §5.6).

The mechanism is not putting secrets in loggable places; this filter is the
backstop. It replaces the value of known-sensitive keys in `extra` fields and
dict log arguments, and scrubs `key=value` / `"key": "value"` pairs in the
message text. Request bodies are never logged by this application.
"""

from __future__ import annotations

import logging
import re
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pin",
        "tan",
        "token",
        "session",
        "session_id",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "set-cookie",
        "pw_hash",
        "ledgehog_session",
    }
)
REDACTED = "[redacted]"

# `api_key` also matches `api-key`: header and field spellings differ.
_KEYS = "|".join(
    re.escape(k).replace("_", "[-_]").replace(r"\-", "[-_]")
    for k in sorted(SENSITIVE_KEYS, key=len, reverse=True)
)
# No letter or digit before the key: `pin` must not match inside `spin`, `tan` inside `Sultan`.
# `_` and `-` do not count, so `x_token`, `x-api-key` and `db_password` still match.
_PAIR = re.compile(
    r"""(?<![A-Za-z0-9])(?P<key>["']?(?:""" + _KEYS + r""")["']?)(?P<sep>\s*[:=]\s*)"""
    r"""(?P<val>(?:(?:bearer|basic)\s+)?(?:"[^"]*"|'[^']*'|[^\s,;&}]+))""",
    re.IGNORECASE,
)
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}


def _is_sensitive(key: object) -> bool:
    return isinstance(key, str) and key.lower() in SENSITIVE_KEYS


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if _is_sensitive(k) else _scrub(v) for k, v in value.items()}
    if isinstance(value, str):
        return _PAIR.sub(lambda m: f"{m.group('key')}{m.group('sep')}{REDACTED}", value)
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key in [k for k in record.__dict__ if k not in _STANDARD]:
            record.__dict__[key] = REDACTED if _is_sensitive(key) else _scrub(record.__dict__[key])
        if isinstance(record.args, dict):
            record.args = _scrub(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_scrub(a) for a in record.args)
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        return True


_FILTER = RedactionFilter()


def install_redaction() -> None:
    """Attach the filter to every handler the root and uvicorn loggers have (idempotent)."""
    names = ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    for name in names:
        for handler in logging.getLogger(name).handlers:
            if _FILTER not in handler.filters:
                handler.addFilter(_FILTER)
