from __future__ import annotations

from pathlib import Path

import pytest

from blazecode.tools import build_registry


@pytest.mark.asyncio
async def test_all_five_tools_work(tmp_path: Path) -> None:
    tools = build_registry()
    assert set(tools) == {"read", "write", "edit", "bash", "grep"}

    written = await tools["write"].run(
        {"path": "src/example.py", "content": "value = 1\n"}, tmp_path
    )
    assert not written.is_error
    assert "+value = 1" in (written.diff or "")

    read = await tools["read"].run({"path": "src/example.py"}, tmp_path)
    assert read.content == "     1  value = 1"

    edited = await tools["edit"].run(
        {
            "path": "src/example.py",
            "old_string": "value = 1",
            "new_string": "value = 2",
        },
        tmp_path,
    )
    assert not edited.is_error
    assert "-value = 1" in (edited.diff or "")

    found = await tools["grep"].run(
        {"pattern": r"value\s*=\s*2", "path": ".", "include": "*.py"}, tmp_path
    )
    assert found.content == "src/example.py:1:value = 2"

    command = await tools["bash"].run({"command": "pwd"}, tmp_path)
    assert command.content == str(tmp_path)


@pytest.mark.asyncio
async def test_tools_reject_escape_and_ambiguous_edit(tmp_path: Path) -> None:
    tools = build_registry()
    outside = await tools["read"].run({"path": "../secret"}, tmp_path)
    assert outside.is_error
    assert "outside" in outside.content

    path = tmp_path / "repeat.txt"
    path.write_text("x x", encoding="utf-8")
    result = await tools["edit"].run(
        {"path": "repeat.txt", "old_string": "x", "new_string": "y"}, tmp_path
    )
    assert result.is_error
    assert "2 times" in result.content


@pytest.mark.asyncio
async def test_bash_reports_timeout_and_exit_code(tmp_path: Path) -> None:
    bash = build_registry()["bash"]
    failed = await bash.run({"command": "exit 7"}, tmp_path)
    assert failed.is_error
    assert "Exit code 7" in failed.content

