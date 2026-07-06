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
