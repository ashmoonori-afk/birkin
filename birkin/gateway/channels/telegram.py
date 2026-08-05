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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import workflow
from . import tg_format
from .base import Channel

if TYPE_CHECKING:
    from ..core import Gateway

_API = "https://api.telegram.org/bot{token}/{method}"
_ATTACHMENT_RE = re.compile(
    r"(?m)^[ \t]*<telegram-attachment[ \t]+"
    r"path=([\"'])(.+?)\1[ \t]*/?>[ \t]*(?:\n|$)"
)
_MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


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
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        return False, str(exc)
    if not data.get("ok"):
        return False, str(data.get("description", "invalid token"))
    return True, data.get("result", {}).get("username", "?")


def _payload_summary(category: str, payload: dict) -> str:
    """The consequential part of a proposal, so a one-tap approve isn't blind
    (the CLI review shows the full payload; the button flow must too)."""
    if category == "shell":
        return f"↳ 실행: {str(payload.get('command', ''))[:200]}"
    if category == "cron":
        h, m = payload.get("hour", "?"), payload.get("minute", 0)
        tgt = payload.get("deliver_chat_id")
        return (f"↳ 매일 {h}:{str(m).zfill(2)} {str(payload.get('value',''))[:120]}"
                + (f" → chat {tgt}" if tgt else ""))
    if category == "skill":
        return f"↳ 스킬: {str(payload.get('name', payload.get('title','')))[:120]}"
    if category == "workflow":
        steps = payload.get("steps") or []
        return "↳ " + " → ".join(str(step)[:60] for step in steps[:4])
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

    def __init__(self, send, edit, *, interval: float = 1.5, cap: int = 3600,
                 min_first: int = 24, min_delta: int = 48,
                 clock=time.monotonic):
        self._send = send            # (text) -> message_id | None
        self._edit = edit            # (message_id, text) -> bool
        self.interval = interval
        self.cap = cap
        self.min_first = min_first   # don't send a 2-char bubble
        # Edit budget is SHARED with sends and timer-driven repeat edits are
        # a throttling target (TDLib #3034) — so an edit needs BOTH the time
        # interval AND min_delta new chars, and the interval backs off.
        self.min_delta = min_delta
        self._clock = clock
        self.message_id: str | None = None
        self._buf: list[str] = []
        self._len = 0
        self._flushed_len = 0
        self._last_flush = 0.0
        self._saturated = False      # preview hit cap; stop editing

    def text(self) -> str:
        return "".join(self._buf)

    def feed(self, piece: str) -> None:
        if not piece:
            return
        self._buf.append(piece)
        self._len += len(piece)
        if workflow.is_proposal_prefix(self.text()):
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
                    if mid is None:      # send failed -> stay silent, deliver
                        self._saturated = True   # the finalized reply instead
                        return
                    self.message_id = mid
                    self._last_flush = now
                    self._flushed_len = self._len
            elif (now - self._last_flush >= self.interval
                  and self._len - self._flushed_len >= self.min_delta):
                preview = self._preview()
                if preview:
                    self._edit(self.message_id, preview)
                self._last_flush = now
                self._flushed_len = self._len
                # back off: long streams edit progressively less often
                self.interval = min(4.0, self.interval * 1.4)
        except Exception:
            self._saturated = True       # cosmetic path must never break a turn

    def _preview(self) -> str:
        t = _stream_visible_text(self.text())
        if len(t) > self.cap:
            self._saturated = True
            return t[:self.cap] + " …"
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


def recover_inbound_text(text: str, entities: Any) -> str:
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
    for entity in entities or []:
        if not isinstance(entity, dict) or entity.get("type") != "text_link":
            continue
        url = str(entity.get("url") or "").strip()
        if url and url not in recovered:
            extra.append(url)
    if extra:
        return recovered + "\n" + "\n".join(extra)
    return recovered


