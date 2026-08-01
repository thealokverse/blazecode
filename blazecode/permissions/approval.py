from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from blazecode.tools.base import Tool

ApprovalCallback = Callable[[str, dict[str, Any]], bool | Awaitable[bool]]

# tools that require a yes/no when approval is on
_SHELL_TOOLS = frozenset({"bash"})
_LEGACY_MODE = {"ask": "on", "auto": "off", "plan": "on"}


@dataclass(slots=True)
class ApprovalManager:
    # on: prompt before shell commands. off: run everything without prompts.
    mode: str = "on"
    callback: ApprovalCallback | None = None

    def approve(self, tool: Tool, arguments: dict[str, Any]) -> tuple[bool, str]:
        # sync path for non interactive callers. agent loop uses approve_async.
        if not self._needs_prompt(tool):
            return True, ""
        return self._decide_sync(tool.name, arguments)

    async def approve_async(
        self, tool: Tool, arguments: dict[str, Any]
    ) -> tuple[bool, str]:
        if not self._needs_prompt(tool):
            return True, ""
        return await self._decide_async(tool.name, arguments)

    def _normalized_mode(self) -> str:
        return _LEGACY_MODE.get(self.mode, self.mode)

    def _needs_prompt(self, tool: Tool) -> bool:
        if self._normalized_mode() != "on":
            return False
        return tool.name in _SHELL_TOOLS

    def _decide_sync(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        if self.callback is None:
            return False, "approval required but no interactive approver is available"
        try:
            decision = self.callback(name, arguments)
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

    async def _decide_async(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[bool, str]:
        if self.callback is None:
            return False, "approval required but no interactive approver is available"
        try:
            decision = self.callback(name, arguments)
            if inspect.isawaitable(decision):
                decision = await decision
        except Exception as exc:
            return False, f"approval prompt failed: {exc}"
        if decision:
            return True, ""
        return False, "user denied approval"
