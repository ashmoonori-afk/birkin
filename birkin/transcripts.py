"""Auto-save conversation transcripts into ``sessions_dir()`` for memory extraction.

Every user/assistant turn — from the gateway (persistent OR non-persistent) and
the REPL — is appended to a per-conversation file in the SAME canonical format
``/save`` writes and the nightly **Morpheus** routine consumes
(``morpheus._gather_sessions`` → ``selfimprove.transcript_from_messages``). So
the existing extractor needs zero changes; transcripts simply start landing in
``~/.birkin/sessions/`` automatically, and the nightly pass turns them into
memory notes.

Why accumulate (user, assistant) *turn pairs* rather than serialise the agent's
message list: in the **persistent gateway** the warm ``claude`` process holds the
conversation, so ``birkin`` only ever sees the new user text and the final reply
per turn — there is no full history object to dump. Appending the pair we DO
have is correct for every path (persistent gateway, non-persistent gateway, REPL).

Files use the reserved ``auto__`` prefix so they stay out of ``/sessions`` /
manual ``/save`` names and can never collide. Append is read-modify-write under a
per-conversation lock (the gateway runs the LLM turn OUTSIDE its global lock, so
distinct conversations can append concurrently) with an atomic 0o600 rename
(reusing ``store._write_json``). Best-effort: this never raises into the chat path.

Privacy: who/what is persisted is gated by the caller (the gateway only auto-saves
*trusted* conversations — see Gateway._autosave_trusted), each turn's text is
secret-redacted and length-capped, and old files are rotated. On POSIX files are
0o600; on Windows confidentiality relies on the user-profile ACL (chmod is a
partial no-op there — same caveat as config.json / store.py).

Pure standard library.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, store

AUTO_PREFIX = "auto__"
_SAFE = re.compile(r"[^A-Za-z0-9_-]")

# Conservative secret masks applied before a transcript is written to disk (and
# therefore before it can reach long-term memory). Defense-in-depth, not a hard
# boundary — the real control is not persisting untrusted input at all.
# Trailing \b is omitted on quantified patterns so a too-long token still matches.
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),                  # Anthropic key/oauth
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),                     # OpenAI incl. sk-proj-
    re.compile(r"AIza[0-9A-Za-z_\-]{35,}"),                   # Google API key
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),                # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),              # GitHub fine-grained
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),              # Slack tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),                          # AWS access key id
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"),             # Telegram bot token
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{12,}"),       # Authorization: Bearer
    re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"),
    # Labeled secrets → redact through end of line (not just the first token).
    re.compile(r"(?im)\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*.+$"),
]

# Per-conversation locks (keyed by channel:chat, NOT by day-file path, so the
# set stays bounded by active conversations). Guarded by _locks_guard.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_last_retention = 0.0  # throttle timestamp; guarded by _retention_lock below
_retention_lock = threading.Lock()  # serialises the throttle + sweep across threads


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lk = _locks.get(key)
        if lk is None:
            lk = _locks[key] = threading.Lock()
        return lk


def _safe(s: str, n: int = 40) -> str:
    return _SAFE.sub("_", str(s))[:n] or "x"


def auto_stem(channel: str, chat_id: str, *, day: str | None = None) -> str:
    """Reserved-namespace stem ``auto__<channel>__<chat>-<h>__<UTC-day>``.

    A short hash of the full chat_id is appended so two long chat ids that share
    a sanitized/truncated 40-char prefix don't merge into one file.
    """
    day = day or datetime.now(timezone.utc).strftime("%Y%m%d")
    h = hashlib.sha1(str(chat_id).encode("utf-8", "replace")).hexdigest()[:6]
    return f"{AUTO_PREFIX}{_safe(channel)}__{_safe(chat_id)}-{h}__{day}"


def is_auto(stem: str) -> bool:
    return stem.startswith(AUTO_PREFIX)


def _mask(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[redacted]", text)
    return text


def _prep(text: str, *, redact: bool, max_chars: int) -> str:
    text = text or ""
    if redact:
        text = _mask(text)  # mask BEFORE truncating so a secret straddling the
        #                     boundary can't leak its un-redacted prefix to disk.
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return text


def _turn_messages(user_text: str, reply_text: str, *, redact: bool,
                   max_chars: int) -> list[dict[str, Any]]:
    return [
        {"role": "user",
         "content": [{"type": "text",
                      "text": _prep(user_text, redact=redact, max_chars=max_chars)}]},
        {"role": "assistant",
         "content": [{"type": "text",
                      "text": _prep(reply_text, redact=redact, max_chars=max_chars)}]},
    ]


def append_turn(channel: str, chat_id: str, user_text: str, reply_text: str,
                *, cfg: dict[str, Any] | None = None) -> Path | None:
    """Append one (user, assistant) turn to the per-(channel,chat,day) auto file.

    Returns the file path, or ``None`` if auto-save is disabled, the user text is
    empty, or anything goes wrong (auditing must never break a chat turn).
    """
    cfg = cfg or config.load_config()
    if not cfg.get("autosave_transcripts", True):
        return None
    if not (user_text or "").strip():
        return None
    try:
        redact = bool(cfg.get("autosave_redact_secrets", True))
        max_chars = int(cfg.get("autosave_max_chars", 4000))
        path = config.sessions_dir() / f"{auto_stem(channel, chat_id)}.json"
        lock_key = f"{_safe(channel)}:{_safe(chat_id)}"
        with _lock_for(lock_key):
            existing = store._read_json(path, [])
            if not isinstance(existing, list):
                existing = []
            existing.extend(_turn_messages(user_text, reply_text,
                                           redact=redact, max_chars=max_chars))
            max_msgs = int(cfg.get("autosave_max_turns", 40)) * 2  # turns→messages
            if max_msgs > 0 and len(existing) > max_msgs:
                existing = existing[-max_msgs:]
            store._write_json(path, existing)
        _maybe_enforce_retention(cfg)
        return path
    except Exception:
        return None


def _maybe_enforce_retention(cfg: dict[str, Any]) -> None:
    """Delete old / excess ``auto__*`` files. Throttled to ~once a minute (it runs
    after every turn) and never touches manual saves.

    The throttle read-check-write AND the sweep run under ``_retention_lock`` so
    concurrent gateway channel threads can't double-sweep and over-delete (the
    cap math reads a shared file list). A non-blocking acquire means a turn whose
    sweep slot is already taken returns immediately instead of stalling the chat.
    """
    global _last_retention
    if not _retention_lock.acquire(blocking=False):
        return  # another thread is already inside the throttle/sweep window
    try:
        now = time.time()
        if now - _last_retention < 60:
            return
        _last_retention = now
        sd = config.sessions_dir()
        days = int(cfg.get("autosave_retention_days", 30))
        cutoff = now - days * 86400 if days > 0 else None
        kept: list[tuple[float, Path]] = []
        for p in sd.glob(f"{AUTO_PREFIX}*.json"):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if cutoff is not None and mtime < cutoff:
                try:
                    p.unlink()
                except OSError:
                    pass
            else:
                kept.append((mtime, p))
        cap = int(cfg.get("autosave_max_files", 500))
        if cap > 0 and len(kept) > cap:
            kept.sort(key=lambda t: t[0])  # by mtime only — never compare Path
            for _mtime, p in kept[:len(kept) - cap]:
                try:
                    p.unlink()
                except OSError:
                    pass
    except Exception:
        pass
    finally:
        _retention_lock.release()
