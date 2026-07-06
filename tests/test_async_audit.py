from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import get_args

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from blazecode.agent import loop
from blazecode.llm import client
from blazecode.llm.client import Done, Error, Event, TextDelta, ToolCallStart, ToolResult
from blazecode.mascot import Mascot
from blazecode.permissions.approval import ApprovalManager
from blazecode.tools import TOOLS
from blazecode.ui import repl
from blazecode.ui.completer import COMMANDS, slash_completer

PACKAGE = Path(__file__).parents[1] / "blazecode"


def test_package_has_one_asyncio_entry_and_no_nested_loop_apis() -> None:
    asyncio_runs: list[tuple[Path, int]] = []
    for path in PACKAGE.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            assert name not in {"run_async", "run_until_complete", "Application"}
            if name == "asyncio.run":
                asyncio_runs.append((path, node.lineno))
    assert len(asyncio_runs) == 1
    assert asyncio_runs[0][0].name == "cli.py"


def test_repl_awaits_prompt_async_and_wires_slash_completer() -> None:
    tree = ast.parse(inspect.getsource(repl.run_repl))
    awaited = {
        _call_name(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
    }
    assert any(name.endswith("prompt_async") for name in awaited)
    completions = list(
        slash_completer().get_completions(Document("/"), CompleteEvent())
    )
    assert {completion.text for completion in completions} == set(COMMANDS)


def test_command_registry_and_dispatch_cover_all_nine_commands() -> None:
    expected = {
        "/help",
        "/status",
        "/provider",
        "/models",
        "/skills",
        "/export",
        "/clear",
        "/resume",
        "/exit",
    }
    assert set(COMMANDS) == expected
    source = inspect.getsource(repl._command)
    assert all(f'command == "{command}"' in source for command in expected)


def test_async_core_is_ui_neutral_and_event_union_is_complete() -> None:
    llm_source = inspect.getsource(client)
    loop_source = inspect.getsource(loop)
    assert "rich" not in llm_source
    assert "prompt_toolkit" not in llm_source
    assert "rich" not in loop_source
    assert "prompt_toolkit" not in loop_source
    assert len(Path(inspect.getsourcefile(loop)).read_text().splitlines()) <= 200
    assert set(get_args(Event)) == {
        TextDelta,
        ToolCallStart,
        ToolResult,
        Done,
        Error,
    }


def test_tools_and_approval_boundaries() -> None:
    assert set(TOOLS) == {"read", "write", "edit", "bash", "grep"}
    prompted: list[str] = []
    manager = ApprovalManager(
        "ask", lambda name, arguments: prompted.append(name) is None
    )
    for name in ("read", "grep"):
        allowed, _ = manager.approve(TOOLS[name], {})
        assert allowed
    assert prompted == []
    for name in ("write", "edit", "bash"):
        allowed, _ = manager.approve(TOOLS[name], {})
        assert allowed
    assert prompted == ["write", "edit", "bash"]


def test_mascot_state_transition_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(Mascot.set_state)
    assert "asyncio" not in inspect.getsource(Mascot.set_state)


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        prefix = (
            function.value.id if isinstance(function.value, ast.Name) else ""
        )
        return f"{prefix}.{function.attr}" if prefix else function.attr
    return ""
