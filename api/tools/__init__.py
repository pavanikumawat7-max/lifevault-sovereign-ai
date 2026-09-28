"""The only two action tools LifeVault has (S7).

Deliberately two, and deliberately these two:

  * `create_reminder` -- writes a `reminders` row and an `.ics` file
  * `draft_email`     -- writes an `.eml` file and **never sends anything**

There is no delete tool and no network tool, by design. Every tool writes
only inside the configured vault directory, never touches the user's
original documents, and is registered here so `policy/policy.py` can
allow-list it by name.

Adding a tool means: a Pydantic params model, a handler returning a plain
dict, a `ToolSpec` registration below, and a `PolicyRule`. Anything that
sends, uploads, deletes or overwrites user files does not belong here.
"""
from __future__ import annotations

from typing import Any, Dict

from tools.registry import ToolRegistry, ToolSpec

from api.tools.create_reminder import (
    CreateReminderParams,
    TOOL_NAME as CREATE_REMINDER,
    create_reminder,
)
from api.tools.draft_email import (
    DraftEmailParams,
    TOOL_NAME as DRAFT_EMAIL,
    draft_email,
)

#: tool name -> Pydantic model validating its parameters
PARAM_MODELS: Dict[str, Any] = {
    CREATE_REMINDER: CreateReminderParams,
    DRAFT_EMAIL: DraftEmailParams,
}

#: The complete set of tool names S7 permits. policy/policy.py allow-lists
#: exactly these; anything else is denied by default.
ALLOWED_TOOLS = tuple(PARAM_MODELS)


def build_registry() -> ToolRegistry:
    """A fresh registry with both tools wired to real handlers."""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name=CREATE_REMINDER,
            description=(
                "Create a local reminder: one reminders row plus an .ics "
                "calendar file in the vault. Does not notify anyone."
            ),
            handler=create_reminder,
        )
    )
    registry.register(
        ToolSpec(
            name=DRAFT_EMAIL,
            description=(
                "Write an .eml draft into the vault. NEVER sends, queues or "
                "transmits anything."
            ),
            handler=draft_email,
        )
    )
    return registry


#: Process-wide registry used by the execute node.
default_registry = build_registry()

__all__ = [
    "ALLOWED_TOOLS",
    "CREATE_REMINDER",
    "DRAFT_EMAIL",
    "PARAM_MODELS",
    "CreateReminderParams",
    "DraftEmailParams",
    "build_registry",
    "create_reminder",
    "default_registry",
    "draft_email",
]
