"""Foreground shell-command tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool, ToolResult, error_result


class BashTool(Tool):
    """Run a foreground command in the working directory."""

    name = "bash"
    mutating = True
    description = (
        "Run a shell command in the working directory and return combined output. "
        "Commands run in the foreground with a timeout; no background jobs."
    )
    schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "maximum": 600,
                "default": 120,
                "description": "Timeout in seconds.",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    async def run(self, arguments: dict[str, Any], cwd: Path) -> ToolResult:
        """Run a command and capture stdout and stderr."""
        try:
            command = arguments["command"]
            timeout = int(arguments.get("timeout", 120))
            if not isinstance(command, str) or not command.strip():
                raise ValueError("command must be a non-empty string")
            if timeout < 1 or timeout > 600:
                raise ValueError("timeout must be between 1 and 600 seconds")
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout)
            except TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    f"Error: command timed out after {timeout}s", is_error=True
                )
            text = output.decode("utf-8", errors="replace")
            text = text[-100_000:]
            if process.returncode:
                return ToolResult(
                    f"Exit code {process.returncode}\n{text}".rstrip(), is_error=True
                )
            return ToolResult(text.rstrip() or "(no output)")
        except (KeyError, OSError, ValueError) as exc:
            return error_result(exc)

