from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# optional live stdout/stderr hook used by long-running tools
OutputCallback = Callable[[str], None]


@dataclass(slots=True)
class ToolResult:
    content: str
    is_error: bool = False
    diff: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


MAX_TOOL_CHARS = 32_000


def bound_text(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    head = (limit * 3) // 4
    tail = max(0, limit - head - 80)
    marker = f"\n… [truncated {omitted} chars; output bounded] …\n"
    return text[:head] + marker + (text[-tail:] if tail else "")


def bound_result(result: ToolResult, limit: int = MAX_TOOL_CHARS) -> ToolResult:
    content = bound_text(result.content, limit)
    if content == result.content:
        return result
    return ToolResult(content, result.is_error, result.diff, result.metadata)


class Tool(ABC):
    name: str
    description: str
    mutating: bool = False
    schema: dict[str, Any]

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    @abstractmethod
    async def run(
        self,
        arguments: dict[str, Any],
        cwd: Path,
        *,
        on_output: OutputCallback | None = None,
    ) -> ToolResult:
        ...


def resolve_path(cwd: Path, value: str, *, must_exist: bool = True) -> Path:
    root = cwd.expanduser().resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ValueError(f"path is outside the working directory: {value}")
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {value}")
    return resolved


def error_result(exc: Exception) -> ToolResult:
    return ToolResult(content=f"Error: {exc}", is_error=True)
