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

