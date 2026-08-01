from __future__ import annotations

import os
import subprocess
from pathlib import Path

from blazecode.skills.loader import SkillLoader

BASE_PROMPT = """\
You are Blazecode, a fast terminal coding agent. Use tools to work in the project.
Be decisive. Prefer action over long plans. Keep replies short.

Rules:
- Read or grep before editing. Never invent file contents or command output.
- edit = precise change; write = new/full file; bash = foreground only.
- One tool at a time when possible. After a tool result, continue or finish.
- Paths stay inside the working directory.
- Never claim success unless a tool result confirms it.
- If a tool fails, fix the args once. do not loop the same call.
- Do not expose secrets.

Project instructions below override style preferences (not safety).
"""

_CONTEXT_LINE_LIMIT = 100
_LISTING_LIMIT = 80


def _truncate_lines(text: str, limit: int = _CONTEXT_LINE_LIMIT) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text.strip()
    return "\n".join(lines[:limit]).rstrip() + "\n… (truncated)"


def project_instructions(cwd: Path) -> str:
    for name in ("AGENTS.md", "BLAZECODE.md", "README.md"):
        path = cwd / name
        if path.is_file():
            try:
                return _truncate_lines(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return ""


def directory_listing(cwd: Path) -> str:
    root = cwd.resolve()
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = result.stdout.splitlines()[:_LISTING_LIMIT]
            extra = len(result.stdout.splitlines()) - len(files)
            body = "\n".join(files)
            if extra > 0:
                body += f"\n… ({extra} more files)"
            return body
    except (OSError, subprocess.SubprocessError, TimeoutError):
        pass
    try:
        entries = sorted(os.listdir(root))
        visible = [
            name + ("/" if (root / name).is_dir() else "")
            for name in entries
            if not name.startswith(".")
        ][:_LISTING_LIMIT]
        return "\n".join(visible)
    except OSError:
        return ""


def build_system_prompt(cwd: Path, skill_loader: SkillLoader) -> str:
    resolved = cwd.resolve()
    sections = [BASE_PROMPT, f"Working directory: {resolved}"]
    listing = directory_listing(resolved)
    if listing:
        sections.append(f"<project_files>\n{listing}\n</project_files>")
    instructions = project_instructions(resolved)
    if instructions:
        sections.append(
            f"<project_instructions>\n{instructions}\n</project_instructions>"
        )
    sections.append(skill_loader.summary())
    sections.append(
        "When a skill is relevant, its complete instructions will be supplied "
        "for that turn; follow them before acting."
    )
    return "\n\n".join(sections)


def relevant_skill_prompt(prompt: str, loader: SkillLoader) -> str:
    selected = loader.relevant(prompt)
    if not selected:
        return ""
    blocks = [
        f"<skill name={skill.name!r}>\n{skill.read()}\n</skill>" for skill in selected
    ]
    return "\n\n".join(blocks)
