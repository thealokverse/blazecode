from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from blazecode.llm.models import (
    load_cached_models,
    normalize_model_ids,
    save_cached_models,
    select_models,
)

_MAX_RETRIES = 3
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

_shared_client: httpx.AsyncClient | None = None
_shared_lock = asyncio.Lock()


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallStart:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Done:
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Error:
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
    lowered = base_url.lower()
    if "openrouter.ai" in lowered:
        headers["HTTP-Referer"] = "https://github.com/thealokverse/blazecode"
        headers["X-Title"] = "Blazecode"
    return headers


def _parse_arguments(raw: str) -> dict[str, Any]:
    # tolerate empty or slightly malformed json from streamed tool args
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        repaired = text.rstrip(", \n\r\t")
        if repaired.count('"') % 2 == 1:
            repaired = repaired + '"'
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


def _normalize_content(content: Any) -> str | None:
    # providers may send str, null, or content part lists
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text is None and item.get("type") == "text":
                    text = item.get("content")
                if text is not None:
                    parts.append(str(text))
        return "".join(parts) if parts else None
    return str(content)


def _accumulate_tool_part(calls: dict[int, dict[str, str]], part: Any) -> None:
    if not isinstance(part, dict):
        return
    try:
        index = int(part.get("index", 0))
    except (TypeError, ValueError):
        index = 0
    current = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
    call_id = part.get("id")
    if call_id:
        text = str(call_id)
        if not current["id"] or len(text) >= len(current["id"]):
            current["id"] = text
    function = part.get("function")
    if function is None:
        name = part.get("name")
        if name:
            current["name"] = _merge_name(current["name"], str(name))
        arguments = part.get("arguments")
        if arguments is not None:
            if isinstance(arguments, dict):
                current["arguments"] = json.dumps(arguments, ensure_ascii=False)
            else:
                current["arguments"] += str(arguments)
        return
    if not isinstance(function, dict):
        return
    name = function.get("name")
    if name:
        current["name"] = _merge_name(current["name"], str(name))
    arguments = function.get("arguments")
    if arguments is None:
        return
    if isinstance(arguments, dict):
        current["arguments"] = json.dumps(arguments, ensure_ascii=False)
    else:
        current["arguments"] += str(arguments)


def _merge_name(existing: str, incoming: str) -> str:
    # merge streamed name fragments without duplicating a full resend
    if not existing:
        return incoming
    if incoming.startswith(existing):
        return incoming
    if existing.startswith(incoming):
        return existing
    if incoming == existing:
        return existing
    return existing + incoming


def _build_payload(
    model: str,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]],
    *,
    reasoning_effort: str = "none",
    base_url: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": list(messages),
        "stream": True,
    }
    effort = reasoning_effort.strip().lower()
    if effort == "adaptive":
        raise ValueError("adaptive reasoning must be resolved before building payload")
    if "openrouter.ai" in base_url.lower():
        payload["reasoning"] = (
            {"enabled": False}
            if effort == "none"
            else {"enabled": True, "effort": effort}
        )
    elif effort != "none":
        payload["reasoning_effort"] = effort
    if tools:
        payload["tools"] = list(tools)
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = False
    return payload


def _error_detail(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]
    if not isinstance(parsed, dict):
        return body[:500]
    error = parsed.get("error", parsed.get("message", body))
    if isinstance(error, dict):
        return str(error.get("message") or error)[:500]
    return str(error)[:500]


async def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    async with _shared_lock:
        if _shared_client is None or _shared_client.is_closed:
            _shared_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=30.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                follow_redirects=True,
            )
        return _shared_client


