from __future__ import annotations

import asyncio
from pathlib import Path

from blazecode.agent.observer import NullObserver, Observer
from blazecode.agent.runtime import (
    Streamer,
    assistant_message,
    calls_signature,
    collect_stream,
    compact_api,
    make_system_prompt,
    prepare_skills,
    recover_stream,
    run_tool,
)
from blazecode.agent.todos import TodoList
from blazecode.agent.tool_events import interrupted_tool_message, resolve_tool_name
from blazecode.config.settings import Settings
from blazecode.context.compaction import summarize_history
from blazecode.context.skills import SkillMeta
from blazecode.llm.client import ToolCallStart, stream_completion
from blazecode.mascot import Mascot, State, blaze
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.message import Message
from blazecode.session.store import SessionStore
from blazecode.tools import TOOLS

_REPEAT_LIMIT = 3
_EMPTY_RETRIES = 1


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
        trusted: bool = True,
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
        self._trusted = trusted
        self._skill_catalog: list[SkillMeta] = []
        self._active_skills: list[SkillMeta] = []
        self._compact_ratio: float | None = None

    def request_cancel(self) -> None:
        self._cancel = True

    def replace_messages(self, messages: list[Message]) -> None:
        self.messages = messages
        self.todos.clear()
        self._system_prompt = None
        on_todos = getattr(self.observer, "on_todos", None)
        if callable(on_todos):
            on_todos(self.todos)

    def compact_now(self) -> str:
        try:
            summary = summarize_history(self.messages)
        except Exception as exc:
            summary = f"earlier conversation omitted ({exc})"
        self._append(Message(role="system", content=f"[context compacted]\n{summary}"))
        return summary

    async def run(self, prompt: str) -> str:
        self._cancel = False
        self._compact_ratio = None
        self._skill_catalog, self._active_skills = prepare_skills(
            self.cwd, prompt, self._trusted
        )
        self._system_prompt = None
        if self._active_skills:
            names = ", ".join(skill.name for skill in self._active_skills)
            self._notice(f"using skill: {names}")
        self._append(Message(role="user", content=prompt))
        final_text = ""
        recent: list[str] = []
        empty_tries = 0
        provider_tries = 0
        try:
            for _ in range(self.max_iterations):
                if self._cancel:
                    return self._finish(final_text, "interrupted", State.IDLE)
                self._state(State.THINKING)
                self.observer.on_response_start()
                text, calls, error, inn, out = await collect_stream(
                    self.streamer,
                    self.settings.provider(),
                    self.settings.default_model,
                    self._api_messages(),
                    self._tool_defs,
                    self.observer,
                    lambda: self._cancel,
                )
                final_text = text or final_text
                if error:
                    recovered, provider_tries = await recover_stream(
                        error,
                        text,
                        inn,
                        out,
                        provider_tries,
                        self._append,
                        self._notice,
                        lambda: setattr(self, "_compact_ratio", min(self.settings.compaction_ratio, 0.4)),
                    )
                    if recovered:
                        continue
                    return self._finish(
                        final_text,
                        error,
                        State.IDLE if error == "interrupted" else State.ERROR,
                    )
                provider_tries = 0
                if not text and not calls:
                    self._append(Message(role="assistant", content="", input_tokens=inn, output_tokens=out))
                    if empty_tries < _EMPTY_RETRIES:
                        empty_tries += 1
                        self._append(
                            Message(
                                role="user",
                                content="Your previous response was empty. Continue or reply briefly.",
                            )
                        )
                        continue
                    return self._finish(final_text, "empty model response", State.ERROR)
                self._append(assistant_message(text, calls, inn, out))
                if not calls:
                    return self._finish(text, None, State.SUCCESS)
                if self._repeat_blocked(calls, recent):
                    return self._finish(final_text, "stopped repeated identical tool calls", State.ERROR)
                for index, call in enumerate(calls):
                    if self._cancel:
                        self._abort_tools(calls[index:])
                        return self._finish(final_text, "interrupted", State.IDLE)
                    try:
                        await self._run_tool(call)
                    except (asyncio.CancelledError, KeyboardInterrupt):
                        self._abort_tools(calls[index:])
                        return self._finish(final_text, "interrupted", State.IDLE)
            remaining = self.todos.render()
            detail = f"agent stopped after reaching the iteration limit ({self.max_iterations})"
            if remaining:
                detail += f"\nremaining todos:\n{remaining}"
            return self._finish(final_text, detail, State.ERROR)
        except (asyncio.CancelledError, KeyboardInterrupt):
            return self._finish(final_text, "interrupted", State.IDLE)

    async def _run_tool(self, call: ToolCallStart) -> None:
        self._append(
            await run_tool(
                call,
                self.cwd,
                self.approval,
                self.observer,
                self.todos,
                self._trusted,
                self._state,
            )
        )

    def _repeat_blocked(self, calls: list[ToolCallStart], recent: list[str]) -> bool:
        recent.append(calls_signature(calls))
        if len(recent) < _REPEAT_LIMIT or len(set(recent[-_REPEAT_LIMIT:])) != 1:
            return False
        for call in calls:
            self._append(
                Message(
                    role="tool",
                    content="Error: repeated identical tool call stopped. Try a different approach.",
                    tool_call_id=call.call_id,
                    name=resolve_tool_name(call.name) or call.name,
                )
            )
        return True

    def _abort_tools(self, calls: list[ToolCallStart]) -> None:
        for call in calls:
            self._append(Message(**interrupted_tool_message(call)))

    def _finish(self, text: str, error: str | None, state: State) -> str:
        self._state(state)
        if error and (state is State.ERROR or error == "interrupted"):
            self.observer.on_error(error)
        self.observer.on_complete()
        return text

    def _api_messages(self) -> list[dict]:
        if self._system_prompt is None:
            self._system_prompt = make_system_prompt(
                self.cwd,
                self._trusted,
                self._skill_catalog,
                self._active_skills,
            )
        return compact_api(
            self._system_prompt,
            self.messages,
            self.todos,
            self.settings,
            self._compact_ratio,
        )


    def _notice(self, message: str) -> None:
        hook = getattr(self.observer, "on_notice", None)
        if callable(hook):
            hook(message)

    def _append(self, message: Message) -> None:
        self.messages.append(message)
        self.store.append(message)

    def _state(self, state: State) -> None:
        self.mascot.set_state(state)
        self.observer.on_state(state)
