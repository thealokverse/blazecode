"""Tests for the agent run loop with a mocked provider (no real API calls)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from blazecode.engine.events import (
    Error as ErrorEvent,
    TextDelta,
    ToolCallRequested,
    ToolResult,
    TurnCompleted,
)
from blazecode.engine.loop import Agent, AgentOptions
from blazecode.engine.session import Session, SessionPaths
from blazecode.permission import PermissionPolicy
from blazecode.providers.client import AssistantTurn, TurnUsage
from blazecode.tools.registry import ToolRegistry


@dataclass
class _ScriptedProvider:
    """Pretends to be a ProviderClient. `script` is a list of AssistantTurns to yield in order.

    Emits the turn's text as chunks before yielding the final AssistantTurn,
    matching the real ProviderClient.stream() contract (where chunks and
    final.text are the same content).
    """
    script: list[AssistantTurn]

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AssistantTurn | str]:
        turn = self.script.pop(0)
        if turn.text:
            yield turn.text
        yield turn


async def test_run_loop_simple_completion(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        script=[AssistantTurn(text="Hello there!", tool_calls=[], usage=TurnUsage(output_tokens=3))]
    )
    paths = SessionPaths(base_dir=tmp_path)
    session = Session(model="gpt-5", provider="openai", paths=paths)
    agent = Agent(
        provider=provider,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        permission=PermissionPolicy(mode="ask"),
        session=session,
        options=AgentOptions(model="gpt-5"),
    )
    events = []
    async for ev in agent.run_turn("hi"):
        events.append(ev)
    assert any(ev.__class__.__name__ == "TurnStarted" for ev in events)
    assert any(isinstance(ev, TextDelta) for ev in events)
    assert any(isinstance(ev, TurnCompleted) for ev in events)
    final_text = "".join(ev.content for ev in events if isinstance(ev, TextDelta))
    assert "Hello there" in final_text


async def test_run_loop_with_tool_call_and_auto_approve(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("world\n")
    provider = _ScriptedProvider(
        script=[
            AssistantTurn(
                text="Let me check that file.",
                tool_calls=[
                    {
                        "id": "call_0",
                        "name": "read",
                        "arguments": {"path": str(tmp_path / "hello.txt")},
                    }
                ],
                usage=TurnUsage(),
            ),
            AssistantTurn(
                text="The file says: world",
                tool_calls=[],
                usage=TurnUsage(output_tokens=5),
            ),
        ]
    )
    paths = SessionPaths(base_dir=tmp_path)
    session = Session(model="gpt-5", provider="openai", paths=paths)
    agent = Agent(
        provider=provider,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        permission=PermissionPolicy(mode="auto"),
        session=session,
        options=AgentOptions(model="gpt-5"),
    )
    events = []
    async for ev in agent.run_turn("what does hello.txt say?"):
        events.append(ev)

    types = [type(ev).__name__ for ev in events]
    assert "ToolCallRequested" in types
    assert "ToolResult" in types
    results = [ev for ev in events if isinstance(ev, ToolResult)]
    assert len(results) == 1
    assert results[0].error is False
    assert "world" in results[0].output

    completed = [ev for ev in events if isinstance(ev, TurnCompleted)]
    assert len(completed) == 1  # only the final assistant turn is "completed"

    req = next(ev for ev in events if isinstance(ev, ToolCallRequested))
    assert req.name == "read"


async def test_run_loop_approval_required_then_denied(tmp_path: Path) -> None:
    provider = _ScriptedProvider(
        script=[
            AssistantTurn(
                text="Writing.",
                tool_calls=[
                    {
                        "id": "call_0",
                        "name": "write",
                        "arguments": {
                            "path": str(tmp_path / "x.txt"),
                            "content": "no",
                        },
                    }
                ],
                usage=TurnUsage(),
            ),
            AssistantTurn(text="OK I gave up.", tool_calls=[], usage=TurnUsage()),
        ]
    )
    paths = SessionPaths(base_dir=tmp_path)
    session = Session(model="gpt-5", provider="openai", paths=paths)
    agent = Agent(
        provider=provider,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        permission=PermissionPolicy(mode="ask"),
        session=session,
        options=AgentOptions(model="gpt-5"),
    )

    events = []
    async for ev in agent.run_turn("write the file"):
        events.append(ev)
        if ev.__class__.__name__ == "ToolCallApprovalNeeded":
            agent.approve(ev.id, False)

    denied_result = next(ev for ev in events if isinstance(ev, ToolResult))
    assert denied_result.error is True
    assert "denied" in denied_result.output.lower()


async def test_run_loop_max_iterations_cap(tmp_path: Path) -> None:
    tool_call = {
        "id": "call_0",
        "name": "read",
        "arguments": {"path": str(tmp_path / "nope.txt")},
    }
    script = [AssistantTurn(text="x", tool_calls=[tool_call], usage=TurnUsage())] * 30
    provider = _ScriptedProvider(script=script)
    paths = SessionPaths(base_dir=tmp_path)
    session = Session(model="gpt-5", provider="openai", paths=paths)
    agent = Agent(
        provider=provider,  # type: ignore[arg-type]
        registry=ToolRegistry(),
        permission=PermissionPolicy(mode="auto"),
        session=session,
        options=AgentOptions(model="gpt-5", max_iterations=3),
    )
    events = []
    async for ev in agent.run_turn("loop forever"):
        events.append(ev)
    err = next((ev for ev in events if isinstance(ev, ErrorEvent)), None)
    assert err is not None
    assert "max iterations" in err.message
