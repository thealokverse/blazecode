from __future__ import annotations

import io

from rich.console import Console

from blazecode.mascot import Mascot, State
from blazecode.tools.base import ToolResult
from blazecode.ui.render import Renderer


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
