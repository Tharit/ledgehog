"""`CsvImporter`: the file importer for statement exports (csv.md)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.plugins.importers.csv.profile import Profile


class CsvImporter:
    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        Profile.from_dict(settings).validate()
