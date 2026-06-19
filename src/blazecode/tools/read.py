"""Read a file with optional line range."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool

MAX_LINES = 2000


class ReadTool(Tool):
    name = "read"
    description = (
        "Read a file's contents with line numbers. Optionally pass start_line and "
        "end_line (1-indexed, inclusive) to read a slice. Files over ~2000 lines are truncated."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path."},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    requires_approval = False

    async def run(self, **kwargs: Any) -> str:
        path = kwargs.get("path")
        start = kwargs.get("start_line")
        end = kwargs.get("end_line")
        if not isinstance(path, str) or not path:
            return "error: 'path' is required"
        p = Path(path).expanduser()
        if not p.exists():
            return f"error: file not found: {p}"
        if not p.is_file():
            return f"error: not a regular file: {p}"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"error: could not read {p}: {exc}"

        lines = text.splitlines()
        total = len(lines)
        truncated = False
        if start is None and end is None and total > MAX_LINES:
            lines = lines[:MAX_LINES]
            truncated = True

        if start is not None or end is not None:
            s = (start if start is not None else 1) - 1
            e = end if end is not None else total
            s = max(0, s)
            e = min(total, e)
            lines = lines[s:e]
            first = s + 1
        else:
            first = 1

        body = "\n".join(f"{first + i:6d}\t{ln}" for i, ln in enumerate(lines))
        if truncated:
            body += f"\n\n... [truncated; file has {total} lines, showing first {MAX_LINES}]"
        elif start is not None or end is not None:
            body += f"\n\n[showing lines {first}-{first + len(lines) - 1} of {total}]"
        return body
