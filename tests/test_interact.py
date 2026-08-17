from __future__ import annotations

import asyncio
import inspect
import io
from pathlib import Path

import pytest
from prompt_toolkit.keys import Keys
from rich.console import Console

from blazecode.config.settings import Provider, Settings
from blazecode.onboarding import switch_or_add_provider, verify_provider
from blazecode.ui.interact import (
    MenuCancelled,
    ask_index,
    complete_menu,
    menu_bindings,
)


class _Session:
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


def test_menu_bindings_map_escape_and_leave_ctrl_c() -> None:
    keys = {binding.keys for binding in menu_bindings().bindings}
    assert (Keys.Escape,) in keys
    assert (Keys.ControlC,) not in keys


@pytest.mark.asyncio
async def test_ask_index_esc_cancels_and_ctrl_c_interrupts() -> None:
    console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    with pytest.raises(MenuCancelled):
        await ask_index(_Session([MenuCancelled()]), console, ["one", "two"])
    with pytest.raises(KeyboardInterrupt):
        await ask_index(_Session([KeyboardInterrupt()]), console, ["one", "two"])
    picked = await ask_index(_Session(["2"]), console, ["one", "two"])
    assert picked == 2


@pytest.mark.asyncio
async def test_complete_menu_distinguishes_esc_from_ctrl_c() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    async def cancel() -> str:
        raise MenuCancelled()

    async def interrupt() -> str:
        raise KeyboardInterrupt()

    async def ok() -> str:
        return "done"

    assert await complete_menu(console, cancel()) is None
    assert "Back." in stream.getvalue()
    assert await complete_menu(console, interrupt()) is None
    assert "Interrupted." in stream.getvalue()
    assert await complete_menu(console, ok()) == "done"


@pytest.mark.asyncio
async def test_provider_switch_uses_running_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    settings = Settings(
        "test",
        "model",
        providers=[Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    loop = asyncio.get_running_loop()
    updated = await switch_or_add_provider(settings, console, _Session(["1"]))
    assert updated.default_provider == "test"
    assert asyncio.get_running_loop() is loop


@pytest.mark.asyncio
async def test_verify_provider_resolves_env_at_use_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    async def fake_list(base_url: str, api_key: str | None, **kwargs: object) -> list[str]:
        del base_url, kwargs
        seen.append(api_key)
        return ["model-a", "model-b"]

    monkeypatch.setattr("blazecode.onboarding.list_models", fake_list)
    monkeypatch.setenv("DYNAMIC_KEY", "first")
    models = await verify_provider("https://example.test/v1", "env:DYNAMIC_KEY")
    assert set(models) == {"model-a", "model-b"}
    monkeypatch.setenv("DYNAMIC_KEY", "second")
    await verify_provider("https://example.test/v1", "env:DYNAMIC_KEY")
    assert seen == ["first", "second"]


def test_onboarding_is_async_and_has_no_nested_loop_entry() -> None:
    from blazecode import onboarding

    assert inspect.iscoroutinefunction(onboarding.run_onboarding)
    assert inspect.iscoroutinefunction(onboarding.switch_or_add_provider)
    assert inspect.iscoroutinefunction(onboarding.verify_provider)
    source = Path(onboarding.__file__).read_text(encoding="utf-8")
    assert "from prompt_toolkit import prompt" not in source
    assert "asyncio.run" not in source
