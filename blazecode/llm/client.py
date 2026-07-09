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


def _headers(
    api_key: str | None,
    base_url: str = "",
    *,
    stream: bool = False,
) -> dict[str, str]:
    headers = {
        "Accept": "text/event-stream" if stream else "application/json",
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # OpenRouter requires attribution headers for some models/routes.
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = "https://github.com/thealokverse/blazecode"
        headers["X-Title"] = "Blazecode"
    return headers


def _parse_arguments(raw: str) -> dict[str, Any]:
    """Parse tool-call arguments, tolerating empty or slightly malformed JSON."""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        # Some providers emit trailing commas or partial objects; try a soft close.
        repaired = text.rstrip(", \n\r\t")
        if not repaired.endswith("}"):
            repaired = repaired + "}"
        if not repaired.startswith("{"):
            repaired = "{" + repaired
        try:
            value = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise ValueError(f"arguments are not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("arguments must decode to an object")
    return value


def _accumulate_tool_part(calls: dict[int, dict[str, str]], part: Any) -> None:
    """Merge one streamed tool-call delta into the accumulator."""
    if not isinstance(part, dict):
        return
    try:
        index = int(part.get("index", 0))
    except (TypeError, ValueError):
        index = 0
    current = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
    call_id = part.get("id")
    if call_id:
        current["id"] += str(call_id)
    function = part.get("function")
    if function is None:
        return
    if not isinstance(function, dict):
        return
    name = function.get("name")
    if name:
        current["name"] += str(name)
    arguments = function.get("arguments")
    if arguments is None:
        return
    if isinstance(arguments, dict):
        # Some gateways send already-decoded argument objects.
        current["arguments"] = json.dumps(arguments)
    else:
        current["arguments"] += str(arguments)


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
            f"{base_url.rstrip('/')}/models",
            headers=_headers(api_key, base_url),
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
            headers=_headers(api_key, base_url, stream=True),
            json=payload,
        ) as response:
            if response.is_error:
                body = (await response.aread()).decode("utf-8", errors="replace")
                try:
                    detail = json.loads(body).get("error", {}).get("message", body)
                except (json.JSONDecodeError, AttributeError, TypeError):
                    detail = body
                yield Error(f"HTTP {response.status_code}: {str(detail)[:500]}")
                return
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    # One bad SSE frame must not abort the whole stream.
                    continue
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    provider_error = chunk["error"]
                    detail = (
                        provider_error.get("message", provider_error)
                        if isinstance(provider_error, dict)
                        else provider_error
                    )
                    yield Error(f"provider error: {str(detail)[:500]}")
                    return
                if chunk.get("usage") and isinstance(chunk["usage"], dict):
                    usage = {
                        key: int(value)
                        for key, value in chunk["usage"].items()
                        if isinstance(value, int)
                    }
                choices = chunk.get("choices")
                if not choices or not isinstance(choices, list):
                    continue
                choice = choices[0]
                if not isinstance(choice, dict):
                    continue
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    continue
                content = delta.get("content")
                if content:
                    yield TextDelta(str(content))
                tool_calls = delta.get("tool_calls")
                if tool_calls is None:
                    continue
                if not isinstance(tool_calls, list):
                    continue
                for part in tool_calls:
                    try:
                        _accumulate_tool_part(calls, part)
                    except Exception:
                        continue
        for index in sorted(calls):
            call = calls[index]
            name = call.get("name") or ""
            if not name:
                continue
            try:
                arguments = _parse_arguments(call.get("arguments", ""))
            except ValueError as exc:
                yield Error(f"invalid arguments for tool {name!r}: {exc}")
                continue
            yield ToolCallStart(
                call.get("id") or f"call_{index}", name, arguments
            )
        yield Done(finish_reason, usage)
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        yield Error(f"provider request failed: {exc}")
    except Exception as exc:
        yield Error(f"provider stream failed: {exc}")
    finally:
        if owned:
            await session.aclose()
