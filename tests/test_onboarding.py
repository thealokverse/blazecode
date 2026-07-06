from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from blazecode.config.settings import Provider
from blazecode import onboarding


def test_verify_provider_is_sync_and_resolves_env_at_use_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers_seen: list[dict[str, str]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": [{"id": "model-b"}, {"id": "model-a"}]}

    class Client:
        def __init__(self, timeout: float) -> None:
            assert timeout == 15.0

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str]) -> Response:
            assert url == "https://example.test/v1/models"
            headers_seen.append(headers)
            return Response()

    monkeypatch.setattr(onboarding.httpx, "Client", Client)
    monkeypatch.setenv("DYNAMIC_KEY", "first")
    assert onboarding.verify_provider(
        "https://example.test/v1", "env:DYNAMIC_KEY"
    ) == ["model-b", "model-a"]
    monkeypatch.setenv("DYNAMIC_KEY", "second")
    onboarding.verify_provider("https://example.test/v1", "env:DYNAMIC_KEY")
    assert headers_seen == [
        {"Authorization": "Bearer first"},
        {"Authorization": "Bearer second"},
    ]


def test_onboarding_is_synchronous_masks_output_and_secures_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter([2, 1])
    raw_key = "sk-or-v1-secret-ab12"
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    monkeypatch.setattr(
        onboarding.IntPrompt,
        "ask",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(
        onboarding,
        "_collect_provider",
        lambda choice, output: Provider(
            "openrouter", "https://openrouter.ai/api/v1", raw_key, []
        ),
    )
    monkeypatch.setattr(
        onboarding, "verify_provider", lambda base_url, api_key: ["model-a"]
    )

    settings = onboarding.run_onboarding(console=console)

    assert settings.default_model == "model-a"
    assert not hasattr(settings, "__await__")
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