async def list_models(
    base_url: str,
    api_key: str | None,
    *,
    client: httpx.AsyncClient | None = None,
    use_cache: bool = True,
) -> list[str]:
    owned = client is None
    session = client or httpx.AsyncClient(timeout=15)
    last_error: Exception | None = None
    try:
        for attempt in range(_MAX_RETRIES):
            try:
                response = await session.get(
                    _models_url(base_url),
                    headers=_headers(api_key, base_url),
                )
                if response.status_code in _RETRYABLE_STATUS and attempt + 1 < _MAX_RETRIES:
                    await asyncio.sleep(0.4 * (2**attempt))
                    continue
                response.raise_for_status()
                models = select_models(normalize_model_ids(response.json()))
                if models and use_cache:
                    save_cached_models(base_url, models)
                return models
            except (httpx.HTTPError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                if attempt + 1 >= _MAX_RETRIES:
                    break
                await asyncio.sleep(0.4 * (2**attempt))
        if use_cache:
            stale = load_cached_models(base_url, ttl=0)
            if stale:
                return select_models(stale)
        if last_error is not None:
            raise last_error
        return []
    finally:
        if owned:
            await session.aclose()


def _models_url(base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/models"
    if "openrouter.ai" in base_url.lower():
        # Let OpenRouter exclude non-text and non-tool-capable models server-side.
        return f"{url}?output_modalities=text&supported_parameters=tools&sort=most-popular"
    return url


async def stream_completion(
    base_url: str,
    api_key: str | None,
    model: str,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]],
    reasoning_effort: str = "none",
    *,
    client: httpx.AsyncClient | None = None,
    max_retries: int = _MAX_RETRIES,
) -> AsyncIterator[Event]:
    payload = _build_payload(
        model,
        messages,
        tools,
        reasoning_effort=reasoning_effort,
        base_url=base_url,
    )
    owned = False
    if client is None:
        session = await _get_shared_client()
    else:
        session = client
    try:
        async for event in _stream_with_retries(
            session, base_url, api_key, payload, max_retries=max_retries
        ):
            yield event
    finally:
        if owned:
            await session.aclose()


async def _stream_with_retries(
    session: httpx.AsyncClient,
    base_url: str,
    api_key: str | None,
    payload: dict[str, Any],
    *,
    max_retries: int,
) -> AsyncIterator[Event]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = _headers(api_key, base_url, stream=True)
    retries = max(1, max_retries)
    drop_parallel = False

    for attempt in range(retries):
        body_payload = dict(payload)
        if drop_parallel:
            body_payload.pop("parallel_tool_calls", None)
        calls: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage: dict[str, int] = {}
        emitted = False
        try:
            async with session.stream(
                "POST", url, headers=headers, json=body_payload
            ) as response:
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    detail = _error_detail(body)
                    lower = detail.lower()
                    if (
                        response.status_code in {400, 422}
                        and "parallel_tool_calls" in lower
                        and "parallel_tool_calls" in body_payload
                        and attempt + 1 < retries
                    ):
                        drop_parallel = True
                        continue
                    if (
                        response.status_code in _RETRYABLE_STATUS
                        and attempt + 1 < retries
                        and not emitted
                    ):
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                    yield Error(f"HTTP {response.status_code}: {detail}")
                    return
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    stripped = line.strip().lstrip("\ufeff")
                    if not stripped.startswith("data:"):
                        continue
                    data = stripped[5:].strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            break
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
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
                            if isinstance(value, (int, float))
                        }
                    choices = chunk.get("choices")
                    if not choices or not isinstance(choices, list):
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        continue
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        message = choice.get("message")
                        delta = message if isinstance(message, dict) else {}
                    content = _normalize_content(delta.get("content"))
                    if content:
                        emitted = True
                        yield TextDelta(content)
                    alt = _normalize_content(delta.get("text"))
                    if alt and alt != content:
                        emitted = True
                        yield TextDelta(alt)
                    tool_calls = delta.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for part in tool_calls:
                            try:
                                _accumulate_tool_part(calls, part)
                                emitted = True
                            except Exception:
                                continue
                    function_call = delta.get("function_call")
                    if isinstance(function_call, dict):
                        _accumulate_tool_part(
                            calls,
                            {
                                "index": 0,
                                "id": delta.get("id") or "call_0",
                                "function": function_call,
                            },
                        )
                        emitted = True
            for index in sorted(calls):
                call = calls[index]
                name = (call.get("name") or "").strip()
                if not name:
                    continue
                try:
                    arguments = _parse_arguments(call.get("arguments", ""))
                except ValueError as exc:
                    arguments = {"_parse_error": str(exc)}
                call_id = (call.get("id") or "").strip() or f"call_{index}"
                yield ToolCallStart(call_id, name, arguments)
            yield Done(finish_reason, usage)
            return
        except (httpx.HTTPError, TimeoutError, OSError) as exc:
            if emitted or attempt + 1 >= retries:
                yield Error(f"provider request failed: {exc}")
                return
            await asyncio.sleep(0.5 * (2**attempt))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield Error(f"provider stream failed: {exc}")
            return
