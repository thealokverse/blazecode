from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from blazecode.config.settings import Provider, Settings
from blazecode.llm.client import Done, Error, TextDelta, ToolCallStart, list_models, stream_completion


@pytest.mark.asyncio
async def test_stream_completion_parses_text_tool_and_usage() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "Hi "}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "there"}, "finish_reason": None}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "read", "arguments": '{"pa'},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": 'th":"README.md"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 4}},
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    body += "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["stream"] is True
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in stream_completion(
                "https://example.test/v1",
                "secret",
                "model",
                [{"role": "user", "content": "hello"}],
                [],
                client=client,
            )
        ]
    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "Hi ",
        "there",
    ]
    call = next(event for event in events if isinstance(event, ToolCallStart))
    assert call.call_id == "call_1"
    assert call.arguments == {"path": "README.md"}
    done = next(event for event in events if isinstance(event, Done))
    assert done.usage["prompt_tokens"] == 3


@pytest.mark.asyncio
async def test_provider_error_and_model_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await list_models("https://example.test/v1", None, client=client) == [
            "a",
            "b",
        ]
        events = [
            event
            async for event in stream_completion(
                "https://example.test/v1", None, "a", [], [], client=client
            )
        ]
    assert isinstance(events[0], Error)
    assert "bad key" in events[0].message


def test_settings_secure_save_and_environment_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Provider("test", "https://example.test/v1", "env:TEST_KEY", ["m"])
    settings = Settings("test", "m", providers=[provider])
    path = tmp_path / "config.json"
    settings.save(path)
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = Settings.load(path)
    monkeypatch.setenv("TEST_KEY", "top-secret")
    assert loaded.provider().resolved_api_key() == "top-secret"
    assert "top-secret" not in path.read_text(encoding="utf-8")

