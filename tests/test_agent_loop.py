from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from blazecode.agent.loop import AgentLoop, NullObserver
from blazecode.config.settings import Provider, Settings
from blazecode.llm.client import Done, Event, TextDelta, ToolCallStart
from blazecode.mascot import Mascot, State
from blazecode.permissions.approval import ApprovalManager
from blazecode.session.store import SessionStore


class RecordingObserver(NullObserver):
    def __init__(self) -> None:
        self.states: list[State] = []
        self.text = ""
        self.tools: list[str] = []

    def on_state(self, state: State) -> None:
        self.states.append(state)

    def on_text(self, text: str) -> None:
        self.text += text

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self.tools.append(name)


@pytest.mark.asyncio
async def test_agent_executes_tool_then_returns_final_text(tmp_path: Path) -> None:
    calls = 0

    async def streamer(
        base_url: str,
        api_key: str | None,
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield ToolCallStart("call_1", "write", {"path": "out.txt", "content": "ok"})
            yield Done("tool_calls")
        else:
            assert messages[-1]["role"] == "tool"
            yield TextDelta("Completed.")
            yield Done("stop")

    settings = Settings(
        "test",
        "model",
        "auto",
        [Provider("test", "https://example.test/v1", "none", ["model"])],
    )
    observer = RecordingObserver()
    mascot = Mascot()
    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        settings,
        tmp_path,
        store,
        ApprovalManager("auto"),
        observer,
        mascot,
        streamer,
    )
    result = await loop.run("Create out.txt")
    assert result == "Completed."
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "ok"
    assert observer.tools == ["write"]
    assert State.EDITING in observer.states
    assert mascot.state is State.SUCCESS
    assert [message.role for message in store.load()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_plan_mode_returns_denied_tool_result(tmp_path: Path) -> None:
    invocation = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal invocation
        invocation += 1
        if invocation == 1:
            yield ToolCallStart("1", "bash", {"command": "touch forbidden"})
            yield Done("tool_calls")
        else:
            yield TextDelta("Could not run it.")
            yield Done("stop")

    settings = Settings(
        "p",
        "m",
        "plan",
        [Provider("p", "https://example.test/v1", "none", ["m"])],
    )
    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        settings,
        tmp_path,
        store,
        ApprovalManager("plan"),
        streamer=streamer,
    )
    await loop.run("run it")
    assert not (tmp_path / "forbidden").exists()
    assert "read-only" in store.load()[2].content


@pytest.mark.asyncio
async def test_cancel_mid_batch_fills_missing_tool_results(tmp_path: Path) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        yield ToolCallStart("c1", "write", {"path": "a.txt", "content": "a"})
        yield ToolCallStart("c2", "write", {"path": "b.txt", "content": "b"})
        yield Done("tool_calls")

    settings = Settings(
        "p",
        "m",
        "auto",
        [Provider("p", "https://example.test/v1", "none", ["m"])],
    )
    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        settings,
        tmp_path,
        store,
        ApprovalManager("auto"),
        streamer=streamer,
    )
    loop.request_cancel()
    # Cancel is checked before each tool; force cancel after first tool via side effect.
    original = loop._run_tool

    async def run_once(call: Any) -> None:
        await original(call)
        loop.request_cancel()

    loop._run_tool = run_once  # type: ignore[method-assign]
    await loop.run("write both")
    messages = store.load()
    tool_msgs = [m for m in messages if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0].tool_call_id == "c1"
    assert tool_msgs[1].tool_call_id == "c2"
    assert "interrupted" in tool_msgs[1].content
    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


@pytest.mark.asyncio
async def test_alias_tool_names_match_in_history(tmp_path: Path) -> None:
    calls = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield ToolCallStart("1", "shell", {"command": "echo hi"})
            yield Done("tool_calls")
        else:
            assistant = args[3][-2]
            tool = args[3][-1]
            assert assistant["tool_calls"][0]["function"]["name"] == "bash"
            assert tool["name"] == "bash"
            yield TextDelta("ok")
            yield Done("stop")

    settings = Settings(
        "p",
        "m",
        "auto",
        [Provider("p", "https://example.test/v1", "none", ["m"])],
    )
    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        settings,
        tmp_path,
        store,
        ApprovalManager("auto"),
        streamer=streamer,
    )
    assert await loop.run("run") == "ok"

