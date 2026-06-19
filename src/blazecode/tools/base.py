"""Tool base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Abstract base class. Subclasses set name/description/parameters and implement run()."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    requires_approval: bool = False

    @abstractmethod
    async def run(self, **kwargs: Any) -> str:
        raise NotImplementedError

    def preview(self, **kwargs: Any) -> str:  # noqa: D401
        """Optional human-readable approval preview."""
        return f"{self.name}({kwargs})"
