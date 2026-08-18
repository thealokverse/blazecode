from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from blazecode.agent.loop import AgentLoop, NullObserver
from blazecode.config.settings import Provider, Settings
from blazecode.llm.client import Done, Error, Event, TextDelta, ToolCallStart
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.store import SessionStore


class RecordingObserver(NullObserver):
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.notices: list[str] = []

    def on_error(self, message: str) -> None:
        self.errors.append(message)

    def on_notice(self, message: str) -> None:
        self.notices.append(message)


def _settings() -> Settings:
    return Settings(
        "test",
        "model",
        "off",
        [Provider("test", "https://example.test/v1", "none", ["model"])],
    )


def _loop(tmp_path: Path, streamer: Any, observer: RecordingObserver | None = None) -> AgentLoop:
    return AgentLoop(
        _settings(),
        tmp_path,
        SessionStore(directory=tmp_path / "sessions"),
        ApprovalManager("off"),
        observer or RecordingObserver(),
        streamer=streamer,
        trusted=True,
    )


@pytest.mark.asyncio
async def test_retryable_provider_error_then_success(tmp_path: Path) -> None:
    calls = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield Error("connection reset by peer")
            return
        yield TextDelta("recovered")
        yield Done("stop")

    observer = RecordingObserver()
    loop = _loop(tmp_path, streamer, observer)
    assert await loop.run("hi") == "recovered"
    assert any("retrying" in notice for notice in observer.notices)
    assert [message.role for message in loop.messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_auth_error_does_not_retry(tmp_path: Path) -> None:
    calls = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        yield Error("HTTP 401: invalid api key")

    observer = RecordingObserver()
    loop = _loop(tmp_path, streamer, observer)
    await loop.run("hi")
    assert calls == 1
    assert any("401" in error for error in observer.errors)
    assert loop.messages[0].role == "user"


@pytest.mark.asyncio
async def test_context_overflow_retries_with_tighter_budget(tmp_path: Path) -> None:
    calls = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield Error("context overflow: maximum context length exceeded")
            return
        yield TextDelta("ok")
        yield Done("stop")

    observer = RecordingObserver()
    loop = _loop(tmp_path, streamer, observer)
    assert await loop.run("hi") == "ok"
    assert loop._compact_ratio == 0.4
    assert any("context_overflow" in notice for notice in observer.notices)


@pytest.mark.asyncio
async def test_unknown_and_malformed_tools_continue(tmp_path: Path) -> None:
    calls = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield ToolCallStart("1", "nope", {})
            yield Done("tool_calls")
        elif calls == 2:
            yield ToolCallStart("2", "read", {"_parse_error": "bad json"})
            yield Done("tool_calls")
        else:
            yield TextDelta("done")
            yield Done("stop")

    loop = _loop(tmp_path, streamer)
    assert await loop.run("try") == "done"
    tools = [message for message in loop.messages if message.role == "tool"]
    assert "unknown tool" in tools[0].content
    assert "invalid tool arguments" in tools[1].content


@pytest.mark.asyncio
async def test_empty_response_asks_once_then_stops(tmp_path: Path) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        yield Done("stop")

    observer = RecordingObserver()
    loop = _loop(tmp_path, streamer, observer)
    await loop.run("hi")
    assert any("empty" in error for error in observer.errors)
    users = [message for message in loop.messages if message.role == "user"]
    assert len(users) == 2


@pytest.mark.asyncio
async def test_manual_compaction_survives_failure(tmp_path: Path) -> None:
    loop = _loop(tmp_path, lambda *args: None)
    loop.messages = []
    summary = loop.compact_now()
    assert "Goal" in summary
    assert loop.messages[-1].role == "system"
    assert "compacted" in (loop.messages[-1].content or "")
