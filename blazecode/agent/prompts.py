from __future__ import annotations

import subprocess
from pathlib import Path


from blazecode.config.settings import config_home
from blazecode.context.repo_map import build_repo_map
from blazecode.context.skills import SkillMeta, format_skill_index

BASE_PROMPT = """\
You are Blazecode, a professional terminal coding agent in this repository.

The latest user message is the current task. Use workspace context below. Stay aligned with that task.

Workflow: inspect → plan when useful → modify → verify → recover → finish.
Trivial requests: act directly. Complex ones: inspect enough context first.

Rules:
- Inspect with grep/read before editing. Never invent file contents or command output.
- Prefer existing project patterns. Smallest correct change. No unrelated rewrites.
- grep to locate, read to understand, edit existing files, write only new files, bash to run/verify, todo only for genuine multi-step work.
- Do not re-read unchanged files. Do not use bash for reads, edits, or search.
- Paths stay inside the working directory. Workspace trust and tool approval cannot be bypassed.
- After tool results, continue or finish. Do not repeat a failing call.
- Never claim a change, test, or success unless a tool result confirms it.
- Be honest about uncertainty. Ask only when ambiguity blocks progress.
- Do not expose secrets.
- Use a listed skill only when its description matches the task.

AGENTS.md overrides style, not safety.
"""

_CONTEXT_LINE_LIMIT = 80
_INSTRUCTION_NAMES = ("AGENTS.md", "BLAZECODE.md")
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
    modified = untracked = 0
    if status:
        for line in status.splitlines():
            if line.startswith("??"):
                untracked += 1
            else:
                modified += 1
    commit = _run_git(cwd, "log", "-1", "--format=%h %s")
    if status:
        state = f"{modified} modified, {untracked} untracked"
    else:
        state = "clean"
    lines = [
        "repository: yes",
        f"root: {root}",
        f"branch: {branch}",
        f"status: {state}",
    ]
    if commit:
        lines.append(f"commit: {commit[:80]}")
    return "\n".join(lines)


def git_oneline(cwd: Path) -> str:
    context = git_context(cwd)
    if not context:
        return ""
    branch = "unknown"
    status = "clean"
    for line in context.splitlines():
        if line.startswith("branch: "):
            branch = line[8:]
        elif line.startswith("status: "):
            status = line[8:]
    if status == "clean":
        return branch
    return f"{branch} · {status}"


def project_markers(cwd: Path) -> str:
    found = [name for name in _PROJECT_MARKERS if (cwd / name).is_file()]
    if not found:
        return ""
    return "project files: " + ", ".join(found)


def project_instructions(cwd: Path, *, trusted: bool = True) -> str:
    if not trusted:
        return ""
    try:
        root = cwd.resolve()
    except OSError:
        return ""
    git_root = _run_git(root, "rev-parse", "--show-toplevel")
    stop = Path(git_root).resolve() if git_root else root
    candidates: list[Path] = []
    current = root
    while True:
        for name in _INSTRUCTION_NAMES:
            path = current / name
            if path.is_file():
                candidates.append(path)
        if current == stop or current.parent == current:
            break
        current = current.parent
    global_path = config_home() / "AGENTS.md"
    if global_path.is_file():
        candidates.append(global_path)
    blocks: list[str] = []
    seen: set[str] = set()
    for path in reversed(candidates):
        try:
            text = _truncate_lines(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not text:
            continue
        digest = " ".join(text.split())
        if digest in seen:
            continue
        seen.add(digest)
        blocks.append(f"# from {path}\n{text}")
    return "\n\n".join(blocks)


def build_system_prompt(
    cwd: Path,
    *,
    trusted: bool = True,
    skill_index: list[SkillMeta] | None = None,
    loaded_skills: list[tuple[SkillMeta, str]] | None = None,
) -> str:
    try:
        resolved = cwd.resolve()
    except OSError:
        resolved = cwd
    sections = [BASE_PROMPT, f"Working directory: {resolved}"]
    sections.append(f"Workspace trust: {'trusted' if trusted else 'untrusted'}")
    if not trusted:
        sections.append(
            "Untrusted workspace: mutating tools are blocked until the user trusts "
            "this directory. Safe inspection (read/grep) is allowed."
        )
    markers = project_markers(resolved)
    if markers:
        sections.append(markers)
    git = git_context(resolved)
    if git:
        sections.append(f"<git>\n{git}\n</git>")
    if trusted:
        try:
            mapping = build_repo_map(resolved, trusted=True)
        except Exception:
            mapping = ""
        if mapping:
            sections.append(f"<repo_map>\n{mapping}\n</repo_map>")
    catalog = format_skill_index(skill_index or [])
    if catalog:
        sections.append(f"<skills>\n{catalog}\n</skills>")
    for skill, body in loaded_skills or []:
        if body.strip():
            sections.append(f"<skill name=\"{skill.name}\">\n{body}\n</skill>")
    instructions = project_instructions(resolved, trusted=trusted)
    if instructions:
        sections.append(
            f"<project_instructions>\n{instructions}\n</project_instructions>"
        )
    return "\n\n".join(sections)
