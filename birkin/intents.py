from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

from . import budget, store
from .llm import LLMClient, LLMError

_MAX_INPUT = 8192
_MAX_ARGUMENT = 4096
_MAX_QUESTION = 300
_PENDING_SECONDS = 300.0
_APPROVE = frozenset({"승인", "확인", "실행", "네", "예", "yes", "y", "confirm", "run"})
_REJECT = frozenset({"취소", "아니요", "아니", "no", "n", "cancel", "reject"})
_ROOTS = frozenset({
    "show", "list", "set", "change", "switch", "clear", "reset", "retry", "undo",
    "compact", "reload", "learn", "remember", "save", "load", "restart", "update",
    "quit", "schedule", "remind", "review", "approve", "interview", "보여", "목록",
    "설정", "바꿔", "변경", "전환", "지워", "초기화", "다시", "불러", "기억", "저장",
    "업데이트", "종료", "예약", "리마인더", "검토", "확인", "인터뷰",
})
_ALIASES = frozenset({"upgrade", "permissions", "q"})

_REPL_SAFE = frozenset({"help", "skills", "skill", "memory", "vault", "tools", "system",
                        "config", "cron", "sessions", "mcp", "clear"})
_REPL_EMPTY_SAFE = frozenset({"model", "provider", "temp", "permission", "soul", "personality"})
_GATEWAY_SAFE = frozenset({"help", "pending"})
_GATEWAY_EMPTY_SAFE = frozenset({"models", "effort"})
_REDACTED_CANDIDATE = "[redacted intent candidate]"


@dataclass(frozen=True, slots=True)
class IntentResult:
    kind: str
    action: str = ""
    argument: str = ""
    question: str = ""
    correlation_id: str = ""
    retained_text: str = ""
    attempted: bool = False
    retained_replacements: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _Pending:
    result: IntentResult
    revision: int
    expires_at: float


def _chat() -> IntentResult:
    return IntentResult("chat")


def _retained(result: IntentResult, text: str) -> IntentResult:
    return replace(result, attempted=True, retained_text=_REDACTED_CANDIDATE,
                   retained_replacements=((text, _REDACTED_CANDIDATE),))


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())


def _tool_schema() -> dict[str, Any]:
    return {"name": "resolve_command", "description": "Resolve one existing command or chat.",
            "input_schema": {"type": "object", "additionalProperties": False,
                             "required": ["kind", "action", "argument", "question"],
                             "properties": {
                                 "kind": {"type": "string", "enum": ["action", "clarify", "chat"]},
                                 "action": {"type": "string"},
                                 "argument": {"type": "string"},
                                 "question": {"type": "string"},
                             }}}


