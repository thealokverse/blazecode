from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def _as_opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class Message:
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def to_dict(self, *, api: bool = False) -> dict[str, Any]:
        value = asdict(self)
        if api:
            value.pop("created_at", None)
            # local accounting only; never send to providers
            value.pop("input_tokens", None)
            value.pop("output_tokens", None)
            # providers reject assistant/user/tool messages with a missing content key
            if value.get("content") is None:
                value["content"] = ""
        return {
            key: item
            for key, item in value.items()
            if item is not None and item != []
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Message":
        content = value.get("content")
        tool_call_id = value.get("tool_call_id")
        name = value.get("name")
        return cls(
            role=str(value["role"]),
            content=str(content) if content is not None else None,
            tool_calls=(
                list(value["tool_calls"])
                if isinstance(value.get("tool_calls"), list)
                else []
            ),
            tool_call_id=str(tool_call_id) if tool_call_id is not None else None,
            name=str(name) if name is not None else None,
            created_at=str(value.get("created_at") or datetime.now(UTC).isoformat()),
            input_tokens=_as_opt_int(value.get("input_tokens")),
            output_tokens=_as_opt_int(value.get("output_tokens")),
        )
