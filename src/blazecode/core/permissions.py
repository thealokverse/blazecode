"""Approval policy for destructive tool calls."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PermissionPolicy:
    """Controls when tool calls require user approval.

    Modes:
      - "ask"        : every requires_approval tool triggers a prompt (default).
      - "auto"       : approve everything (set via --yolo or /yolo).
      - "deny-shell" : approve file writes/edits, but always ask for shell.
    """

    mode: str = "ask"
    _approve_all: bool = False

    def set_mode(self, mode: str) -> None:
        if mode not in {"ask", "auto", "deny-shell"}:
            raise ValueError(
                f"unknown permission mode: {mode!r} (expected ask/auto/deny-shell)"
            )
        self.mode = mode

    def approve_all_for_session(self) -> None:
        self._approve_all = True

    def requires_prompt(self, tool_name: str, *, tool_requires_approval: bool) -> bool:
        if self.mode == "auto" or self._approve_all:
            return False
        if not tool_requires_approval:
            return False
        if self.mode == "deny-shell" and tool_name != "shell":
            return False
        return True
