from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Any

from blazecode.tools.base import OutputCallback, Tool, ToolResult, error_result


class BashTool(Tool):
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

    async def run(
        self,
        arguments: dict[str, Any],
        cwd: Path,
        *,
        on_output: OutputCallback | None = None,
    ) -> ToolResult:
        process: asyncio.subprocess.Process | None = None
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
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    _drain(process, on_output), timeout
                )
            except TimeoutError:
                await _kill_process(process)
                return ToolResult(
                    f"Error: command timed out after {timeout}s", is_error=True
                )
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            combined = out
            if err:
                combined = f"{out}{err}" if out else err
            text = combined[-100_000:]
            if process.returncode:
                return ToolResult(
                    f"Exit code {process.returncode}\n{text}".rstrip(), is_error=True
                )
            return ToolResult(text.rstrip() or "(no output)")
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                await _kill_process(process)
            raise
        except (KeyError, OSError, ValueError) as exc:
            if process is not None and process.returncode is None:
                await _kill_process(process)
            return error_result(exc)
        finally:
            if process is not None and process.returncode is None:
                await _kill_process(process)


async def _drain(
    process: asyncio.subprocess.Process,
    on_output: OutputCallback | None,
) -> tuple[bytes, bytes]:
    stdout_parts: list[bytes] = []
    stderr_parts: list[bytes] = []

    async def read(stream: asyncio.StreamReader | None, parts: list[bytes]) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            parts.append(chunk)
            if on_output is not None:
                on_output(chunk.decode("utf-8", errors="replace"))

    await asyncio.gather(
        read(process.stdout, stdout_parts),
        read(process.stderr, stderr_parts),
        process.wait(),
    )
    return b"".join(stdout_parts), b"".join(stderr_parts)


async def _kill_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    pid = process.pid
    try:
        if pid is not None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                process.kill()
        else:
            process.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except (TimeoutError, ProcessLookupError):
        pass
