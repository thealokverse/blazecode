"""Tool registry: build schemas for the model and dispatch calls."""

from __future__ import annotations

import json
from typing import Any, Iterable

from blazecode.tools.base import Tool
from blazecode.tools.edit import EditTool
from blazecode.tools.glob_tool import GlobTool
from blazecode.tools.grep import GrepTool
from blazecode.tools.read import ReadTool
from blazecode.tools.shell import ShellTool
from blazecode.tools.write import WriteTool


# Tools that should flip the mascot to (⌕‿⌕) while running.
SEARCHING_TOOLS = {"read", "glob", "grep"}
# Tools that flip the mascot to (⌐■_■) while running.
EDITING_TOOLS = {"write", "edit"}
# Tools that flip the mascot to (ಠ_ಠ) while running.
DEBUGGING_TOOLS = {"shell"}


def mascot_for(tool_name: str) -> str:
    if tool_name in SEARCHING_TOOLS:
        return "(⌕‿⌕)"
    if tool_name in EDITING_TOOLS:
        return "(⌐■_■)"
    if tool_name in DEBUGGING_TOOLS:
        return "(ಠ_ಠ)"
    return ""


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        if tools is None:
            for t in (ReadTool(), WriteTool(), EditTool(),
                      GlobTool(), GrepTool(), ShellTool()):
                self.register(t)
        else:
            for t in tools:
                self.register(t)

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("tool.name must be non-empty")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def preview(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self.get(name)
        try:
            return str(tool.preview(**arguments))
        except Exception as exc:
            return f"{name}({json.dumps(arguments, sort_keys=True)}): [preview failed: {exc}]"
