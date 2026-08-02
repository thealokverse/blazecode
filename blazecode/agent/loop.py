# provider agnostic coding agent loop
# streams model output, runs tools, and persists each turn

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

# injectable streamer type used by tests and alternate backends
Streamer = Callable[
    [str, str | None, str, Sequence[dict[str, Any]], Sequence[dict[str, Any]]],
    AsyncIterator[Event],
]


class AgentLoop:
    # owns one session: history, skills, tools, and the model stream

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
        # ui or embedded frontend; null when nothing needs rendering
        self.observer = observer or NullObserver()
        self.mascot = mascot
        # default is the live openai compatible client; tests pass a fake
        self.streamer = streamer
        # hard cap so a runaway tool chain cannot loop forever
        self.max_iterations = max_iterations
        self.skills = SkillLoader(self.cwd)
        # resume prior messages if this store already has a session on disk
        self.messages = store.load()
        self._cancel = False
        # rebuilt lazily so skill reloads and cwd context stay fresh
        self._system_prompt: str | None = None
        # tool schemas are stable for the process lifetime
        self._tool_defs = [tool.definition() for tool in TOOLS.values()]

    def request_cancel(self) -> None:
        # cooperative stop; checked between stream chunks and tool calls
        self._cancel = True

    def reload_skills(self) -> None:
        # drop discovery cache and force system prompt rebuild next turn
        self.skills.invalidate()
        self._system_prompt = None

    def replace_messages(self, messages: list[Message]) -> None:
        # used by /clear and /resume after the store pointer changes
        self.messages = messages

    async def run(self, prompt: str) -> str:
        # one user turn: stream, maybe run tools, repeat until done or error
        self._cancel = False
        self._append(Message(role="user", content=prompt))
        # skill bodies load only when the prompt looks relevant
        extra_skills = relevant_skill_prompt(prompt, self.skills)
        final_text = ""
        try:
            for _ in range(self.max_iterations):
                if self._cancel:
                    return self._finish(final_text, "interrupted", State.IDLE)

                # each iteration is one model round trip
                self._state(State.THINKING)
                self.observer.on_response_start()
                text, calls, error = await self._collect_stream(
                    self.settings.provider(), self._api_messages(extra_skills), self._tool_defs
                )
                final_text = text or final_text

                if error:
                    # keep partial assistant text so history stays coherent
                    if text:
                        self._append(Message(role="assistant", content=text))
                    state = State.IDLE if error == "interrupted" else State.ERROR
                    return self._finish(final_text, error, state)

                # always record the assistant message before running tools
                self._append(
                    Message(role="assistant", content=text or None,
                            tool_calls=[tool_call_message(c) for c in calls])
                )

                # no tool calls means the model is finished answering
                if not calls:
                    return self._finish(text, None, State.SUCCESS)

                # run tools in order; remaining ones get abort markers on cancel
                for index, call in enumerate(calls):
                    if self._cancel:
                        self._abort_tools(calls[index:])
                        return self._finish(final_text, "interrupted", State.IDLE)
                    try:
                        await self._run_tool(call)
                    except asyncio.CancelledError:
                        self._abort_tools(calls[index:])
                        raise

            # safety net if the model keeps requesting tools
            return self._finish(
                final_text,
                f"agent stopped after {self.max_iterations} tool iterations",
                State.ERROR,
            )
        except asyncio.CancelledError:
            # hard cancel from the event loop; still close the ui turn cleanly
            self._finish(final_text, None, State.IDLE)
            raise

    def _abort_tools(self, calls: Sequence[ToolCallStart]) -> None:
        # write synthetic tool errors so the api history stays well formed
        for call in calls:
            self._append(Message(**interrupted_tool_message(call)))

    def _finish(self, text: str, error: str | None, state: State) -> str:
        # shared exit path for success, error, and interrupt
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
        # drain one completion into text, tool calls, and optional error
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
                    # full call already assembled by the stream client
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
        # approve, execute, notify ui, and append the tool result message
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
        # build the request payload: system + compacted history as api dicts
        if self._system_prompt is None:
            self._system_prompt = build_system_prompt(self.cwd, self.skills)
        system_text = self._system_prompt
        if skill_prompt:
            # turn specific skill text is appended only for this round trip
            system_text += f"\n\nRelevant skill instructions:\n\n{skill_prompt}"
        window = self.settings.context_window
        if window == DEFAULT_CONTEXT_WINDOW:
            # fall back to known model windows when config kept the default
            window = context_window(self.settings.default_model)
        compacted = compact_messages(
            [Message(role="system", content=system_text), *self.messages],
            int(window * self.settings.compaction_ratio),
        )
        return [m.to_dict(api=True) for m in compacted]

    def _append(self, message: Message) -> None:
        # keep memory and the jsonl session file in lockstep
        self.messages.append(message)
        self.store.append(message)

    def _state(self, state: State) -> None:
        # update mascot face and push the same state to the observer
        self.mascot.set_state(state)
        self.observer.on_state(state)
