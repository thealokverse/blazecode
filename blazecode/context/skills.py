from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from blazecode.config.settings import config_home

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n(.*))?\Z", re.S)
_TOKEN = re.compile(r"[a-z0-9]{3,}")
_MAX_BODY = 8_000


@dataclass(frozen=True, slots=True)
class SkillMeta:
    name: str
    description: str
    path: Path
    origin: str


def discover_skills(cwd: Path, *, trusted: bool = True) -> list[SkillMeta]:
    found: list[SkillMeta] = []
    seen: set[str] = set()
    for directory, origin in _skill_roots(cwd, trusted=trusted):
        if not directory.is_dir():
            continue
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            path = child / "SKILL.md" if child.is_dir() else child
            if path.name != "SKILL.md" or not path.is_file():
                continue
            meta = parse_skill(path, origin)
            if meta is None or meta.name in seen:
                continue
            seen.add(meta.name)
            found.append(meta)
    return found


def parse_skill(path: Path, origin: str) -> SkillMeta | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _FRONTMATTER.match(text)
    if not match:
        return None
    fields = _parse_frontmatter(match.group(1))
    name = (fields.get("name") or path.parent.name).strip()
    description = (fields.get("description") or "").strip()
    if not name or not description:
        return None
    if any(ch in name for ch in "/\\") or len(name) > 64:
        return None
    return SkillMeta(name=name, description=description[:240], path=path, origin=origin)


def load_skill(skill: SkillMeta) -> str:
    text = skill.path.read_text(encoding="utf-8", errors="replace")
    match = _FRONTMATTER.match(text)
    body = (match.group(2) if match else text).strip()
    if len(body) > _MAX_BODY:
        body = body[:_MAX_BODY].rstrip() + "\n… (skill truncated)"
    return body


def select_skills(
    catalog: list[SkillMeta], prompt: str, *, limit: int = 2
) -> list[SkillMeta]:
    if not catalog or not prompt.strip() or limit < 1:
        return []
    query = set(_TOKEN.findall(prompt.lower()))
    if not query:
        return []
    scored: list[tuple[int, SkillMeta]] = []
    for skill in catalog:
        haystack = f"{skill.name} {skill.description}".lower()
        tokens = set(_TOKEN.findall(haystack))
        overlap = len(query & tokens)
        if overlap == 0:
            continue
        # name hits count extra so `/skill code-review` still matches
        if skill.name.lower().replace("_", "-") in prompt.lower():
            overlap += 3
        scored.append((overlap, skill))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [skill for _score, skill in scored[:limit]]


def format_skill_index(catalog: list[SkillMeta]) -> str:
    if not catalog:
        return ""
    lines = []
    for skill in catalog[:24]:
        lines.append(f"- {skill.name} ({skill.origin}): {skill.description}")
    extra = len(catalog) - min(len(catalog), 24)
    if extra > 0:
        lines.append(f"- … {extra} more (use /skills)")
    return "\n".join(lines)


def _skill_roots(cwd: Path, *, trusted: bool) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    if trusted:
        try:
            current = cwd.expanduser().resolve()
        except OSError:
            current = cwd
        seen: set[Path] = set()
        for base in (current, _git_root(current)):
            if base is None or base in seen:
                continue
            seen.add(base)
            roots.append((base / "skills", "project"))
            roots.append((base / ".blazecode" / "skills", "project"))
    roots.append((config_home() / "skills", "global"))
    return roots


def _parse_frontmatter(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current: str | None = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        if current and (raw.startswith(" ") or raw.startswith("\t")):
            fields[current] = (fields[current] + " " + raw.strip()).strip()
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip().lower()
        if not key:
            continue
        fields[key] = value.strip().strip("\"'")
        current = key
    return fields


def _git_root(cwd: Path) -> Path | None:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return Path(result.stdout.strip()).resolve()
    except OSError:
        return None
