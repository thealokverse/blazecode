from __future__ import annotations

from pathlib import Path

from blazecode.session.message import Message
from blazecode.session.store import SessionStore


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


def test_session_load_hardens_corrupt_lines(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    store = SessionStore(directory=sessions)
    store.append(Message("user", "ok"))
    valid = store.path.read_text(encoding="utf-8").splitlines()[0]
    store.path.write_text(
        "\n".join(
            [
                '{"role": 5, "content": null, "input_tokens": "12x"}',
                valid.replace('"content": "ok"', '"content": 42'),
            ]
        ),
        encoding="utf-8",
    )

    messages = store.load()
    assert len(messages) == 2
    assert messages[0].role == "5"
    assert messages[0].content is None
    assert messages[0].input_tokens is None
    assert messages[1].content == "42"