# What each codex item kind reads as in a chat heartbeat. Unknown kinds
# fall back to a neutral word rather than leaking protocol names at a user.
_PROGRESS_KIND_LABELS = {
    "command_execution": "도구 실행",
    "agent_message": "응답 생성",
}


def heartbeat_text(elapsed_minutes: int, progress: dict | None = None) -> str:
    """One heartbeat line: elapsed time, plus what the turn is doing.

    A 26-minute turn used to show only a minute counter while 12 minutes of
    real tool work ran. ``progress`` is the holder the session's on_progress
    updates from the turn thread; the pinger reads a snapshot here (plain
    dict item reads are GIL-atomic, and a heartbeat one write behind is
    fine). No holder, or one with nothing in it, reads exactly like before.
    """
    base = f"⏳ 작업 진행 중 · {elapsed_minutes}분"
    if not progress:
        return base
    details: list[str] = []
    activity = int(progress.get("activity") or 0)
    streamed = int(progress.get("streamed") or 0)
    if activity:
        label = _PROGRESS_KIND_LABELS.get(
            str(progress.get("last_kind") or ""), "작업 이벤트")
        details.append(f"{label} {activity}회")
    if streamed:
        details.append(f"응답 {streamed}개 도착")
    if not details:
        return base
    return base + " · " + " · ".join(details)


