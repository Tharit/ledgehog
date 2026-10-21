"""The concrete classifiers and the factory the composition root registers with core."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.plugins.classifier import Classifier, RuleSpec
from app.plugins.classifiers.history import HistoryClassifier
from app.plugins.classifiers.llm import LlmClassifier
from app.plugins.classifiers.rules import RulesClassifier, default_rule_tools

__all__ = [
    "HistoryClassifier",
    "LlmClassifier",
    "RulesClassifier",
    "default_classifiers",
    "default_rule_tools",
]


def default_classifiers(rules: Sequence[RuleSpec]) -> Sequence[Classifier]:
    """Pass 1 (rules), pass 2 (history), pass 3 (the model's stored answer). Pass 3 only reads what is stored,
    so it is here with or without a model configured: answers stored earlier stand either way."""
    return [RulesClassifier(rules), HistoryClassifier(), LlmClassifier()]
