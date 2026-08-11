from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


_MARK = {
    TodoStatus.PENDING: "○",
    TodoStatus.IN_PROGRESS: "◐",
    TodoStatus.COMPLETED: "✓",
}


@dataclass(slots=True)
class TodoItem:
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING


@dataclass(slots=True)
class TodoList:
    items: list[TodoItem] = field(default_factory=list)
    _counter: int = 0

    def clear(self) -> None:
        self.items.clear()
        self._counter = 0

    def replace(self, entries: list[tuple[str, str]]) -> list[TodoItem]:
        # entries: (content, status_name)
        self.items.clear()
        self._counter = 0
        for content, status_name in entries:
            self._counter += 1
            status = _parse_status(status_name)
            self.items.append(
                TodoItem(id=str(self._counter), content=content.strip(), status=status)
            )
        return list(self.items)

    def update(self, item_id: str, *, content: str | None = None, status: str | None = None) -> TodoItem:
        item = self._get(item_id)
        if content is not None and content.strip():
            item.content = content.strip()
        if status is not None:
            item.status = _parse_status(status)
        return item

    def _get(self, item_id: str) -> TodoItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(f"unknown todo id: {item_id}")

    def render(self) -> str:
        if not self.items:
            return ""
        lines = []
        for item in self.items:
            lines.append(f"  {_MARK[item.status]} {item.content}")
        return "\n".join(lines)

    def summary(self) -> str:
        if not self.items:
            return "No todos."
        lines = [f"{item.id}. [{item.status.value}] {item.content}" for item in self.items]
        return "\n".join(lines)


def _parse_status(value: str) -> TodoStatus:
    token = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "pending": TodoStatus.PENDING,
        "todo": TodoStatus.PENDING,
        "in_progress": TodoStatus.IN_PROGRESS,
        "doing": TodoStatus.IN_PROGRESS,
        "active": TodoStatus.IN_PROGRESS,
        "completed": TodoStatus.COMPLETED,
        "done": TodoStatus.COMPLETED,
        "complete": TodoStatus.COMPLETED,
    }
    if token not in aliases:
        raise ValueError(f"invalid todo status: {value!r}")
    return aliases[token]
