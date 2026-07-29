"""Provider-agnostic coding-agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

from blazecode.agent.observer import NullObserver, Observer
from blazecode.agent.prompts import build_system_prompt, relevant_skill_prompt
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
from blazecode.skills.loader import SkillLoader
from blazecode.tools import TOOLS

Streamer = Callable[
    [str, str | None, str, Sequence[dict[str, Any]], Sequence[dict[str, Any]]],
    AsyncIterator[Event],
]

class AgentLoop:
    """Stream model output, execute tools, and persist each turn."""

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
        self.skills = SkillLoader(self.cwd)
        self.messages = store.load()
        self._cancel = False
        self._system_prompt: str | None = None
        self._tool_defs = [tool.definition() for tool in TOOLS.values()]

    def request_cancel(self) -> None:
        """Cooperatively stop after the current stream or tool finishes."""
        self._cancel = True

    def reload_skills(self) -> None:
        """Refresh skill discovery and rebuild the system prompt next turn."""
        self.skills.invalidate()
        self._system_prompt = None

    def replace_messages(self, messages: list[Message]) -> None:
        """Replace in-memory history after resume or clear."""
        self.messages = messages

    async def run(self, prompt: str) -> str:
        """Run one user turn through completion or an unrecoverable error."""
        self._cancel = False
        self._append(Message(role="user", content=prompt))
        extra_skills = relevant_skill_prompt(prompt, self.skills)
        final_text = ""
        try:
            for _ in range(self.max_iterations):
                if self._cancel:
                    return self._finish(final_text, "interrupted", State.IDLE)
                self.observer.on_response_start()
                self._state(State.THINKING)
                text, calls, error = await self._collect_stream(
                    self.settings.provider(), self._api_messages(extra_skills), self._tool_defs
                )
                final_text = text or final_text
                if error:
                    if text:
                        self._append(Message(role="assistant", content=text))
                    state = State.IDLE if error == "interrupted" else State.ERROR
                    return self._finish(final_text, error, state)
                self._append(
                    Message(role="assistant", content=text or None,
                            tool_calls=[tool_call_message(c) for c in calls])
                )
                if not calls:
                    return self._finish(text, None, State.SUCCESS)
                for index, call in enumerate(calls):
                    if self._cancel:
                        self._abort_tools(calls[index:])
                        return self._finish(final_text, "interrupted", State.IDLE)
                    try:
                        await self._run_tool(call)
                    except asyncio.CancelledError:
                        self._abort_tools(calls[index:])
                        raise
            return self._finish(
                final_text,
                f"agent stopped after {self.max_iterations} tool iterations",
                State.ERROR,
            )
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
    ) -> tuple[str, list[ToolCallStart], str | None]:
        text_parts: list[str] = []
        calls: list[ToolCallStart] = []
        try:
            async for event in self.streamer(
                provider.base_url,
                provider.resolved_api_key(),
                self.settings.default_model,
                messages,
                tools,
            ):
                if self._cancel:
                    return "".join(text_parts), calls, "interrupted"
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                    self.observer.on_text(event.text)
                elif isinstance(event, ToolCallStart):
                    calls.append(event)
                elif isinstance(event, Error):
                    return "".join(text_parts), calls, event.message
                elif isinstance(event, Done):
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return "".join(text_parts), calls, f"provider failure: {exc}"
        return "".join(text_parts), calls, None

    async def _run_tool(self, call: ToolCallStart) -> None:
        resolved = resolve_tool_name(call.name)
        tool = TOOLS.get(resolved) if resolved else None
        if tool is not None and not call.arguments.get("_parse_error"):
            self._state(tool_state(tool))
            self.observer.on_tool_call(tool.name, call.arguments)
        result = await execute_tool(call, self.cwd, self.approval)
        if result.is_error:
            self._state(State.DEBUGGING)
        label = tool.name if tool is not None else (resolved or call.name)
        self.observer.on_tool_result(label, result)
        self._append(Message(role="tool", content=result.content,
                             tool_call_id=call.call_id, name=label))

    def _api_messages(self, skill_prompt: str) -> list[dict[str, Any]]:
        if self._system_prompt is None:
            self._system_prompt = build_system_prompt(self.cwd, self.skills)
        system_text = self._system_prompt
        if skill_prompt:
            system_text += f"\n\nRelevant skill instructions:\n\n{skill_prompt}"
        window = self.settings.context_window
        if window == DEFAULT_CONTEXT_WINDOW:
            window = context_window(self.settings.default_model)
        compacted = compact_messages(
            [Message(role="system", content=system_text), *self.messages],
            int(window * self.settings.compaction_ratio),
        )
        return [m.to_dict(api=True) for m in compacted]

    def _append(self, message: Message) -> None:
        self.messages.append(message)
        self.store.append(message)

    def _state(self, state: State) -> None:
        self.mascot.set_state(state)
        self.observer.on_state(state)
