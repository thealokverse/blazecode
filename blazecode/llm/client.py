"""OpenAI-compatible async streaming client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class TextDelta:
    """Incremental assistant text."""

    text: str


@dataclass(frozen=True, slots=True)
class ToolCallStart:
    """A complete streamed function call ready for execution."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """A locally executed tool result passed through the event layer."""

    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Done:
    """Successful end of a completion stream."""

    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Error:
    """Provider or protocol failure."""

    message: str


Event = TextDelta | ToolCallStart | ToolResult | Done | Error


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def list_models(
    base_url: str,
    api_key: str | None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Fetch model identifiers from an OpenAI-compatible endpoint."""
    owned = client is None
    session = client or httpx.AsyncClient(timeout=15)
    try:
        response = await session.get(
            f"{base_url.rstrip('/')}/models", headers=_headers(api_key)
        )
        response.raise_for_status()
        payload = response.json()
        models = [
            str(item["id"])
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
        return sorted(set(models))
    finally:
        if owned:
            await session.aclose()


async def stream_completion(
    base_url: str,
    api_key: str | None,
    model: str,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]],
    *,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[Event]:
    """Stream one OpenAI-compatible chat completion as typed events."""
    payload = {
        "model": model,
        "messages": list(messages),
        "tools": list(tools),
        "tool_choice": "auto",
        "stream": True,
    }
    owned = client is None
    session = client or httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15))
    calls: dict[int, dict[str, str]] = {}
    finish_reason: str | None = None
    usage: dict[str, int] = {}
    try:
        async with session.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            headers=_headers(api_key),
            json=payload,
        ) as response:
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                try:
                    detail = json.loads(body).get("error", {}).get("message", body)
                except (json.JSONDecodeError, AttributeError):
                    detail = body
                yield Error(f"HTTP {response.status_code}: {str(detail)[:500]}")
                return
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    yield Error("provider returned malformed streaming JSON")
                    return
                if chunk.get("error"):
                    provider_error = chunk["error"]
                    detail = (
                        provider_error.get("message", provider_error)
                        if isinstance(provider_error, dict)
                        else provider_error
                    )
                    yield Error(f"provider error: {str(detail)[:500]}")
                    return
                if chunk.get("usage"):
                    usage = {
                        key: int(value)
                        for key, value in chunk["usage"].items()
                        if isinstance(value, int)
                    }
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if content:
                    yield TextDelta(str(content))
                for part in delta.get("tool_calls") or []:
                    index = int(part.get("index", 0))
                    current = calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if part.get("id"):
                        current["id"] += str(part["id"])
                    function = part.get("function") or {}
                    if function.get("name"):
                        current["name"] += str(function["name"])
                    if function.get("arguments"):
                        current["arguments"] += str(function["arguments"])
        for index in sorted(calls):
            call = calls[index]
            try:
                arguments = json.loads(call["arguments"] or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must decode to an object")
            except (json.JSONDecodeError, ValueError) as exc:
                yield Error(f"invalid arguments for tool {call['name']!r}: {exc}")
                return
            yield ToolCallStart(
                call["id"] or f"call_{index}", call["name"], arguments
            )
        yield Done(finish_reason, usage)
    except (httpx.HTTPError, TimeoutError) as exc:
        yield Error(f"provider request failed: {exc}")
    finally:
        if owned:
            await session.aclose()
