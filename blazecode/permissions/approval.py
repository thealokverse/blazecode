"""Central approval gate for mutating tool calls."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from blazecode.tools.base import Tool

ApprovalCallback = Callable[[str, dict[str, Any]], bool | Awaitable[bool]]


@dataclass(slots=True)
class ApprovalManager:
    """Enforce ask, auto, or plan approval policy."""

    mode: str = "ask"
    callback: ApprovalCallback | None = None

    def approve(self, tool: Tool, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Synchronously return whether a tool invocation may proceed.

        This compatibility method is for non-interactive callers.  The agent
        loop uses :meth:`approve_async`, so a terminal UI can safely ask for
        confirmation without blocking the event loop.
        """
        approved, reason = self._policy(tool)
        if not approved or not tool.mutating or self.mode != "ask":
            return approved, reason
        if self.callback is None:
            return False, "approval required but no interactive approver is available"
        try:
            decision = self.callback(tool.name, arguments)
        except Exception as exc:
            return False, f"approval prompt failed: {exc}"
        if inspect.isawaitable(decision):
            # Do not leak an unawaited coroutine when a caller accidentally
            # uses the synchronous API with an async terminal approver.
            close = getattr(decision, "close", None)
            if callable(close):
                close()
            return False, "approval requires an asynchronous interactive approver"
        if decision:
            return True, ""
        return False, "user denied approval"

    async def approve_async(
        self, tool: Tool, arguments: dict[str, Any]
    ) -> tuple[bool, str]:
        """Return whether a tool may proceed, awaiting an approver if needed."""
        approved, reason = self._policy(tool)
        if not approved or not tool.mutating or self.mode != "ask":
            return approved, reason
        if self.callback is None:
            return False, "approval required but no interactive approver is available"
        try:
            decision = self.callback(tool.name, arguments)
            if inspect.isawaitable(decision):
                decision = await decision
        except Exception as exc:
            return False, f"approval prompt failed: {exc}"
        if decision:
            return True, ""
        return False, "user denied approval"

    def _policy(self, tool: Tool) -> tuple[bool, str]:
        """Apply the non-interactive portion of the approval policy."""
        if not tool.mutating:
            return True, ""
        if self.mode == "auto":
            return True, ""
        if self.mode == "plan":
            return False, "approval mode 'plan' is read-only"
        if self.mode != "ask":
            return False, f"unknown approval mode: {self.mode}"
        return True, ""
