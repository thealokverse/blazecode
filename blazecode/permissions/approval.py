"""Central approval gate for mutating tool calls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from blazecode.tools.base import Tool

ApprovalCallback = Callable[[str, dict[str, Any]], bool]


@dataclass(slots=True)
class ApprovalManager:
    """Enforce ask, auto, or plan approval policy."""

    mode: str = "ask"
    callback: ApprovalCallback | None = None

    def approve(self, tool: Tool, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Return whether a tool invocation may proceed and why."""
        if not tool.mutating:
            return True, ""
        if self.mode == "auto":
            return True, ""
        if self.mode == "plan":
            return False, "approval mode 'plan' is read-only"
        if self.mode != "ask":
            return False, f"unknown approval mode: {self.mode}"
        if self.callback is None:
            return False, "approval required but no interactive approver is available"
        if self.callback(tool.name, arguments):
            return True, ""
        return False, "user denied approval"

