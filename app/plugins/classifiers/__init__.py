"""The concrete classifiers and the factory the composition root registers with core."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.plugins.classifier import Classifier, RuleSpec
from app.plugins.classifiers.history import HistoryClassifier
from app.plugins.classifiers.rules import RulesClassifier, default_rule_tools

__all__ = ["HistoryClassifier", "RulesClassifier", "default_classifiers", "default_rule_tools"]


def default_classifiers(rules: Sequence[RuleSpec]) -> Sequence[Classifier]:
    """Pass 1 (rules) then pass 2 (history), by authority; pass 3 joins with step 12."""
    return [RulesClassifier(rules), HistoryClassifier()]
