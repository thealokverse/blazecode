"""Run a shell command."""

from __future__ import annotations

import subprocess
from typing import Any

from blazecode.tools.base import Tool

DEFAULT_TIMEOUT = 120
MAX_OUTPUT_CHARS = 10_000


class ShellTool(Tool):
    name = "shell"
    description = (
        "Run an arbitrary shell command. Captures stdout/stderr. "
        "Returns the truncated combined output and exit code. Use sparingly; "
        "prefer dedicated tools (read/write/edit/grep) where possible."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 3600},
        },
        "required": ["command"],
        "additionalProperties": False,
    }
    requires_approval = True

    async def run(self, **kwargs: Any) -> str:
        command = kwargs.get("command")
        timeout = int(kwargs.get("timeout") or DEFAULT_TIMEOUT)
        if not isinstance(command, str) or not command.strip():
            return "error: 'command' is required"
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True,
                text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return f"error: command timed out after {timeout}s: {command}"
        except FileNotFoundError as exc:
            return f"error: could not invoke shell: {exc}"
        except OSError as exc:
            return f"error: {exc}"

        combined = (proc.stdout or "") + (proc.stderr or "")
        truncated = len(combined) > MAX_OUTPUT_CHARS
        if truncated:
            combined = combined[:MAX_OUTPUT_CHARS]
        suffix = f"\n... [output truncated at {MAX_OUTPUT_CHARS} chars]" if truncated else ""
        return f"exit {proc.returncode}\n{combined}{suffix}"

    def preview(self, *, command: str, timeout: int | None = None, **_kwargs: Any) -> str:
        t = timeout if timeout else DEFAULT_TIMEOUT
        return f"shell ({t}s timeout): {command}"
