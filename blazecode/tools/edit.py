"""Exact find-and-replace editing tool."""

from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool, ToolResult, error_result, resolve_path


class EditTool(Tool):
    """Apply a deterministic exact-string replacement."""

    name = "edit"
    mutating = True
    description = (
        "Replace an exact string in an existing UTF-8 file. Read the file first; "
        "by default the old string must occur exactly once."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Existing file path."},
            "old_string": {"type": "string", "description": "Exact text to replace."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {
                "type": "boolean",
                "default": False,
                "description": "Replace every occurrence instead of requiring one.",
            },
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    }

    async def run(self, arguments: dict[str, Any], cwd: Path) -> ToolResult:
        """Replace text and return a unified diff."""
        try:
            path = resolve_path(cwd, str(arguments["path"]))
            old_string = arguments["old_string"]
            new_string = arguments["new_string"]
            replace_all = arguments.get("replace_all", False)
            if not isinstance(old_string, str) or not isinstance(new_string, str):
                raise ValueError("old_string and new_string must be strings")
            if not isinstance(replace_all, bool):
                raise ValueError("replace_all must be a boolean")
            if not old_string:
                raise ValueError("old_string cannot be empty")
            old_content = path.read_text(encoding="utf-8")
            occurrences = old_content.count(old_string)
            if occurrences == 0:
                raise ValueError("old_string was not found")
            if occurrences > 1 and not replace_all:
                raise ValueError(
                    f"old_string occurs {occurrences} times; provide more context "
                    "or set replace_all"
                )
            new_content = old_content.replace(
                old_string, new_string, -1 if replace_all else 1
            )
            path.write_text(new_content, encoding="utf-8")
            relative = path.relative_to(cwd.resolve())
            diff = "".join(
                unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                )
            )
            return ToolResult(f"Edited {relative}", diff=diff)
        except (KeyError, OSError, UnicodeDecodeError, ValueError) as exc:
            return error_result(exc)

