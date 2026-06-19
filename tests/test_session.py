"""Tests for Session persistence and truncation."""
import json
from pathlib import Path

import pytest

from blazecode.engine.session import Session, SessionPaths, make_session_id


def _session(tmp_path, **kw) -> Session:
    return Session(model="gpt-4o", provider="openai", paths=SessionPaths(base_dir=tmp_path), **kw)


def test_basic_append_and_messages(tmp_path):
    s = _session(tmp_path)
    s.append({"role": "user", "content": "hi"})
    s.append({"role": "assistant", "content": "hello"})
    msgs = s.to_messages()
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_persistence_round_trip(tmp_path):
    s = _session(tmp_path, session_id="abc123")
    s.append({"role": "user", "content": "hello"})
    s.append({"role": "assistant", "content": "hi"})
    s.record_usage({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    path = s.persist()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 3
    summary = json.loads(lines[-1])
    assert summary["_summary"] is True
    assert summary["stats"]["total_tokens"] == 15

    s2 = Session.resume("abc123", paths=SessionPaths(base_dir=tmp_path))
    assert [m["role"] for m in s2.to_messages()] == ["user", "assistant"]
    assert s2.stats.total_tokens == 15


def test_truncation_drops_old_non_system(tmp_path):
    s = _session(tmp_path)
    s.append({"role": "system", "content": "you are helpful."})
    big = "x" * 5000
    for i in range(40):
        s.append({"role": "user", "content": f"{i}: {big}"})
        s.append({"role": "assistant", "content": f"reply {i}: {big}"})

    trimmed = s.truncate_if_needed(model="gpt-4o", context_window=4000)
    assert trimmed is True
    msgs = s.to_messages()
    assert msgs[0]["role"] == "system"
    assert len(msgs) < 1 + 80  # significantly fewer than 80


def test_truncation_no_op_when_small(tmp_path):
    s = _session(tmp_path)
    s.append({"role": "system", "content": "you are helpful."})
    s.append({"role": "user", "content": "hi"})
    s.append({"role": "assistant", "content": "hello"})
    assert s.truncate_if_needed(model="gpt-4o", context_window=128_000) is False


def test_session_id_format():
    sid = make_session_id()
    parts = sid.split("-")
    assert len(parts) == 3
    assert parts[0].isdigit() and len(parts[0]) == 8
    assert parts[1].isdigit() and len(parts[1]) == 6


def test_list_saved(tmp_path):
    s = _session(tmp_path, session_id="listed")
    s.append({"role": "user", "content": "first prompt"})
    s.persist()
    rows = Session.list_saved(paths=SessionPaths(base_dir=tmp_path))
    assert any(r["session_id"] == "listed" and "first prompt" in r["first_message"] for r in rows)


def test_resume_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Session.resume("missing", paths=SessionPaths(base_dir=tmp_path))


def test_replace_system(tmp_path):
    s = _session(tmp_path)
    s.replace_system("first system")
    s.append({"role": "user", "content": "hi"})
    s.replace_system("updated system")
    assert s.to_messages()[0]["content"] == "updated system"
