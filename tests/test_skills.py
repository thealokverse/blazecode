from __future__ import annotations

from pathlib import Path

import pytest

from blazecode.agent.prompts import build_system_prompt
from blazecode.agent.tool_events import execute_tool
from blazecode.context.skills import discover_skills, load_skill, parse_skill, select_skills
from blazecode.llm.client import ToolCallStart
from blazecode.permissions.approval import ApprovalManager


def _write_skill(root: Path, name: str, description: str, body: str = "Do the thing.") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    path = folder / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_valid_and_invalid_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    _write_skill(tmp_path / "skills", "code-review", "Review code for correctness.")
    (tmp_path / "skills" / "broken").mkdir()
    (tmp_path / "skills" / "broken" / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
    (tmp_path / "skills" / "empty").mkdir()
    (tmp_path / "skills" / "empty" / "SKILL.md").write_text(
        "---\nname: empty\n---\n", encoding="utf-8"
    )
    found = discover_skills(tmp_path, trusted=True)
    assert [skill.name for skill in found] == ["code-review"]
    assert parse_skill(tmp_path / "skills" / "broken" / "SKILL.md", "project") is None


def test_project_skill_overrides_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BLAZECODE_HOME", str(home))
    _write_skill(home / "skills", "python", "Global python help.")
    _write_skill(tmp_path / "skills", "python", "Project python help.")
    found = discover_skills(tmp_path, trusted=True)
    assert len(found) == 1
    assert found[0].origin == "project"
    assert "Project" in found[0].description


def test_untrusted_skips_project_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BLAZECODE_HOME", str(home))
    _write_skill(tmp_path / "skills", "local", "Project only skill.")
    _write_skill(home / "skills", "global", "Global skill for tests.")
    found = discover_skills(tmp_path, trusted=False)
    assert [skill.name for skill in found] == ["global"]


def test_lazy_loading_and_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    _write_skill(tmp_path / "skills", "code-review", "Review code for correctness.")
    _write_skill(tmp_path / "skills", "testing", "Write and run unit tests.")
    catalog = discover_skills(tmp_path)
    selected = select_skills(catalog, "please review this code")
    assert [skill.name for skill in selected] == ["code-review"]
    body = load_skill(selected[0])
    assert "Do the thing." in body
    prompt = build_system_prompt(tmp_path, skill_index=catalog, loaded_skills=[])
    assert "code-review" in prompt
    assert "Do the thing." not in prompt
    loaded = build_system_prompt(
        tmp_path, skill_index=catalog, loaded_skills=[(selected[0], body)]
    )
    assert "Do the thing." in loaded


@pytest.mark.asyncio
async def test_skill_cannot_bypass_permissions(tmp_path: Path) -> None:
    result = await execute_tool(
        ToolCallStart("1", "write", {"path": "secret.txt", "content": "x"}),
        tmp_path,
        ApprovalManager("on"),
        trusted=True,
    )
    assert result.is_error
    assert "approval required" in result.content
    assert not (tmp_path / "secret.txt").exists()
