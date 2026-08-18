from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

from blazecode.agent.errors import FailureKind, backoff_seconds, classify_error, should_retry
from blazecode.agent.observer import Observer
from blazecode.agent.prompts import build_system_prompt
from blazecode.agent.todos import TodoList
from blazecode.agent.tool_events import (
    execute_tool,
    resolve_tool_name,
    tool_call_message,
    tool_state,
)
from blazecode.config.settings import Provider, Settings
from blazecode.context.compaction import compact_messages
from blazecode.context.skills import SkillMeta, discover_skills, load_skill, select_skills
from blazecode.llm.client import Done, Error, Event, TextDelta, ToolCallStart
from blazecode.llm.models import DEFAULT_CONTEXT_WINDOW, context_window
from blazecode.mascot import State
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.message import Message
from blazecode.tools import TOOLS

Streamer = Callable[
    [str, str | None, str, Sequence[dict[str, Any]], Sequence[dict[str, Any]]],
    AsyncIterator[Event],
]
PROVIDER_RETRIES = 3


async def collect_stream(
    streamer: Streamer,
    provider: Provider,
    model: str,
    messages: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]],
    observer: Observer,
    cancelled: Callable[[], bool],
) -> tuple[str, list[ToolCallStart], str | None, int | None, int | None]:
    text_parts: list[str] = []
    calls: list[ToolCallStart] = []
    try:
        async for event in streamer(
            provider.base_url, provider.resolved_api_key(), model, messages, tools
        ):
            if cancelled():
                return "".join(text_parts), calls, "interrupted", None, None
            if isinstance(event, TextDelta):
                text_parts.append(event.text)
                observer.on_text(event.text)
            elif isinstance(event, ToolCallStart):
                calls.append(event)
            elif isinstance(event, Error):
                return "".join(text_parts), calls, event.message, None, None
            elif isinstance(event, Done):
                usage = event.usage
                return (
                    "".join(text_parts),
                    calls,
                    None,
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                )
    except asyncio.CancelledError:
        return "".join(text_parts), calls, "interrupted", None, None
    except Exception as exc:
        return "".join(text_parts), calls, f"provider failure: {exc}", None, None
    return "".join(text_parts), calls, None, None, None


async def recover_stream(
    error: str,
    text: str,
    inn: int | None,
    out: int | None,
    tries: int,
    append: Callable[[Message], None],
    notice: Callable[[str], None],
    tighten: Callable[[], None],
) -> tuple[bool, int]:
    if error == "interrupted":
        if text:
            append(Message(role="assistant", content=text, input_tokens=inn, output_tokens=out))
        return False, tries
    kind = classify_error(error)
    if should_retry(kind, tries, PROVIDER_RETRIES):
        tries += 1
        if kind is FailureKind.CONTEXT_OVERFLOW:
            tighten()
        notice(f"retrying ({kind.value}): {error}")
        await asyncio.sleep(backoff_seconds(tries - 1))
        return True, tries
    if text:
        append(Message(role="assistant", content=text, input_tokens=inn, output_tokens=out))
    return False, tries


def prepare_skills(cwd: Path, prompt: str, trusted: bool) -> tuple[list[SkillMeta], list[SkillMeta]]:
    try:
        catalog = discover_skills(cwd, trusted=trusted)
        return catalog, select_skills(catalog, prompt)
    except Exception:
        return [], []


def make_system_prompt(
    cwd: Path,
    trusted: bool,
    catalog: Sequence[SkillMeta],
    active: Sequence[SkillMeta],
) -> str:
    loaded: list[tuple[SkillMeta, str]] = []
    for skill in active:
        try:
            loaded.append((skill, load_skill(skill)))
        except OSError:
            continue
    return build_system_prompt(
        cwd, trusted=trusted, skill_index=list(catalog), loaded_skills=loaded
    )


def compact_api(
    system_text: str,
    messages: Sequence[Message],
    todos: TodoList,
    settings: Settings,
    compact_ratio: float | None,
) -> list[dict[str, Any]]:
    if todos.items:
        system_text += f"\n\nCurrent todos:\n{todos.summary()}"
    window = settings.context_window
    if window == DEFAULT_CONTEXT_WINDOW:
        window = context_window(settings.default_model)
    ratio = compact_ratio or settings.compaction_ratio
    budget = max(1, int(window * ratio))
    payload = [Message(role="system", content=system_text), *messages]
    try:
        compacted = compact_messages(payload, budget)
    except Exception:
        compacted = [payload[0], *list(messages)[-6:]]
    return [message.to_dict(api=True) for message in compacted]


async def run_tool(
    call: ToolCallStart,
    cwd: Path,
    approval: ApprovalManager,
    observer: Observer,
    todos: TodoList,
    trusted: bool,
    set_state: Callable[[State], None],
) -> Message:
    resolved = resolve_tool_name(call.name)
    tool = TOOLS.get(resolved) if resolved else None
    label = tool.name if tool is not None else (resolved or call.name)
    if tool is not None and not call.arguments.get("_parse_error"):
        set_state(tool_state(tool))
        observer.on_tool_call(tool.name, call.arguments)

    def on_output(chunk: str) -> None:
        observer.on_tool_output(label, chunk)

    result = await execute_tool(
        call, cwd, approval, on_output=on_output, todo_store=todos, trusted=trusted
    )
    if result.is_error:
        set_state(State.DEBUGGING)
    observer.on_tool_result(label, result)
    if label == "todo" and not result.is_error:
        on_todos = getattr(observer, "on_todos", None)
        if callable(on_todos):
            on_todos(todos)
    return Message(role="tool", content=result.content, tool_call_id=call.call_id, name=label)


def calls_signature(calls: Sequence[ToolCallStart]) -> str:
    payload = []
    for call in calls:
        args = {key: value for key, value in call.arguments.items() if not str(key).startswith("_")}
        try:
            encoded = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            encoded = str(args)
        payload.append(f"{resolve_tool_name(call.name) or call.name}:{encoded}")
    return hashlib.sha256("\n".join(payload).encode()).hexdigest()


def assistant_message(
    text: str, calls: Sequence[ToolCallStart], inn: int | None, out: int | None
) -> Message:
    return Message(
        role="assistant",
        content=text or None,
        input_tokens=inn,
        output_tokens=out,
        tool_calls=[tool_call_message(call) for call in calls],
    )
