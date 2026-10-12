"""The classifiers settling resolves with (architecture §5.1, §5.4), supplied by the composition root.

Core must not import the concrete plugins, so the composition root (`app.main`, and the scripts
that settle on their own) hands core a factory: from the rules of one settle it builds the
classifiers in authority order (rules, history, later the model). Settling asks `classifiers_for`
once per settle, so the rules are read once and never go stale mid-settle.

A process that never configured a factory fails loudly: `ClassifiersNotConfigured` is raised on
the first settle and reported in `SettleResult.error`. Silently resolving nothing would look like
a working ledger with every entry unclassified.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.core.plugins.classifier import Classifier, RuleSpec

ClassifierFactory = Callable[[Sequence[RuleSpec]], Sequence[Classifier]]


class ClassifiersNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "no classifier factory configured: the composition root must call configure_classifiers()"
        )


_factory: ClassifierFactory | None = None


def configure_classifiers(factory: ClassifierFactory) -> None:
    """Install the factory (replacing any earlier one)."""
    global _factory
    _factory = factory


def unconfigure_classifiers() -> None:
    """Forget the factory (tests of the unconfigured state, and their teardown)."""
    global _factory
    _factory = None


def current_factory() -> ClassifierFactory | None:
    """The installed factory, for a test that restores it."""
    return _factory


def classifiers_for(rules: Sequence[RuleSpec]) -> Sequence[Classifier]:
    """The classifiers for these rules, by authority; raises `ClassifiersNotConfigured`."""
    if _factory is None:
        raise ClassifiersNotConfigured
    return _factory(rules)
