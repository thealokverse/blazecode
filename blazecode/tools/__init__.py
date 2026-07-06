"""The complete Blazecode tool registry."""

from __future__ import annotations

from blazecode.tools.base import Tool
from blazecode.tools.bash import BashTool
from blazecode.tools.edit import EditTool
from blazecode.tools.grep import GrepTool
from blazecode.tools.read import ReadTool
from blazecode.tools.write import WriteTool


def build_registry() -> dict[str, Tool]:
    """Create the five-tool registry."""
    tools: list[Tool] = [ReadTool(), WriteTool(), EditTool(), BashTool(), GrepTool()]
    return {tool.name: tool for tool in tools}


TOOLS = build_registry()

__all__ = ["TOOLS", "Tool", "build_registry"]
