"""The deterministic test importers (`testdocs`, `testfetch`), dev/test only.

One package so that the scripted fetch importer can build on the document one.
"""

from app.plugins.importers.testing.testdocs import PROVIDERS, TestDocumentImporter
from app.plugins.importers.testing.testfetch import PIXEL_PNG, TestFetchImporter

__all__ = ["PIXEL_PNG", "PROVIDERS", "TestDocumentImporter", "TestFetchImporter"]
