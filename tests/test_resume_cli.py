from __future__ import annotations

from pathlib import Path
import pytest
from rich.console import Console
from typer.testing import CliRunner

from blazecode import cli
from blazecode.config.settings import Provider, Settings
from blazecode.session.message import Message
from blazecode.session.store import SessionStore
from blazecode.ui.repl import _render_resumed_history


def test_cli_resume_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BLAZECODE_HOME", str(home))
    monkeypatch.setattr(cli, "needs_onboarding", lambda: False)
    settings = Settings("test", "model", providers=[Provider("test", "http://test", "none", ["model"])])
    monkeypatch.setattr(cli.Settings, "load", lambda: settings)

    sessions_dir = home / "sessions"
    s1 = SessionStore(session_id="20260101-100000-aaaa1111", directory=sessions_dir)
    s1.append(Message("user", "First"))

    s2 = SessionStore(session_id="20260102-100000-bbbb2222", directory=sessions_dir)
    s2.append(Message("user", "Second"))

    received_store: list[SessionStore] = []

    async def fake_run(
        value: Settings, prompt: str | None, console: object, store: SessionStore | None = None
    ) -> None:
        if store:
            received_store.append(store)

    monkeypatch.setattr(cli, "_run", fake_run)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--resume", "-p", "Continue"])
    assert result.exit_code == 0
    assert len(received_store) == 1
    assert received_store[0].session_id == "20260102-100000-bbbb2222"


def test_cli_resume_empty_sessions_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("BLAZECODE_HOME", str(home))
    monkeypatch.setattr(cli, "needs_onboarding", lambda: False)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--resume"])
    assert result.exit_code == 2
    assert "No saved sessions" in result.stdout


def test_render_resumed_history() -> None:
    console = Console(record=True)
    messages = [
        Message("user", "Hello assistant"),
        Message("assistant", "Hello! How can I help you?"),
    ]
    _render_resumed_history(console, messages)
    text = console.export_text()
    assert "Hello assistant" in text
    assert "Hello! How can I help you?" in text
