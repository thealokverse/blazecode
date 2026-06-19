"""Glob file paths under cwd, respecting .gitignore."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Iterable

from blazecode.tools.base import Tool


def _load_gitignore(root: Path) -> list[str]:
    gi = root / ".gitignore"
    if not gi.is_file():
        return []
    out: list[str] = []
    try:
        for raw in gi.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    except OSError:
        return []
    return out


def _gitignored(rel: str, patterns: Iterable[str]) -> bool:
    parts = rel.split("/")
    name = parts[0]
    for pat in patterns:
        p = pat.rstrip("/")
        if p.startswith("**"):
            base = p.removeprefix("**/").removesuffix("/**")
            if not base or base in parts:
                return True
        if fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p):
            return True
        if any(fnmatch.fnmatch(part, p) for part in parts):
            return True
    return False


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    i, n, out = 0, len(pattern), ["^"]
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
                if i < n and pattern[i] == "/":
                    i += 1
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append("\\[")
            else:
                out.append(pattern[i : j + 1])
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


class GlobTool(Tool):
    name = "glob"
    description = "List file paths matching a glob (e.g. '**/*.py'). Honors .gitignore."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    requires_approval = False

    async def run(self, **kwargs: Any) -> str:
        pattern = kwargs.get("pattern")
        limit = int(kwargs.get("limit") or 200)
        if not isinstance(pattern, str) or not pattern:
            return "error: 'pattern' is required"
        cwd = Path.cwd()
        regex = _glob_to_regex(pattern)
        ignore = _load_gitignore(cwd)
        matches: list[str] = []
        for p in cwd.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(cwd).as_posix()
            except ValueError:
                continue
            if regex.match(rel) and not _gitignored(rel, ignore):
                matches.append(rel)
        matches.sort()
        if len(matches) > limit:
            matches = matches[:limit]
            truncated = True
        else:
            truncated = False
        if not matches:
            return f"(no matches for {pattern!r})"
        body = "\n".join(matches)
        if truncated:
            body += f"\n... [truncated to {limit} results]"
        return body
