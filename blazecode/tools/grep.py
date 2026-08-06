from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from blazecode.tools.base import OutputCallback, Tool, ToolResult, error_result, resolve_path

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
        "target",
        ".eggs",
        "eggs",
        ".idea",
        ".vscode",
        "vendor",
        "coverage",
        "htmlcov",
    }
)


class GrepTool(Tool):
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

    async def run(
        self,
        arguments: dict[str, Any],
        cwd: Path,
        *,
        on_output: OutputCallback | None = None,
    ) -> ToolResult:
        try:
            regex = re.compile(str(arguments["pattern"]))
            target = resolve_path(cwd, str(arguments.get("path", ".")))
            include = str(arguments.get("include", "*"))
            maximum = int(arguments.get("max_results", 200))
            if maximum < 1 or maximum > 1000:
                raise ValueError("max_results must be between 1 and 1000")
            root = cwd.resolve()
            matches: list[str] = []
            if target.is_file():
                _search_file(target, root, regex, include, matches, maximum)
            else:
                _walk(str(target), root, regex, include, matches, maximum)
            suffix = "\n(result limit reached)" if len(matches) >= maximum else ""
            return ToolResult(
                ("\n".join(matches) + suffix) if matches else "No matches found."
            )
        except (KeyError, OSError, re.error, ValueError) as exc:
            return error_result(exc)


def _walk(
    directory: str,
    root: Path,
    regex: re.Pattern[str],
    include: str,
    matches: list[str],
    maximum: int,
) -> None:
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(matches) >= maximum:
                    return
                name = entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if name in _SKIP_DIRS:
                            continue
                        _walk(entry.path, root, regex, include, matches, maximum)
                    elif entry.is_file(follow_symlinks=False):
                        _search_file(
                            Path(entry.path), root, regex, include, matches, maximum
                        )
                except OSError:
                    continue
    except OSError:
        return


def _search_file(
    path: Path,
    root: Path,
    regex: re.Pattern[str],
    include: str,
    matches: list[str],
    maximum: int,
) -> None:
    if len(matches) >= maximum:
        return
    if not fnmatch.fnmatch(path.name, include):
        return
    try:
        if path.stat().st_size > 2_000_000:
            return
        data = path.read_bytes()
    except OSError:
        return
    if b"\x00" in data:
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    relative = path.relative_to(root)
    for number, line in enumerate(text.splitlines(), start=1):
        if regex.search(line):
            matches.append(f"{relative}:{number}:{line}")
            if len(matches) >= maximum:
                return
