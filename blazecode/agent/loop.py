from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

from blazecode.agent.observer import NullObserver, Observer
from blazecode.agent.prompts import build_system_prompt
from blazecode.agent.todos import TodoList
from blazecode.agent.tool_events import (
    execute_tool,
    interrupted_tool_message,
    resolve_tool_name,
    tool_call_message,
    tool_state,
)
from blazecode.config.settings import Provider, Settings
from blazecode.context.compaction import compact_messages
from blazecode.llm.client import Done, Error, Event, TextDelta, ToolCallStart, stream_completion
from blazecode.llm.models import DEFAULT_CONTEXT_WINDOW, context_window
from blazecode.mascot import Mascot, State, blaze
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.message import Message
from blazecode.session.store import SessionStore
from blazecode.tools import TOOLS

Streamer = Callable[
    [str, str | None, str, Sequence[dict[str, Any]], Sequence[dict[str, Any]]],
    AsyncIterator[Event],
]
_REPEAT_LIMIT = 3


class AgentLoop:
    def __init__(
        self,
        settings: Settings,
        cwd: Path,
        store: SessionStore,
        approval: ApprovalManager,
        observer: Observer | None = None,
        mascot: Mascot = blaze,
        streamer: Streamer = stream_completion,
        max_iterations: int = 40,
    ) -> None:
        self.settings = settings
        self.cwd = cwd.resolve()
        self.store = store
        self.approval = approval
        self.observer = observer or NullObserver()
        self.mascot = mascot
        self.streamer = streamer
        self.max_iterations = max_iterations
        self.messages = store.load()
        self.todos = TodoList()
        self._cancel = False
        self._system_prompt: str | None = None
        self._tool_defs = [tool.definition() for tool in TOOLS.values()]

    def request_cancel(self) -> None:
        self._cancel = True

    def replace_messages(self, messages: list[Message]) -> None:
        self.messages = messages
        self.todos.clear()
        on_todos = getattr(self.observer, "on_todos", None)
        if callable(on_todos):
            on_todos(self.todos)

    async def run(self, prompt: str) -> str:
        self._cancel = False
        self._append(Message(role="user", content=prompt))
        final_text = ""
        recent: list[str] = []
        try:
            for _ in range(self.max_iterations):
                if self._cancel:
                    return self._finish(final_text, "interrupted", State.IDLE)
                self._state(State.THINKING)
                self.observer.on_response_start()
                text, calls, error, inn, out = await self._collect_stream(
                    self.settings.provider(), self._api_messages(), self._tool_defs
                )
                final_text = text or final_text
                if error:
                    if text:
                        self._append(Message(role="assistant", content=text, input_tokens=inn, output_tokens=out))
                    state = State.IDLE if error == "interrupted" else State.ERROR
                    return self._finish(final_text, error, state)
                if not text and not calls:
                    self._append(Message(role="assistant", content="", input_tokens=inn, output_tokens=out))
                    self._append(Message(role="user", content="Your previous response was empty. Continue or reply briefly."))
                    continue
                self._append(Message(
                    role="assistant", content=text or None, input_tokens=inn, output_tokens=out,
                    tool_calls=[tool_call_message(c) for c in calls],
                ))
                if not calls:
                    return self._finish(text, None, State.SUCCESS)
                sig = _calls_signature(calls)
                recent.append(sig)
                if len(recent) >= _REPEAT_LIMIT and len(set(recent[-_REPEAT_LIMIT:])) == 1:
                    for call in calls:
                        self._append(Message(
                            role="tool",
                            content="Error: repeated identical tool call stopped. Try a different approach.",
                            tool_call_id=call.call_id,
                            name=resolve_tool_name(call.name) or call.name,
                        ))
                    return self._finish(final_text, "stopped repeated identical tool calls", State.ERROR)
                for index, call in enumerate(calls):
                    if self._cancel:
                        self._abort_tools(calls[index:])
                        return self._finish(final_text, "interrupted", State.IDLE)
                    try:
                        await self._run_tool(call)
                    except asyncio.CancelledError:
                        self._abort_tools(calls[index:])
                        raise
            remaining = self.todos.render()
            detail = f"agent stopped after reaching the iteration limit ({self.max_iterations})"
            if remaining:
                detail += f"\nremaining todos:\n{remaining}"
            return self._finish(final_text, detail, State.ERROR)
        except asyncio.CancelledError:
            self._finish(final_text, None, State.IDLE)
            raise

    def _abort_tools(self, calls: Sequence[ToolCallStart]) -> None:
        for call in calls:
            self._append(Message(**interrupted_tool_message(call)))

    def _finish(self, text: str, error: str | None, state: State) -> str:
        self._state(state)
        if error and (state is State.ERROR or error == "interrupted"):
            self.observer.on_error(error)
        self.observer.on_complete()
        return text

    async def _collect_stream(
        self,
        provider: Provider,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> tuple[str, list[ToolCallStart], str | None, int | None, int | None]:
        text_parts: list[str] = []
        calls: list[ToolCallStart] = []
        try:
            async for event in self.streamer(
                provider.base_url, provider.resolved_api_key(),
                self.settings.default_model, messages, tools,
            ):
                if self._cancel:
                    return "".join(text_parts), calls, "interrupted", None, None
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                    self.observer.on_text(event.text)
                elif isinstance(event, ToolCallStart):
                    calls.append(event)
                elif isinstance(event, Error):
                    return "".join(text_parts), calls, event.message, None, None
                elif isinstance(event, Done):
                    usage = event.usage
                    return (
                        "".join(text_parts), calls, None,
                        usage.get("prompt_tokens"), usage.get("completion_tokens"),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return "".join(text_parts), calls, f"provider failure: {exc}", None, None
        return "".join(text_parts), calls, None, None, None

    async def _run_tool(self, call: ToolCallStart) -> None:
        resolved = resolve_tool_name(call.name)
        tool = TOOLS.get(resolved) if resolved else None
        label = tool.name if tool is not None else (resolved or call.name)
        if tool is not None and not call.arguments.get("_parse_error"):
            self._state(tool_state(tool))
            self.observer.on_tool_call(tool.name, call.arguments)

        def on_output(chunk: str) -> None:
            self.observer.on_tool_output(label, chunk)

        result = await execute_tool(
            call, self.cwd, self.approval, on_output=on_output, todo_store=self.todos
        )
        if result.is_error:
            self._state(State.DEBUGGING)
        self.observer.on_tool_result(label, result)
        if label == "todo" and not result.is_error:
            on_todos = getattr(self.observer, "on_todos", None)
            if callable(on_todos):
                on_todos(self.todos)
        self._append(Message(role="tool", content=result.content, tool_call_id=call.call_id, name=label))

    def _api_messages(self) -> list[dict[str, Any]]:
        if self._system_prompt is None:
            self._system_prompt = build_system_prompt(self.cwd)
        system_text = self._system_prompt
        if self.todos.items:
            system_text += f"\n\nCurrent todos:\n{self.todos.summary()}"
        window = self.settings.context_window
        if window == DEFAULT_CONTEXT_WINDOW:
            window = context_window(self.settings.default_model)
        budget = max(1, int(window * self.settings.compaction_ratio))
        compacted = compact_messages(
            [Message(role="system", content=system_text), *self.messages],
            budget,
        )
        return [m.to_dict(api=True) for m in compacted]

    def _append(self, message: Message) -> None:
        self.messages.append(message)
        self.store.append(message)

    def _state(self, state: State) -> None:
        self.mascot.set_state(state)
        self.observer.on_state(state)


def _calls_signature(calls: Sequence[ToolCallStart]) -> str:
    payload = []
    for call in calls:
        args = {k: v for k, v in call.arguments.items() if not str(k).startswith("_")}
        try:
            encoded = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            encoded = str(args)
        payload.append(f"{resolve_tool_name(call.name) or call.name}:{encoded}")
    return hashlib.sha256("\n".join(payload).encode()).hexdigest()
