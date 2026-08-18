from __future__ import annotations

import asyncio
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
        self.errors: list[str] = []

    def on_state(self, state: State) -> None:
        self.states.append(state)

    def on_text(self, text: str) -> None:
        self.text += text

    def on_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self.tools.append(name)

    def on_error(self, message: str) -> None:
        self.errors.append(message)


def _settings(mode: str = "on") -> Settings:
    return Settings(
        "test",
        "model",
        mode,
        [Provider("test", "https://example.test/v1", "none", ["model"])],
    )


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

    observer = RecordingObserver()
    mascot = Mascot()
    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
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
async def test_tool_call_extra_is_replayed_on_the_next_provider_turn(
    tmp_path: Path,
) -> None:
    calls = 0
    seen: list[dict[str, Any]] = []

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
            yield ToolCallStart(
                "call_1",
                "write",
                {"path": "out.txt", "content": "ok"},
                extra={"extra_content": {"google": {"thought_signature": "sig-1"}}},
            )
            yield Done("tool_calls")
            return
        seen.extend(messages)
        assistant = next(
            message
            for message in messages
            if message.get("role") == "assistant" and message.get("tool_calls")
        )
        tool_call = assistant["tool_calls"][0]
        assert tool_call["extra_content"]["google"]["thought_signature"] == "sig-1"
        yield TextDelta("wrote it")
        yield Done("stop")

    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        streamer=streamer,
    )
    assert await loop.run("Create out.txt") == "wrote it"
    assert seen
    stored = next(message for message in store.load() if message.tool_calls)
    assert stored.tool_calls[0]["extra_content"]["google"]["thought_signature"] == "sig-1"


@pytest.mark.asyncio
async def test_cancelled_stream_finishes_without_raising(tmp_path: Path) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        yield TextDelta("partial")
        raise asyncio.CancelledError

    store = SessionStore(directory=tmp_path / "sessions")
    observer = RecordingObserver()
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        observer,
        streamer=streamer,
    )
    result = await loop.run("go")
    assert result == "partial"
    assert "interrupted" in observer.errors
    assert store.load()[-1].role == "assistant"
    assert store.load()[-1].content == "partial"


@pytest.mark.asyncio
async def test_cancel_during_tool_aborts_remaining_without_raising(
    tmp_path: Path,
) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        yield ToolCallStart("c1", "write", {"path": "a.txt", "content": "a"})
        yield ToolCallStart("c2", "write", {"path": "b.txt", "content": "b"})
        yield Done("tool_calls")

    store = SessionStore(directory=tmp_path / "sessions")
    observer = RecordingObserver()
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        observer,
        streamer=streamer,
    )
    original = loop._run_tool

    async def boom(call: ToolCallStart) -> None:
        if call.call_id == "c2":
            raise asyncio.CancelledError
        await original(call)

    loop._run_tool = boom  # type: ignore[method-assign]
    result = await loop.run("write both")
    assert result == ""
    assert "interrupted" in observer.errors
    tools = [message for message in store.load() if message.role == "tool"]
    assert [item.tool_call_id for item in tools] == ["c1", "c2"]
    assert "interrupted" in tools[1].content
    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()




@pytest.mark.asyncio
async def test_approval_on_without_callback_denies_all_tools(tmp_path: Path) -> None:
    invocation = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal invocation
        invocation += 1
        if invocation == 1:
            yield ToolCallStart("1", "read", {"path": "x.txt"})
            yield Done("tool_calls")
        else:
            yield TextDelta("Could not run it.")
            yield Done("stop")

    store = SessionStore(directory=tmp_path / "sessions")
    (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
    loop = AgentLoop(
        _settings("on"),
        tmp_path,
        store,
        ApprovalManager("on"),
        streamer=streamer,
    )
    await loop.run("read it")
    assert "approval required" in store.load()[2].content


@pytest.mark.asyncio
async def test_approval_off_runs_bash_without_prompt(tmp_path: Path) -> None:
    invocation = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal invocation
        invocation += 1
        if invocation == 1:
            yield ToolCallStart("1", "bash", {"command": "touch allowed"})
            yield Done("tool_calls")
        else:
            yield TextDelta("done")
            yield Done("stop")

    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        streamer=streamer,
    )
    await loop.run("run it")
    assert (tmp_path / "allowed").exists()


