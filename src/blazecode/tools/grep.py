"""Grep file contents with ripgrep if available, else pure-Python fallback."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool

MAX_RESULTS = 500
MAX_LINE_LEN = 500


def _python_grep(root: Path, pattern: str, include_glob: str | None) -> str:
    regex = re.compile(pattern)
    out: list[str] = []
    files = 0
    results = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if include_glob and not path.match(include_glob):
            continue
        files += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rel = path.relative_to(root).as_posix()
                snippet = line if len(line) <= MAX_LINE_LEN else line[:MAX_LINE_LEN] + "..."
                out.append(f"{rel}:{lineno}: {snippet}")
                results += 1
                if results >= MAX_RESULTS:
                    out.append(f"... [truncated at {MAX_RESULTS} matches]")
                    return "\n".join(out)
    if not out:
        return f"(no matches for {pattern!r} in {files} files)"
    return "\n".join(out)


class GrepTool(Tool):
    name = "grep"
    description = (
        "Search file contents for a regex, recursively. "
        "Uses ripgrep if available; falls back to a pure-Python walk."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "include": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    requires_approval = False

    async def run(self, **kwargs: Any) -> str:
        pattern = kwargs.get("pattern")
        include = kwargs.get("include")
        path = kwargs.get("path") or "."
        if not isinstance(pattern, str) or not pattern:
            return "error: 'pattern' is required"
        root = Path(path).expanduser()
        if root.exists() and not root.is_dir():
            return f"error: not a directory: {root}"
        rg = shutil.which("rg")
        if rg:
            cmd = [rg, "--line-number", "--no-heading", "--color=never",
                   "--max-columns=200", pattern, str(root)]
            if include:
                cmd.extend(["-g", include])
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                     timeout=60, check=False)
            except subprocess.TimeoutExpired:
                return "error: ripgrep timed out"
            if proc.returncode == 0:
                out = proc.stdout.rstrip()
                return out or f"(no matches for {pattern!r})"
            if proc.returncode == 1:
                return f"(no matches for {pattern!r})"
            return f"error: ripgrep failed (exit {proc.returncode}): {proc.stderr.strip()}"
        return _python_grep(root if root.is_dir() else Path.cwd(), pattern, include)
