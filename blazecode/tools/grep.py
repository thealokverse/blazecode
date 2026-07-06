"""Portable in-process text-search tool."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from blazecode.tools.base import Tool, ToolResult, error_result, resolve_path


class GrepTool(Tool):
    """Search files recursively with a regular expression."""

    name = "grep"
    description = "Search text files with a regular expression and return matching lines."
    schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "path": {
                "type": "string",
                "default": ".",
                "description": "File or directory to search.",
            },
            "include": {
                "type": "string",
                "default": "*",
                "description": "Filename glob such as '*.py'.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 1000,
                "default": 200,
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    async def run(self, arguments: dict[str, Any], cwd: Path) -> ToolResult:
        """Search matching files without starting a subprocess."""
        try:
            regex = re.compile(str(arguments["pattern"]))
            target = resolve_path(cwd, str(arguments.get("path", ".")))
            include = str(arguments.get("include", "*"))
            maximum = int(arguments.get("max_results", 200))
            if maximum < 1 or maximum > 1000:
                raise ValueError("max_results must be between 1 and 1000")
            files = [target] if target.is_file() else target.rglob("*")
            matches: list[str] = []
            skipped = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv"}
            for path in files:
                if len(matches) >= maximum:
                    break
                if not path.is_file() or any(part in skipped for part in path.parts):
                    continue
                if not fnmatch.fnmatch(path.name, include):
                    continue
                try:
                    data = path.read_bytes()
                    if b"\x00" in data or len(data) > 5_000_000:
                        continue
                    for number, line in enumerate(
                        data.decode("utf-8").splitlines(), start=1
                    ):
                        if regex.search(line):
                            relative = path.relative_to(cwd.resolve())
                            matches.append(f"{relative}:{number}:{line}")
                            if len(matches) >= maximum:
                                break
                except (OSError, UnicodeDecodeError):
                    continue
            suffix = "\n(result limit reached)" if len(matches) >= maximum else ""
            return ToolResult(
                ("\n".join(matches) + suffix) if matches else "No matches found."
            )
        except (KeyError, OSError, re.error, ValueError) as exc:
            return error_result(exc)

