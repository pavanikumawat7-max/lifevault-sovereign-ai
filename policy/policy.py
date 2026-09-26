"""Policy allow-list interface.

Governs whether a proposed tool call is denied outright, allowed to run
without asking a human, or requires human approval first. S1 ships a
deny-by-default allow-list with no real rules configured -- later
sessions populate real PolicyRule entries per tool.

`evaluate()`'s three possible outcomes ("deny", "needs_approval", "allow")
are exactly the values graph/nodes.py's `policy_check` node stub is typed
to produce, so wiring this in later doesn't change the graph's shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class PolicyRule:
    tool: str
    allowed: bool = False
    requires_approval: bool = True
    notes: str = ""


class PolicyAllowList:
    """Deny-by-default: a tool with no rule, or a rule with allowed=False,
    always evaluates to "deny"."""

    def __init__(self, rules: Optional[Dict[str, PolicyRule]] = None) -> None:
        self._rules: Dict[str, PolicyRule] = dict(rules) if rules else {}

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules[rule.tool] = rule

    def get_rule(self, tool: str) -> Optional[PolicyRule]:
        return self._rules.get(tool)

    def evaluate(self, tool: str) -> str:
        """Returns one of: "deny", "needs_approval", "allow"."""
        rule = self._rules.get(tool)
        if rule is None or not rule.allowed:
            return "deny"
        return "needs_approval" if rule.requires_approval else "allow"


# Process-wide default policy. Empty (deny-everything) until a later
# session configures real rules.
default_policy = PolicyAllowList()
