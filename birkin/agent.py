"""The core agent loop: a provider-agnostic tool-calling cycle.

``Agent`` is intentionally small and decoupled:

- It does not know about skills, memory, or the WebUI.
- The *system prompt* (including any skill index and memory) is built by the
  caller and passed in.
- *Tools* are provided via a registry exposing ``specs()`` and
  ``execute(name, input)``.

This keeps the loop easy to reason about and reuse for both the top-level
agent and isolated subagents.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

from .llm import LLMClient


class Registry(Protocol):
    def specs(self) -> list[dict[str, Any]]: ...
    def execute(self, name: str, tool_input: dict[str, Any]) -> "ToolResultLike": ...


class ToolResultLike(Protocol):
    content: str
    is_error: bool


# Event hook: (event_type, payload) for UI / logging.
#   "tool_start" -> {"name", "input"}
#   "tool_end"   -> {"name", "is_error", "content"}
EventCallback = Optional[Callable[[str, dict[str, Any]], None]]


class Agent:
    def __init__(self, *, client: LLMClient, system: str, registry: Registry,
                 max_turns: int = 24, model: Optional[str] = None,
                 on_event: EventCallback = None):
        self.client = client
        self.system = system
        self.registry = registry
        self.max_turns = max_turns
        self.model = model
        self.on_event = on_event
        self.messages: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.messages = []

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event:
            try:
                self.on_event(event, payload)
            except Exception:
                pass  # UI hooks must never break the loop

    def run(self, user_text: str,
            on_text: Optional[Callable[[str], None]] = None) -> str:
        """Send a user message and run the loop until the assistant stops
        calling tools (or the turn guard trips). Returns the final text."""
        self.messages.append(
            {"role": "user", "content": [{"type": "text", "text": user_text}]})
        return self._loop(on_text)

    def _loop(self, on_text) -> str:
        final_text = ""
        tool_specs = self.registry.specs()
        for _turn in range(self.max_turns):
            assistant = self.client.complete(
                system=self.system, messages=self.messages,
                tools=tool_specs, model=self.model, on_text=on_text)
            self.messages.append(
                {"role": "assistant", "content": assistant["content"]})

            tool_uses = [b for b in assistant["content"]
                         if b.get("type") == "tool_use"]
            text = "".join(b["text"] for b in assistant["content"]
                           if b.get("type") == "text")
            if text:
                final_text = text

            if not tool_uses:
                return final_text

            results: list[dict[str, Any]] = []
            for tu in tool_uses:
                name, tool_input = tu.get("name", ""), tu.get("input", {}) or {}
                self._emit("tool_start", {"name": name, "input": tool_input})
                res = self.registry.execute(name, tool_input)
                self._emit("tool_end", {"name": name, "is_error": res.is_error,
                                        "content": res.content})
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.get("id"),
                    "content": res.content,
                    "is_error": res.is_error,
                })
            self.messages.append({"role": "user", "content": results})

        final_text += "\n\n[birkin] Reached the maximum number of tool turns " \
                      f"({self.max_turns}); stopping to avoid a loop."
        return final_text
