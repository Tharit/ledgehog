"""The second seam: rule tools, configured by the composition root, loud when missing."""

from __future__ import annotations

import pytest

from app.core.resolution.registry import (
    RuleTools,
    RuleToolsNotConfigured,
    configure_rule_tools,
    current_rule_tools,
    rule_tools,
    unconfigure_rule_tools,
)


def test_unconfigured_rule_tools_raise() -> None:
    unconfigure_rule_tools()
    assert current_rule_tools() is None
    with pytest.raises(RuleToolsNotConfigured, match="configure_rule_tools"):
        rule_tools()


def test_configured_rule_tools_are_returned_and_replaced() -> None:
    first = RuleTools(
        validate=lambda r: None, matches=lambda r, e, p: True, precedence_order=lambda rs: list(rs)
    )
    second = RuleTools(validate=lambda r: None, matches=lambda r, e, p: False, precedence_order=lambda rs: [])
    configure_rule_tools(first)
    assert rule_tools() is first
    configure_rule_tools(second)
    assert rule_tools() is second
