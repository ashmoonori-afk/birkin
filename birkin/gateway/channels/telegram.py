"""Telegram channel via long polling (standard library only).

Uses the Telegram Bot API over HTTPS with ``urllib`` — no third-party SDK.
Enable in config:

    "channels": {"telegram": {"enabled": true, "token": "<bot token>"}}

Create a bot and get the token from @BotFather.
"""

from __future__ import annotations

import html
import json
import mimetypes
import re
import inspect
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Final, Protocol, TypeAlias, TypeGuard

from typing_extensions import override

from ... import config
from ...codex_session import codex_activity_label
from ..turn_support import TURN_ERROR_REPLY, match_command
from ..workflow import (
    WorkflowProposal,
    finish as finish_workflow,
    has_reserved_marker,
    is_proposal_prefix,
    is_workflow,
    mark_interrupted,
    mark_running,
    parse_proposal,
    queue_proposal,
    resolve_proposal,
    restore_claim,
    restore_stranded_claims,
)
from .base import Channel, ChannelGateway, TurnGateway
from .tg_format import (
    split as split_telegram_message,
    to_html as telegram_html,
    to_plain as telegram_plain,
)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
TelegramParam: TypeAlias = str | int

_API: Final = "https://api.telegram.org/bot{token}/{method}"
_ATTACHMENT_RE = re.compile(
    r"(?m)^[ \t]*<telegram-attachment[ \t]+"
    + r"path=([\"'])(.+?)\1[ \t]*/?>[ \t]*(?:\n|$)"
)
_MAX_DOCUMENT_BYTES: Final = 50 * 1024 * 1024
MAX_PUBLIC_WORKERS: Final = 4
_BUSY_REPLY: Final = "Birkin is busy; try again shortly."


class _UrlResponse(Protocol):
    def __enter__(self) -> "_UrlResponse": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None: ...
    def read(self, amt: int | None = None) -> bytes: ...


class _ClaimGateway(Protocol):
    def execute_claimed_action(
        self,
        aid: str,
        on_progress: Callable[[dict[str, object]], None] | None = None,
    ) -> str: ...


class _TrustCheck(Protocol):
    def __call__(self, channel: str) -> bool: ...


class _ProgressChannel(Protocol):
    def progress_holder(self, chat_id: str) -> dict[str, object]: ...
    def typing_target(
        self,
    ) -> Callable[[str, threading.Event, dict[str, object] | None], None]: ...


def _is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict)


def _is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    return isinstance(value, (list, dict))


def _json_object(value: JsonValue | object) -> JsonObject:
    return value if _is_json_object(value) else {}


def _get_attribute(
    getter: Callable[[object, str], object],
    target: object,
    name: str,
) -> object:
    return getter(target, name)


def _is_trust_check(value: object) -> TypeGuard[_TrustCheck]:
    return callable(value)


def _command_is_trusted(gateway: ChannelGateway) -> bool:
    value = _get_attribute(getattr, gateway, "_command_trusted")
    if not _is_trust_check(value):
        raise TypeError(type(value).__name__)
    return value("telegram")


def _invoke_json_loader(loader: Callable[[str], object], raw: str) -> object:
    return loader(raw)


def _open_url(
    opener: Callable[..., _UrlResponse],
    url: str | urllib.request.Request,
    timeout: int,
) -> _UrlResponse:
    return opener(url, timeout=timeout)


def _invoke_config_loader(
    loader: Callable[[], dict[str, object]],
) -> dict[str, object]:
    return loader()


def _invoke_companion_answer(
    answer: Callable[..., dict[str, object]],
    arguments: tuple[str, str, str],
) -> dict[str, object]:
    commitment_id, verb, source_ref = arguments
    return answer(commitment_id, verb, source_ref=source_ref)


def _decode_json(raw: bytes) -> JsonValue:
    value = _invoke_json_loader(json.loads, raw.decode("utf-8", "replace"))
    return value if _is_json_value(value) else None


