"""Base types and path safeguards shared by tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ToolResult:
    """Result returned by a tool invocation."""

    content: str
    is_error: bool = False
    diff: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """Interface implemented by all model-callable tools."""

    name: str
    description: str
    mutating: bool = False
    schema: dict[str, Any]

    def definition(self) -> dict[str, Any]:
        """Return an OpenAI function-tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    @abstractmethod
    async def run(self, arguments: dict[str, Any], cwd: Path) -> ToolResult:
        """Execute this tool within ``cwd``."""


def resolve_path(cwd: Path, value: str, *, must_exist: bool = True) -> Path:
    """Resolve ``value`` and reject paths outside ``cwd``."""
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
    """Convert an expected tool exception into a model-visible error."""
    return ToolResult(content=f"Error: {exc}", is_error=True)
