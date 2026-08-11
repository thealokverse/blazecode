from __future__ import annotations

from pathlib import Path
from typing import Any

from blazecode.tools.base import OutputCallback, Tool, ToolResult, error_result


class TodoTool(Tool):
    name = "todo"
    mutating = False
    description = (
        "Track multi-step work for the current session. "
        "Use only when a task has several meaningful steps. "
        "Actions: replace (set full list), update (change one item), list."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["replace", "update", "list"],
                "description": "replace sets the full list; update changes one item; list shows current todos.",
            },
            "items": {
                "type": "array",
                "description": "For replace: list of {content, status}. status is pending|in_progress|completed.",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "default": "pending",
                        },
                    },
                    "required": ["content"],
                },
            },
            "id": {
                "type": "string",
                "description": "For update: todo id from list/replace.",
            },
            "content": {
                "type": "string",
                "description": "For update: optional new content.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "For update: optional new status.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, store: Any | None = None) -> None:
        self.store = store

    async def run(
        self,
        arguments: dict[str, Any],
        cwd: Path,
        *,
        on_output: OutputCallback | None = None,
    ) -> ToolResult:
        del cwd, on_output
        if self.store is None:
            return ToolResult("Error: todo store is not available", is_error=True)
        try:
            action = str(arguments.get("action", "")).strip().lower()
            if action == "list":
                return ToolResult(self.store.summary())
            if action == "replace":
                raw_items = arguments.get("items")
                if not isinstance(raw_items, list) or not raw_items:
                    raise ValueError("replace requires a non-empty items list")
                entries: list[tuple[str, str]] = []
                for item in raw_items:
                    if not isinstance(item, dict):
                        raise ValueError("each item must be an object")
                    content = str(item.get("content", "")).strip()
                    if not content:
                        raise ValueError("todo content must be non-empty")
                    status = str(item.get("status", "pending"))
                    entries.append((content, status))
                # only one in_progress at a time
                in_prog = sum(1 for _, status in entries if status.replace("-", "_") == "in_progress")
                if in_prog > 1:
                    raise ValueError("at most one todo may be in_progress")
                items = self.store.replace(entries)
                return ToolResult(_format_items(items))
            if action == "update":
                item_id = str(arguments.get("id", "")).strip()
                if not item_id:
                    raise ValueError("update requires id")
                content = arguments.get("content")
                status = arguments.get("status")
                if content is None and status is None:
                    raise ValueError("update requires content and/or status")
                if status is not None:
                    status = str(status)
                    if status.replace("-", "_") == "in_progress":
                        for existing in self.store.items:
                            if existing.id != item_id and existing.status.value == "in_progress":
                                existing.status = type(existing.status).PENDING
                item = self.store.update(
                    item_id,
                    content=str(content) if content is not None else None,
                    status=status,
                )
                return ToolResult(
                    f"{item.id}. [{item.status.value}] {item.content}\n\n{self.store.summary()}"
                )
            raise ValueError(f"unknown action: {action!r}")
        except (KeyError, TypeError, ValueError) as exc:
            return error_result(exc)


def _format_items(items: list[Any]) -> str:
    if not items:
        return "No todos."
    return "\n".join(f"{item.id}. [{item.status.value}] {item.content}" for item in items)