def _json_int(value: JsonValue, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        return int(value)
    raise TypeError(type(value).__name__)


def _json_float(value: JsonValue, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (str, int, float)):
        return float(value)
    raise TypeError(type(value).__name__)


def _stream_visible_text(text: str) -> str:
    """Hide a final attachment marker, including while it is still streaming."""
    line_start = text.rfind("\n") + 1
    tail = text[line_start:].lstrip()
    marker = "<telegram-attachment"
    if tail.startswith(marker) or marker.startswith(tail):
        return text[:line_start].rstrip()
    return text


def verify_token(token: str) -> tuple[bool, str]:
    """Check a bot token via getMe. Returns (ok, bot_username_or_error)."""
    if not token:
        return False, "empty token"
    url = _API.format(token=token, method="getMe")
    try:
        response = _open_url(urllib.request.urlopen, url, 10)
        with response:
            data = _json_object(_decode_json(response.read()))
    except Exception as exc:
        return False, str(exc)
    if not data.get("ok"):
        return False, str(data.get("description", "invalid token"))
    result = _json_object(data.get("result"))
    return True, str(result.get("username", "?"))


def _payload_summary(category: str, payload: JsonObject) -> str:
    """The consequential part of a proposal, so a one-tap approve isn't blind
    (the CLI review shows the full payload; the button flow must too)."""
    if category == "shell":
        return f"↳ 실행: {str(payload.get('command', ''))[:200]}"
    if category == "cron":
        h, m = payload.get("hour", "?"), payload.get("minute", 0)
        tgt = payload.get("deliver_chat_id")
        return f"↳ 매일 {h}:{str(m).zfill(2)} {str(payload.get('value', ''))[:120]}" + (
            f" → chat {tgt}" if tgt else ""
        )
    if category == "skill":
        return f"↳ 스킬: {str(payload.get('name', payload.get('title', '')))[:120]}"
    if category == "workflow":
        raw_steps = payload.get("steps")
        steps: list[JsonValue] = raw_steps if isinstance(raw_steps, list) else []
        return "↳ " + " → ".join(str(step)[:60] for step in steps[:4])
    if category == "operation":
        operation = payload.get("operation")
        if not _is_json_object(operation):
            return "↳ operation: invalid payload"
        tool = str(operation.get("tool", "?"))
        gate = str(operation.get("gate", "?"))
        cwd = str(operation.get("cwd", "?"))
        raw_input = json.dumps(
            operation.get("input", {}),
            ensure_ascii=False,
            sort_keys=True,
        )
        preview = raw_input[:1200]
        if len(raw_input) > len(preview):
            preview += f"… ({len(raw_input)} chars)"
        environment = operation.get("environment")
        env_summary = ""
        if _is_json_object(environment):
            env_summary = ", ".join(
                f"{key}={value}" for key, value in sorted(environment.items())
            )
        digest = str(payload.get("digest", ""))[:16]
        lines = [
            f"↳ tool: {tool}",
            f"gate: {gate}",
            f"cwd: {cwd}",
            f"input: {preview}",
        ]
        if env_summary:
            lines.append(f"environment: {env_summary}")
        lines.append(f"digest: {digest}")
        return "\n".join(lines)
    return f"↳ {str(payload)[:200]}" if payload else ""


class _Streamer:
    """Edit-stream a growing reply into one Telegram message (hermes-style).

    Feed receives append-style text pieces from the model. The first flush
    sends a plain message; later flushes edit it in place, throttled to
    ``interval`` seconds so Telegram's flood control never triggers. The
    preview is plain text capped at ``cap`` chars; ``finalize`` is the
    channel's job (format + chunk the full reply properly).

    Injectable ``send``/``edit`` callables keep this unit-testable without a
    network. Every network error is swallowed: streaming is cosmetic — the
    finalized reply is the delivery of record.
    """

    def __init__(
        self,
        send: Callable[[str], str | None],
        edit: Callable[[str, str], bool],
        *,
        interval: float = 1.5,
        cap: int = 3600,
        min_first: int = 24,
        min_delta: int = 48,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._send: Callable[[str], str | None] = send
        self._edit: Callable[[str, str], bool] = edit
        self.interval: float = interval
        self.cap: int = cap
        self.min_first: int = min_first  # don't send a 2-char bubble
        # Edit budget is SHARED with sends and timer-driven repeat edits are
        # a throttling target (TDLib #3034) — so an edit needs BOTH the time
        # interval AND min_delta new chars, and the interval backs off.
        self.min_delta: int = min_delta
        self._clock: Callable[[], float] = clock
        self.message_id: str | None = None
        self._buf: list[str] = []
        self._len: int = 0
        self._flushed_len: int = 0
        self._last_flush: float = 0.0
        self._saturated: bool = False  # preview hit cap; stop editing

    def text(self) -> str:
        return "".join(self._buf)

    def feed(self, piece: str) -> None:
        if not piece:
            return
        self._buf.append(piece)
        self._len += len(piece)
        if is_proposal_prefix(self.text()):
            return
        if self._saturated:
            return
        now = self._clock()
        try:
            if self.message_id is None:
                if self._len >= self.min_first:
                    preview = self._preview()
                    if not preview:
                        return
                    mid = self._send(preview)
                    if mid is None:  # send failed -> stay silent, deliver
                        self._saturated = True  # the finalized reply instead
                        return
                    self.message_id = mid
                    self._last_flush = now
                    self._flushed_len = self._len
            elif (
                now - self._last_flush >= self.interval
                and self._len - self._flushed_len >= self.min_delta
            ):
                preview = self._preview()
                if preview:
                    _ = self._edit(self.message_id, preview)
                self._last_flush = now
                self._flushed_len = self._len
                # back off: long streams edit progressively less often
                self.interval = min(4.0, self.interval * 1.4)
        except Exception:
            self._saturated = True  # cosmetic path must never break a turn

    def _preview(self) -> str:
        t = _stream_visible_text(self.text())
        if len(t) > self.cap:
            self._saturated = True
            return t[: self.cap] + " …"
        return t


# Characters markdown gives a meaning to, and therefore the only ones a client
# has any reason to escape. A backslash before anything else -- C:\Users, \d+,
# a line-ending backslash -- is the user's own text and is left alone. Getting
# this wrong would corrupt every Windows path and regex pasted into the bot,
# which is most of what this particular bot is handed.
_MARKDOWN_SPECIALS = set("_*[]()~`>#+-=|{}.!\\")


def _unescape_markdown(text: str) -> str:
    """Undo ``\\x`` where markdown defines the escape; leave every other one."""
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text) and text[i + 1] in _MARKDOWN_SPECIALS:
            out.append(text[i + 1])
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def recover_inbound_text(text: str, entities: JsonValue) -> str:
    """The message as the sender meant it, not as markdown encoded it.

    A client that formats an outgoing link escapes the characters markdown
    treats specially, so a tracking URL arrives as ``...&utm\\_source=...``.
    Passed through verbatim that asks for a query parameter named
    ``utm\\_source``; the page does not answer, and the model retries until the
    turn's budget is gone.

    Two recoveries, in order of authority:

    * a ``text_link`` entity carries the real URL, which may not appear in the
      text at all (a hyperlinked word). Telegram is telling us the truth
      directly, so it wins.
    * otherwise the markdown escapes are undone -- and only those. See
      ``_MARKDOWN_SPECIALS``.

    Returns the SAME object when nothing needed recovering, so a caller can
    tell with ``is`` whether the message was touched.
    """
    recovered = _unescape_markdown(text) if "\\" in (text or "") else text
    extra: list[str] = []
    entity_values = entities if isinstance(entities, list) else []
    for entity in entity_values:
        if not _is_json_object(entity) or entity.get("type") != "text_link":
            continue
        url = str(entity.get("url") or "").strip()
        if url and url not in recovered:
            extra.append(url)
    if extra:
        return recovered + "\n" + "\n".join(extra)
    return recovered


def heartbeat_text(
    elapsed_minutes: int,
    progress: dict[str, object] | None = None,
) -> str:
    """One heartbeat line: elapsed time, plus what the turn is doing.

    A 26-minute turn used to show only a minute counter while 12 minutes of
    real tool work ran. ``progress`` is the holder the session's on_progress
    updates from the turn thread; the pinger reads a snapshot here (plain
    dict item reads are GIL-atomic, and a heartbeat one write behind is
    fine). No holder, or one with nothing in it, reads exactly like before.
    """
    progress = progress or {}
    active_kind = str(progress.get("active_kind") or "")
    last_kind = str(progress.get("last_kind") or "")
    phase = str(progress.get("phase") or "")
    stage = phase or codex_activity_label(active_kind or last_kind)
    base = f"⏳ {stage} ({elapsed_minutes}분)"
    if not progress:
        return base
    details: list[str] = []
    activity_value = progress.get("activity")
    streamed_value = progress.get("streamed")
    activity = (
        activity_value
        if isinstance(activity_value, int) and not isinstance(activity_value, bool)
        else 0
    )
    streamed = (
        streamed_value
        if isinstance(streamed_value, int) and not isinstance(streamed_value, bool)
        else 0
    )
    if activity:
        details.append(f"이벤트 {activity}회")
    if streamed:
        details.append(f"응답 {streamed}개 도착")
    if not details:
        return base
    line = base + " · " + " · ".join(details)
    return line


def execute_claimed_with_progress(
    gateway: _ClaimGateway,
    channel: _ProgressChannel,
    chat_id: str,
    aid: str,
) -> str:
    """Run one approved action with live heartbeats while it works.

    An approved moirai task executes synchronously inside the callback
    handler, which used to mean minutes of silence in chat. The gateway
    now reports phase transitions through on_progress; this feeds them
    into the per-chat holder _keep_typing already renders.

    Capability-aware for the same reason ask_session is: existing test
    fakes and older gateways expose execute_claimed_action(aid) with no
    on_progress, and passing it blindly would TypeError every approval.
    """
    try:
        accepts = (
            "on_progress"
            in inspect.signature(gateway.execute_claimed_action).parameters
        )
    except (TypeError, ValueError):
        accepts = False
    if not accepts:
        return gateway.execute_claimed_action(aid)
    progress = channel.progress_holder(chat_id)
    progress.clear()
    stop = threading.Event()
    pinger = threading.Thread(
        target=channel.typing_target(), args=(str(chat_id), stop), daemon=True
    )
    pinger.start()
    try:
        return gateway.execute_claimed_action(aid, on_progress=progress.update)
    finally:
        stop.set()
        pinger.join(timeout=16)


class TelegramChannel(Channel):
    name: str = "telegram"
    _HEARTBEAT_INTERVAL: float = 180.0
    _MAX_FILE: int = 20_000_000

    def __init__(
        self,
        token: str,
        allowed_chat_ids: list[str] | None = None,
        stream: bool = True,
        max_public_workers: int = 4,
    ):
        if isinstance(max_public_workers, bool) or not 1 <= max_public_workers <= 64:
            raise ValueError("max_public_workers must be between 1 and 64")
        self.token: str = token
        # When non-empty, only these chat ids may drive the agent (access control
        # for a reachable bot). build_channels refuses an empty allowlist.
        self.allowed_chat_ids: set[str] = set(allowed_chat_ids or [])
        self.stream: bool = bool(stream)
        # Per-chat edit cooldown from 429 retry_after — edits during the
        # cooldown are skipped locally instead of hammering the API.
        self._edit_pause_until: dict[str, float] = {}
        # In-flight turn worker per chat, so the poll loop keeps reading updates
        # while a turn runs and a new message can interrupt it.
        self._workers: dict[str, threading.Thread] = {}
        self._action_workers: dict[str, threading.Thread] = {}
        self._workflow_ids: dict[str, str] = {}
        self._worker_slots: threading.BoundedSemaphore = threading.BoundedSemaphore(
            max_public_workers,
        )
        self._worker_lock: threading.Lock = threading.Lock()
        self._progress: dict[str, dict[str, object]] = {}

    def _start_public_worker(
        self,
        registry: dict[str, threading.Thread],
        key: str,
        target: Callable[..., None],
        args: tuple[object, ...] = (),
    ) -> threading.Thread | None:
        if not self._worker_slots.acquire(blocking=False):
            return None
        worker: threading.Thread

        def run() -> None:
            try:
                target(*args)
            finally:
                with self._worker_lock:
                    if registry.get(key) is worker:
                        _ = registry.pop(key, None)
                self._worker_slots.release()

        worker = threading.Thread(target=run, daemon=True)
        with self._worker_lock:
            registry[key] = worker
        try:
            worker.start()
        except RuntimeError:
            with self._worker_lock:
                if registry.get(key) is worker:
                    _ = registry.pop(key, None)
            self._worker_slots.release()
            raise
        return worker

    def _call(
        self,
        method: str,
        params: dict[str, TelegramParam],
        timeout: int = 60,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> JsonValue:
        url = _API.format(token=self.token, method=method)
        data = (
            body if body is not None else urllib.parse.urlencode(params).encode("utf-8")
        )
        req = urllib.request.Request(url, data=data, method="POST")
        if content_type:
            req.add_header("Content-Type", content_type)
        response = _open_url(urllib.request.urlopen, req, timeout)
        with response:
            return _decode_json(response.read())

    def _send_chunk(
        self, chat_id: str, text: str, parse_mode: str | None = None
    ) -> bool:
        """Send one message. Returns True only if Telegram accepted it."""
        params: dict[str, TelegramParam] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        try:
            result = _json_object(self._call("sendMessage", params))
            return bool(_json_object(result).get("ok"))
        except Exception as exc:  # HTTPError (e.g. 400 bad entity), network, …
            print(f"[telegram] send error ({parse_mode or 'plain'}): {exc}")
            return False

    def _send_reply(self, chat_id: str, reply: str) -> bool:
        """Render the agent's markdown to Telegram HTML and send it in size-safe
        chunks. If Telegram rejects a chunk's HTML (a converter edge case), that
        chunk degrades to plain text — so a reply is never dropped or duplicated.
        """
        try:
            chunks = split_telegram_message(telegram_html(reply))
        except Exception as exc:  # converter bug must never eat the message
            print(f"[telegram] format error: {exc}")
            chunks = split_telegram_message(reply)
            delivered = bool(chunks)
            for plain in chunks:
                delivered = self._send_chunk(chat_id, plain) and delivered
            return delivered
        delivered = bool(chunks)
        for chunk in chunks:
            accepted = self._send_chunk(chat_id, chunk, parse_mode="HTML")
            if not accepted:
                accepted = self._send_chunk(chat_id, telegram_plain(chunk))
            delivered = accepted and delivered
        return delivered

    @staticmethod
    def _attachment_roots() -> list[Path]:
        """Directories an outbound attachment may come from.

        The gateway's codex session writes into ``workspace_roots`` (its cwd),
        which is NOT the gateway process's own cwd — rooting only at
        ``Path.cwd()`` rejected every file the agent actually produced.
        """
        roots = [Path.cwd().resolve()]
        try:
            loaded = _invoke_config_loader(config.load_config)
            raw_roots = loaded.get("workspace_roots")
            json_roots = raw_roots if _is_json_value(raw_roots) else None
            roots_values = json_roots if isinstance(json_roots, list) else []
            for raw in roots_values:
                candidate = Path(str(raw)).expanduser()
                try:
                    resolved = candidate.resolve(strict=True)
                except (OSError, RuntimeError):
                    continue
                if resolved.is_dir() and resolved not in roots:
                    roots.append(resolved)
        except Exception:
            pass  # config trouble must not break reply delivery
        return roots

    @staticmethod
    def _extract_attachments(reply: str) -> tuple[str, list[Path]]:
        """Remove explicit attachment markers and resolve safe workspace files."""
        roots = TelegramChannel._attachment_roots()
        paths: list[Path] = []
        for match in _ATTACHMENT_RE.finditer(reply):
            raw = html.unescape(str(match.group(2))).strip()
            candidate = Path(raw).expanduser()
            candidates = (
                [candidate]
                if candidate.is_absolute()
                else [root / candidate for root in roots]
            )
            for cand in candidates:
                try:
                    resolved = cand.resolve(strict=True)
                except (OSError, RuntimeError):
                    continue
                if not resolved.is_file():
                    continue
                if not any(root in resolved.parents for root in roots):
                    continue
                if resolved not in paths:
                    paths.append(resolved)
                break
        return _ATTACHMENT_RE.sub("", reply).strip(), paths

    def _send_document(self, chat_id: str, path: Path) -> bool:
        """Upload one workspace file through Telegram's multipart API."""
        try:
            if path.stat().st_size > _MAX_DOCUMENT_BYTES:
                return False
            with path.open("rb") as handle:
                content = handle.read(_MAX_DOCUMENT_BYTES + 1)
            if len(content) > _MAX_DOCUMENT_BYTES:
                return False
            boundary = f"----birkin-{uuid.uuid4().hex}"
            filename = path.name.replace('"', "_").replace("\r", "").replace("\n", "")
            content_type = (
                mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
            prefix = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
                f"{chat_id}\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="document"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
            result = self._call(
                "sendDocument",
                {},
                body=prefix + content + suffix,
                content_type=f"multipart/form-data; boundary={boundary}",
            )
            return bool(_json_object(result).get("ok"))
        except Exception as exc:
            print(f"[telegram] document send error ({path.name}): {exc}")
            return False

    def _deliver_reply(
        self,
        chat_id: str,
        reply: str,
        streamer: _Streamer | None = None,
        *,
        allow_attachments: bool = True,
    ) -> bool:
        """Deliver visible reply text followed by explicitly marked files."""
        if allow_attachments:
            visible, paths = self._extract_attachments(reply)
        else:
            visible, paths = reply, []
        delivered = True
        if visible:
            if streamer is not None:
                delivered = (
                    self._finalize_stream(chat_id, streamer, visible) is not False
                )
            else:
                delivered = self._send_reply(chat_id, visible) is not False
        elif not paths:
            delivered = self._send_reply(chat_id, "(no reply)") is not False
        for path in paths:
            if not self._send_document(chat_id, path):
                delivered = False
                _ = self._send_reply(
                    chat_id, f"⚠️ 파일을 첨부하지 못했습니다: `{path.name}`"
                )
        return delivered

    def _send_plain(self, chat_id: str, text: str) -> str | None:
        """Send one plain message; return its message_id (for later edits).

        Known tradeoff: if Telegram accepts the send but the RESPONSE is lost
        (timeout after delivery), we return None, streaming stops, and the
        finalize path sends the full reply as a fresh message — a possible
        duplicate. sendMessage has no idempotency key; we bias toward
        guaranteed delivery over deduplication.
        """
        try:
            res = self._call("sendMessage", {"chat_id": chat_id, "text": text})
        except Exception as exc:
            print(f"[telegram] stream send error: {exc}")
            return None
        response = _json_object(res)
        if not response.get("ok"):
            return None
        result = _json_object(response.get("result"))
        return str(result.get("message_id") or "") or None

    def _edit(
        self, chat_id: str, message_id: str, text: str, parse_mode: str | None = None
    ) -> bool:
        """Edit a message. Returns True when the target message now shows
        ``text`` — including Telegram's 400 "message is not modified", which
        means the displayed content ALREADY equals what we wanted. Genuine
        failures (flood control, bad entities, network) return False so the
        caller's fallback chain still delivers."""
        if time.monotonic() < self._edit_pause_until.get(chat_id, 0.0):
            return False  # in a 429 cooldown: skip locally, don't call
        params: dict[str, TelegramParam] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        try:
            response = _json_object(self._call("editMessageText", params))
            return bool(response.get("ok"))
        except urllib.error.HTTPError as exc:
            try:
                body = _json_object(_decode_json(exc.read()))
            except Exception:
                body = {}
            desc = str(body.get("description", ""))
            if exc.code == 429:
                # honor retry_after: pause ALL edits to this chat
                parameters = _json_object(body.get("parameters"))
                retry = _json_float(parameters.get("retry_after"), 5.0) or 5.0
                self._edit_pause_until[chat_id] = time.monotonic() + retry
                return False
            return "message is not modified" in desc.lower()
        except Exception:
            return False  # network etc. — let the fallback chain deliver

    def _finalize_stream(self, chat_id: str, streamer: "_Streamer", reply: str) -> bool:
        """Turn the streamed preview into the delivery of record.

        The streamed message is edited to the (formatted) first chunk of the
        final reply; any overflow goes out as normal chunked messages. If
        nothing was ever streamed, fall back to the plain send path.
        """
        if streamer.message_id is None:
            return self._send_reply(chat_id, reply)
        try:
            chunks = split_telegram_message(telegram_html(reply))
            first_html = True
        except Exception:
            chunks = split_telegram_message(reply)
            first_html = False
        if not chunks:
            return False
        mid = streamer.message_id
        first = chunks[0]
        delivered = True
        # _edit treats "message is not modified" as success, so this chain is
        # a straight escalation: HTML edit -> plain edit -> fresh message.
        if not (first_html and self._edit(chat_id, mid, first, parse_mode="HTML")):
            plain = telegram_plain(first) if first_html else first
            if not self._edit(chat_id, mid, plain):
                delivered = self._send_chunk(chat_id, plain)
        for chunk in chunks[1:]:
            accepted = first_html and self._send_chunk(
                chat_id, chunk, parse_mode="HTML"
            )
            if not accepted:
                accepted = self._send_chunk(
                    chat_id,
                    telegram_plain(chunk) if first_html else chunk,
                )
            delivered = accepted and delivered
        return delivered

    # -- inline-button approvals (P0-2) --------------------------------------

    @staticmethod
    def _approval_markup(aid: str) -> str:
        """reply_markup JSON for one pending action. callback_data is capped
        at 64 bytes by Telegram — ids are short, but clamp defensively."""
        aid = str(aid)[:56]
        return json.dumps(
            {
                "inline_keyboard": [
                    [
                        {"text": "✅ 승인", "callback_data": f"apv:{aid}"},
                        {"text": "❌ 거부", "callback_data": f"rej:{aid}"},
                    ]
                ]
            }
        )

    @staticmethod
    def companion_markup(commitment_id: str) -> str:
        """reply_markup JSON for one check-in (same 64-byte callback_data cap)."""
        cid = str(commitment_id)[:40]
        return json.dumps(
            {
                "inline_keyboard": [
                    [
                        {"text": "✅ 완료", "callback_data": f"companion:done:{cid}"},
                        {
                            "text": "🚧 막힘",
                            "callback_data": f"companion:blocked:{cid}",
                        },
                    ],
                    [
                        {
                            "text": "⏰ 나중에",
                            "callback_data": f"companion:snooze:{cid}",
                        },
                        {"text": "🛑 그만", "callback_data": f"companion:stop:{cid}"},
                        {
                            "text": "🙏 아니에요",
                            "callback_data": f"companion:wrong:{cid}",
                        },
                    ],
                ]
            }
        )

    def _handle_companion_callback(
        self, cq_id: str, data: str, chat_id: str, message_id: str, original: str
    ) -> None:
        """Apply one check-in button tap and edit the receipt in place.

        The commitment's stored context is re-checked against the tapping chat:
        ``callback_data`` is client-supplied, so the binding is verified in
        storage before any state changes.
        """
        from ... import companion

        parts = data.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            self._answer_callback(cq_id, "")
            return
        _, verb, commitment_id = parts
        record = companion.get_commitment(commitment_id)
        if record is None:
            self._answer_callback(cq_id, "이미 삭제된 약속이에요")
            return
        if record.get("context_id") != f"telegram:{chat_id}":
            self._answer_callback(cq_id, "unauthorized")
            return
        try:
            result = _invoke_companion_answer(
                companion.answer,
                (commitment_id, verb, f"telegram:{chat_id}:{message_id}"),
            )
        except companion.CompanionError as exc:
            self._answer_callback(cq_id, str(exc)[:190])
            return
        result_value = result["message"]
        if not isinstance(result_value, str):
            raise TypeError(type(result_value).__name__)
        self._answer_callback(cq_id, result_value.splitlines()[0][:190])
        if message_id:
            _ = self._edit(
                chat_id,
                message_id,
                f"{original}\n\n{result_value}"[:4000],
            )

    def _send_pending_buttons(
        self,
        gateway: ChannelGateway,
        chat_id: str,
    ) -> None:
        """Render /pending as one message per action with approve/reject
        buttons (inline buttons add no chat clutter — the official pattern)."""
        items: list[dict[str, object]] = []
        for record in gateway.pending_actions():
            if record.get("category") == "workflow":
                record_payload = record.get("payload")
                if (
                    not _is_json_object(record_payload)
                    or str(record_payload.get("chat_id", "")) != chat_id
                ):
                    continue
            items.append(record)
        if not items:
            _ = self._send_chunk(chat_id, "📭 No pending approvals.")
            return
        _ = self._send_chunk(chat_id, f"📋 {len(items)} pending approval(s):")
        for rec in items[:10]:
            raw_category = rec.get("category")
            category = raw_category if isinstance(raw_category, str) else ""
            raw_payload = rec.get("payload")
            payload = _json_object(raw_payload)
            text = (
                f"[{category}] {rec.get('title')}\n"
                f"{str(rec.get('description', ''))[:200]}\n"
                f"{_payload_summary(category, payload)}"
            )
            try:
                _ = self._call(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": text,
                        "reply_markup": self._approval_markup(str(rec.get("id", ""))),
                    },
                )
            except Exception as exc:
                print(f"[telegram] pending send error: {exc}")

    def _send_workflow_proposal(
        self, chat_id: str, proposal: WorkflowProposal, task: str
    ) -> None:
        aid = queue_proposal(proposal, task, chat_id)
        try:
            _ = self._call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": proposal.render_html(),
                    "parse_mode": "HTML",
                    "reply_markup": self._approval_markup(aid),
                },
            )
        except (OSError, urllib.error.URLError, ValueError) as exc:
            print(f"[telegram] workflow proposal send error: {exc}")

    def _handle_callback(
        self, gateway: ChannelGateway, cq: JsonObject, offset: int = 0
    ) -> None:
        """One button tap: resolve the action, ACK the query (mandatory —
        clients show a spinner up to a minute otherwise), and edit the
        original message in place with the outcome."""
        cq_id = str(cq.get("id", ""))
        data = str(cq.get("data", ""))
        msg = _json_object(cq.get("message"))
        chat = _json_object(msg.get("chat"))
        sender = _json_object(cq.get("from"))
        chat_id = str(chat.get("id", ""))
        from_id = str(sender.get("id", ""))
        if not self.allowed_chat_ids:
            # An OPEN bot must not allow one-tap approval of queued actions.
            self._answer_callback(cq_id, "approvals need allowed_chat_ids")
            return
        # Approval is privileged, so gate on WHO tapped, not just the chat:
        # in an allowlisted group any member could otherwise approve. The
        # tapping user's id must itself be allowlisted (for a private chat
        # chat_id == user_id, so this is unchanged there).
        if chat_id not in self.allowed_chat_ids or from_id not in self.allowed_chat_ids:
            self._answer_callback(cq_id, "unauthorized")
            return
        if ":" not in data:
            self._answer_callback(cq_id, "")
            return
        if data.startswith("companion:"):
            self._handle_companion_callback(
                cq_id,
                data,
                chat_id,
                str(msg.get("message_id", "")),
                str(msg.get("text", "")),
            )
            return
        verb, aid = data.split(":", 1)
        if verb not in ("apv", "rej"):
            self._answer_callback(cq_id, "")
            return
        if is_workflow(aid):
            prev = self._workers.get(chat_id)
            action = self._action_workers.get(chat_id)
            if verb == "apv" and (
                (prev is not None and prev.is_alive())
                or (action is not None and action.is_alive())
            ):
                self._answer_callback(cq_id, "다른 작업이 진행 중입니다")
                return
            resolution = resolve_proposal(aid, chat_id, approve=(verb == "apv"))
            result = resolution.message
            resume_prompt = resolution.resume_prompt
            self._answer_callback(cq_id, result[:190])
            mid = str(msg.get("message_id", ""))
            old = str(msg.get("text", ""))
            if mid:
                _ = self._edit(chat_id, mid, f"{old}\n\n{result}"[:4000])
            if resume_prompt is None:
                return
            self._workflow_ids[chat_id] = aid
            try:
                worker = self._start_public_worker(
                    self._workers,
                    chat_id,
                    lambda: self._run_turn(
                        gateway,
                        chat_id,
                        resume_prompt,
                        offset,
                        aid,
                    ),
                )
                if worker is None:
                    _ = restore_claim(aid)
                    _ = self._workflow_ids.pop(chat_id, None)
                    _ = self._send_plain(chat_id, _BUSY_REPLY)
            except RuntimeError:
                _ = restore_claim(aid)
                _ = self._workflow_ids.pop(chat_id, None)
                if mid:
                    _ = self._edit(
                        chat_id,
                        mid,
                        f"{old}\n\n⚠ 시작하지 못했습니다. 다시 승인해 주세요.",
                    )
            return

        claimed = False
        if verb == "rej":
            result = gateway.resolve_action(
                aid,
                approve=False,
                actor_id=f"human:telegram:{from_id}",
                via="gateway:telegram",
            )
        else:
            prev = self._workers.get(chat_id)
            action = self._action_workers.get(chat_id)
            if (prev is not None and prev.is_alive()) or (
                action is not None and action.is_alive()
            ):
                self._answer_callback(cq_id, "다른 작업이 진행 중입니다")
                return
            result, claimed = gateway.claim_action(
                aid,
                actor_id=f"human:telegram:{from_id}",
                via="gateway:telegram",
            )
        self._answer_callback(cq_id, result[:190])
        mid = str(msg.get("message_id", ""))
        old = str(msg.get("text", ""))
        if mid:
            _ = self._edit(chat_id, mid, f"{old}\n\n{result}"[:4000])
        if verb == "rej" or not claimed:
            return
        try:
            worker = self._start_public_worker(
                self._action_workers,
                chat_id,
                lambda: self._run_claimed_action(
                    gateway,
                    chat_id,
                    aid,
                    mid,
                    old,
                ),
            )
            if worker is None:
                gateway.restore_action_claim(aid)
                _ = self._send_plain(chat_id, _BUSY_REPLY)
        except RuntimeError:
            gateway.restore_action_claim(aid)
            if mid:
                _ = self._edit(
                    chat_id, mid, f"{old}\n\n⚠ 시작하지 못했습니다. 다시 승인해 주세요."
                )

    def _run_claimed_action(
        self,
        gateway: ChannelGateway,
        chat_id: str,
        aid: str,
        message_id: str,
        original: str,
    ) -> None:
        stop = threading.Event()
        pinger = threading.Thread(
            target=self._keep_typing, args=(chat_id, stop), daemon=True
        )
        pinger.start()
        try:
            result = execute_claimed_with_progress(gateway, self, chat_id, aid)
        finally:
            stop.set()
            pinger.join(timeout=16)
        if message_id:
            _ = self._edit(chat_id, message_id, f"{original}\n\n{result}"[:4000])

    def _answer_callback(self, cq_id: str, text: str) -> None:
        try:
            params: dict[str, TelegramParam] = {"callback_query_id": cq_id}
            if text:
                params["text"] = text[:190]
            _ = self._call("answerCallbackQuery", params, timeout=15)
        except Exception as exc:
            print(f"[telegram] answerCallbackQuery error: {exc}")

    # -- inbound media (P2-1) -----------------------------------------------

    def _incoming_media(self, msg: JsonObject) -> tuple[str, int] | None:
        """(file_id, size) for a supported attachment, largest photo size, or
        None. Voice is accepted for download but the agent needs external STT
        to transcribe it (zero-dep constraint)."""
        raw_photos = msg.get("photo")
        photos = (
            [_json_object(photo) for photo in raw_photos]
            if isinstance(raw_photos, list)
            else []
        )
        if photos:  # array of sizes, ascending — take the largest under cap
            best = max(photos, key=lambda photo: _json_int(photo.get("file_size")))
            return str(best.get("file_id", "")), _json_int(best.get("file_size"))
        for key in ("document", "voice", "audio", "video"):
            obj = msg.get(key)
            if _is_json_object(obj) and obj.get("file_id"):
                return str(obj["file_id"]), _json_int(obj.get("file_size"))
        return None

    def _download_media(self, file_id: str) -> str | None:
        """getFile + download to ~/.birkin/uploads. Returns the saved path or
        None. Never raises — a failed download degrades to a text note."""
        import os
        import urllib.request
        from ... import config  # birkin package (channels -> gateway -> birkin)

        try:
            res = self._call("getFile", {"file_id": file_id}, timeout=20)
            response_data = _json_object(res)
            result = _json_object(response_data.get("result"))
            fp = str(result.get("file_path") or "")
            if not response_data.get("ok") or not fp:
                return None
            up = config.birkin_home() / "uploads"
            up.mkdir(parents=True, exist_ok=True)
            # sanitize: keep only the basename, no traversal into other dirs
            name = os.path.basename(fp.replace("\\", "/")) or file_id
            dest = up / f"{file_id[:12]}_{name}"
            url = f"https://api.telegram.org/file/bot{self.token}/{fp}"
            response = _open_url(urllib.request.urlopen, url, 60)
            with response:
                data = response.read(self._MAX_FILE + 1)
            if len(data) > self._MAX_FILE:
                return None
            _ = dest.write_bytes(data)
            return str(dest)
        except Exception as exc:
            print(f"[telegram] media download failed: {exc}")
            return None

    def _compose_media_text(self, msg: JsonObject) -> str | None:
        """Turn an inbound attachment into a text turn the agent can act on:
        download it and hand the agent the local path (a vision-capable CLI
        reads an image directly). Returns None if there's no media."""
        media = self._incoming_media(msg)
        if media is None:
            return None
        # An OPEN bot (no allowlist) must not download attachments — every
        # message could persist up to 20 MB, a trivial disk-exhaustion vector.
        # Media is only fetched for allowlisted chats.
        if not self.allowed_chat_ids:
            raw_caption = msg.get("caption")
            caption = str(raw_caption).strip() if raw_caption else ""
            return (
                caption + "\n" if caption else ""
            ) + "[첨부는 허용된 채팅에서만 받아요. allowed_chat_ids를 설정해 주세요.]"
        file_id, size = media
        raw_caption = msg.get("caption")
        caption = str(raw_caption).strip() if raw_caption else ""
        if size and size > self._MAX_FILE:
            return (
                caption + "\n" if caption else ""
            ) + "[사용자가 파일을 보냈지만 20MB를 넘어 받을 수 없었어요.]"
        path = self._download_media(file_id)
        if not path:
            return (
                caption + "\n" if caption else ""
            ) + "[첨부 파일을 받지 못했어요. 다시 보내 주시겠어요?]"
        is_voice = bool(msg.get("voice") or msg.get("audio"))
        if is_voice:
            note = (
                f"[사용자가 음성 메시지를 보냈습니다: {path}. 음성-텍스트 "
                f"변환(STT)은 아직 설정돼 있지 않아 내용은 읽을 수 없어요.]"
            )
        else:
            note = (
                f"[사용자가 파일을 보냈습니다: {path}. 필요하면 파일 읽기 "
                f"도구로 열어 보세요. 이미지라면 직접 보고 설명해 주세요.]"
            )
        return (caption + "\n\n" + note) if caption else note

    def progress_holder(self, chat_id: str) -> dict[str, object]:
        try:
            holders = self._progress
        except AttributeError:
            holders = {}
            self._progress = holders
        return holders.setdefault(str(chat_id), {})

    def typing_target(
        self,
    ) -> Callable[[str, threading.Event, dict[str, object] | None], None]:
        return self._keep_typing

    def _keep_typing(
        self,
        chat_id: str,
        stop: threading.Event,
        _progress: dict[str, object] | None = None,
    ) -> None:
        """Show a 'typing…' indicator until ``stop`` is set.

        Replies can take many seconds (the CLI backend spawns a full agent), so
        without this the user stares at silence and assumes it's dead. Telegram
        clears the indicator after ~5s, so we re-send it every few seconds.
        """
        started = time.monotonic()
        interval = self._HEARTBEAT_INTERVAL
        next_heartbeat = started + interval if interval > 0 else float("inf")
        heartbeat_id = None
        try:
            while not stop.is_set():
                try:
                    _ = self._call(
                        "sendChatAction",
                        {"chat_id": chat_id, "action": "typing"},
                        timeout=15,
                    )
                except (OSError, urllib.error.URLError, ValueError):
                    pass  # cosmetic — ignore transient network errors
                except Exception as exc:
                    print(f"[telegram] typing error: {exc}")
                    return
                now = time.monotonic()
                if now >= next_heartbeat:
                    elapsed = max(1, int((now - started) // 60))
                    text = heartbeat_text(
                        elapsed, getattr(self, "_progress", {}).get(chat_id)
                    )
                    if heartbeat_id is None:
                        heartbeat_id = self._send_plain(chat_id, text)
                    else:
                        _ = self._edit(chat_id, heartbeat_id, text)
                    next_heartbeat = now + interval
                wait_for = (
                    min(4.0, max(0.01, next_heartbeat - now)) if interval > 0 else 4.0
                )
                _ = stop.wait(wait_for)
        finally:
            if heartbeat_id is not None:
                try:
                    _ = self._call(
                        "deleteMessage",
                        {
                            "chat_id": chat_id,
                            "message_id": heartbeat_id,
                        },
                        timeout=15,
                    )
                except (OSError, urllib.error.URLError, ValueError):
                    _ = self._edit(chat_id, heartbeat_id, "🏁 작업 종료")

    def _run_turn(
        self,
        gateway: TurnGateway,
        chat_id: str,
        text: str,
        _offset: int,
        workflow_id: str | None = None,
    ) -> None:
        """One turn, run in its own thread so the poll loop stays responsive
        (and a follow-up message can interrupt this via gateway.interrupt)."""
        if workflow_id is None and has_reserved_marker(text):
            _ = self._send_reply(
                chat_id, "⚠️ 내부 워크플로 표식은 예약되어 있어 사용할 수 없습니다."
            )
            return
        if workflow_id is not None and not mark_running(workflow_id, chat_id):
            _ = self._send_reply(
                chat_id, "⚠️ 이 작업 승인은 더 이상 실행할 수 없습니다."
            )
            _ = self._workflow_ids.pop(chat_id, None)
            return
        stop = threading.Event()
        # Written by the session's on_progress on the turn thread, read by
        # the pinger for heartbeat lines. A plain dict suffices: item writes
        # are GIL-atomic and a heartbeat one update behind is harmless.
        progress: dict[str, object] = {}
        pinger = threading.Thread(
            target=self._keep_typing, args=(chat_id, stop, progress), daemon=True
        )
        pinger.start()
        streamer = (
            _Streamer(
                lambda t, c=chat_id: self._send_plain(c, t),
                lambda mid, t, c=chat_id: self._edit(c, mid, t),
            )
            if self.stream
            else None
        )
        failed = False
        try:
            # One progress holder per chat, reused across turns so the
            # pinger thread can read it without a signature change. Created
            # via __dict__.setdefault because tests build this channel with
            # __new__ and never run __init__.
            progress = self.progress_holder(chat_id)
            progress.clear()
            # Forward progress only to a gateway whose handle() accepts it.
            # Tests drive this channel against fakes carrying the older
            # signature, and a blind kwarg TypeErrors every one of their
            # turns into the generic error reply.
            try:
                _params = inspect.signature(gateway.handle).parameters
                _takes_kwargs = any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in _params.values()
                )
                _takes_progress = "on_progress" in _params or _takes_kwargs
                _takes_workflow = "workflow_id" in _params or _takes_kwargs
            except (TypeError, ValueError):
                _takes_progress = False
                _takes_workflow = False
            on_text = streamer.feed if streamer else None
            if _takes_progress and _takes_workflow:
                reply = gateway.handle(
                    "telegram",
                    chat_id,
                    text,
                    on_text=on_text,
                    workflow_id=workflow_id,
                    on_progress=progress.update,
                )
            elif _takes_progress:
                reply = gateway.handle(
                    "telegram",
                    chat_id,
                    text,
                    on_text=on_text,
                    on_progress=progress.update,
                )
            elif _takes_workflow:
                reply = gateway.handle(
                    "telegram",
                    chat_id,
                    text,
                    on_text=on_text,
                    workflow_id=workflow_id,
                )
            else:
                reply = gateway.handle(
                    "telegram",
                    chat_id,
                    text,
                    on_text=on_text,
                )
            failed = reply == TURN_ERROR_REPLY
        except Exception as exc:
            print(f"[telegram] turn error: {exc}")
            reply = "⚠️ 처리 중 문제가 생겼어요."
            failed = True
        finally:
            stop.set()
            pinger.join(timeout=16)
        # The reply exists now; the sends below can still die with it
        # unsent. Record the obligation first, discharge it after.
        from ... import delivery

        obligation = delivery.record("telegram", chat_id, reply or "")
        trusted_chat = bool(self.allowed_chat_ids and chat_id in self.allowed_chat_ids)
        proposal = parse_proposal(reply or "") if trusted_chat else None
        delivered = True
        if proposal is not None and workflow_id is not None:
            failed = True
            _ = self._send_reply(
                chat_id,
                "⚠️ 승인된 작업이 실행되지 않고 다시 제안되어 중단했습니다.",
            )
        elif proposal is not None:
            self._send_workflow_proposal(chat_id, proposal, text)
        else:
            delivered = self._deliver_reply(
                chat_id,
                reply or "(no reply)",
                streamer=streamer,
                allow_attachments=trusted_chat,
            )
        if delivered:
            delivery.clear(obligation)
        if workflow_id is not None:
            _ = finish_workflow(workflow_id, "error" if failed else "completed")
            if self._workflow_ids.get(chat_id) == workflow_id:
                _ = self._workflow_ids.pop(chat_id, None)
        if gateway.pending_hard_restart:
            # The main poll loop already advances with this batch's offset.
            # A second getUpdates here races its active long poll and makes
            # Telegram report a false duplicate-poller 409 against ourselves.
            gateway.do_hard_restart()  # replaces the process; never returns

    def _redeliver_pending(self) -> int:
        from ... import delivery

        def send(chat_id: str, text: str) -> bool:
            trusted_chat = chat_id in self.allowed_chat_ids
            if self.allowed_chat_ids and not trusted_chat:
                return False
            return self._deliver_reply(
                chat_id,
                text,
                allow_attachments=trusted_chat,
            )

        return delivery.redeliver("telegram", send, prefix="[재전송]\n")

    @override
    def start(self, gateway: ChannelGateway) -> None:
        print("  · telegram channel polling for updates")
        owed = self._redeliver_pending()
        if owed:
            print(
                f"[telegram] redelivered {owed} reply(ies) owed from a "
                + "previous run"
            )
        restored = restore_stranded_claims()
        if restored:
            print(f"[telegram] restored {restored} unstarted workflow approval(s)")
        # Drop any leftover webhook (long-polling and webhooks are mutually
        # exclusive — a stale webhook would 409 every getUpdates).
        try:
            _ = self._call("deleteWebhook", {})
        except Exception:
            pass
        # Register the command menu so typing "/" shows them in the Telegram UI.
        try:
            _ = self._call(
                "setMyCommands", {"commands": json.dumps(gateway.command_menu())}
            )
        except Exception as exc:
            print(f"[telegram] setMyCommands failed: {exc}")
        # If we just re-exec'd from a /hard-restart (or /models) on Telegram,
        # greet the chat that asked so they know we're back online.
        try:
            cid = gateway.take_restart_greeting("telegram")
            if cid:
                _ = self._send_reply(cid, gateway.restart_greeting())
        except Exception as exc:
            print(f"[telegram] restart greeting failed: {exc}")
        offset = 0
        while True:
            try:
                res = self._call(
                    "getUpdates", {"offset": offset, "timeout": 50}, timeout=60
                )
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    print(
                        "[telegram] 409 Conflict — another process is polling "
                        + "this bot (@only one `birkin gateway` may run per token). "
                        + "Stop the other instance; retrying in 5s…"
                    )
                else:
                    print(f"[telegram] poll error: {exc}")
                time.sleep(5)
                continue
            except Exception as exc:
                print(f"[telegram] poll error: {exc}")
                time.sleep(5)
                continue
            # A proxy/error can yield a non-object top-level JSON; .get() on a
            # list/str would raise AttributeError and kill this polling thread
            # (the channel would silently die with no restart). Skip the batch.
            if not isinstance(res, dict):
                print(
                    f"[telegram] unexpected getUpdates response: {type(res).__name__}"
                )
                time.sleep(1)
                continue
            raw_updates = res.get("result")
            updates = raw_updates if isinstance(raw_updates, list) else []
            for raw_update in updates:
                upd = _json_object(raw_update)
                offset = max(offset, _json_int(upd.get("update_id")) + 1)
                cq = _json_object(upd.get("callback_query"))
                if cq:  # approval button tap (P0-2)
                    try:
                        self._handle_callback(gateway, cq, offset)
                    except Exception as exc:
                        print(f"[telegram] callback error: {exc}")
                    continue
                msg = _json_object(upd.get("message"))
                chat = _json_object(msg.get("chat"))
                chat_id = str(chat.get("id", ""))
                raw_text = msg.get("text")
                text = recover_inbound_text(
                    raw_text if isinstance(raw_text, str) else "",
                    msg.get("entities"),
                )
                if not chat_id:
                    continue
                # Access control BEFORE any download — an unauthorized chat must
                # not make us fetch its files.
                if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
                    print(
                        f"[telegram] ignoring message from unauthorized chat {chat_id}"
                    )
                    continue
                if not text:
                    # No text — maybe an attachment (photo/voice/document). P2-1
                    text = self._compose_media_text(msg) or ""
                if not text:
                    continue
                # A new message while this chat's previous turn is still running
                # interrupts it (mid-input interruption), then runs the new one.
                prev = self._workers.get(chat_id)
                if prev is not None and prev.is_alive():
                    workflow_id = self._workflow_ids.get(chat_id)
                    if workflow_id is not None:
                        _ = mark_interrupted(workflow_id)
                    _ = gateway.interrupt("telegram", chat_id)
                    prev.join(timeout=20)
                else:
                    _ = gateway.interrupt("telegram", chat_id)
                # /pending on a trusted channel renders as inline buttons
                # here; the gateway's text fallback serves everything else.
                if match_command(text)[0] == "pending" and _command_is_trusted(gateway):
                    self._send_pending_buttons(gateway, chat_id)
                    continue
                # Run the turn in a worker so the loop keeps polling (and can
                # see the next message to interrupt this one).
                worker = self._start_public_worker(
                    self._workers,
                    chat_id,
                    lambda: self._run_turn(gateway, chat_id, text, offset),
                )
                if worker is None:
                    _ = self._send_plain(chat_id, _BUSY_REPLY)
