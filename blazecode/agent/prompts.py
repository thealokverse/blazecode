from __future__ import annotations

import os
import subprocess
from pathlib import Path

BASE_PROMPT = """\
You are Blazecode, a professional terminal coding agent in this repository.

The latest user message is the current task. Use the project files, git state, and project instructions below. Stay aligned with that task.

Workflow: inspect → plan when useful → act → verify → report.

Rules:
- Inspect relevant code with tools before editing. Never invent file contents or command output.
- Prefer the smallest correct change. Do not refactor unrelated code.
- edit for precise edits; write for new or full-file rewrites; bash only for foreground commands.
- Paths must stay inside the working directory.
- After tool results, continue or finish. Do not repeat the same failing call.
- Never claim a change, test, or success unless a tool result confirms it.
- Be honest about uncertainty. Ask only when a real ambiguity blocks progress.
- Do not expose secrets.
- For multi-step work, use the todo tool to track progress. Skip todos for trivial requests.

AGENTS.md overrides style preferences, not safety.
"""

_CONTEXT_LINE_LIMIT = 100
_LISTING_LIMIT = 80
_AGENTS_FILE = "AGENTS.md"
_PROJECT_MARKERS = (
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "Gemfile",
    "mix.exs",
    "CMakeLists.txt",
    "Makefile",
    "requirements.txt",
    "Pipfile",
    "poetry.lock",
    "uv.lock",
    "tsconfig.json",
)


def _truncate_lines(text: str, limit: int = _CONTEXT_LINE_LIMIT) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text.strip()
    return "\n".join(lines[:limit]).rstrip() + "\n… (truncated)"


def _run_git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_context(cwd: Path) -> str:
    root = _run_git(cwd, "rev-parse", "--show-toplevel")
    if not root:
        return ""
    branch = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    status = _run_git(cwd, "status", "--porcelain")
    dirty = "dirty" if status else "clean"
    lines = [f"git root: {root}", f"branch: {branch}", f"status: {dirty}"]
    if status:
        changed = status.splitlines()[:20]
        lines.append("changes:\n" + "\n".join(changed))
        extra = len(status.splitlines()) - len(changed)
        if extra > 0:
            lines.append(f"… ({extra} more)")
    return "\n".join(lines)


def project_markers(cwd: Path) -> str:
    found = [name for name in _PROJECT_MARKERS if (cwd / name).is_file()]
    if not found:
        return ""
    return "project files: " + ", ".join(found)


def project_instructions(cwd: Path) -> str:
    # nearest AGENTS.md from cwd up to git root (or cwd only if not a repo)
    root = cwd.resolve()
    git_root = _run_git(root, "rev-parse", "--show-toplevel")
    stop = Path(git_root).resolve() if git_root else root
    candidates: list[Path] = []
    current = root
    while True:
        path = current / _AGENTS_FILE
        if path.is_file():
            candidates.append(path)
        if current == stop or current.parent == current:
            break
        current = current.parent
    if not candidates:
        return ""
    # nearest first, then parents (more specific overrides later in prompt order)
    blocks: list[str] = []
    for path in reversed(candidates):
        try:
            text = _truncate_lines(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if text:
            blocks.append(f"# from {path}\n{text}")
    return "\n\n".join(blocks)


def directory_listing(cwd: Path) -> str:
    root = cwd.resolve()
    listing = _run_git(root, "ls-files")
    if listing:
        files = listing.splitlines()[:_LISTING_LIMIT]
        extra = len(listing.splitlines()) - len(files)
        body = "\n".join(files)
        if extra > 0:
            body += f"\n… ({extra} more files)"
        return body
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


def build_system_prompt(
    cwd: Path,
) -> str:
    resolved = cwd.resolve()
    sections = [BASE_PROMPT, f"Working directory: {resolved}"]
    markers = project_markers(resolved)
    if markers:
        sections.append(markers)
    git = git_context(resolved)
    if git:
        sections.append(f"<git>\n{git}\n</git>")
    listing = directory_listing(resolved)
    if listing:
        sections.append(f"<project_files>\n{listing}\n</project_files>")
    instructions = project_instructions(resolved)
    if instructions:
        sections.append(
            f"<project_instructions>\n{instructions}\n</project_instructions>"
        )
    return "\n\n".join(sections)
