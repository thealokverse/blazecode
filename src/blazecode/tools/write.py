"""Create or fully overwrite a file."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool


class WriteTool(Tool):
    name = "write"
    description = (
        "Create or fully overwrite a file with the given content. "
        "Parent directories are created as needed. Prefer 'edit' for small changes."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }
    requires_approval = True

    async def run(self, **kwargs: Any) -> str:
        path = kwargs.get("path")
        content = kwargs.get("content")
        if not isinstance(path, str) or not path:
            return "error: 'path' is required"
        if not isinstance(content, str):
            return "error: 'content' must be a string"
        p = Path(path).expanduser()
        try:
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"error: could not write {p}: {exc}"
        return f"wrote {len(content)} bytes to {p}"

    def preview(self, *, path: str, content: str, **_kwargs: Any) -> str:
        p = Path(path).expanduser()
        header = f"write {p} ({len(content)} bytes, {len(content.splitlines())} lines)"
        if not p.exists():
            return header + "\n  (new file)"
        try:
            old = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return header + f"\n  (could not read existing file: {exc})"
        diff = difflib.unified_diff(
            old, content.splitlines(),
            fromfile=f"a/{p.name}", tofile=f"b/{p.name}", lineterm="",
        )
        body = "\n".join(diff)
        return header + ("\n" + body if body else "\n  (no changes)")
