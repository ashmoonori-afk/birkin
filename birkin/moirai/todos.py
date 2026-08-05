"""The step ledger for a hard task.

A hard task used to reach the model as one opaque turn: 26 minutes of work
with nothing a human could see, and nothing recoverable about which part was
done when it died. This is the internal todo list the user asked for -- items,
transitions, discovered follow-up work, and a snapshot the chat heartbeat can
render.

Deliberately dumb: no persistence, no threads of its own. It lives for one
moirai run, and the journal already records what each agent call did. The one
piece of policy it owns is the item cap -- a worker that keeps discovering
follow-ups must run out of room, not run forever.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# Enough for a genuinely hard task, small enough that a follow-up loop dies of
# starvation rather than running all night.
DEFAULT_MAX_ITEMS = 24

_PENDING = "pending"
_IN_PROGRESS = "in_progress"
_DONE = "done"


class TodoList:
    """Ordered steps with a cap, transitions, and a heartbeat snapshot."""

    def __init__(self, items: list[str], *,
                 emit: Optional[Callable[[dict[str, Any]], None]] = None,
                 max_items: int = DEFAULT_MAX_ITEMS) -> None:
        self._max = max(1, int(max_items))
        self._emit = emit
        self.items: list[dict[str, Any]] = [
            {"text": str(text).strip(), "status": _PENDING, "note": ""}
            for text in items[: self._max] if str(text).strip()]

    # -- introspection -----------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def done_count(self) -> int:
        return sum(1 for item in self.items if item["status"] == _DONE)

    @property
    def is_complete(self) -> bool:
        return bool(self.items) and self.done_count == self.total

    def next_pending(self) -> Optional[int]:
        for index, item in enumerate(self.items):
            if item["status"] == _PENDING:
                return index
        return None

    # -- transitions -------------------------------------------------------

    def _valid(self, index: int) -> bool:
        return 0 <= index < len(self.items)

    def start(self, index: int) -> None:
        if self._valid(index):
            self.items[index]["status"] = _IN_PROGRESS
            self._notify()

    def done(self, index: int, note: str = "") -> None:
        if self._valid(index):
            self.items[index]["status"] = _DONE
            self.items[index]["note"] = str(note)
            self._notify()

    def append(self, text: str) -> bool:
        """Add discovered follow-up work. False when the cap is reached.

        Refusing rather than queueing is the point: the caller can then SAY
        the follow-up was dropped, instead of silently working forever.
        """
        if len(self.items) >= self._max or not str(text).strip():
            return False
        self.items.append({"text": str(text).strip(),
                           "status": _PENDING, "note": ""})
        self._notify()
        return True

    # -- what the heartbeat shows ------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        current = next((item["text"] for item in self.items
                        if item["status"] == _IN_PROGRESS), "")
        return {"todo_total": self.total, "todo_done": self.done_count,
                "todo_current": current}

    def render(self) -> str:
        snap = self.snapshot()
        head = f"할 일 {snap['todo_done']}/{snap['todo_total']}"
        if snap["todo_current"]:
            return f"{head} · 진행 중: {snap['todo_current']}"
        return f"{head} · 완료" if self.is_complete else head

    def _notify(self) -> None:
        if self._emit is None:
            return
        try:
            self._emit(self.snapshot())
        except Exception:
            pass                     # an observer bug must not kill the work
