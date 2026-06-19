"""Exact search-and-replace edit."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool


class EditTool(Tool):
    name = "edit"
    description = (
        "Replace an exact, uniquely-occurring string in a file. "
        "old_string must appear exactly once. Use 'write' for new files or full rewrites."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    }
    requires_approval = True

    async def run(self, **kwargs: Any) -> str:
        path = kwargs.get("path")
        old = kwargs.get("old_string")
        new = kwargs.get("new_string")
        if not isinstance(path, str) or not path:
            return "error: 'path' is required"
        if not isinstance(old, str):
            return "error: 'old_string' must be a string"
        if not isinstance(new, str):
            return "error: 'new_string' must be a string"
        p = Path(path).expanduser()
        if not p.exists():
            return f"error: file not found: {p}"
        if not p.is_file():
            return f"error: not a regular file: {p}"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"error: could not read {p}: {exc}"

        occurrences = text.count(old)
        if occurrences == 0:
            return (
                f"error: old_string not found in {p}. "
                "Check whitespace and indentation exactly."
            )
        if occurrences > 1:
            return (
                f"error: old_string matches {occurrences} places in {p}. "
                "Provide more surrounding context so it matches exactly once."
            )
        new_text = text.replace(old, new, 1)
        try:
            p.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            return f"error: could not write {p}: {exc}"
        return f"edited {p}: replaced {len(old)} chars with {len(new)} chars"

    def preview(self, *, path: str, old_string: str, new_string: str, **_kwargs: Any) -> str:
        p = Path(path).expanduser()
        header = f"edit {p}"
        if not p.exists():
            return header + "\n  (file does not yet exist; use 'write' to create it)"
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return header + f"\n  (could not read existing file: {exc})"
        old_lines = text.splitlines()
        new_lines = text.replace(old_string, new_string, 1).splitlines()
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{p.name}", tofile=f"b/{p.name}", lineterm="",
        )
        body = "\n".join(diff)
        return header + ("\n" + body if body else "\n  (no changes)")
