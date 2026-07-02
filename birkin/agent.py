"""The core agent loop: a provider-agnostic tool-calling cycle.

``Agent`` is intentionally small and decoupled:

- It does not know about skills, memory, or the WebUI.
- The *system prompt* (including any skill index and memory) is built by the
  caller and passed in.
- *Tools* are provided via a registry exposing ``specs()`` and
  ``execute(name, input)``.

**Automatic skill-ization (copied from hermes).** Without any extra LLM call,
the loop counts tool-calling work and periodically *nudges* the model to persist
what it learned: if a turn does substantial tool work but never saves a skill,
an ephemeral note is injected on the next turn suggesting ``create_skill`` /
``improve_skill``; a turn-based nudge does the same for memory. Counters reset
whenever the relevant tool is actually used. Nudges are ephemeral — they are
added to the system prompt for a turn only and never stored in history.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol

from .llm import LLMClient

SKILL_TOOLS = {"create_skill", "improve_skill"}
MEMORY_TOOLS = {"remember", "memory_write_note", "memory_link"}

_SKILL_NUDGE = (
    "[birkin self-improvement] You've done several tool steps without saving a "
    "skill. If what you just did is a reusable, generalizable procedure, call "
    "create_skill to capture it (or improve_skill to refine an existing one) so "
    "it persists for next time. If nothing is worth saving, ignore this note.")

_MEMORY_NUDGE = (
    "[birkin self-improvement] If you've learned a durable fact about the user "
    "or project, persist it with remember or memory_write_note (and link related "
    "notes). Otherwise ignore this note.")


class Registry(Protocol):
    def specs(self) -> list[dict[str, Any]]: ...
    def execute(self, name: str, tool_input: dict[str, Any]) -> "ToolResultLike": ...


class ToolResultLike(Protocol):
    content: str
    is_error: bool


class AbortLike(Protocol):
    """Anything with ``is_set()`` — e.g. ``threading.Event`` — used to interrupt."""
    def is_set(self) -> bool: ...


# Event hook: (event_type, payload) for UI / logging.
#   "tool_start" -> {"name", "input"}
#   "tool_end"   -> {"name", "is_error", "content"}
EventCallback = Optional[Callable[[str, dict[str, Any]], None]]


class Agent:
    def __init__(self, *, client: LLMClient, system: str, registry: Registry,
                 max_turns: int = 24, model: Optional[str] = None,
                 on_event: EventCallback = None, self_improve: bool = True,
                 skill_nudge_interval: int = 3, memory_nudge_interval: int = 6):
        self.client = client
        self.system = system
        self.registry = registry
        self.max_turns = max_turns
        self.model = model
        self.on_event = on_event
        self.messages: list[dict[str, Any]] = []

        # Automatic skill-ization / memory nudges (hermes-style).
        self.self_improve = self_improve
        self.skill_nudge_interval = skill_nudge_interval
        self.memory_nudge_interval = memory_nudge_interval
        self._iters_since_skill = 0
        self._turns_since_memory = 0
        self._pending_nudge = ""
        # Per-turn telemetry (read by the caller for run records).
        self.last_tools: list[str] = []
        self.last_iterations = 0

    def reset(self) -> None:
        self.messages = []
        self._iters_since_skill = 0
        self._turns_since_memory = 0
        self._pending_nudge = ""

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event:
            try:
                self.on_event(event, payload)
            except Exception:
                pass  # UI hooks must never break the loop

    def run(self, user_text: str,
            on_text: Optional[Callable[[str], None]] = None,
            abort: Optional["AbortLike"] = None) -> str:
        """Send a user message and run the loop until the assistant stops
        calling tools (or the turn guard trips). Returns the final text.

        ``abort`` (anything with ``is_set()``, e.g. a ``threading.Event``) lets a
        caller interrupt: it is checked between turns and threaded into the LLM
        call so a streaming response or CLI subprocess stops promptly (Esc in the
        REPL)."""
        self.messages.append(
            {"role": "user", "content": [{"type": "text", "text": user_text}]})
        self.last_tools = []
        self.last_iterations = 0
        self._turns_since_memory += 1
        nudge = self._pending_nudge       # consume any nudge queued last turn
        self._pending_nudge = ""
        return self._loop(on_text, extra_system=nudge, abort=abort)

    @staticmethod
    def _aborted(abort: Optional["AbortLike"]) -> bool:
        return abort is not None and abort.is_set()

    def _loop(self, on_text, extra_system: str = "",
              abort: Optional["AbortLike"] = None) -> str:
        final_text = ""
        tool_specs = self.registry.specs()
        system = self.system + (f"\n\n{extra_system}" if extra_system else "")
        used_skill = used_memory = False

        for _turn in range(self.max_turns):
            if self._aborted(abort):
                return (final_text + "\n\n[birkin] aborted.").strip()
            assistant = self.client.complete(
                system=system, messages=self.messages,
                tools=tool_specs, model=self.model, on_text=on_text, abort=abort)
            self.messages.append(
                {"role": "assistant", "content": assistant["content"]})

            tool_uses = [b for b in assistant["content"]
                         if b.get("type") == "tool_use"]
            text = "".join(b["text"] for b in assistant["content"]
                           if b.get("type") == "text")
            if text:
                final_text = text

            # Abort can land mid-stream: the assistant turn may already carry
            # tool_use blocks the user asked us NOT to run (Esc). Honor that
            # before executing — but still answer every tool_use with a
            # tool_result so the message history stays API-valid next turn.
            if self._aborted(abort) or assistant.get("stop_reason") == "aborted":
                if tool_uses:
                    self.messages.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": tu.get("id"),
                         "content": "aborted", "is_error": True}
                        for tu in tool_uses]})
                self._update_nudges(used_skill, used_memory)
                return (final_text + "\n\n[birkin] aborted.").strip()

            if not tool_uses:
                if assistant.get("stop_reason") == "max_tokens":
                    final_text += "\n\n[birkin] response was cut off at the token " \
                                  "limit (max_tokens); ask me to continue."
                self._update_nudges(used_skill, used_memory)
                return final_text

            self.last_iterations += 1
            if self.skill_nudge_interval > 0:
                self._iters_since_skill += 1

            results: list[dict[str, Any]] = []
            for tu in tool_uses:
                name, tool_input = tu.get("name", ""), tu.get("input", {}) or {}
                self.last_tools.append(name)
                if name in SKILL_TOOLS:
                    used_skill = True
                    self._iters_since_skill = 0
                if name in MEMORY_TOOLS:
                    used_memory = True
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

        self._update_nudges(used_skill, used_memory)
        final_text += "\n\n[birkin] Reached the maximum number of tool turns " \
                      f"({self.max_turns}); stopping to avoid a loop."
        return final_text

    def _update_nudges(self, used_skill: bool, used_memory: bool) -> None:
        """Queue an ephemeral self-improvement nudge for the next turn."""
        if not self.self_improve:
            return
        parts: list[str] = []
        if (self.skill_nudge_interval > 0
                and self._iters_since_skill >= self.skill_nudge_interval
                and not used_skill):
            parts.append(_SKILL_NUDGE)
            self._iters_since_skill = 0
        if (self.memory_nudge_interval > 0
                and self._turns_since_memory >= self.memory_nudge_interval
                and not used_memory):
            parts.append(_MEMORY_NUDGE)
            self._turns_since_memory = 0
        if parts:
            self._pending_nudge = "\n\n".join(parts)
