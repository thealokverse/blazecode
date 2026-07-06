"""Read-file tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool, ToolResult, error_result, resolve_path


class ReadTool(Tool):
    """Read a bounded range of lines from a text file."""

    name = "read"
    description = "Read a UTF-8 text file with optional line offset and limit."
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
            "offset": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "First one-based line to return.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5000,
                "default": 1000,
                "description": "Maximum number of lines to return.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    async def run(self, arguments: dict[str, Any], cwd: Path) -> ToolResult:
        """Read the requested line range."""
        try:
            path = resolve_path(cwd, str(arguments["path"]))
            if not path.is_file():
                raise ValueError(f"not a file: {arguments['path']}")
            offset = int(arguments.get("offset", 1))
            limit = int(arguments.get("limit", 1000))
            if offset < 1 or limit < 1 or limit > 5000:
                raise ValueError("offset/limit are outside the allowed range")
            data = path.read_bytes()
            if b"\x00" in data:
                raise ValueError("binary files cannot be read")
            lines = data.decode("utf-8").splitlines()
            selected = lines[offset - 1 : offset - 1 + limit]
            numbered = [
                f"{number:>6}  {line}"
                for number, line in enumerate(selected, start=offset)
            ]
            if offset > len(lines) and lines:
                return ToolResult(
                    f"Error: offset {offset} exceeds file length {len(lines)}",
                    is_error=True,
                )
            return ToolResult("\n".join(numbered) or "(empty file)")
        except (KeyError, OSError, UnicodeDecodeError, ValueError) as exc:
            return error_result(exc)

