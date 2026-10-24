"""The email importer as the composition root builds it: the real extractor and builder."""

from __future__ import annotations

from app.plugins.importers.email.document import EmailDocumentBuilder
from app.plugins.importers.email.extract import ModelExtractor, ModelSpec
from app.plugins.importers.email.importer import EmailImporter
from app.utils.config import ModelConfig, VisionModelConfig


def email_importer(model: ModelConfig, vision_model: VisionModelConfig | None = None) -> EmailImporter:
    """The text is read by `model`, PDF pages by `vision_model` where one is configured (spec §5)."""
    text = ModelSpec(
        model.endpoint,
        model.name,
        model.api_key.reveal() if model.api_key else None,
        model.reasoning_effort,
    )
    vision = (
        ModelSpec(
            vision_model.endpoint,
            vision_model.name,
            vision_model.api_key.reveal() if vision_model.api_key else None,
        )
        if vision_model
        else None
    )
    return EmailImporter(ModelExtractor(text, vision), EmailDocumentBuilder())
