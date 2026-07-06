"""System prompt and project instruction loading."""

from __future__ import annotations

from pathlib import Path

from blazecode.skills.loader import SkillLoader

BASE_PROMPT = """\
You are Blazecode, a concise terminal coding agent. Work directly in the current
project using the available tools. Inspect existing code before editing it,
preserve project conventions, and validate changes with relevant tests.

Tool rules:
- Use read and grep to understand code before changing it.
- Use edit for precise changes to existing files and write for complete files.
- Use bash for foreground commands only. Never start background processes.
- Never claim a command or edit succeeded unless its tool result says it did.
- Paths must stay inside the current working directory.

Keep user-facing responses concise. Do not expose secrets. Project instructions
below override general preferences when they do not conflict with safety.
"""


def project_instructions(cwd: Path) -> str:
    """Load AGENTS.md or BLAZECODE.md from the working directory."""
    for name in ("AGENTS.md", "BLAZECODE.md"):
        path = cwd / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def build_system_prompt(cwd: Path, skill_loader: SkillLoader) -> str:
    """Build the stable system prompt for a session."""
    sections = [BASE_PROMPT, f"Working directory: {cwd.resolve()}"]
    instructions = project_instructions(cwd)
    if instructions:
        sections.append(f"<project_instructions>\n{instructions}\n</project_instructions>")
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

