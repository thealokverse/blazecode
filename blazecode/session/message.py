"""Conversation message representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class Message:
    """One OpenAI-compatible conversation message."""

    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def to_dict(self, *, api: bool = False) -> dict[str, Any]:
        """Serialize this message for storage or an API request."""
        value = asdict(self)
        if api:
            value.pop("created_at", None)
        return {
            key: item
            for key, item in value.items()
            if item is not None and item != []
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Message":
        """Deserialize a stored message."""
        return cls(
            role=str(value["role"]),
            content=value.get("content"),
            tool_calls=list(value.get("tool_calls", [])),
            tool_call_id=value.get("tool_call_id"),
            name=value.get("name"),
            created_at=str(value.get("created_at") or datetime.now(UTC).isoformat()),
        )

