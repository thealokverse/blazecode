"""Provider-agnostic coding-agent loop."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

from blazecode.agent.observer import NullObserver, Observer
from blazecode.agent.prompts import (
    build_system_prompt,
    relevant_skill_prompt,
)
from blazecode.agent.tool_events import tool_call_message, tool_state
from blazecode.config.settings import Provider, Settings
from blazecode.context.compaction import compact_messages
from blazecode.llm.client import (
    Done,
    Error,
    Event,
    TextDelta,
    ToolCallStart,
    stream_completion,
)
from blazecode.mascot import Mascot, State, blaze
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.message import Message
from blazecode.session.store import SessionStore
from blazecode.skills.loader import SkillLoader
from blazecode.tools import TOOLS
from blazecode.tools.base import ToolResult

Streamer = Callable[
    [
        str,
        str | None,
        str,
        Sequence[dict[str, Any]],
        Sequence[dict[str, Any]],
    ],
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
        max_iterations: int = 20,
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

    async def run(self, prompt: str) -> str:
        """Run one user turn through completion or an unrecoverable error."""
        user = Message(role="user", content=prompt)
        self._append(user)
        extra_skills = relevant_skill_prompt(prompt, self.skills)
        final_text = ""

        for _ in range(self.max_iterations):
            provider = self.settings.provider()
            api_messages = self._api_messages(extra_skills)
            tool_definitions = [tool.definition() for tool in TOOLS.values()]
            self._state(State.THINKING)
            self.observer.on_response_start()
            text, calls, error = await self._collect_stream(
                provider, api_messages, tool_definitions
            )
            final_text = text or final_text
            if error:
                self._state(State.ERROR)
                self.observer.on_error(error)
                self.observer.on_complete()
                return final_text

            assistant = Message(
                role="assistant",
                content=text or None,
                tool_calls=[tool_call_message(call) for call in calls],
            )
            self._append(assistant)
            if not calls:
                self._state(State.SUCCESS)
                self.observer.on_complete()
                return text

            for call in calls:
                result = await self._execute(call)
                self._append(
                    Message(
                        role="tool",
                        content=result.content,
                        tool_call_id=call.call_id,
                        name=call.name,
                    )
                )

        message = f"agent stopped after {self.max_iterations} tool iterations"
        self._state(State.ERROR)
        self.observer.on_error(message)
        self.observer.on_complete()
        return final_text

    def replace_messages(self, messages: list[Message]) -> None:
        """Replace in-memory history after resume or clear."""
        self.messages = messages

    async def _collect_stream(
        self,
        provider: Provider,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> tuple[str, list[ToolCallStart], str | None]:
        text_parts: list[str] = []
        calls: list[ToolCallStart] = []
        try:
            key = provider.resolved_api_key()
            async for event in self.streamer(
                provider.base_url,
                key,
                self.settings.default_model,
                messages,
                tools,
            ):
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                    self.observer.on_text(event.text)
                elif isinstance(event, ToolCallStart):
                    calls.append(event)
                elif isinstance(event, Error):
                    return "".join(text_parts), calls, event.message
                elif isinstance(event, Done):
                    continue
        except Exception as exc:
            return "".join(text_parts), calls, f"provider failure: {exc}"
        return "".join(text_parts), calls, None

    async def _execute(self, call: ToolCallStart) -> ToolResult:
        tool = TOOLS.get(call.name)
        if tool is None:
            result = ToolResult(f"Error: unknown tool {call.name!r}", is_error=True)
            self._state(State.DEBUGGING)
            self.observer.on_tool_result(call.name, result)
            return result
        self._state(tool_state(tool))
        self.observer.on_tool_call(call.name, call.arguments)
        approved, reason = self.approval.approve(tool, call.arguments)
        if not approved:
            result = ToolResult(f"Error: {reason}", is_error=True)
        else:
            try:
                result = await tool.run(call.arguments, self.cwd)
            except Exception as exc:
                result = ToolResult(f"Error: {exc}", is_error=True)
        if result.is_error:
            self._state(State.DEBUGGING)
        self.observer.on_tool_result(call.name, result)
        return result

    def _api_messages(self, skill_prompt: str) -> list[dict[str, Any]]:
        system = Message(
            role="system", content=build_system_prompt(self.cwd, self.skills)
        )
        history = list(self.messages)
        if skill_prompt:
            history.append(
                Message(
                    role="system",
                    content="Relevant skill instructions:\n\n" + skill_prompt,
                )
            )
        maximum = int(self.settings.context_window * self.settings.compaction_ratio)
        compacted = compact_messages([system, *history], maximum)
        return [message.to_dict(api=True) for message in compacted]

    def _append(self, message: Message) -> None:
        self.messages.append(message)
        self.store.append(message)

    def _state(self, state: State) -> None:
        self.mascot.set_state(state)
        self.observer.on_state(state)
