from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from blazecode import __version__
from blazecode import cli
from blazecode.config.settings import Provider, Settings
from blazecode.ui import repl


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
    approval_session = _PromptSession([])
    repl_sessions = iter([main_session, approval_session])
    monkeypatch.setattr(repl, "PromptSession", lambda *args, **kwargs: next(repl_sessions))
    choices = iter(["2"])
    monkeypatch.setattr(repl.IntPrompt, "ask", lambda *args, **kwargs: int(next(choices)))

    await repl.run_repl(settings, cwd=tmp_path)

    assert settings.default_model == "second"
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
    approval_session = _PromptSession([])
    repl_sessions = iter([main_session, approval_session])
    monkeypatch.setattr(repl, "PromptSession", lambda *args, **kwargs: next(repl_sessions))
    monkeypatch.setattr(
        repl, "switch_or_add_provider", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt())
    )

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
    repl_sessions = iter([main_session, _PromptSession([])])
    monkeypatch.setattr(repl, "PromptSession", lambda *args, **kwargs: next(repl_sessions))

    await repl.run_repl(settings, cwd=tmp_path)

    assert len(main_session.calls) == 1


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
    approval_session = _PromptSession([])
    repl_sessions = iter([main_session, approval_session])
    monkeypatch.setattr(repl, "PromptSession", lambda *args, **kwargs: next(repl_sessions))
    monkeypatch.setattr(repl.IntPrompt, "ask", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    await repl.run_repl(settings, cwd=tmp_path)

    assert settings.default_model == "first"
    assert len(main_session.calls) == 2
