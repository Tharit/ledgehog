"""Repository-root pytest hook: never descend into `.env*` files (they are configuration,
not tests, and some sandboxes forbid even stat-ing them)."""

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path):  # type: ignore[no-untyped-def]
    if collection_path.name.startswith(".env"):
        return True
    return None