class TelegramChannel(Channel):
    name = "telegram"
    _HEARTBEAT_INTERVAL = 180.0

    def __init__(self, token: str, allowed_chat_ids: list[str] | None = None,
                 stream: bool = True):
        self.token = token
        # When non-empty, only these chat ids may drive the agent (access control
        # for a reachable bot). build_channels refuses an empty allowlist.
        self.allowed_chat_ids = set(allowed_chat_ids or [])
        self.stream = bool(stream)
        # Per-chat edit cooldown from 429 retry_after — edits during the
        # cooldown are skipped locally instead of hammering the API.
        self._edit_pause_until: dict[str, float] = {}
        # In-flight turn worker per chat, so the poll loop keeps reading updates
        # while a turn runs and a new message can interrupt it.
        self._workers: dict[str, threading.Thread] = {}
        self._action_workers: dict[str, threading.Thread] = {}
        self._workflow_ids: dict[str, str] = {}

    def _call(self, method: str, params: dict[str, Any], timeout: int = 60, *,
              body: bytes | None = None,
              content_type: str | None = None) -> dict[str, Any]:
        url = _API.format(token=self.token, method=method)
        data = (body if body is not None
                else urllib.parse.urlencode(params).encode("utf-8"))
        req = urllib.request.Request(url, data=data, method="POST")
        if content_type:
            req.add_header("Content-Type", content_type)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    def _send_chunk(self, chat_id: str, text: str, parse_mode: str | None = None) -> bool:
        """Send one message. Returns True only if Telegram accepted it."""
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        try:
            return bool(self._call("sendMessage", params).get("ok"))
        except Exception as exc:  # HTTPError (e.g. 400 bad entity), network, …
            print(f"[telegram] send error ({parse_mode or 'plain'}): {exc}")
            return False

    def _send_reply(self, chat_id: str, reply: str) -> bool:
        """Render the agent's markdown to Telegram HTML and send it in size-safe
        chunks. If Telegram rejects a chunk's HTML (a converter edge case), that
        chunk degrades to plain text — so a reply is never dropped or duplicated.
        """
        try:
            chunks = tg_format.split(tg_format.to_html(reply))
        except Exception as exc:  # converter bug must never eat the message
            print(f"[telegram] format error: {exc}")
            chunks = tg_format.split(reply)
            delivered = bool(chunks)
            for plain in chunks:
                delivered = self._send_chunk(chat_id, plain) and delivered
            return delivered
        delivered = bool(chunks)
        for chunk in chunks:
            accepted = self._send_chunk(
                chat_id, chunk, parse_mode="HTML")
            if not accepted:
                accepted = self._send_chunk(
                    chat_id, tg_format.to_plain(chunk))
            delivered = accepted and delivered
        return delivered

    @staticmethod
    def _extract_attachments(reply: str) -> tuple[str, list[Path]]:
        """Remove explicit attachment markers and resolve safe workspace files."""
        root = Path.cwd().resolve()
        paths: list[Path] = []
        for match in _ATTACHMENT_RE.finditer(reply):
            raw = html.unescape(match.group(2)).strip()
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if root != resolved and root not in resolved.parents:
                continue
            if resolved.is_file() and resolved not in paths:
                paths.append(resolved)
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
            filename = path.name.replace('"', "_").replace("\r", "").replace(
                "\n", "")
            content_type = (mimetypes.guess_type(filename)[0]
                            or "application/octet-stream")
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
            return bool(result.get("ok"))
        except Exception as exc:
            print(f"[telegram] document send error ({path.name}): {exc}")
            return False

    def _deliver_reply(self, chat_id: str, reply: str,
                       streamer: "_Streamer | None" = None) -> bool:
        """Deliver visible reply text followed by explicitly marked files."""
        visible, paths = self._extract_attachments(reply)
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
                self._send_reply(
                    chat_id, f"⚠️ 파일을 첨부하지 못했습니다: `{path.name}`")
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
        if not res.get("ok"):
            return None
        return str((res.get("result") or {}).get("message_id") or "") or None

    def _edit(self, chat_id: str, message_id: str, text: str,
              parse_mode: str | None = None) -> bool:
        """Edit a message. Returns True when the target message now shows
        ``text`` — including Telegram's 400 "message is not modified", which
        means the displayed content ALREADY equals what we wanted. Genuine
        failures (flood control, bad entities, network) return False so the
        caller's fallback chain still delivers."""
        if time.monotonic() < self._edit_pause_until.get(chat_id, 0.0):
            return False   # in a 429 cooldown: skip locally, don't call
        params: dict[str, Any] = {"chat_id": chat_id,
                                  "message_id": message_id, "text": text}
        if parse_mode:
            params["parse_mode"] = parse_mode
        try:
            return bool(self._call("editMessageText", params).get("ok"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", "replace"))
            except Exception:
                body = {}
            desc = str(body.get("description", ""))
            if exc.code == 429:
                # honor retry_after: pause ALL edits to this chat
                retry = float((body.get("parameters") or {})
                              .get("retry_after", 5) or 5)
                self._edit_pause_until[chat_id] = time.monotonic() + retry
                return False
            return "message is not modified" in desc.lower()
        except Exception:
            return False   # network etc. — let the fallback chain deliver

    def _finalize_stream(self, chat_id: str, streamer: "_Streamer",
                         reply: str) -> bool:
        """Turn the streamed preview into the delivery of record.

        The streamed message is edited to the (formatted) first chunk of the
        final reply; any overflow goes out as normal chunked messages. If
        nothing was ever streamed, fall back to the plain send path.
        """
        if streamer.message_id is None:
            return self._send_reply(chat_id, reply)
        try:
            chunks = tg_format.split(tg_format.to_html(reply))
            first_html = True
        except Exception:
            chunks = tg_format.split(reply)
            first_html = False
        if not chunks:
            return False
        mid = streamer.message_id
        first = chunks[0]
        delivered = True
        # _edit treats "message is not modified" as success, so this chain is
        # a straight escalation: HTML edit -> plain edit -> fresh message.
        if not (first_html and self._edit(chat_id, mid, first,
                                          parse_mode="HTML")):
            plain = tg_format.to_plain(first) if first_html else first
            if not self._edit(chat_id, mid, plain):
                delivered = self._send_chunk(chat_id, plain)
        for chunk in chunks[1:]:
            accepted = (
                first_html
                and self._send_chunk(chat_id, chunk, parse_mode="HTML")
            )
            if not accepted:
                accepted = self._send_chunk(
                    chat_id,
                    tg_format.to_plain(chunk) if first_html else chunk,
                )
            delivered = accepted and delivered
        return delivered

    # -- inline-button approvals (P0-2) --------------------------------------

    @staticmethod
    def _approval_markup(aid: str) -> str:
        """reply_markup JSON for one pending action. callback_data is capped
        at 64 bytes by Telegram — ids are short, but clamp defensively."""
        aid = str(aid)[:56]
        return json.dumps({"inline_keyboard": [[
            {"text": "✅ 승인", "callback_data": f"apv:{aid}"},
            {"text": "❌ 거부", "callback_data": f"rej:{aid}"},
        ]]})

    @staticmethod
    def companion_markup(commitment_id: str) -> str:
        """reply_markup JSON for one check-in (same 64-byte callback_data cap)."""
        cid = str(commitment_id)[:40]
        return json.dumps({"inline_keyboard": [
            [{"text": "✅ 완료", "callback_data": f"companion:done:{cid}"},
             {"text": "🚧 막힘", "callback_data": f"companion:blocked:{cid}"}],
            [{"text": "⏰ 나중에", "callback_data": f"companion:snooze:{cid}"},
             {"text": "🛑 그만", "callback_data": f"companion:stop:{cid}"},
             {"text": "🙏 아니에요", "callback_data": f"companion:wrong:{cid}"}],
        ]})

    def _handle_companion_callback(self, cq_id: str, data: str, chat_id: str,
                                   message_id: str, original: str) -> None:
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
            result = companion.answer(
                commitment_id, verb,
                source_ref=f"telegram:{chat_id}:{message_id}")
        except companion.CompanionError as exc:
            self._answer_callback(cq_id, str(exc)[:190])
            return
        self._answer_callback(cq_id, result["message"].splitlines()[0][:190])
        if message_id:
            self._edit(chat_id, message_id,
                       f"{original}\n\n{result['message']}"[:4000])

    def _send_pending_buttons(self, gateway: "Gateway", chat_id: str) -> None:
        """Render /pending as one message per action with approve/reject
        buttons (inline buttons add no chat clutter — the official pattern)."""
        items = [
            rec for rec in gateway.pending_actions()
            if rec.get("category") != "workflow"
            or (isinstance(rec.get("payload"), dict)
                and str(rec["payload"].get("chat_id", "")) == chat_id)
        ]
        if not items:
            self._send_chunk(chat_id, "📭 No pending approvals.")
            return
        self._send_chunk(chat_id, f"📋 {len(items)} pending approval(s):")
        for rec in items[:10]:
            text = (f"[{rec.get('category')}] {rec.get('title')}\n"
                    f"{str(rec.get('description', ''))[:200]}\n"
                    f"{_payload_summary(rec.get('category'), rec.get('payload') or {})}")
            try:
                self._call("sendMessage",
                           {"chat_id": chat_id, "text": text,
                            "reply_markup": self._approval_markup(
                                rec.get("id", ""))})
            except Exception as exc:
                print(f"[telegram] pending send error: {exc}")

    def _send_workflow_proposal(self, chat_id: str,
                                proposal: workflow.WorkflowProposal,
                                task: str) -> None:
        aid = workflow.queue_proposal(proposal, task, chat_id)
        try:
            self._call("sendMessage", {
                "chat_id": chat_id,
                "text": proposal.render(),
                "reply_markup": self._approval_markup(aid),
            })
        except (OSError, urllib.error.URLError, ValueError) as exc:
            print(f"[telegram] workflow proposal send error: {exc}")

    def _handle_callback(self, gateway: "Gateway", cq: dict[str, Any],
                         offset: int = 0) -> None:
        """One button tap: resolve the action, ACK the query (mandatory —
        clients show a spinner up to a minute otherwise), and edit the
        original message in place with the outcome."""
        cq_id = str(cq.get("id", ""))
        data = str(cq.get("data", ""))
        msg = cq.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        from_id = str((cq.get("from") or {}).get("id", ""))
        if not self.allowed_chat_ids:
            # An OPEN bot must not allow one-tap approval of queued actions.
            self._answer_callback(cq_id, "approvals need allowed_chat_ids")
            return
        # Approval is privileged, so gate on WHO tapped, not just the chat:
        # in an allowlisted group any member could otherwise approve. The
        # tapping user's id must itself be allowlisted (for a private chat
        # chat_id == user_id, so this is unchanged there).
        if chat_id not in self.allowed_chat_ids or \
                from_id not in self.allowed_chat_ids:
            self._answer_callback(cq_id, "unauthorized")
            return
        if ":" not in data:
            self._answer_callback(cq_id, "")
            return
        if data.startswith("companion:"):
            self._handle_companion_callback(
                cq_id, data, chat_id, str(msg.get("message_id", "")),
                str(msg.get("text", "")))
            return
        verb, aid = data.split(":", 1)
        if verb not in ("apv", "rej"):
            self._answer_callback(cq_id, "")
            return
        if workflow.is_workflow(aid):
            prev = self._workers.get(chat_id)
            action = self._action_workers.get(chat_id)
            if verb == "apv" and ((prev is not None and prev.is_alive())
                                  or (action is not None and action.is_alive())):
                self._answer_callback(cq_id, "다른 작업이 진행 중입니다")
                return
            resolution = workflow.resolve_proposal(
                aid, chat_id, approve=(verb == "apv"))
            result = resolution.message
            resume_prompt = resolution.resume_prompt
            self._answer_callback(cq_id, result[:190])
            mid = str(msg.get("message_id", ""))
            old = str(msg.get("text", ""))
            if mid:
                self._edit(chat_id, mid, f"{old}\n\n{result}"[:4000])
            if resume_prompt is None:
                return
            worker = threading.Thread(
                target=self._run_turn,
                args=(gateway, chat_id, resume_prompt, offset, aid),
                daemon=True,
            )
            self._workers[chat_id] = worker
            self._workflow_ids[chat_id] = aid
            try:
                worker.start()
            except RuntimeError:
                workflow.restore_claim(aid)
                self._workers.pop(chat_id, None)
                self._workflow_ids.pop(chat_id, None)
                if mid:
                    self._edit(chat_id, mid, f"{old}\n\n⚠ 시작하지 못했습니다. 다시 승인해 주세요.")
            return

        claimed = False
        if verb == "rej":
            result = gateway.resolve_action(aid, approve=False)
        else:
            prev = self._workers.get(chat_id)
            action = self._action_workers.get(chat_id)
            if ((prev is not None and prev.is_alive())
                    or (action is not None and action.is_alive())):
                self._answer_callback(cq_id, "다른 작업이 진행 중입니다")
                return
            result, claimed = gateway.claim_action(aid)
        self._answer_callback(cq_id, result[:190])
        mid = str(msg.get("message_id", ""))
        old = str(msg.get("text", ""))
        if mid:
            self._edit(chat_id, mid, f"{old}\n\n{result}"[:4000])
        if verb == "rej" or not claimed:
            return
        worker = threading.Thread(
            target=self._run_claimed_action,
            args=(gateway, chat_id, aid, mid, old),
            daemon=True,
        )
        self._action_workers[chat_id] = worker
        try:
            worker.start()
        except RuntimeError:
            gateway.restore_action_claim(aid)
            self._action_workers.pop(chat_id, None)
            if mid:
                self._edit(chat_id, mid, f"{old}\n\n⚠ 시작하지 못했습니다. 다시 승인해 주세요.")

    def _run_claimed_action(self, gateway: "Gateway", chat_id: str, aid: str,
                            message_id: str, original: str) -> None:
        stop = threading.Event()
        pinger = threading.Thread(target=self._keep_typing,
                                  args=(chat_id, stop), daemon=True)
        pinger.start()
        try:
            result = gateway.execute_claimed_action(aid)
        finally:
            stop.set()
            pinger.join(timeout=16)
        if message_id:
            self._edit(chat_id, message_id, f"{original}\n\n{result}"[:4000])

    def _answer_callback(self, cq_id: str, text: str) -> None:
        try:
            params: dict[str, Any] = {"callback_query_id": cq_id}
            if text:
                params["text"] = text[:190]
            self._call("answerCallbackQuery", params, timeout=15)
        except Exception as exc:
            print(f"[telegram] answerCallbackQuery error: {exc}")

    # -- inbound media (P2-1) -----------------------------------------------

    _MAX_FILE = 20_000_000   # Bot API cloud download cap

    def _incoming_media(self, msg: dict[str, Any]) -> tuple[str, int] | None:
        """(file_id, size) for a supported attachment, largest photo size, or
        None. Voice is accepted for download but the agent needs external STT
        to transcribe it (zero-dep constraint)."""
        photos = msg.get("photo") or []
        if photos:  # array of sizes, ascending — take the largest under cap
            best = max(photos, key=lambda p: p.get("file_size", 0))
            return best.get("file_id"), int(best.get("file_size", 0))
        for key in ("document", "voice", "audio", "video"):
            obj = msg.get(key)
            if isinstance(obj, dict) and obj.get("file_id"):
                return obj["file_id"], int(obj.get("file_size", 0))
        return None

    def _download_media(self, file_id: str) -> str | None:
        """getFile + download to ~/.birkin/uploads. Returns the saved path or
        None. Never raises — a failed download degrades to a text note."""
        import os
        import urllib.request
        from ... import config   # birkin package (channels -> gateway -> birkin)
        try:
            res = self._call("getFile", {"file_id": file_id}, timeout=20)
            fp = ((res.get("result") or {}).get("file_path") or "")
            if not res.get("ok") or not fp:
                return None
            up = config.birkin_home() / "uploads"
            up.mkdir(parents=True, exist_ok=True)
            # sanitize: keep only the basename, no traversal into other dirs
            name = os.path.basename(fp.replace("\\", "/")) or file_id
            dest = up / f"{file_id[:12]}_{name}"
            url = (f"https://api.telegram.org/file/bot{self.token}/{fp}")
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read(self._MAX_FILE + 1)
            if len(data) > self._MAX_FILE:
                return None
            dest.write_bytes(data)
            return str(dest)
        except Exception as exc:
            print(f"[telegram] media download failed: {exc}")
            return None

    def _compose_media_text(self, msg: dict[str, Any]) -> str | None:
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
            return ((msg.get("caption") or "").strip() + "\n" if
                    msg.get("caption") else "") + \
                "[첨부는 허용된 채팅에서만 받아요. allowed_chat_ids를 설정해 주세요.]"
        file_id, size = media
        caption = (msg.get("caption") or "").strip()
        if size and size > self._MAX_FILE:
            return (caption + "\n" if caption else "") + \
                "[사용자가 파일을 보냈지만 20MB를 넘어 받을 수 없었어요.]"
        path = self._download_media(file_id)
        if not path:
            return (caption + "\n" if caption else "") + \
                "[첨부 파일을 받지 못했어요. 다시 보내 주시겠어요?]"
        is_voice = bool(msg.get("voice") or msg.get("audio"))
        if is_voice:
            note = (f"[사용자가 음성 메시지를 보냈습니다: {path}. 음성-텍스트 "
                    f"변환(STT)은 아직 설정돼 있지 않아 내용은 읽을 수 없어요.]")
        else:
            note = (f"[사용자가 파일을 보냈습니다: {path}. 필요하면 파일 읽기 "
                    f"도구로 열어 보세요. 이미지라면 직접 보고 설명해 주세요.]")
        return (caption + "\n\n" + note) if caption else note

    def _keep_typing(self, chat_id: str, stop: threading.Event,
                     progress: dict | None = None) -> None:
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
                    self._call("sendChatAction",
                               {"chat_id": chat_id, "action": "typing"}, timeout=15)
                except (OSError, urllib.error.URLError, ValueError):
                    pass  # cosmetic — ignore transient network errors
                except Exception as exc:
                    print(f"[telegram] typing error: {exc}")
                    return
                now = time.monotonic()
                if now >= next_heartbeat:
                    elapsed = max(1, int((now - started) // 60))
                    text = heartbeat_text(
                        elapsed,
                        getattr(self, "_progress", {}).get(chat_id))
                    if heartbeat_id is None:
                        heartbeat_id = self._send_plain(chat_id, text)
                    else:
                        self._edit(chat_id, heartbeat_id, text)
                    next_heartbeat = now + interval
                wait_for = (min(4.0, max(0.01, next_heartbeat - now))
                            if interval > 0 else 4.0)
                stop.wait(wait_for)
        finally:
            if heartbeat_id is not None:
                try:
                    self._call("deleteMessage", {
                        "chat_id": chat_id,
                        "message_id": heartbeat_id,
                    }, timeout=15)
                except (OSError, urllib.error.URLError, ValueError):
                    self._edit(chat_id, heartbeat_id, "🏁 작업 종료")

    def _run_turn(self, gateway: "Gateway", chat_id: str, text: str,
                  offset: int, workflow_id: str | None = None) -> None:
        """One turn, run in its own thread so the poll loop stays responsive
        (and a follow-up message can interrupt this via gateway.interrupt)."""
        if workflow_id is None and workflow.has_reserved_marker(text):
            self._send_reply(chat_id, "⚠️ 내부 워크플로 표식은 예약되어 있어 사용할 수 없습니다.")
            return
        if workflow_id is not None and not workflow.mark_running(
                workflow_id, chat_id):
            self._send_reply(chat_id, "⚠️ 이 작업 승인은 더 이상 실행할 수 없습니다.")
            self._workflow_ids.pop(chat_id, None)
            return
        stop = threading.Event()
        # Written by the session's on_progress on the turn thread, read by
        # the pinger for heartbeat lines. A plain dict suffices: item writes
        # are GIL-atomic and a heartbeat one update behind is harmless.
        progress: dict[str, Any] = {}
        pinger = threading.Thread(target=self._keep_typing,
                                  args=(chat_id, stop, progress), daemon=True)
        pinger.start()
        streamer = (_Streamer(
            lambda t, c=chat_id: self._send_plain(c, t),
            lambda mid, t, c=chat_id: self._edit(c, mid, t))
            if self.stream else None)
        failed = False
        try:
            # One progress holder per chat, reused across turns so the
            # pinger thread can read it without a signature change. Created
            # via __dict__.setdefault because tests build this channel with
            # __new__ and never run __init__.
            progress = self.__dict__.setdefault(
                "_progress", {}).setdefault(chat_id, {})
            progress.clear()
            kwargs: dict[str, Any] = {
                "on_text": streamer.feed if streamer else None,
            }
            if workflow_id is not None:
                kwargs["workflow_id"] = workflow_id
            # Forward progress only to a gateway whose handle() accepts it.
            # Tests drive this channel against fakes carrying the older
            # signature, and a blind kwarg TypeErrors every one of their
            # turns into the generic error reply.
            try:
                _params = inspect.signature(gateway.handle).parameters
                _takes = ("on_progress" in _params
                          or any(p.kind is inspect.Parameter.VAR_KEYWORD
                                 for p in _params.values()))
            except (TypeError, ValueError):
                _takes = False
            if _takes:
                kwargs["on_progress"] = progress.update
            reply = gateway.handle("telegram", chat_id, text, **kwargs)
            from ..core import TURN_ERROR_REPLY
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
        proposal = workflow.parse_proposal(reply or "")
        delivered = True
        if proposal is not None and workflow_id is not None:
            failed = True
            self._send_reply(
                chat_id,
                "⚠️ 승인된 작업이 실행되지 않고 다시 제안되어 중단했습니다.",
            )
        elif proposal is not None:
            self._send_workflow_proposal(chat_id, proposal, text)
        else:
            delivered = self._deliver_reply(
                chat_id, reply or "(no reply)", streamer=streamer)
        if delivered:
            delivery.clear(obligation)
        if workflow_id is not None:
            workflow.finish(workflow_id, "error" if failed else "completed")
            if self._workflow_ids.get(chat_id) == workflow_id:
                self._workflow_ids.pop(chat_id, None)
        if gateway.pending_hard_restart:
            try:
                self._call("getUpdates", {"offset": offset, "timeout": 0})
            except Exception:
                pass
            gateway.do_hard_restart()  # replaces the process; never returns

    def start(self, gateway: "Gateway") -> None:
        print("  · telegram channel polling for updates")
        from ... import delivery
        owed = delivery.redeliver(
            "telegram", lambda chat_id, text: self._deliver_reply(chat_id, text),
            prefix="[재전송]\n")
        if owed:
            print(f"[telegram] redelivered {owed} reply(ies) owed from a "
                  f"previous run")
        restored = workflow.restore_stranded_claims()
        if restored:
            print(f"[telegram] restored {restored} unstarted workflow approval(s)")
        # Drop any leftover webhook (long-polling and webhooks are mutually
        # exclusive — a stale webhook would 409 every getUpdates).
        try:
            self._call("deleteWebhook", {})
        except Exception:
            pass
        # Register the command menu so typing "/" shows them in the Telegram UI.
        try:
            from ..core import command_menu
            self._call("setMyCommands",
                       {"commands": json.dumps(command_menu())})
        except Exception as exc:
            print(f"[telegram] setMyCommands failed: {exc}")
        # If we just re-exec'd from a /hard-restart (or /models) on Telegram,
        # greet the chat that asked so they know we're back online.
        try:
            cid = gateway.take_restart_greeting("telegram")
            if cid:
                from ..core import _RESTART_GREETING
                self._send_reply(cid, _RESTART_GREETING)
        except Exception as exc:
            print(f"[telegram] restart greeting failed: {exc}")
        offset = 0
        while True:
            try:
                res = self._call("getUpdates", {"offset": offset, "timeout": 50}, timeout=60)
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    print("[telegram] 409 Conflict — another process is polling "
                          "this bot (@only one `birkin gateway` may run per token). "
                          "Stop the other instance; retrying in 5s…")
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
                print(f"[telegram] unexpected getUpdates response: {type(res).__name__}")
                time.sleep(1)
                continue
            for upd in res.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)
                cq = upd.get("callback_query")
                if cq:                     # approval button tap (P0-2)
                    try:
                        self._handle_callback(gateway, cq, offset)
                    except Exception as exc:
                        print(f"[telegram] callback error: {exc}")
                    continue
                msg = upd.get("message") or {}
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = recover_inbound_text(msg.get("text", ""),
                                            msg.get("entities"))
                if not chat_id:
                    continue
                # Access control BEFORE any download — an unauthorized chat must
                # not make us fetch its files.
                if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
                    print(f"[telegram] ignoring message from unauthorized chat {chat_id}")
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
                        workflow.mark_interrupted(workflow_id)
                    gateway.interrupt("telegram", chat_id)
                    prev.join(timeout=20)
                else:
                    gateway.interrupt("telegram", chat_id)
                # /pending on a trusted channel renders as inline buttons
                # here; the gateway's text fallback serves everything else.
                from ..core import match_command
                if (match_command(text)[0] == "pending"
                        and gateway._command_trusted("telegram")):
                    self._send_pending_buttons(gateway, chat_id)
                    continue
                # Run the turn in a worker so the loop keeps polling (and can
                # see the next message to interrupt this one).
                w = threading.Thread(target=self._run_turn,
                                     args=(gateway, chat_id, text, offset),
                                     daemon=True)
                self._workers[chat_id] = w
                w.start()
