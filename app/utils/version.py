"""The application's own version, read from the installed package metadata.

FinTS sends it as the product version and the OpenAPI schema states it.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def app_version() -> str:
    """The application's own version: FinTS sends it as the product version, and the OpenAPI
    schema states it."""
    try:
        return version("ledgehog")
    except PackageNotFoundError:
        return "0.0.0"
