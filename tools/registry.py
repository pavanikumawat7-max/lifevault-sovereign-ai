"""Tool registry interface.

A `ToolRegistry` is where later sessions will register real tools (e.g.
"send_email", "create_calendar_event") that the LangGraph `execute` node
can invoke after policy + human approval. S1 defines the registration and
lookup contract only -- no real tools are registered, and `run()` on a
tool with no handler wired always raises NotImplementedError.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class ToolSpec:
    """Describes one tool. `handler` is optional in S1 -- a spec can be
    registered (e.g. for policy/UI purposes) before real logic exists."""

    name: str
    description: str
    handler: Optional[Callable[[dict], dict]] = None


class ToolRegistry:
    """In-memory registry of ToolSpecs, keyed by unique name."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool '{spec.name}' is already registered")
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def run(self, name: str, parameters: dict) -> dict:
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"Unknown tool: '{name}'")
        if spec.handler is None:
            raise NotImplementedError(
                f"Tool '{name}' has no handler wired yet (S1 stub)"
            )
        return spec.handler(parameters)


# Process-wide default registry. Later sessions register real tools here
# (or construct their own ToolRegistry() for tests).
default_registry = ToolRegistry()
