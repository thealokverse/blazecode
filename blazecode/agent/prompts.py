"""System prompt and project instruction loading."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from blazecode.skills.loader import SkillLoader

BASE_PROMPT = """\
You are Blazecode, a concise terminal coding agent. Work directly in the current
project using the available tools. Inspect existing code before editing it,
preserve project conventions, and validate changes with relevant tests.

Tool rules:
- Use read and grep to understand code before changing it.
- When asked to explain a file, directory, or repository, always use the read
  (and grep if needed) tools to inspect the actual sources before answering.
  Never invent file contents or structure.
- Use edit for precise changes to existing files and write for complete files.
- Use bash for foreground commands only. Never start background processes.
- Never claim a command or edit succeeded unless its tool result says it did.
- Paths must stay inside the current working directory.

Keep user-facing responses concise. Do not expose secrets. Project instructions
below override general preferences when they do not conflict with safety.
"""

_CONTEXT_LINE_LIMIT = 100
_LISTING_LIMIT = 80


def _truncate_lines(text: str, limit: int = _CONTEXT_LINE_LIMIT) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text.strip()
    return "\n".join(lines[:limit]).rstrip() + "\n… (truncated)"


def project_instructions(cwd: Path) -> str:
    """Load AGENTS.md, BLAZECODE.md, or README.md from the working directory."""
    for name in ("AGENTS.md", "BLAZECODE.md", "README.md"):
        path = cwd / name
        if path.is_file():
            try:
                return _truncate_lines(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return ""


def directory_listing(cwd: Path) -> str:
    """Return a shallow listing of project files for system context."""
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
    """Build the stable system prompt for a session."""
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
    """Load complete instructions only for skills relevant to this turn."""
    selected = loader.relevant(prompt)
    if not selected:
        return ""
    blocks = [
        f"<skill name={skill.name!r}>\n{skill.read()}\n</skill>" for skill in selected
    ]
    return "\n\n".join(blocks)
