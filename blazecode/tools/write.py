"""Write-file tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool, ToolResult, error_result, resolve_path

_DIFF_CHAR_LIMIT = 200_000


class WriteTool(Tool):
    """Create or replace a UTF-8 text file."""

    name = "write"
    mutating = True
    description = "Write complete UTF-8 content to a file, creating parents as needed."
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write."},
            "content": {"type": "string", "description": "Complete new file content."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    async def run(self, arguments: dict[str, Any], cwd: Path) -> ToolResult:
        """Write the supplied content and return its diff."""
        from difflib import unified_diff

        try:
            path = resolve_path(cwd, str(arguments["path"]), must_exist=False)
            content = arguments["content"]
            if content is None:
                raise ValueError("content is required")
            if not isinstance(content, str):
                content = str(content)
            old = ""
            if path.exists():
                try:
                    old = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    old = path.read_bytes().decode("utf-8", errors="replace")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
            relative = path.relative_to(cwd.resolve())
            if len(old) + len(content) > _DIFF_CHAR_LIMIT:
                diff = f"(diff omitted for large file: {relative})"
            else:
                diff = "".join(
                    unified_diff(
                        old.splitlines(keepends=True),
                        content.splitlines(keepends=True),
                        fromfile=f"a/{relative}",
                        tofile=f"b/{relative}",
                    )
                )
            return ToolResult(f"Wrote {relative}", diff=diff)
        except (KeyError, OSError, UnicodeDecodeError, UnicodeEncodeError, ValueError) as exc:
            return error_result(exc)