class IntentEngine:
    def __init__(self, cfg: dict[str, Any], client: Any, actions: Iterable[str], *, surface: str,
                 audit: Callable[..., Any] | None = store.save_run) -> None:
        self.cfg = cfg
        self.client = client
        self.actions = frozenset(actions)
        self.surface = surface
        self._audit = audit
        self._pending: dict[str, _Pending] = {}
        self._revision: dict[str, int] = {}
        self._locks: dict[str, threading.RLock] = {}

    def _lock(self, key: str) -> threading.RLock:
        return self._locks.setdefault(key, threading.RLock())

    def pending(self, key: str) -> IntentResult | None:
        with self._lock(key):
            item = self._pending.get(key)
            if item is None or item.expires_at <= time.monotonic():
                self._pending.pop(key, None)
                return None
            return item.result

    def cancel(self, key: str) -> None:
        with self._lock(key):
            self._revision[key] = self._revision.get(key, 0) + 1
            self._pending.pop(key, None)

    def resolve(self, text: str, key: str) -> IntentResult:
        with self._lock(key):
            previous = self.pending(key)
            normalized = _normalize(text)
            if previous is not None and normalized.casefold() in _APPROVE:
                self._pending.pop(key, None)
                return IntentResult("command", previous.action, previous.argument,
                                    correlation_id=previous.correlation_id)
            if previous is not None and normalized.casefold() in _REJECT:
                self.cancel(key)
                return IntentResult("reply", question="Cancelled.")
            self.cancel(key)
            mode = self.cfg.get("natural_language_commands", "off")
            if mode == "off" or not self._candidate(text):
                return _chat()
            if len(text) > _MAX_INPUT or budget.is_over(self.cfg)[0]:
                return _chat()
            revision = self._revision[key]
        started = time.monotonic()
        attempted, raw = self._compile(text)
        decision = self._parse(raw)
        if decision is None:
            self._record(text, raw, IntentResult("failure"), started)
            return _retained(_chat(), text) if attempted else _chat()
        result = self._apply_policy(decision, mode)
        audited = self._record(text, raw, result, started)
        with self._lock(key):
            if revision != self._revision.get(key):
                return _retained(_chat(), text) if attempted else _chat()
            if result.kind in {"preview", "command"} and not audited:
                return _retained(_chat(), text) if attempted else _chat()
            if result.kind == "preview":
                self._pending[key] = _Pending(result, revision, time.monotonic() + _PENDING_SECONDS)
            return _retained(result, text) if attempted else result

    def _candidate(self, text: str) -> bool:
        if not text or text.startswith("/"):
            return False
        folded = text.casefold()
        return (any(root in folded for root in _ROOTS)
                or any(action in folded for action in self.actions)
                or folded == "q"
                or any(alias in folded for alias in _ALIASES if alias != "q"))

    def _cli_classifier_prompt(self) -> str:
        actions = ", ".join(sorted(self.actions))
        return (
            "Classify one command. Return exactly one JSON object and nothing else.\n"
            'Envelope schema: {"kind":"action|clarify|chat","action":"string",'
            '"argument":"string","question":"string"}.\n'
            f"Allowed canonical actions for {self.surface}: {actions}.\n"
            "Surface contract: action must be one listed canonical action; chat uses "
            "empty action, argument, and question; clarify uses an empty action and "
            "argument with a non-empty question."
        )

    def _compile(self, text: str) -> tuple[bool, dict[str, Any] | None]:
        provider = getattr(self.client, "provider", "")
        if provider == "local-cli":
            return False, None
        attempted = False
        try:
            if provider in {"anthropic", "claude-oauth", "openai"}:
                compiler = self.client
                if isinstance(self.client, LLMClient):
                    compiler = LLMClient(provider=provider, model=getattr(self.client, "model", ""),
                        api_key=getattr(self.client, "api_key", ""), base_url=getattr(self.client, "base_url", ""),
                        max_tokens=256, temperature=0, oauth=getattr(self.client, "oauth", False))
                kwargs = {
                    "system": "Classify one command. Use only resolve_command.",
                    "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}],
                    "tools": [_tool_schema()],
                }
                if compiler is self.client:
                    kwargs.update({"temperature": 0, "max_tokens": 256})
                attempted = True
                reply = compiler.complete(**kwargs)
                content = reply.get("content", [])
                uses = [item for item in content if item.get("type") == "tool_use"
                        and item.get("name") == "resolve_command"]
                return attempted, uses[0].get("input") if len(content) == 1 and len(uses) == 1 else None
            if provider in {"claude-cli", "codex-cli"}:
                copy = type(self.client)(provider=provider, model=getattr(self.client, "model", ""),
                    api_key=getattr(self.client, "api_key", "cli"), base_url=getattr(self.client, "base_url", ""),
                    cli_access="read-only", cli_timeout=min(int(getattr(self.client, "cli_timeout", 45)), 45),
                    cli_output_limit=65536)
                copy.birkin_mcp = False
                attempted = True
                reply = copy.complete(system=self._cli_classifier_prompt(),
                    messages=[{"role": "user", "content": [{"type": "text", "text": text}]}])
                blocks = reply.get("content", [])
                if len(blocks) != 1 or blocks[0].get("type") != "text":
                    return attempted, None
                parsed = json.loads(blocks[0].get("text", ""))
                return attempted, parsed if isinstance(parsed, dict) else None
        except (AttributeError, json.JSONDecodeError, LLMError, TypeError, ValueError):
            return attempted, None
        return False, None

    def _parse(self, value: dict[str, Any] | None) -> IntentResult | None:
        if not isinstance(value, dict) or set(value) != {"kind", "action", "argument", "question"}:
            return None
        kind, action, argument, question = (value[name] for name in ("kind", "action", "argument", "question"))
        if not all(isinstance(item, str) for item in (kind, action, argument, question)):
            return None
        if kind not in {"action", "clarify", "chat"} or "\0" in argument:
            return None
        if len(argument) > _MAX_ARGUMENT or len(question) > _MAX_QUESTION:
            return None
        if kind == "chat":
            return IntentResult("chat") if not action and not argument and not question else None
        if kind == "clarify":
            return IntentResult("reply", question=question) if not action and not argument and question else None
        if action not in self.actions or question:
            return None
        return IntentResult("action", action, _normalize(argument), correlation_id=uuid.uuid4().hex)

    def _apply_policy(self, decision: IntentResult, mode: str) -> IntentResult:
        if decision.kind != "action":
            return decision
        if decision.action == "permission" and decision.argument:
            return IntentResult("reject", question="Natural permission changes are rejected; use /permission.")
        if mode == "observe":
            return _chat()
        if mode == "auto-safe" and self._is_auto_safe(decision.action, decision.argument):
            return IntentResult("command", decision.action, decision.argument,
                                correlation_id=decision.correlation_id)
        return IntentResult("preview", decision.action, decision.argument,
                            correlation_id=decision.correlation_id)

    def _is_auto_safe(self, action: str, argument: str) -> bool:
        if self.surface == "repl":
            return action in _REPL_SAFE or (not argument and action in _REPL_EMPTY_SAFE)
        if self.surface == "gateway":
            return (action in _GATEWAY_SAFE or (not argument and action in _GATEWAY_EMPTY_SAFE)
                    or (action == "remind" and argument in {"", "list"}))
        return False

    def _record(self, input_text: str, output: dict[str, Any] | None, result: IntentResult,
                started: float) -> bool:
        if self._audit is None:
            return True
        rendered = json.dumps(output, ensure_ascii=False, sort_keys=True) if output else ""
        details = {"correlation_id": result.correlation_id, "surface": self.surface,
                   "action": result.action, "outcome": result.kind,
                   "effect": self._effect(result.action, result.argument),
                   "elapsed_ms": int((time.monotonic() - started) * 1000),
                   "argument_sha256": hashlib.sha256(result.argument.encode()).hexdigest(),
                   "provider": getattr(self.client, "provider", ""),
                   "model": getattr(self.client, "model", ""),
                   "preview": "[redacted intent candidate]"}
        try:
            self._audit("intent", f"intent {result.kind}", details, store.estimate_usage(input_text, rendered))
        except OSError:
            return False
        return True

    def _effect(self, action: str, argument: str) -> str:
        if not action:
            return "none"
        return "read-ui" if self._is_auto_safe(action, argument) else "confirm"
