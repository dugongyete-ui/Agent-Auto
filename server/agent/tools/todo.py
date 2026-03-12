"""
TodoList tools for Dzeck AI Agent.
Provides progress tracking via todo.md file management.
"""
import os
from typing import Optional, List

from server.agent.models.tool_result import ToolResult
from server.agent.tools.base import BaseTool, tool

TODO_DIR = "/tmp/dzeck-ai"
TODO_FILE = os.path.join(TODO_DIR, "todo.md")


def todo_write(items: List[str], title: Optional[str] = None) -> ToolResult:
    """Create or overwrite a todo.md checklist for tracking task progress."""
    os.makedirs(TODO_DIR, exist_ok=True)
    header = title or "Todo List"
    lines = [f"# {header}\n"]
    for item in items:
        lines.append(f"- [ ] {item}")
    content = "\n".join(lines) + "\n"
    try:
        with open(TODO_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(
            success=True,
            message=f"TodoList created with {len(items)} items at {TODO_FILE}",
            data={"type": "todo_write", "file": TODO_FILE, "item_count": len(items)},
        )
    except Exception as e:
        return ToolResult(success=False, message=f"Failed to write todo: {e}")


def todo_update(item_text: str, completed: bool = True) -> ToolResult:
    """Update a single item in todo.md by marking it completed or uncompleted."""
    if not os.path.exists(TODO_FILE):
        return ToolResult(success=False, message="No todo.md found. Create one first with todo_write.")
    try:
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        old_marker = "- [ ]" if completed else "- [x]"
        new_marker = "- [x]" if completed else "- [ ]"

        search = f"{old_marker} {item_text}"
        if search not in content:
            if f"{new_marker} {item_text}" in content:
                status = "completed" if completed else "uncompleted"
                return ToolResult(
                    success=True,
                    message=f"Item already marked as {status}: {item_text}",
                    data={"type": "todo_update", "item": item_text, "already_done": True},
                )
            return ToolResult(
                success=False,
                message=f"Item not found in todo.md: '{item_text}'. Check exact text.",
            )

        content = content.replace(search, f"{new_marker} {item_text}", 1)
        with open(TODO_FILE, "w", encoding="utf-8") as f:
            f.write(content)

        status = "completed" if completed else "uncompleted"
        return ToolResult(
            success=True,
            message=f"Todo item marked {status}: {item_text}",
            data={"type": "todo_update", "item": item_text, "completed": completed},
        )
    except Exception as e:
        return ToolResult(success=False, message=f"Failed to update todo: {e}")


def todo_read() -> ToolResult:
    """Read the current todo.md to check progress."""
    if not os.path.exists(TODO_FILE):
        return ToolResult(
            success=True,
            message="No todo.md exists yet.",
            data={"type": "todo_read", "exists": False, "content": ""},
        )
    try:
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        total = content.count("- [ ]") + content.count("- [x]")
        done = content.count("- [x]")
        return ToolResult(
            success=True,
            message=f"Todo progress: {done}/{total} items completed.\n\n{content}",
            data={
                "type": "todo_read",
                "exists": True,
                "content": content,
                "total": total,
                "done": done,
            },
        )
    except Exception as e:
        return ToolResult(success=False, message=f"Failed to read todo: {e}")


class TodoTool(BaseTool):
    """TodoList tool class - provides task progress tracking capabilities."""

    name: str = "todo"

    def __init__(self) -> None:
        super().__init__()

    @tool(
        name="todo_write",
        description=(
            "Create or overwrite a TodoList (todo.md) for tracking task progress. "
            "Use this at the START of any multi-step task to create a visible checklist. "
            "Each item should be a clear, actionable step. "
            "The TodoList is rendered as a widget visible to the user."
        ),
        parameters={
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of todo items (each a clear, actionable step)",
            },
            "title": {
                "type": "string",
                "description": "(Optional) Title for the todo list. Defaults to 'Todo List'.",
            },
        },
        required=["items"],
    )
    def _todo_write(self, items: List[str], title: Optional[str] = None) -> ToolResult:
        return todo_write(items=items, title=title)

    @tool(
        name="todo_update",
        description=(
            "Mark a specific todo item as completed or uncompleted. "
            "Use the EXACT text of the item as it appears in the TodoList. "
            "Call this immediately after completing each step to keep progress visible."
        ),
        parameters={
            "item_text": {
                "type": "string",
                "description": "Exact text of the todo item to update",
            },
            "completed": {
                "type": "boolean",
                "description": "True to mark as done (default), False to mark as not done",
            },
        },
        required=["item_text"],
    )
    def _todo_update(self, item_text: str, completed: bool = True) -> ToolResult:
        return todo_update(item_text=item_text, completed=completed)

    @tool(
        name="todo_read",
        description=(
            "Read the current TodoList to check progress. "
            "Returns the full todo.md content with completion counts."
        ),
        parameters={},
        required=[],
    )
    def _todo_read(self) -> ToolResult:
        return todo_read()
