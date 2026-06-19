"""Tests for the agent run loop with a mocked provider (no real API calls)."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from blazecode.core.events import Error, TextDelta, ToolCallRequested, ToolResult, TurnCompleted
from blazecode.core.permissions import PermissionPolicy
from blazecode.engine.loop import Agent, AgentOptions
from blazecode.engine.session import Session, SessionPaths
from blazecode.providers.client import Turn, TurnUsage
from blazecode.tools.registry import ToolRegistry


@dataclass
class _ScriptedProvider:
    script: list[Turn]

    async def stream(self, *, model, messages, tools=None):
        turn = self.script.pop(0)
        if turn.text:
            yield turn.text
        yield turn


async def test_simple_completion(tmp_path):
    provider = _ScriptedProvider(script=[
        Turn(text="Hello!", tool_calls=[], usage=TurnUsage(output_tokens=2)),
    ])
    session = Session(model="gpt-4o", provider="openai", paths=SessionPaths(base_dir=tmp_path))
    agent = Agent(provider=provider, registry=ToolRegistry(),
                  permission=PermissionPolicy(), session=session,
                  options=AgentOptions(model="gpt-4o"))
    events = []
    async for ev in agent.run_turn("hi"):
        events.append(ev)
    assert any(ev.__class__.__name__ == "TurnStarted" for ev in events)
    assert any(isinstance(ev, TextDelta) for ev in events)
    assert any(isinstance(ev, TurnCompleted) for ev in events)
    assert "Hello!" in "".join(ev.content for ev in events if isinstance(ev, TextDelta))


async def test_tool_call_with_auto_approve(tmp_path):
    (tmp_path / "hello.txt").write_text("world\n")
    provider = _ScriptedProvider(script=[
        Turn(text="checking", tool_calls=[{"id": "c0", "name": "read",
                                            "arguments": {"path": str(tmp_path / "hello.txt")}}]),
        Turn(text="done", tool_calls=[], usage=TurnUsage(output_tokens=1)),
    ])
    session = Session(model="gpt-4o", provider="openai", paths=SessionPaths(base_dir=tmp_path))
    perm = PermissionPolicy(mode="auto")
    agent = Agent(provider=provider, registry=ToolRegistry(), permission=perm,
                  session=session, options=AgentOptions(model="gpt-4o"))
    events = []
    async for ev in agent.run_turn("?"):
        events.append(ev)
    types = [type(ev).__name__ for ev in events]
    assert "ToolCallRequested" in types and "ToolResult" in types
    result = next(ev for ev in events if isinstance(ev, ToolResult))
    assert result.error is False and "world" in result.output
    completed = [ev for ev in events if isinstance(ev, TurnCompleted)]
    assert len(completed) == 1


async def test_approval_required_then_denied(tmp_path):
    provider = _ScriptedProvider(script=[
        Turn(text="writing", tool_calls=[{"id": "c0", "name": "write",
                                          "arguments": {"path": str(tmp_path / "x.txt"), "content": "no"}}]),
        Turn(text="ok", tool_calls=[]),
    ])
    session = Session(model="gpt-4o", provider="openai", paths=SessionPaths(base_dir=tmp_path))
    agent = Agent(provider=provider, registry=ToolRegistry(),
                  permission=PermissionPolicy(), session=session,
                  options=AgentOptions(model="gpt-4o"))
    events = []
    async for ev in agent.run_turn("do it"):
        events.append(ev)
        if ev.__class__.__name__ == "ToolCallApprovalNeeded":
            agent.approve(ev.id, False)
    result = next(ev for ev in events if isinstance(ev, ToolResult))
    assert result.error is True and "denied" in result.output.lower()


async def test_max_iterations_cap(tmp_path):
    tc = {"id": "c0", "name": "read", "arguments": {"path": str(tmp_path / "nope.txt")}}
    provider = _ScriptedProvider(script=[Turn(text="x", tool_calls=[tc])] * 30)
    session = Session(model="gpt-4o", provider="openai", paths=SessionPaths(base_dir=tmp_path))
    agent = Agent(provider=provider, registry=ToolRegistry(),
                  permission=PermissionPolicy(mode="auto"),
                  session=session, options=AgentOptions(model="gpt-4o", max_iterations=3))
    events = []
    async for ev in agent.run_turn("loop"):
        events.append(ev)
    err = next((ev for ev in events if isinstance(ev, Error)), None)
    assert err is not None and "max iterations" in err.message
