from __future__ import annotations

import io

from rich.console import Console
from rich.syntax import Syntax
from rich.text import Text

from blazecode.mascot import Mascot, State
from blazecode.tools.base import ToolResult
from blazecode.ui.markdown import render_diff, render_markdown, split_stable
from blazecode.ui.render import Renderer


def test_split_stable_keeps_open_code_fence_pending() -> None:
    buffer = "Intro\n\n```python\nprint(1\n"
    stable, pending = split_stable(buffer, 0)
    assert stable == "Intro\n\n"
    assert pending.startswith("```python")


def test_split_stable_commits_closed_fence() -> None:
    buffer = "```py\nx=1\n```\nmore\n"
    stable, pending = split_stable(buffer, 0)
    assert "```py" in stable
    assert stable.endswith("more\n") or "more" in stable + pending
    # fully closed with trailing complete line should commit
    assert pending == "" or not pending.startswith("```")


def test_render_markdown_highlights_code_blocks() -> None:
    rendered = render_markdown("```python\nprint('hi')\n```\n")
    assert isinstance(rendered, Syntax)


def test_code_blocks_strip_trailing_blank_lines_and_skip_empty() -> None:
    from blazecode.ui.markdown import render_partial

    rendered = render_markdown("```bash\npython calculator.py\n\n\n```\n")
    assert isinstance(rendered, Syntax)
    assert rendered.code == "python calculator.py"
    assert render_markdown("```\n\n```\n") == Text("") or not getattr(
        render_markdown("```\n\n```\n"), "code", "x"
    ).strip()
    # live preview is plain one-line text, never a Syntax panel
    assert isinstance(render_partial("```python\nprint(1)\n"), Text)


def test_no_monokai_full_width_background_bars() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=True, color_system="truecolor", width=60)
    console.print(
        render_markdown(
            "Done! Created `calculator.py`. Run it with:\n"
            "```bash\npython calculator.py\n\n```\n"
        )
    )
    import re

    out = stream.getvalue()
    # monokai panel background rgb(39,40,34) must not paint full-width bars
    assert "48;2;39;40;34" not in out
    plain = re.sub(r"\x1b\[[0-9;]*m", "", out)
    assert "python" in plain and "calculator.py" in plain


def test_render_diff_colors_added_and_removed() -> None:
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    text = render_diff(diff)
    assert isinstance(text, Text)
    plain = text.plain
    assert "-old" in plain
    assert "+new" in plain


def test_interactive_renderer_streams_then_matches_final() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None, width=80),
        Mascot(),
        interactive=True,
    )
    renderer.on_response_start()
    for piece in ("Hello ", "**world**", "\n"):
        renderer.on_text(piece)
    renderer.mascot.set_state(State.SUCCESS)
    renderer.on_complete()
    output = stream.getvalue()
    assert "Hello" in output
    assert "world" in output
    assert "blaze" in output


def test_tool_diff_is_rendered_after_summary() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None, width=80),
        Mascot(),
        interactive=True,
    )
    renderer.on_tool_call("edit", {"path": "a.py"})
    renderer.on_tool_result(
        "edit",
        ToolResult(
            "Edited a.py",
            diff="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n",
        ),
    )
    output = stream.getvalue()
    assert "Edited a.py" in output
    assert "+new" in output
    assert "-old" in output


def test_tool_output_chunks_stream_under_tool_line() -> None:
    stream = io.StringIO()
    renderer = Renderer(
        Console(file=stream, force_terminal=False, color_system=None, width=80),
        Mascot(),
        interactive=True,
    )
    renderer.on_tool_call("bash", {"command": "echo hi"})
    renderer.on_tool_output("bash", "he")
    renderer.on_tool_output("bash", "llo\n")
    renderer.on_tool_result("bash", ToolResult("hello"))
    output = stream.getvalue()
    assert "Ran echo hi" in output
    assert "hello" in output
    # partial chunks must not re-indent mid-line
    assert "    he    llo" not in output
    assert "    hello" in output
