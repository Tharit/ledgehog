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


def default_classifiers(rules: Sequence[RuleSpec], *, model: bool = False) -> Sequence[Classifier]:
    """Pass 1 (rules) then pass 2 (history), and pass 3 (the model's stored answer) when one is configured."""
    chain: list[Classifier] = [RulesClassifier(rules), HistoryClassifier()]
    if model:
        chain.append(LlmClassifier())
    return chain
