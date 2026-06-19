"""Agent run loop.

Drives one user turn: stream provider response, dispatch tool calls, retry
transient errors with backoff, surface approvals to the UI.

Strict message formatting:
  * Every tool execution appends an OpenAI-format tool message that includes
    `tool_call_id`, `name`, and `content` (Anthropic rejects tool messages
    that don't carry the tool name).
  * Tool errors (including malformed JSON from the model) are surfaced to the
    model as a tool result with `error=True`, not as an exception that
    crashes the loop.

Provider errors:
  * The provider client NEVER raises. It yields `Error` events directly.
  * The engine loop passes `Error` events from the client straight through
    to the UI and aborts the turn WITHOUT touching the session history
    (the LLM turn never successfully started).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from blazecode.core.errors import ProviderError
from blazecode.core.events import (
    Error,
    TextDelta,
    ToolCallApprovalNeeded,
    ToolCallRequested,
    ToolResult,
    TurnCompleted,
    TurnStarted,
)
from blazecode.core.permissions import PermissionPolicy
from blazecode.engine.session import Session
from blazecode.providers.client import ProviderClient, Turn
from blazecode.providers.registry import provider_shortcut_for_model
from blazecode.tools.registry import ToolRegistry


# ---- message shaping helpers (OpenAI format) ----

def _tool_message(*, call_id: str, name: str, output: str, error: bool) -> dict[str, Any]:
    """Build a strict tool message.

    Anthropic's API rejects tool messages that don't include the tool name,
    so we always set it.
    """
    msg: dict[str, Any] = {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": output,
    }
    if error:
        msg["error"] = True
    return msg


def _assistant_with_tool_calls(turn: Turn) -> dict[str, Any]:
    """Build the OpenAI assistant message that includes tool_calls."""
    msg: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
    calls: list[dict[str, Any]] = []
    for tc in turn.tool_calls:
        args = tc.get("arguments", {})
        if not isinstance(args, str):
            args = json.dumps(args)
        calls.append(
            {
                "id": tc.get("id") or "call_0",
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": args,
                },
            }
        )
    if calls:
        msg["tool_calls"] = calls
    return msg


# ---- options ----

@dataclass
class AgentOptions:
    model: str
    max_iterations: int = 25
    context_window: int = 128_000


# ---- agent ----

@dataclass
class Agent:
    """Drives the agentic loop for a session."""

    provider: ProviderClient
    registry: ToolRegistry
    permission: PermissionPolicy
    session: Session
    options: AgentOptions
    _pending: dict[str, asyncio.Future[bool]] = field(
        default_factory=dict, init=False, repr=False
    )

    # ---- public ----

    def session_info(self):
        from blazecode.core.events import SessionInfo
        return SessionInfo(
            session_id=self.session.session_id,
            model=self.options.model,
            provider=provider_shortcut_for_model(self.options.model),
        )

    def approve(self, call_id: str, decision: bool) -> None:
        fut = self._pending.pop(call_id, None)
        if fut is not None and not fut.done():
            fut.set_result(decision)

    def run_turn(self, user_input: str) -> AsyncIterator[Any]:
        return _run_turn(self, user_input)


# ---- main loop ----

async def _run_turn(agent: Agent, user_input: str) -> AsyncIterator[Any]:
    yield TurnStarted()
    # The user message IS appended to history even if the turn later fails —
    # it's part of the user's input, not a model response.
    agent.session.append({"role": "user", "content": user_input})

    iterations = 0
    while True:
        iterations += 1
        if iterations > agent.options.max_iterations:
            yield Error(
                message=f"tool-call chain exceeded max iterations ({agent.options.max_iterations})",
                recoverable=False,
            )
            return

        if agent.session.truncate_if_needed(
            model=agent.options.model,
            context_window=agent.options.context_window,
        ):
            yield TextDelta(content="\n[history trimmed to fit context window]\n")

        # Drive the provider in a task; bridge text deltas live to the outer gen.
        # The client yields `str | Turn | Error`. text -> queue, Turn -> holder,
        # Error -> holder (with the same "skip session update" semantics).
        text_queue: asyncio.Queue[Any] = asyncio.Queue()
        done_event = asyncio.Event()
        final_holder: dict[str, Any] = {}

        async def _driver() -> None:
            try:
                result = await _stream_with_retries(agent, text_queue)
                if isinstance(result, Error):
                    final_holder["error"] = result
                elif isinstance(result, Turn):
                    final_holder["turn"] = result
                else:
                    final_holder["error"] = Error(
                        message="no assistant turn produced", recoverable=False
                    )
            except BaseException as exc:  # defense in depth — should never fire
                final_holder["error"] = _error_event_from_exception(exc)
            finally:
                done_event.set()

        driver_task = asyncio.create_task(_driver())

        while True:
            get_task = asyncio.create_task(text_queue.get())
            done_task = asyncio.create_task(done_event.wait())
            done, _ = await asyncio.wait(
                {get_task, done_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if get_task in done:
                piece = get_task.result()
                if isinstance(piece, Error):
                    # Error event from the client itself. Forward and stop.
                    yield piece
                    # Drain remaining text (probably empty) and stop driver.
                    while not text_queue.empty():
                        text_queue.get_nowait()
                    if not done_task.done():
                        await done_task
                    await driver_task
                    return
                if isinstance(piece, TextDelta):
                    yield piece
                    continue
                # Non-text sentinel: drain and stop.
                while not text_queue.empty():
                    extra = text_queue.get_nowait()
                    if isinstance(extra, TextDelta):
                        yield extra
                if not done_task.done():
                    await done_task
                await driver_task
                break
            if done_task in done:
                while not text_queue.empty():
                    extra = text_queue.get_nowait()
                    if isinstance(extra, TextDelta):
                        yield extra
                await driver_task
                break

        err = final_holder.get("error")
        if err is not None:
            # Provider failed; do NOT touch session history (no model turn).
            yield err
            return
        turn = final_holder.get("turn")
        if turn is None:
            yield Error(message="no assistant turn produced", recoverable=False)
            return

        agent.session.record_usage(turn.usage.to_dict())

        if not turn.tool_calls:
            yield TurnCompleted(usage=turn.usage.to_dict())
            agent.session.persist()
            return

        agent.session.append(_assistant_with_tool_calls(turn))

        for tc in turn.tool_calls:
            call_id = tc.get("id") or "call_0"
            name = tc.get("name") or ""
            args = tc.get("arguments") or {}

            yield ToolCallRequested(id=call_id, name=name, arguments=args)

            if (
                isinstance(args, dict)
                and "_parse_error" in args
            ):
                err_msg = (
                    "error: tool arguments were not valid JSON and could not be parsed: "
                    f"{args.get('_raw', '')[:200]}"
                )
                yield ToolResult(id=call_id, name=name, output=err_msg, error=True)
                agent.session.append(
                    _tool_message(call_id=call_id, name=name, output=err_msg, error=True)
                )
                continue

            if name not in agent.registry:
                err = f"error: unknown tool: {name!r}"
                yield ToolResult(id=call_id, name=name, output=err, error=True)
                agent.session.append(
                    _tool_message(call_id=call_id, name=name, output=err, error=True)
                )
                continue

            tool = agent.registry.get(name)
            if agent.permission.requires_prompt(
                name, tool_requires_approval=tool.requires_approval
            ):
                preview = agent.registry.preview(name, args)
                loop = asyncio.get_running_loop()
                approval_future: asyncio.Future[bool] = loop.create_future()
                agent._pending[call_id] = approval_future
                try:
                    yield ToolCallApprovalNeeded(
                        id=call_id, name=name, arguments=args, preview=preview
                    )
                    decision = await approval_future
                finally:
                    agent._pending.pop(call_id, None)
                if not decision:
                    msg = "denied by user"
                    yield ToolResult(id=call_id, name=name, output=msg, error=True)
                    agent.session.append(
                        _tool_message(call_id=call_id, name=name, output=msg, error=True)
                    )
                    continue

            output, error = await _run_tool_safely(agent, name, args)
            yield ToolResult(id=call_id, name=name, output=output, error=error)
            agent.session.append(
                _tool_message(call_id=call_id, name=name, output=output, error=error)
            )


def _error_event_from_exception(exc: BaseException) -> Error:
    if isinstance(exc, ProviderError):
        return Error(message=str(exc), recoverable=exc.recoverable)
    if isinstance(exc, asyncio.CancelledError):
        return Error(message="cancelled", recoverable=False)
    return Error(message=f"unexpected error: {exc}", recoverable=False)


async def _stream_with_retries(
    agent: Agent, text_queue: asyncio.Queue[Any]
) -> Turn | Error:
    """Stream one provider turn with retry/backoff for transient errors.

    The client yields `str | Turn | Error`. We push text to the queue,
    forward errors (with retry when `recoverable=True`), and return the
    final `Turn` on success.
    """
    messages = agent.session.to_messages()
    tools = agent.registry.schemas()
    max_attempts = 3
    backoff = 1.0
    last_error: Error | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            final: Turn | None = None
            async for piece in agent.provider.stream(
                model=agent.options.model, messages=messages, tools=tools
            ):
                if isinstance(piece, Error):
                    if piece.recoverable and attempt < max_attempts:
                        await text_queue.put(
                            TextDelta(
                                content=f"\n[retrying ({attempt}/{max_attempts - 1})...]\n"
                            )
                        )
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        last_error = piece
                        break
                    return piece
                if isinstance(piece, Turn):
                    final = piece
                elif isinstance(piece, str):
                    await text_queue.put(TextDelta(content=piece))
            else:
                return final or Turn(text="")
        except asyncio.CancelledError:
            raise
    return last_error or Error(message="retries exhausted", recoverable=False)


async def _run_tool_safely(
    agent: Agent, name: str, args: dict[str, Any]
) -> tuple[str, bool]:
    try:
        tool = agent.registry.get(name)
        output = await tool.run(**args)
        if not isinstance(output, str):
            output = str(output)
        return output, False
    except Exception as exc:
        return f"error: tool {name!r} failed: {type(exc).__name__}: {exc}", True


_NO_EMOJI = "You are a professional CLI coding agent. Never use emojis in your responses."


def build_agent(
    *,
    model: str,
    session: Session,
    registry: ToolRegistry | None = None,
    permission: PermissionPolicy | None = None,
    provider: ProviderClient | None = None,
    max_iterations: int = 25,
    context_window: int = 128_000,
) -> Agent:
    agent = Agent(
        provider=provider or ProviderClient(),
        registry=registry or ToolRegistry(),
        permission=permission or PermissionPolicy(),
        session=session,
        options=AgentOptions(
            model=model, max_iterations=max_iterations, context_window=context_window
        ),
    )
    agent.session.replace_system(_NO_EMOJI)
    return agent


__all__ = ["Agent", "AgentOptions", "build_agent"]
