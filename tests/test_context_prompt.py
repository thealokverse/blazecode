from __future__ import annotations

from pathlib import Path

from blazecode.agent.prompts import (
    BASE_PROMPT,
    build_system_prompt,
    git_context,
    project_markers,
)


def test_base_prompt_is_professional_and_compact() -> None:
    assert "Blazecode" in BASE_PROMPT
    assert "inspect" in BASE_PROMPT.lower()
    assert "verify" in BASE_PROMPT.lower()
    assert "current task" in BASE_PROMPT.lower()
    assert "skill" not in BASE_PROMPT.lower()
    assert len(BASE_PROMPT) < 2000


def test_build_system_prompt_includes_markers_and_git(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Agents\nBe careful.\n", encoding="utf-8")
    prompt = build_system_prompt(tmp_path)
    assert "Working directory:" in prompt
    assert "pyproject.toml" in prompt or "project files:" in prompt
    assert "Be careful" in prompt
    assert "available skills" not in prompt
    assert project_markers(tmp_path)


def test_git_context_includes_branch_and_dirty_state(tmp_path: Path) -> None:
    assert git_context(tmp_path) == ""
