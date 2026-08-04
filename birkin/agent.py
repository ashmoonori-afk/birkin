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

import threading
from typing import Any, Callable, Optional, Protocol

from . import compaction, parallel
from .config import CLI_PROVIDERS
from .llm import LLMClient, LLMError

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

_STEER_NOTE = ("[birkin: mid-turn message from the user — a direct instruction "
               "sent while you were working, not tool output. Adjust course.]")

_GRACE_PROMPT = (
    "[birkin] You've hit the maximum number of tool-calling turns for this "
    "request, so no further tools will run. Without calling any more tools, "
    "briefly tell the user what you accomplished, what you found, and what "
    "still needs doing.")


def _append_user_text(messages: list[dict[str, Any]], text: str) -> None:
    """Add ``text`` to the conversation as user-authored content.

    Folds into a trailing user message when there is one — so a tool-result
    message gains a text block rather than being followed by a second user
    message — and otherwise appends a new one.
    """
    block = {"type": "text", "text": text}
    if messages and messages[-1].get("role") == "user" \
            and isinstance(messages[-1].get("content"), list):
        messages[-1] = {**messages[-1],
                        "content": messages[-1]["content"] + [block]}
    else:
        messages.append({"role": "user", "content": [block]})


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
#   "compact"    -> {"reason", "before", "after"}
EventCallback = Optional[Callable[[str, dict[str, Any]], None]]

# How many times one turn may compact-and-retry after a context overflow before
# giving up and surfacing the error.
_MAX_COMPACT_RETRIES = 2


