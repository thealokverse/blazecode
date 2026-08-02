from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from rich.console import Console

from blazecode.agent.loop import AgentLoop
from blazecode.config.settings import Provider, Settings
from blazecode.llm.client import Done, Event, TextDelta, ToolCallStart, _build_payload
from blazecode.llm.reasoning import classify_reasoning_effort
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.store import SessionStore
from blazecode.ui import repl


def _settings(effort: str = "none") -> Settings:
    return Settings(
        "p",
        "m",
        providers=[Provider("p", "https://example.test/v1", "none", ["m"])],
        reasoning_effort=effort,
    )


@pytest.mark.parametrize(
    "effort",
    ["none", "low", "medium", "high", "xhigh", "max", "adaptive"],
)
def test_settings_accept_and_persist_reasoning_modes(tmp_path: Path, effort: str) -> None:
    path = tmp_path / "config.json"
    settings = _settings(effort)

    settings.validate()
    settings.save(path)

    assert Settings.load(path).reasoning_effort == effort


def test_settings_reject_unknown_reasoning_mode() -> None:
    with pytest.raises(ValueError, match="reasoning_effort must be one of"):
        _settings("ultra").validate()


def test_openrouter_payload_uses_reasoning_object() -> None:
    payload = _build_payload(
        "model",
        [{"role": "user", "content": "hi"}],
        [],
        reasoning_effort="high",
        base_url="https://openrouter.ai/api/v1",
    )

    assert payload["reasoning"] == {"enabled": True, "effort": "high"}
    assert "reasoning_effort" not in payload


def test_openai_compatible_payload_uses_top_level_effort() -> None:
    payload = _build_payload(
        "model",
        [{"role": "user", "content": "hi"}],
        [],
        reasoning_effort="max",
        base_url="https://api.openai.com/v1",
    )

    assert payload["reasoning_effort"] == "max"
    assert "reasoning" not in payload


def test_none_disables_openrouter_reasoning() -> None:
    payload = _build_payload(
        "model",
        [{"role": "user", "content": "hi"}],
        [],
        reasoning_effort="none",
        base_url="https://openrouter.ai/api/v1",
    )

    assert payload["reasoning"] == {"enabled": False}


def test_none_preserves_generic_provider_compatibility() -> None:
    payload = _build_payload(
        "model",
        [{"role": "user", "content": "hi"}],
        [],
        reasoning_effort="none",
        base_url="https://example.test/v1",
    )

    assert "reasoning_effort" not in payload
    assert "reasoning" not in payload


def test_adaptive_must_be_resolved_before_building_payload() -> None:
    with pytest.raises(ValueError, match="adaptive reasoning must be resolved"):
        _build_payload(
            "model",
            [{"role": "user", "content": "hi"}],
            [],
            reasoning_effort="adaptive",
            base_url="https://example.test/v1",
        )


def test_reasoning_command_sets_persists_and_reports_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BLAZECODE_HOME", str(tmp_path))
    settings = _settings()
    settings.save()
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    updated = repl._set_reasoning(settings, "xhigh", console)
    assert updated.reasoning_effort == "xhigh"
    assert Settings.load().reasoning_effort == "xhigh"

    repl._set_reasoning(updated, "", console)
    assert "Reasoning: xhigh" in stream.getvalue()


def test_reasoning_command_rejects_unknown_mode(tmp_path: Path) -> None:
    settings = _settings()
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    updated = repl._set_reasoning(settings, "ultra", console)

    assert updated.reasoning_effort == "none"
    assert "Usage: /reasoning" in stream.getvalue()


@pytest.mark.asyncio
async def test_adaptive_classifier_returns_a_concrete_effort() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "xhigh"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        effort = await classify_reasoning_effort(
            "https://example.test/v1",
            "secret",
            "model",
            "Fix the race condition and verify the concurrency invariants.",
            client=client,
        )

    assert effort == "xhigh"
    assert captured["stream"] is False
    assert "tools" not in captured
    assert "adaptive" not in json.dumps(captured["messages"]).lower()


@pytest.mark.asyncio
async def test_adaptive_classifier_falls_back_to_medium() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ULTRA"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        effort = await classify_reasoning_effort(
            "https://example.test/v1",
            None,
            "model",
            "hello",
            client=client,
        )

    assert effort == "medium"


@pytest.mark.asyncio
async def test_agent_classifies_once_and_reuses_effort_for_tool_followups(
    tmp_path: Path,
) -> None:
    classifications = 0
    streamed_efforts: list[str] = []

    async def classifier(
        base_url: str,
        api_key: str | None,
        model: str,
        prompt: str,
    ) -> str:
        nonlocal classifications
        classifications += 1
        assert prompt == "Create out.txt"
        return "xhigh"

    async def streamer(
        base_url: str,
        api_key: str | None,
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        reasoning_effort: str,
    ) -> AsyncIterator[Event]:
        streamed_efforts.append(reasoning_effort)
        if len(streamed_efforts) == 1:
            yield ToolCallStart(
                "call_1", "write", {"path": "out.txt", "content": "ok"}
            )
            yield Done("tool_calls")
        else:
            yield TextDelta("Done.")
            yield Done("stop")

    settings = _settings("adaptive")
    loop = AgentLoop(
        settings,
        tmp_path,
        SessionStore(directory=tmp_path / "sessions"),
        ApprovalManager("off"),
        streamer=streamer,
        reasoning_classifier=classifier,
    )

    assert await loop.run("Create out.txt") == "Done."
    assert classifications == 1
    assert streamed_efforts == ["xhigh", "xhigh"]
