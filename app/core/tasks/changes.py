"""The change register (architecture §4.2, §5.2): one opaque value per key, in process memory.

Keys: `ledger`, `documents` and `account:<id>`. A value is `"<boot>:<n>"`: the process's boot token and
a counter shared by all keys, so a value changes on every bump and, after a restart (a new register, a
new boot token), differs from every value of an earlier process. Clients compare values for equality and
never read them. One worker process (architecture §3) makes this register the only one.

Only keys that were bumped are stored. A key never bumped reads as the start value `"<boot>:0"`
(`start_value`): the API answers with it for every account it knows of that the register does not.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Iterable

from app.utils.db.changes import DOCUMENTS, LEDGER, account_key

__all__ = ["DOCUMENTS", "LEDGER", "ChangeRegister", "account_key"]


class ChangeRegister:
    def __init__(self) -> None:
        self._boot = secrets.token_hex(4)
        self._lock = threading.Lock()
        self._counter = 0
        self._values: dict[str, str] = {}

    @property
    def start_value(self) -> str:
        return f"{self._boot}:0"

    def bump(self, keys: Iterable[str]) -> None:
        """Give every key a new value; one call is one instant."""
        with self._lock:
            self._counter += 1
            value = f"{self._boot}:{self._counter}"
            for key in keys:
                self._values[key] = value

    def value(self, key: str) -> str:
        with self._lock:
            return self._values.get(key, self.start_value)

    def accounts(self, account_ids: Iterable[int]) -> dict[int, str]:
        """A value for each of `account_ids`: its own, or the start value if no write has touched it."""
        with self._lock:
            return {i: self._values.get(account_key(i), self.start_value) for i in account_ids}
