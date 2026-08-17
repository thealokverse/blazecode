from __future__ import annotations

import asyncio
import io
import tomllib
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from blazecode import __version__
from blazecode import cli
from blazecode.config.settings import Provider, Settings
from blazecode.ui import repl
from blazecode.ui.interact import MenuCancelled


class _PromptSession:
    def __init__(self, responses: list[str | BaseException]) -> None:
        self.responses = iter(responses)
        self.calls: list[object] = []

    async def prompt_async(self, prompt: object, **kwargs: object) -> str:
        del kwargs
        self.calls.append(prompt)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


def test_package_version_matches_release_metadata() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == metadata["project"]["version"]
    assert metadata["project"]["authors"] == [
        {"name": "light", "email": "alightalok007@gmail.com"}
    ]


def test_headless_surface_only_exposes_prompt_and_version() -> None:
    runner = CliRunner()
    version = runner.invoke(cli.app, ["--version"])
    assert version.exit_code == 0
    assert version.stdout.strip() == f"blazecode {__version__}"

    for arguments in (
        ["--help"],
        ["--model", "x"],
        ["--provider", "x"],
        ["--print", "x"],
    ):
        result = runner.invoke(cli.app, arguments)
        assert result.exit_code != 0


def test_short_prompt_flag_runs_headless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        "test",
        "model",
        providers=[Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    received: list[tuple[Settings, str | None, object]] = []

    async def fake_run(
        value: Settings, prompt: str | None, console: object, store: object = None
    ) -> None:
        received.append((value, prompt, store))

    monkeypatch.setattr(cli, "needs_onboarding", lambda: False)
    monkeypatch.setattr(cli.Settings, "load", lambda: settings)
    monkeypatch.setattr(cli, "_run", fake_run)
    result = CliRunner().invoke(cli.app, ["-p", "Say hello"])

    assert result.exit_code == 0
    assert len(received) == 1
    assert received[0][0] == settings
    assert received[0][1] == "Say hello"


def test_resume_missing_session_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "needs_onboarding", lambda: False)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--resume"])

    assert result.exit_code == 2
    assert "No saved sessions" in result.stdout
    sessions_dir = tmp_path / "sessions"
    if sessions_dir.exists():
        assert list(sessions_dir.glob("*.jsonl")) == []


def _patch_repl_sessions(
    monkeypatch: pytest.MonkeyPatch,
    main: _PromptSession,
    menu: _PromptSession | None = None,
) -> None:
    monkeypatch.setattr(repl, "PromptSession", lambda *args, **kwargs: main)
    monkeypatch.setattr(repl, "menu_session", lambda: menu or _PromptSession([]))


@pytest.mark.asyncio
async def test_repl_starts_and_runs_nested_model_selection_in_one_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    settings = Settings(
        "test",
        "first",
        providers=[Provider("test", "https://example.test/v1", "none", ["first", "second"])],
    )
    main_session = _PromptSession(["/models", "/exit"])
    _patch_repl_sessions(monkeypatch, main_session, _PromptSession(["2"]))

    await repl.run_repl(settings, cwd=tmp_path)

    assert settings.default_model == "second"
    assert len(main_session.calls) == 2


@pytest.mark.asyncio
async def test_repl_esc_inside_provider_selector_returns_to_repl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    settings = Settings(
        "test",
        "model",
        providers=[Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    main_session = _PromptSession(["/provider", "/exit"])
    _patch_repl_sessions(monkeypatch, main_session, _PromptSession([MenuCancelled()]))

    await repl.run_repl(settings, cwd=tmp_path)

    assert settings.default_provider == "test"
    assert len(main_session.calls) == 2


@pytest.mark.asyncio
async def test_repl_ctrl_c_inside_provider_selector_returns_to_repl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    settings = Settings(
        "test",
        "model",
        providers=[Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    main_session = _PromptSession(["/provider", "/exit"])
    _patch_repl_sessions(monkeypatch, main_session, _PromptSession([KeyboardInterrupt()]))

    await repl.run_repl(settings, cwd=tmp_path)

    assert settings.default_provider == "test"
    assert len(main_session.calls) == 2


@pytest.mark.asyncio
async def test_repl_ctrl_c_at_main_prompt_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    settings = Settings(
        "test",
        "model",
        providers=[Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    main_session = _PromptSession([KeyboardInterrupt()])
    _patch_repl_sessions(monkeypatch, main_session)

    await repl.run_repl(settings, cwd=tmp_path)

    assert len(main_session.calls) == 1


@pytest.mark.asyncio
async def test_repl_esc_inside_nested_selector_returns_to_repl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    settings = Settings(
        "test",
        "first",
        providers=[Provider("test", "https://example.test/v1", "none", ["first", "second"])],
    )
    main_session = _PromptSession(["/models", "/exit"])
    _patch_repl_sessions(monkeypatch, main_session, _PromptSession([MenuCancelled()]))

    await repl.run_repl(settings, cwd=tmp_path)

    assert settings.default_model == "first"
    assert len(main_session.calls) == 2


@pytest.mark.asyncio
async def test_repl_ctrl_c_inside_nested_selector_returns_to_repl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path / "home"))
    settings = Settings(
        "test",
        "first",
        providers=[Provider("test", "https://example.test/v1", "none", ["first", "second"])],
    )
    main_session = _PromptSession(["/models", "/exit"])
    _patch_repl_sessions(monkeypatch, main_session, _PromptSession([KeyboardInterrupt()]))

    await repl.run_repl(settings, cwd=tmp_path)

    assert settings.default_model == "first"
    assert len(main_session.calls) == 2


@pytest.mark.asyncio
async def test_run_onboards_inside_the_existing_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from blazecode import cli

    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    settings = Settings(
        "test",
        "model",
        providers=[Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    loops: list[asyncio.AbstractEventLoop] = []

    async def fake_onboard(**kwargs: object) -> Settings:
        del kwargs
        loops.append(asyncio.get_running_loop())
        return settings

    async def fake_repl(*args: object, **kwargs: object) -> None:
        del args, kwargs
        loops.append(asyncio.get_running_loop())

    monkeypatch.setattr(cli, "run_onboarding", fake_onboard)
    monkeypatch.setattr(cli, "run_repl", fake_repl)
    console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    await cli._run(None, None, console)
    assert len(loops) == 2
    assert loops[0] is loops[1]
