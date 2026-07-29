from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from blazecode.agent.loop import AgentLoop
from blazecode.config.settings import Provider, Settings
from blazecode.llm.client import Done, Event, TextDelta, ToolCallStart, stream_completion
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.store import SessionStore


@pytest.mark.asyncio
async def test_invalid_tool_arguments_become_tool_errors_not_hard_fail() -> None:
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "read",
                                    "arguments": "{not-json",
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    body += "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in stream_completion(
                "https://example.test/v1",
                "secret",
                "model",
                [{"role": "user", "content": "hi"}],
                [],
                client=client,
            )
        ]
    call = next(event for event in events if isinstance(event, ToolCallStart))
    assert "_parse_error" in call.arguments
    assert any(isinstance(event, Done) for event in events)


@pytest.mark.asyncio
async def test_agent_honors_cancel_between_iterations(tmp_path: Path) -> None:
    calls = 0

    async def streamer(
        base_url: str,
        api_key: str | None,
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield ToolCallStart(
                "call_1", "write", {"path": "a.txt", "content": "1"}
            )
            yield Done("tool_calls")
        else:
            yield TextDelta("should-not-run")
            yield Done("stop")

    settings = Settings(
        "test",
        "model",
        "auto",
        [Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        settings,
        tmp_path,
        store,
        ApprovalManager("auto"),
        streamer=streamer,
    )

    async def run_and_cancel() -> str:
        # Cancel after the first tool lands by patching _run_tool.
        original = loop._run_tool

        async def wrapped(call: ToolCallStart) -> None:
            await original(call)
            loop.request_cancel()

        loop._run_tool = wrapped  # type: ignore[method-assign]
        return await loop.run("write then stop")

    result = await run_and_cancel()
    assert result != "should-not-run"
    assert calls == 1
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "1"


@pytest.mark.asyncio
async def test_retry_on_transient_http_then_succeed() -> None:
    attempts = {"n": 0}
    body = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in stream_completion(
                "https://example.test/v1",
                "secret",
                "model",
                [{"role": "user", "content": "hi"}],
                [],
                client=client,
            )
        ]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["ok"]
    assert attempts["n"] == 2
