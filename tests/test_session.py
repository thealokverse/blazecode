"""Tests for the Session class: persistence and truncation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blazecode.engine.session import Session, SessionPaths, make_session_id
from blazecode.engine.session import SESSION_DIR


def _make_session(tmp_path: Path, **kw) -> Session:
    paths = SessionPaths(base_dir=tmp_path)
    return Session(model="gpt-5", provider="openai", paths=paths, **kw)


def test_session_basic_append_and_messages(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    s.append({"role": "user", "content": "hi"})
    s.append({"role": "assistant", "content": "hello"})
    msgs = s.to_messages()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hi"


def test_session_persistence_round_trip(tmp_path: Path) -> None:
    s = _make_session(tmp_path, session_id="abc12345")
    s.append({"role": "user", "content": "hello there"})
    s.append({"role": "assistant", "content": "hi yourself"})
    s.record_usage({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    path = s.persist()
    assert path.exists()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 3
    summary = json.loads(lines[-1])
    assert summary["_summary"] is True
    assert summary["stats"]["total_tokens"] == 15

    s2 = Session.resume("abc12345", paths=SessionPaths(base_dir=tmp_path))
    assert [m["role"] for m in s2.to_messages()] == ["user", "assistant"]
    assert s2.stats.total_tokens == 15


def test_session_truncation_drops_old_non_system(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    s.append({"role": "system", "content": "you are helpful."})
    # Simulate a huge history.
    big = "x" * 2000
    for i in range(40):
        s.append({"role": "user", "content": f"{i}: {big}"})
        s.append({"role": "assistant", "content": f"reply {i}: {big}"})

    # With a 4k context window, the estimated size is huge -> trim.
    trimmed = s.truncate_if_needed(context_window=4000, keep_last_n=4)
    assert trimmed is True
    msgs = s.to_messages()
    # System message + last 4 exchanges (8 messages) = 9
    assert msgs[0]["role"] == "system"
    assert len(msgs) == 1 + 4 * 2


def test_session_truncation_no_op_when_small(tmp_path: Path) -> None:
    s = _make_session(tmp_path)
    s.append({"role": "system", "content": "you are helpful."})
    s.append({"role": "user", "content": "hi"})
    s.append({"role": "assistant", "content": "hello"})
    trimmed = s.truncate_if_needed(context_window=128_000)
    assert trimmed is False
    assert len(s.to_messages()) == 3


def test_session_id_format() -> None:
    sid = make_session_id()
    parts = sid.split("-")
    # YYYYMMDD-HHMMSS-XXXXXX
    assert len(parts) == 3
    assert len(parts[0]) == 8 and parts[0].isdigit()
    assert len(parts[1]) == 6 and parts[1].isdigit()
    assert len(parts[2]) == 6


def test_session_list_saved(tmp_path: Path) -> None:
    s = _make_session(tmp_path, session_id="listed")
    s.append({"role": "user", "content": "first prompt here"})
    s.persist()
    rows = Session.list_saved(paths=SessionPaths(base_dir=tmp_path))
    assert any(r["session_id"] == "listed" and "first prompt" in r["first_message"]
               for r in rows)


def test_session_resume_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Session.resume("does-not-exist", paths=SessionPaths(base_dir=tmp_path))
