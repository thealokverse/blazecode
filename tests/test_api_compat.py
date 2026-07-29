from __future__ import annotations

import json

import httpx
import pytest

from blazecode.agent.tool_events import resolve_tool_name, tool_call_message
from blazecode.llm.client import Done, TextDelta, ToolCallStart, stream_completion
from blazecode.session.message import Message


def test_assistant_tool_call_messages_include_empty_content() -> None:
    message = Message(
        role="assistant",
        content=None,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read", "arguments": "{}"},
            }
        ],
    )
    payload = message.to_dict(api=True)
    assert payload["content"] == ""
    assert payload["tool_calls"]


def test_tool_result_messages_always_have_content() -> None:
    message = Message(role="tool", content=None, tool_call_id="call_1", name="read")
    payload = message.to_dict(api=True)
    assert payload["content"] == ""
    assert payload["tool_call_id"] == "call_1"


def test_empty_assistant_stop_includes_content_key() -> None:
    payload = Message(role="assistant", content=None).to_dict(api=True)
    assert payload == {"role": "assistant", "content": ""}


def test_tool_call_message_uses_resolved_name() -> None:
    serialized = tool_call_message(ToolCallStart("1", "shell", {"command": "true"}))
    assert serialized["function"]["name"] == "bash"


def test_tool_call_message_strips_internal_keys() -> None:
    call = ToolCallStart("1", "read", {"path": "a.py", "_parse_error": "x"})
    serialized = tool_call_message(call)
    args = json.loads(serialized["function"]["arguments"])
    assert args == {"path": "a.py"}


def test_resolve_tool_name_aliases() -> None:
    assert resolve_tool_name("Read") == "read"
    assert resolve_tool_name("shell") == "bash"
    assert resolve_tool_name("nope") is None


@pytest.mark.asyncio
async def test_stream_handles_content_part_lists_and_name_resends() -> None:
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "content": [{"type": "text", "text": "Hello "}],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "content": [{"type": "text", "text": "GLM"}],
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_abc",
                                "function": {"name": "re", "arguments": ""},
                            }
                        ],
                    }
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
                                "id": "call_abc",
                                "function": {
                                    "name": "read",
                                    "arguments": '{"path":"x.py"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    body += "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload.get("parallel_tool_calls") is False
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            event
            async for event in stream_completion(
                "https://example.test/v1",
                "secret",
                "glm-4.7",
                [{"role": "user", "content": "hi"}],
                [{"type": "function", "function": {"name": "read"}}],
                client=client,
            )
        ]
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "Hello GLM"
    call = next(e for e in events if isinstance(e, ToolCallStart))
    assert call.name == "read"
    assert call.arguments == {"path": "x.py"}
    assert call.call_id == "call_abc"
    assert any(isinstance(e, Done) for e in events)
