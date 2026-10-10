"""Password hashing: argon2id via argon2-cffi (architecture §5.6)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters

# Verified against when a login is unknown or disabled, so that path costs the
# same as a real one and response time does not reveal which logins exist.
_DUMMY_HASH = _hasher.hash("ledgehog-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """True when `password` matches `stored_hash`; a malformed hash is a plain mismatch."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with parameters older than the current ones."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


def verify_dummy(password: str) -> None:
    """Spend the cost of one verification without a real account behind it."""
    verify_password(_DUMMY_HASH, password)
