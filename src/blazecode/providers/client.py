"""OpenAI SDK wrapper: minimal, bulletproof streaming, clean error boundaries."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from blazecode.core.events import Error
from blazecode.providers.registry import (
    PROVIDERS,
    base_url_for_provider,
    provider_shortcut_for_model,
)

DEFAULT_MAX_TOKENS = 4096
RETRY_MAX_TOKENS = 500
MIN_TOKENS = 300

# ---- helpers ----


def _base_url_for(model: str) -> str | None:
    shortcut = provider_shortcut_for_model(model)
    return base_url_for_provider(shortcut)


def _api_key_for(model: str) -> str | None:
    shortcut = provider_shortcut_for_model(model)
    info = PROVIDERS.get(shortcut)
    if not info or not info.env_var:
        return "ollama"
    key = os.environ.get(info.env_var)
    return key or "missing"


def _model_id_for(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _friendly_message(exc: BaseException) -> str:
    msg = getattr(exc, "message", None)
    if not msg:
        msg = str(exc) or type(exc).__name__
    if msg.startswith("{") and msg.endswith("}"):
        try:
            obj = json.loads(msg)
            if isinstance(obj, dict):
                err = obj.get("error")
                if isinstance(err, dict):
                    for k in ("message", "error", "detail"):
                        v = err.get(k)
                        if isinstance(v, str) and v:
                            return v
                elif isinstance(err, str):
                    return err
                if "message" in obj and isinstance(obj["message"], str):
                    return obj["message"]
        except (json.JSONDecodeError, ValueError):
            pass
    if len(msg) > 500:
        msg = msg[:500] + "..."
    return msg


def _parse_402_affordable(message: str) -> int | None:
    """Parse 'can only afford NNNN' from a 402 error message."""
    m = re.search(r"can only afford (\d+)", message, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*tokens?\s*(remaining|budget|credit)", message, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _format_error(exc: BaseException, *, model: str) -> Error:
    name = type(exc).__name__
    msg = _friendly_message(exc)
    if isinstance(exc, AuthenticationError):
        prefix = "Authentication failed"
        recoverable = False
    elif isinstance(exc, PermissionDeniedError):
        prefix = "Permission denied"
        recoverable = False
    elif isinstance(exc, RateLimitError):
        prefix = "Rate limited"
        recoverable = True
    elif isinstance(exc, NotFoundError):
        prefix = "Model not found"
        recoverable = False
    elif isinstance(exc, BadRequestError):
        prefix = "Bad request"
        recoverable = False
    elif isinstance(exc, APIConnectionError):
        prefix = "API connection failed"
        recoverable = True
    elif isinstance(exc, APIError):
        prefix = "Provider error"
        recoverable = False
    else:
        prefix = "Unexpected error"
        recoverable = False
    shortcut = provider_shortcut_for_model(model)
    info = PROVIDERS.get(shortcut)
    hint = info.env_var if info else None
    suffix = f" — set {hint} in your environment or ~/.blazecode/config.toml" if hint else ""
    return Error(message=f"{prefix}: {name}: {msg}{suffix}", recoverable=recoverable)


# ---- data shapes ----


@dataclass
class TurnUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: TurnUsage = field(default_factory=TurnUsage)
    finish_reason: str | None = None


# ---- ProviderClient ----


class ProviderClient:
    """Thin wrapper around `AsyncOpenAI` with streaming, tool calls, and
    offline-safe error handling.
    """

    def __init__(self) -> None:
        self._clients: dict[str, AsyncOpenAI] = {}

    def _client_for(self, model: str) -> AsyncOpenAI:
        if model in self._clients:
            return self._clients[model]
        client = AsyncOpenAI(
            base_url=_base_url_for(model),
            api_key=_api_key_for(model),
        )
        self._clients[model] = client
        return client

    def _tools_payload(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        return tools or None

    # ---- pre-flight check ----

    async def test_connection(self, model: str) -> tuple[bool, str]:
        shortcut = provider_shortcut_for_model(model)
        if shortcut == "ollama":
            return True, "ollama: no key required"
        info = PROVIDERS.get(shortcut)
        env = info.env_var if info else None
        if env and not os.environ.get(env):
            return False, f"missing {env} — set it in your environment or ~/.blazecode/config.toml"
        try:
            client = self._client_for(model)
            await client.chat.completions.create(
                model=_model_id_for(model),
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True, "connection ok"
        except Exception as exc:
            return False, _friendly_message(exc)

    # ---- streaming with dynamic token scaling ----

    async def _stream_completion(
        self,
        client: AsyncOpenAI,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> AsyncIterator[str | Turn | Error]:
        """Stream with a given max_tokens. Lets create() errors propagate up."""
        kwargs: dict[str, Any] = {
            "model": _model_id_for(model),
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = self._tools_payload(tools)

        response = await client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        tc_slots: dict[int, dict[str, Any]] = {}
        usage = TurnUsage()
        finish_reason: str | None = None

        try:
            async for chunk in response:
                if getattr(chunk, "usage", None):
                    u = chunk.usage
                    usage.input_tokens = int(getattr(u, "prompt_tokens", 0) or 0)
                    usage.output_tokens = int(getattr(u, "completion_tokens", 0) or 0)
                    usage.total_tokens = int(getattr(u, "total_tokens", 0) or 0)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "finish_reason", None):
                    finish_reason = delta.finish_reason
                content = getattr(delta, "content", None)
                if content:
                    text_parts.append(content)
                    yield content
                for tc_delta in (getattr(delta, "tool_calls", None) or []):
                    idx = int(getattr(tc_delta, "index", 0) or 0)
                    slot = tc_slots.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if getattr(tc_delta, "id", None):
                        slot["id"] = tc_delta.id
                    fn = getattr(tc_delta, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments
        except Exception as exc:
            yield _format_error(exc, model=model)
            return

        tool_calls: list[dict[str, Any]] = []
        for idx in sorted(tc_slots):
            slot = tc_slots[idx]
            args_raw = slot.get("arguments") or ""
            parsed: dict[str, Any]
            if not args_raw.strip():
                parsed = {}
            else:
                try:
                    parsed = json.loads(args_raw)
                    if not isinstance(parsed, dict):
                        parsed = {"_value": parsed}
                except json.JSONDecodeError:
                    parsed = {"_raw": args_raw, "_parse_error": "arguments were not valid JSON"}
            tool_calls.append(
                {
                    "id": slot.get("id") or f"call_{idx}",
                    "name": slot.get("name") or "",
                    "arguments": parsed,
                    "arguments_raw": args_raw,
                }
            )

        yield Turn(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[str | Turn | Error]:
        """Stream a chat completion with silent 402 auto-recovery.

        On a 402 Payment Required error, retries internally with a reduced
        max_tokens. No intermediate text or notices are yielded — only the
        final successful stream or an Error event is visible.
        """
        client = self._client_for(model)

        attempts = [(max_tokens, False)]
        if max_tokens > RETRY_MAX_TOKENS:
            attempts.append((RETRY_MAX_TOKENS, True))

        for attempt_max, is_fallback in attempts:
            try:
                async for piece in self._stream_completion(
                    client, model, messages, tools, attempt_max
                ):
                    yield piece
                return
            except APIStatusError as exc:
                if exc.status_code == 402 and is_fallback:
                    yield Error(
                        message=(
                            "Credit limit too low even at reduced token count. "
                            "Run /models and pick a cheaper or free model "
                            "(e.g. openrouter/google/gemini-2.0-flash-exp:free)."
                        ),
                        recoverable=False,
                    )
                    return
                if exc.status_code != 402:
                    yield _format_error(exc, model=model)
                    return
                # 402 on the first attempt — silently retry with fallback below
            except Exception as exc:
                yield _format_error(exc, model=model)
                return

    # ---- non-streaming ----

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> Turn:
        client = self._client_for(model)
        kwargs: dict[str, Any] = {
            "model": _model_id_for(model),
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = self._tools_payload(tools)
        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            return Turn(text=f"error: {_friendly_message(exc)}")
        choice = resp.choices[0]
        text = getattr(choice.message, "content", "") or ""
        tc_slots: dict[int, dict[str, Any]] = {}
        for tc_delta in (getattr(choice.message, "tool_calls", None) or []):
            idx = int(getattr(tc_delta, "index", 0) or 0)
            slot = tc_slots.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if getattr(tc_delta, "id", None):
                slot["id"] = tc_delta.id
            fn = getattr(tc_delta, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    slot["name"] = fn.name
                if getattr(fn, "arguments", None):
                    slot["arguments"] += fn.arguments
        tool_calls: list[dict[str, Any]] = []
        for idx in sorted(tc_slots):
            slot = tc_slots[idx]
            args_raw = slot.get("arguments") or ""
            try:
                parsed = json.loads(args_raw) if args_raw.strip() else {}
            except json.JSONDecodeError:
                parsed = {"_raw": args_raw}
            tool_calls.append({
                "id": slot.get("id") or f"call_{idx}",
                "name": slot.get("name") or "",
                "arguments": parsed,
            })
        usage = TurnUsage()
        if getattr(resp, "usage", None):
            u = resp.usage
            usage.input_tokens = int(getattr(u, "prompt_tokens", 0) or 0)
            usage.output_tokens = int(getattr(u, "completion_tokens", 0) or 0)
            usage.total_tokens = int(getattr(u, "total_tokens", 0) or 0)
        return Turn(text=text, tool_calls=tool_calls, usage=usage)


def ensure_env_loaded(keys: dict[str, str]) -> None:
    for name, value in keys.items():
        if value and not os.environ.get(name):
            os.environ[name] = value


__all__ = ["ProviderClient", "Turn", "TurnUsage", "Error", "ensure_env_loaded", "DEFAULT_MAX_TOKENS"]