class Agent:
    def __init__(self, *, client: LLMClient, system: str, registry: Registry,
                 max_turns: int = 24, model: Optional[str] = None,
                 on_event: EventCallback = None, self_improve: bool = True,
                 skill_nudge_interval: int = 3, memory_nudge_interval: int = 6,
                 auto_compact: bool = True, context_window: int = 200_000,
                 parallel_tools: bool = True, parallel_workers: int = 8,
                 hooks: Any = None):
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

        # Automatic context compaction. CLI providers run their own agent loop
        # in a child process and compact their own context, so birkin only
        # guards the native API transports.
        self.auto_compact = bool(auto_compact) and getattr(
            client, "provider", "") not in CLI_PROVIDERS
        self.context_window = int(context_window)
        # Anti-thrash latch: history length at which compaction last failed to
        # make progress. Retry only once the conversation has grown past it.
        self._compact_floor = 0
        # Newest pre-compaction snapshot id -- the head of the lineage chain
        # that keeps compacted-away history recoverable (see lineage.py).
        self._lineage_head: Optional[str] = None

        # Mid-turn steering. Written from another thread (the REPL key
        # listener, a gateway channel poller) and drained by the loop thread;
        # the lock guards the slot, and only the loop thread touches messages.
        self._pending_steer = ""
        self._steer_lock = threading.Lock()

        # Concurrent execution of read-only tool batches.
        self.parallel_tools = bool(parallel_tools)
        self.parallel_workers = max(1, int(parallel_workers))
        # hooks.HookBus | None — pre_llm_call context injection.
        self.hooks = hooks

    def reset(self) -> None:
        self.messages = []
        self._iters_since_skill = 0
        self._turns_since_memory = 0
        self._pending_nudge = ""
        self._compact_floor = 0
        with self._steer_lock:
            self._pending_steer = ""

    # -- mid-turn steering -------------------------------------------------

    def steer(self, text: str) -> bool:
        """Queue a user instruction for the turn already running.

        Thread-safe. Returns False for empty text. Several steers arriving
        before the next drain are concatenated rather than overwriting.
        """
        text = (text or "").strip()
        if not text:
            return False
        with self._steer_lock:
            self._pending_steer = (f"{self._pending_steer}\n{text}"
                                   if self._pending_steer else text)
        return True

    def _drain_steer(self) -> str:
        with self._steer_lock:
            text, self._pending_steer = self._pending_steer, ""
        return text

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
        # A steer that landed after the last tool batch of the previous turn
        # has nowhere to go but here — carry it rather than dropping it.
        carried = self._drain_steer()
        if carried:
            user_text = f"{user_text}\n\n[carried over from mid-turn]\n{carried}"
        self.messages.append(
            {"role": "user", "content": [{"type": "text", "text": user_text}]})
        self.last_tools = []
        self.last_iterations = 0
        self._turns_since_memory += 1
        nudge = self._pending_nudge       # consume any nudge queued last turn
        self._pending_nudge = ""
        if self.hooks is not None:
            # Rides the same ephemeral per-turn channel as the
            # self-improvement nudges. birkin rebuilds its system prompt
            # every turn anyway, so unlike hermes there is no cached
            # prefix to protect by injecting into the user message.
            try:
                extra = self.hooks.pre_llm(
                    user_text, model=self.model or "",
                    provider=getattr(self.client, "provider", ""))
            except Exception:
                extra = ""
            if extra:
                nudge = f"{nudge}\n\n{extra}" if nudge else extra
        return self._loop(on_text, extra_system=nudge, abort=abort)

    @staticmethod
    def _aborted(abort: Optional["AbortLike"]) -> bool:
        return abort is not None and abort.is_set()

    # -- context compaction ------------------------------------------------

    def compact_now(self, reason: str = "manual") -> bool:
        """Compact the history in place. True when it actually shrank."""
        if len(self.messages) <= self._compact_floor:
            return False
        compacted = compaction.compact(
            self.client, self.messages, model=self.model,
            tail_budget=compaction.tail_budget_for(self.context_window))
        if compacted is self.messages:
            self._compact_floor = len(self.messages)
            return False
        before, after = len(self.messages), len(compacted)
        # Snapshot the history being replaced BEFORE swapping it out, so the
        # summarized turns stay recoverable. Best-effort: a failed snapshot
        # must never block the compaction that keeps the chat alive.
        from . import lineage
        snap = lineage.snapshot(self.messages, parent=self._lineage_head,
                                reason=reason)
        if snap:
            self._lineage_head = snap
        self.messages = compacted
        self._compact_floor = 0
        self._emit("compact", {"reason": reason, "before": before,
                               "after": after, "lineage": snap})
        return True

    def _complete(self, system: str, tool_specs, on_text, abort):
        """One model call, wrapped in the two compaction gates.

        Preflight catches the common case cheaply; the overflow retry is the
        backstop for when the chars/4 estimate was wrong (it usually is, by a
        little — prompt-cached blocks and CJK both skew it).
        """
        if self.auto_compact and len(self.messages) >= 8:
            est = compaction.estimate_tokens(self.messages, system, tool_specs)
            if compaction.should_compact(est, self.context_window):
                self.compact_now("preflight")

        attempts = 0
        while True:
            try:
                return self.client.complete(
                    system=system, messages=self.messages, tools=tool_specs,
                    model=self.model, on_text=on_text, abort=abort)
            except LLMError as exc:
                attempts += 1
                if (attempts > _MAX_COMPACT_RETRIES or not self.auto_compact
                        or not compaction.is_overflow(exc)
                        or not self.compact_now("overflow")):
                    raise

    def _loop(self, on_text, extra_system: str = "",
              abort: Optional["AbortLike"] = None) -> str:
        final_text = ""
        tool_specs = self.registry.specs()
        system = self.system + (f"\n\n{extra_system}" if extra_system else "")
        used_skill = used_memory = False

        for _turn in range(self.max_turns):
            if self._aborted(abort):
                self._drain_steer()      # an interrupt supersedes a steer
                return (final_text + "\n\n[birkin] aborted.").strip()
            # Deliver anything the user typed while the previous model call or
            # tool batch was running. Folding it into the trailing user message
            # (rather than appending a new one) keeps it user-authored content
            # arriving before the next model call, which is the whole point.
            steer = self._drain_steer()
            if steer:
                _append_user_text(self.messages, f"{_STEER_NOTE}\n{steer}")
                self._emit("steer", {"text": steer})
            assistant = self._complete(system, tool_specs, on_text, abort)
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
                self._drain_steer()      # an interrupt supersedes a steer
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

            # Bookkeeping for the whole batch happens here, on the loop
            # thread, before anything fans out — so the nudge counters are
            # never touched from a worker.
            for tu in tool_uses:
                name = tu.get("name", "")
                self.last_tools.append(name)
                if name in SKILL_TOOLS:
                    used_skill = True
                    self._iters_since_skill = 0
                if name in MEMORY_TOOLS:
                    used_memory = True

            results = self._run_tools(tool_uses, abort)
            self.messages.append({"role": "user", "content": results})

        self._update_nudges(used_skill, used_memory)
        final_text = self._grace_summary(system, on_text, abort) or final_text
        final_text += "\n\n[birkin] Reached the maximum number of tool turns " \
                      f"({self.max_turns}); stopping to avoid a loop."
        return final_text

    # -- tool execution ----------------------------------------------------

    def _result_block(self, tool_use: dict[str, Any], content: str,
                      is_error: bool) -> dict[str, Any]:
        return {"type": "tool_result", "tool_use_id": tool_use.get("id"),
                "content": content, "is_error": is_error}

    def _run_one(self, tool_use: dict[str, Any]) -> dict[str, Any]:
        name = tool_use.get("name", "")
        res = self.registry.execute(name, tool_use.get("input", {}) or {})
        return self._result_block(tool_use, res.content, res.is_error)

    def _run_tools(self, tool_uses: list[dict[str, Any]],
                   abort: Optional["AbortLike"]) -> list[dict[str, Any]]:
        """Execute a tool batch, returning results in EMISSION order.

        Exactly one tool_result per tool_use, always: a missing or duplicated
        one makes the next API call fail outright.
        """
        if not self.parallel_tools or len(tool_uses) < 2:
            return [self._execute_with_events(tu) for tu in tool_uses]

        results: list[dict[str, Any]] = []
        for kind, calls in parallel.plan_segments(tool_uses):
            if kind == "parallel":
                results.extend(self._run_parallel(calls, abort))
            else:
                results.extend(self._execute_with_events(tu) for tu in calls)
        return results

    def _execute_with_events(self, tool_use: dict[str, Any]) -> dict[str, Any]:
        name = tool_use.get("name", "")
        tid = tool_use.get("id")
        tool_input = tool_use.get("input", {}) or {}
        self._emit("tool_start", {"name": name, "input": tool_input, "id": tid})
        block = self._run_one(tool_use)
        self._emit("tool_end", {"name": name, "is_error": block["is_error"],
                                "content": block["content"], "id": tid})
        return block

    def _run_parallel(self, calls: list[dict[str, Any]],
                      abort: Optional["AbortLike"]) -> list[dict[str, Any]]:
        """Run read-only calls concurrently, preserving their order.

        Events are emitted from this thread only — ui.py's printer and the
        REPL spinner both assume single-threaded output, and keeping the
        emission here means neither needs to learn about threads.
        """
        from concurrent.futures import ThreadPoolExecutor, wait

        for tu in calls:
            self._emit("tool_start", {"name": tu.get("name", ""),
                                      "input": tu.get("input", {}) or {},
                                      "id": tu.get("id")})

        slots: list[Optional[dict[str, Any]]] = [None] * len(calls)
        with ThreadPoolExecutor(
                max_workers=min(len(calls), self.parallel_workers)) as pool:
            futures = {}
            for i, tu in enumerate(calls):
                futures[pool.submit(self._run_one, tu)] = i
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=0.25)
                for fut in done:
                    i = futures[fut]
                    try:
                        slots[i] = fut.result()
                    except Exception as exc:   # registry.execute catches its
                        slots[i] = self._result_block(  # own; this is a guard
                            calls[i], f"Tool failed: {exc}", True)
                if pending and self._aborted(abort):
                    for fut in pending:
                        fut.cancel()
                    # Running reads cannot be killed; give them a moment, then
                    # answer whatever is still missing so history stays valid.
                    done, pending = wait(pending, timeout=3.0)
                    for fut in done:
                        i = futures[fut]
                        try:
                            slots[i] = fut.result()
                        except Exception:
                            slots[i] = None
                    break

        out: list[dict[str, Any]] = []
        for i, tu in enumerate(calls):
            block = slots[i] or self._result_block(tu, "aborted", True)
            self._emit("tool_end", {"name": tu.get("name", ""),
                                    "is_error": block["is_error"],
                                    "content": block["content"],
                                    "id": tu.get("id")})
            out.append(block)
        return out

    def _grace_summary(self, system: str, on_text, abort) -> str:
        """One last turn so an exhausted run reports what it got done.

        Without this the user just gets the stop notice plus whatever text the
        model happened to emit before its final tool call — often nothing.

        The call goes out with no tools, which makes it impossible for the
        model to start more work it cannot finish. Any failure here is
        swallowed: the grace call is a courtesy and must never turn an
        exhausted run into a raised error.
        """
        if self._aborted(abort):
            return ""
        restore = list(self.messages)
        _append_user_text(self.messages, _GRACE_PROMPT)
        try:
            assistant = self._complete(system, None, on_text, abort)
        except Exception:
            self.messages = restore     # leave history exactly as we found it
            return ""
        self.messages.append(
            {"role": "assistant", "content": assistant["content"]})
        # Belt and braces: a provider that returns tool_use despite being sent
        # no tools would otherwise leave a dangling tool_use and 400 the next
        # turn of this conversation.
        stray = [b for b in assistant["content"] if b.get("type") == "tool_use"]
        if stray:
            self.messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": b.get("id"),
                 "content": "turn budget exhausted; not executed",
                 "is_error": True} for b in stray]})
        return "".join(b["text"] for b in assistant["content"]
                       if b.get("type") == "text").strip()

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
