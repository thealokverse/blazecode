from __future__ import annotations

from pathlib import Path

from blazecode.session.message import Message
from blazecode.session.store import SessionStore
from blazecode.skills.loader import SkillLoader


def test_session_append_resume_list_and_export(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    store = SessionStore(directory=sessions)
    store.append(Message("user", "Build the feature"))
    store.append(Message("assistant", "Done"))
    listed = store.list_sessions()
    assert listed[0].title == "Build the feature"

    resumed = SessionStore(directory=sessions)
    messages = resumed.resume(store.session_id)
    assert [message.content for message in messages] == ["Build the feature", "Done"]
    exported = resumed.export_markdown(messages, tmp_path / "session.md")
    assert "## User" in exported.read_text(encoding="utf-8")
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_session_resume_keeps_current_session_on_invalid_target(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    store = SessionStore(directory=sessions)
    store.append(Message("user", "Current"))
    original_id = store.session_id
    (sessions / "broken.jsonl").write_text("not json\n", encoding="utf-8")

    try:
        store.resume("broken")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid session should not resume")
    assert store.session_id == original_id
    assert store.load()[0].content == "Current"


def test_global_and_local_skill_discovery_and_add(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("BLAZECODE_HOME", str(home))
    source = tmp_path / "source-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: python-testing\ndescription: Write robust pytest tests\n---\n# Rules\n",
        encoding="utf-8",
    )
    loader = SkillLoader(project)
    added = loader.add(source)
    assert added.name == "python-testing"
    assert loader.relevant("Please write pytest tests")[0].name == "python-testing"
    assert "# Rules" in loader.relevant("python testing")[0].read()
    assert loader.relevant("write a plain text file") == []


def test_loose_markdown_skills_include_planner_and_skip_invalid_files(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "state"
    project = tmp_path / "project"
    local_skills = project / ".blazecode" / "skills"
    local_skills.mkdir(parents=True)
    monkeypatch.setenv("BLAZECODE_HOME", str(home))
    (local_skills / "review.md").write_text(
        "# Review\n\nInspect changes carefully and run focused tests.\n",
        encoding="utf-8",
    )
    (local_skills / "empty.md").write_text("", encoding="utf-8")
    loader = SkillLoader(project)

    skills = loader.discover()
    assert "planner" in skills
    assert skills["review"].description == "Review"
    assert loader.relevant("plan this implementation")[0].name == "planner"
    assert loader.relevant("review the changes")[0].name == "review"
    assert any("empty.md" in issue for issue in loader.issues())


def test_skill_add_accepts_a_markdown_file(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "release-check.md"
    source.write_text("# Release check\n\nVerify packaging and tests.\n", encoding="utf-8")
    monkeypatch.setenv("BLAZECODE_HOME", str(home))

    skill = SkillLoader(project).add(source)
    assert skill.name == "release-check"
    assert (home / "skills" / "release-check.md").is_file()


def test_skill_add_rejects_path_traversal(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "state"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("BLAZECODE_HOME", str(home))
    source = tmp_path / "evil"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: ../../pwned\ndescription: bad\n---\n# x\n",
        encoding="utf-8",
    )
    loader = SkillLoader(project)
    try:
        loader.add(source)
        raised = False
    except ValueError:
        raised = True
    assert raised
    assert not (tmp_path / "pwned").exists()
    assert not (home / "pwned").exists()