@pytest.mark.asyncio
async def test_cancel_mid_batch_fills_missing_tool_results(tmp_path: Path) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        yield ToolCallStart("c1", "write", {"path": "a.txt", "content": "a"})
        yield ToolCallStart("c2", "write", {"path": "b.txt", "content": "b"})
        yield Done("tool_calls")

    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        streamer=streamer,
    )
    loop.request_cancel()
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

    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        streamer=streamer,
    )
    assert await loop.run("run") == "ok"


@pytest.mark.asyncio
async def test_iteration_limit_stops_agent(tmp_path: Path) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        yield ToolCallStart("1", "bash", {"command": "echo loop"})
        yield Done("tool_calls")

    store = SessionStore(directory=tmp_path / "sessions")
    observer = RecordingObserver()
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        observer,
        streamer=streamer,
        max_iterations=2,
    )
    await loop.run("loop forever")
    assert any("iteration limit" in err for err in observer.errors)


@pytest.mark.asyncio
async def test_repeated_identical_tool_calls_stop(tmp_path: Path) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        yield ToolCallStart("1", "bash", {"command": "echo same"})
        yield Done("tool_calls")

    store = SessionStore(directory=tmp_path / "sessions")
    observer = RecordingObserver()
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        observer,
        streamer=streamer,
        max_iterations=10,
    )
    await loop.run("repeat")
    assert any("repeated" in err for err in observer.errors)


@pytest.mark.asyncio
async def test_provider_failure_is_reported(tmp_path: Path) -> None:
    async def streamer(*args: Any) -> AsyncIterator[Event]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    store = SessionStore(directory=tmp_path / "sessions")
    observer = RecordingObserver()
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        observer,
        streamer=streamer,
    )
    await loop.run("hi")
    assert any("provider failure" in err for err in observer.errors)


@pytest.mark.asyncio
async def test_todo_tool_updates_session_list(tmp_path: Path) -> None:
    calls = 0

    async def streamer(*args: Any) -> AsyncIterator[Event]:
        nonlocal calls
        calls += 1
        if calls == 1:
            yield ToolCallStart(
                "1",
                "todo",
                {
                    "action": "replace",
                    "items": [
                        {"content": "step one", "status": "in_progress"},
                        {"content": "step two", "status": "pending"},
                    ],
                },
            )
            yield Done("tool_calls")
        else:
            yield TextDelta("tracked")
            yield Done("stop")

    store = SessionStore(directory=tmp_path / "sessions")
    loop = AgentLoop(
        _settings("off"),
        tmp_path,
        store,
        ApprovalManager("off"),
        streamer=streamer,
    )
    assert await loop.run("multi step") == "tracked"
    assert len(loop.todos.items) == 2
    assert "step one" in loop.todos.render()


@pytest.mark.asyncio
async def test_todos_are_scoped_to_each_agent_loop(tmp_path: Path) -> None:
    async def one_step_todo(content: str) -> AgentLoop:
        calls = 0

        async def streamer(*args: Any) -> AsyncIterator[Event]:
            nonlocal calls
            calls += 1
            if calls == 1:
                yield ToolCallStart(
                    f"call_{content}",
                    "todo",
                    {
                        "action": "replace",
                        "items": [{"content": content, "status": "completed"}],
                    },
                )
                yield Done("tool_calls")
            else:
                yield TextDelta("done")
                yield Done("stop")

        loop = AgentLoop(
            _settings("off"),
            tmp_path,
            SessionStore(directory=tmp_path / f"sessions-{content}"),
            ApprovalManager("off"),
            streamer=streamer,
        )
        await loop.run(content)
        return loop

    first = await one_step_todo("first")
    second = await one_step_todo("second")

    assert first.todos.summary() == "1. [completed] first"
    assert second.todos.summary() == "1. [completed] second"
