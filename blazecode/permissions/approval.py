from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from blazecode.tools.base import Tool

ApprovalCallback = Callable[[str, dict[str, Any]], bool | Awaitable[bool]]


@dataclass(slots=True)
class ApprovalManager:
    mode: str = "ask"
    callback: ApprovalCallback | None = None

    def approve(self, tool: Tool, arguments: dict[str, Any]) -> tuple[bool, str]:
        # sync path for non interactive callers. agent loop uses approve_async.
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
            # close unawaited coroutine if sync api was used with an async approver
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
        if not tool.mutating:
            return True, ""
        if self.mode == "auto":
            return True, ""
        if self.mode == "plan":
            return False, "approval mode 'plan' is read-only"
        if self.mode != "ask":
            return False, f"unknown approval mode: {self.mode}"
        return True, ""
