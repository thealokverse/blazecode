from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from blazecode.config.settings import Provider, Settings
from blazecode.permissions.approval import ApprovalManager
from blazecode.tools import TOOLS
from blazecode.ui import repl
from blazecode.ui.render import Renderer


def test_approval_on_off_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    settings = Settings(
        "p",
        "m",
        "off",
        [Provider("p", "https://example.test/v1", "none", ["m"])],
    )
    settings.save(tmp_path / "config.json")
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    updated = repl._set_approval(settings, "on", console)
    assert updated.approval_mode == "on"
    updated = repl._set_approval(updated, "off", console)
    assert updated.approval_mode == "off"
    repl._set_approval(updated, "", console)
    assert "Approval:" in stream.getvalue()


def test_legacy_approval_modes_normalize_on_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    path = tmp_path / "config.json"
    for legacy, expected in (("ask", "on"), ("auto", "off"), ("plan", "on")):
        Settings(
            "p",
            "m",
            "on",
            [Provider("p", "https://example.test/v1", "none", ["m"])],
        ).save(path)
        raw = path.read_text(encoding="utf-8").replace('"on"', f'"{legacy}"', 1)
        path.write_text(raw, encoding="utf-8")
        loaded = Settings.load(path)
        assert loaded.approval_mode == expected


@pytest.mark.asyncio
async def test_async_approval_callback_is_awaited() -> None:
    asked: list[tuple[str, dict[str, Any]]] = []

    async def approve(name: str, arguments: dict[str, Any]) -> bool:
        asked.append((name, arguments))
        return True

    manager = ApprovalManager("on", approve)
    allowed, reason = await manager.approve_async(
        TOOLS["bash"], {"command": "echo ok"}
    )
    assert allowed
    assert reason == ""
    assert asked == [("bash", {"command": "echo ok"})]

    # file edits never prompt
    asked.clear()
    allowed, reason = await manager.approve_async(
        TOOLS["write"], {"path": "out.txt", "content": "ok"}
    )
    assert allowed
    assert asked == []


@pytest.mark.asyncio
async def test_approval_off_skips_prompts() -> None:
    prompted = 0

    async def approve(name: str, arguments: dict[str, Any]) -> bool:
        nonlocal prompted
        prompted += 1
        return False

    manager = ApprovalManager("off", approve)
    allowed, _ = await manager.approve_async(TOOLS["bash"], {"command": "rm -rf /"})
    assert allowed
    assert prompted == 0


@pytest.mark.asyncio
async def test_repl_approver_uses_prompt_toolkit_session_and_denies_interrupt() -> None:
    class Session:
        def __init__(self, response: str | BaseException) -> None:
            self.response = response
            self.prompts: list[str] = []

        async def prompt_async(self, prompt: str) -> str:
            self.prompts.append(prompt)
            if isinstance(self.response, BaseException):
                raise self.response
            return self.response

    class FakeRenderer:
        def __init__(self) -> None:
            self.paused = 0
            self.resumed = 0

        def tool_target(self, name: str, arguments: dict[str, Any]) -> str:
            return arguments["command"]

        def pause_activity(self) -> None:
            self.paused += 1

        def resume_activity(self) -> None:
            self.resumed += 1

    renderer = FakeRenderer()
    session = Session("yes")
    approver = repl._interactive_approver(session, renderer)  # type: ignore[arg-type]
    assert await approver("bash", {"command": "echo hi"})
    assert session.prompts == ["Run echo hi? [y/N] "]
    assert (renderer.paused, renderer.resumed) == (1, 1)

    interrupted = repl._interactive_approver(  # type: ignore[arg-type]
        Session(KeyboardInterrupt()), renderer
    )
    assert not await interrupted("bash", {"command": "echo hi"})


def test_approval_target_escapes_terminal_controls() -> None:
    target = Renderer.tool_target("bash", {"command": "echo ok\x1b[2J\nnext"})
    assert target == r"echo ok\x1b[2J\nnext"
