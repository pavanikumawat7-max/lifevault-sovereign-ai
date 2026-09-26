import pytest

from policy.policy import PolicyAllowList, PolicyRule
from tools.registry import ToolRegistry, ToolSpec


def test_tool_registry_register_and_get():
    reg = ToolRegistry()
    reg.register(ToolSpec(name="noop", description="does nothing"))
    assert reg.get("noop") is not None
    assert reg.get("missing") is None


def test_tool_registry_rejects_duplicate_registration():
    reg = ToolRegistry()
    reg.register(ToolSpec(name="noop", description="does nothing"))
    with pytest.raises(ValueError):
        reg.register(ToolSpec(name="noop", description="dup"))


def test_tool_registry_run_without_handler_raises():
    reg = ToolRegistry()
    reg.register(ToolSpec(name="noop", description="does nothing"))
    with pytest.raises(NotImplementedError):
        reg.run("noop", {})


def test_tool_registry_run_unknown_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.run("missing", {})


def test_policy_default_deny():
    policy = PolicyAllowList()
    assert policy.evaluate("send_email") == "deny"


def test_policy_allow_with_approval():
    policy = PolicyAllowList()
    policy.add_rule(PolicyRule(tool="send_email", allowed=True, requires_approval=True))
    assert policy.evaluate("send_email") == "needs_approval"


def test_policy_allow_without_approval():
    policy = PolicyAllowList()
    policy.add_rule(PolicyRule(tool="log_note", allowed=True, requires_approval=False))
    assert policy.evaluate("log_note") == "allow"
