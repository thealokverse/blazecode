from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from blazecode import __version__
from blazecode.mascot import Mascot, State
from blazecode.tools.base import ToolResult
from blazecode.ui.render import Renderer, render_header, render_status


def test_headless_renderer_streams_only_model_text() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None),
        Mascot(),
        interactive=False,
    )

    renderer.on_response_start()
    renderer.on_state(State.THINKING)
    renderer.on_tool_call("read", {"path": "src/main.py"})
    renderer.on_tool_result("read", ToolResult("file contents"))
    renderer.on_text("Hello **world**")
    renderer.on_complete()

    assert stream.getvalue() == "Hello **world**\n"


def test_interactive_completed_turn_has_success_mascot_and_blank_line() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None),
        Mascot(),
        interactive=True,
    )

    renderer.on_text("Done.")
    renderer.mascot.set_state(State.SUCCESS)
    renderer.on_complete()

    assert stream.getvalue() == "Done.\nblaze (ᵔ◡ᵔ)\n\n"


def test_interactive_error_turn_has_error_mascot_and_blank_line() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None),
        Mascot(),
        interactive=True,
    )

    renderer.mascot.set_state(State.ERROR)
    renderer.on_error("provider failure")
    renderer.on_complete()

    assert stream.getvalue() == "provider failure\nblaze (╥﹏╥)\n\n"


def test_tool_completion_is_compact_and_uses_the_call_target() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None),
        Mascot(),
        interactive=True,
    )

    renderer.on_tool_call("read", {"path": "src/main.py"})
    renderer.on_tool_result("read", ToolResult("long file contents"))

    assert stream.getvalue() == "  ↳ Read src/main.py\n"


def test_header_keeps_the_existing_box(tmp_path: Path) -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=True, color_system=None, width=80)
    render_header(
        console,
        "gpt-test",
        tmp_path,
        git_line="main",
        trusted=False,
        provider="openai",
    )
    text = stream.getvalue()
    assert f"Blazecode (v{__version__})" in text
    assert "model:" in text
    assert "openai / gpt-test" in text
    assert "/models to change" in text
    assert "directory:" in text
    assert "git:" in text
    assert "main" in text
    assert "trust:" in text
    assert "untrusted" in text
    assert "─" in text or "│" in text


def test_status_uses_quiet_labeled_rows() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=80)
    render_status(
        console,
        session="sess-1",
        provider="openai",
        model="gpt-test",
        approval="on",
        workspace="trusted",
        tokens=1240,
        state="idle",
        face="(•‿•)",
        git_line="main",
    )
    text = stream.getvalue()
    assert "session" in text and "sess-1" in text
    assert "provider" in text and "openai" in text
    assert "model" in text and "gpt-test" in text
    assert "approval" in text
    assert "1,240" in text
    assert "blaze" in text


def test_notice_is_compact_and_muted() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None),
        Mascot(),
        interactive=True,
    )
    renderer.on_notice("using skill: review")
    assert stream.getvalue() == "  · using skill: review\n"
