from __future__ import annotations

from pathlib import Path

import pytest

from blazecode.agent.tool_events import execute_tool
from blazecode.llm.client import ToolCallStart
from blazecode.permissions.approval import ApprovalManager
from blazecode.permissions.trust import grant_trust, is_trusted, workspace_root


def test_first_time_directory_is_untrusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    assert is_trusted(tmp_path) is False


def test_trust_persists_and_covers_nested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    child = tmp_path / "src"
    child.mkdir()
    granted = grant_trust(tmp_path)
    assert granted == workspace_root(tmp_path)
    assert is_trusted(tmp_path)
    assert is_trusted(child)


def test_symlink_trust_uses_resolved_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    grant_trust(link)
    assert is_trusted(real)
    assert is_trusted(link)


@pytest.mark.asyncio
async def test_untrusted_blocks_mutating_not_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    (tmp_path / "note.txt").write_text("hi", encoding="utf-8")
    approval = ApprovalManager("off")
    blocked = await execute_tool(
        ToolCallStart("1", "write", {"path": "x.txt", "content": "no"}),
        tmp_path,
        approval,
        trusted=False,
    )
    assert blocked.is_error
    assert "not trusted" in blocked.content
    assert not (tmp_path / "x.txt").exists()
    allowed = await execute_tool(
        ToolCallStart("2", "read", {"path": "note.txt"}),
        tmp_path,
        approval,
        trusted=False,
    )
    assert not allowed.is_error
    assert "hi" in allowed.content
