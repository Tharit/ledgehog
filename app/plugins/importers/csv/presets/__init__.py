"""Shipped presets: profiles without account details, as JSON package data (csv.md §8)."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from app.plugins.importers.csv.importer import CsvImporter


def load_presets() -> dict[str, dict[str, Any]]:
    """Every shipped preset by name (its file name), each validated; fresh copies per call."""
    out: dict[str, dict[str, Any]] = {}
    for entry in sorted(files(__package__).iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".json"):
            settings: dict[str, Any] = json.loads(entry.read_text(encoding="utf-8"))
            CsvImporter().validate_settings(settings)
            out[entry.name.removesuffix(".json")] = settings
    return out
