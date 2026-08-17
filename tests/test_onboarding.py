from __future__ import annotations

import inspect
import io
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from blazecode.config.settings import Provider
from blazecode import onboarding


class _Session:
    def __init__(self, responses: list[str | BaseException]) -> None:
        self.responses = iter(responses)

    async def prompt_async(self, prompt: object, **kwargs: object) -> str:
        del prompt, kwargs
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.asyncio
async def test_onboarding_masks_output_and_secures_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter([2, 1])
    raw_key = "sk-or-v1-secret-ab12"
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))

    async def fake_ask_index(*args: Any, **kwargs: Any) -> int:
        del args, kwargs
        return next(answers)

    async def fake_collect(choice: int, output: Console, session: object) -> Provider:
        del choice, output, session
        return Provider("openrouter", "https://openrouter.ai/api/v1", raw_key, [])

    async def fake_verify(base_url: str, api_key: str) -> list[str]:
        del base_url, api_key
        return ["model-a"]

    monkeypatch.setattr(onboarding, "ask_index", fake_ask_index)
    monkeypatch.setattr(onboarding, "_collect_provider", fake_collect)
    monkeypatch.setattr(onboarding, "verify_provider", fake_verify)

    settings = await onboarding.run_onboarding(console=console)

    assert settings.default_model == "model-a"
    assert not hasattr(settings, "__await__")
    assert inspect.iscoroutinefunction(onboarding.run_onboarding)
    assert "✓ Key verified" in stream.getvalue()
    assert raw_key not in stream.getvalue()
    path = tmp_path / "config.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert raw_key in path.read_text(encoding="utf-8")


def test_api_key_masking_and_late_provider_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = Provider(
        "openrouter",
        "https://openrouter.ai/api/v1",
        "sk-123456ab12",
        ["model"],
    )
    assert provider.masked_api_key() == "sk-...ab12"
    provider.api_key = "env:LATE_KEY"
    monkeypatch.setenv("LATE_KEY", "one")
    assert provider.resolved_api_key() == "one"
    monkeypatch.setenv("LATE_KEY", "two")
    assert provider.resolved_api_key() == "two"


def test_friendly_error_handles_empty_exception_messages() -> None:
    assert onboarding._friendly_error(EOFError()) == "EOFError"


@pytest.mark.asyncio
async def test_proxy_preset_prompts_url_and_uses_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    choice = [
        preset.name for preset in onboarding.PROVIDER_PRESETS
    ].index("anthropic") + 1
    provider = await onboarding._collect_provider(
        choice, console, _Session(["https://my-proxy.example/v1", "y"])
    )

    assert provider.name == "anthropic"
    assert provider.base_url == "https://my-proxy.example/v1"
    assert provider.api_key == "env:ANTHROPIC_API_KEY"


@pytest.mark.asyncio
async def test_custom_preset_prompts_name_url_key_and_models() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    choice = [preset.name for preset in onboarding.PROVIDER_PRESETS].index("") + 1
    provider = await onboarding._collect_provider(
        choice,
        console,
        _Session(["mybox", "https://my.example/v1", "sk-123456ab12", ""]),
    )

    assert provider.name == "mybox"
    assert provider.base_url == "https://my.example/v1"
    assert provider.api_key == "sk-123456ab12"
    assert provider.models == []


@pytest.mark.asyncio
async def test_onboarding_retries_empty_model_lists_without_recursing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    choices = iter([1, 1, 1, 1])
    responses = iter([[], [], ["glm-4.7"]])
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))

    async def fake_ask_index(*args: Any, **kwargs: Any) -> int:
        del args, kwargs
        return next(choices)

    async def fake_collect(choice: int, output: Console, session: object) -> Provider:
        del choice, output, session
        return Provider("zai", "https://example.test/v1", "key", [])

    async def fake_verify(base_url: str, api_key: str) -> list[str]:
        del base_url, api_key
        return next(responses)

    monkeypatch.setattr(onboarding, "ask_index", fake_ask_index)
    monkeypatch.setattr(onboarding, "_collect_provider", fake_collect)
    monkeypatch.setattr(onboarding, "verify_provider", fake_verify)

    settings = await onboarding.run_onboarding(console=console)
    assert settings.default_model == "glm-4.7"
    assert stream.getvalue().count("Welcome to Blazecode!") == 1


@pytest.mark.asyncio
async def test_collect_api_key_uses_async_session() -> None:
    preset = next(
        item for item in onboarding.PROVIDER_PRESETS if item.name == "openai"
    )
    key = await onboarding._collect_api_key(preset, _Session(["sk-live"]))
    assert key == "sk-live"
