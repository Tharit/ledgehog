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

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from app.core.plugins.classifier import Classifier, EntryInput, RuleSpec

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


@dataclass(frozen=True, slots=True)
class RuleTools:
    """What core needs of the rules plugin to write and preview a rule (spec §5.9, rules.md).

    The same functions the rules classifier settles with, so a preview can never disagree with
    settling: `validate` raises `RuleInvalid` for a rule that cannot be saved, `matches` is the one
    match function (conditions only; core adds the currency and closing tests of a counter-account
    rule) and `precedence_order` the evaluation order.
    """

    validate: Callable[[RuleSpec], None]
    matches: Callable[[RuleSpec, EntryInput, int | None], bool]
    precedence_order: Callable[[Iterable[RuleSpec]], list[RuleSpec]]


class RuleToolsNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__("no rule tools configured: the composition root must call configure_rule_tools()")


_rule_tools: RuleTools | None = None


def configure_rule_tools(tools: RuleTools) -> None:
    """Install the tools (replacing any earlier ones)."""
    global _rule_tools
    _rule_tools = tools


def unconfigure_rule_tools() -> None:
    """Forget the tools (tests of the unconfigured state, and their teardown)."""
    global _rule_tools
    _rule_tools = None


def current_rule_tools() -> RuleTools | None:
    """The installed tools, for a test that restores them."""
    return _rule_tools


def rule_tools() -> RuleTools:
    """The installed tools; raises `RuleToolsNotConfigured`."""
    if _rule_tools is None:
        raise RuleToolsNotConfigured
    return _rule_tools
