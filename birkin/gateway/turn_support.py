"""Shared gateway turn parsing, policy, and reply contracts."""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Protocol

from .turn_support_commands import (
    GATEWAY_COMMANDS as GATEWAY_COMMANDS,
    PRIVILEGED_COMMANDS as PRIVILEGED_COMMANDS,
    gateway_help_text as gateway_help_text,
    match_command as match_command,
)
from .turn_types import (
    AskSession,
    ConversationKey,
    GatewayTurn,
    ProgressCallback,
    TextCallback,
)
from .workflow import WORKFLOW_POLICY

InflightOwner = tuple[  # noqa: OBJECT_OK - opaque identity token contract
    object, AskSession, threading.Event
]

# Preserve the private spellings imported by existing gateway consumers.
_GATEWAY_COMMANDS = GATEWAY_COMMANDS
_PRIVILEGED_COMMANDS = PRIVILEGED_COMMANDS


class SessionTurnRecorder(Protocol):
    """The runtime session's turn recorder, named as the session declares it."""

    def _record_turn(
        self,
        text: str,
        reply: str,
        *,
        review_skills: bool = True,
        session_id: str | None = None,
    ) -> None: ...


class TurnContract(GatewayTurn, SessionTurnRecorder, Protocol):
    """Public accessors over the gateway's protected turn surface.

    Both declaring contracts — the gateway itself and the runtime session —
    name their turn hooks with a leading underscore, so a stage module that
    calls them directly is reaching into a protected surface. Deriving from
    both keeps every underscore access inside the declaring hierarchy and
    leaves the stages with a public call to make.
    """

    @staticmethod
    def channel_trusted(
        gateway: GatewayTurn,
        channel: str,
        chat_id: str,
        sender_id: str | None,
    ) -> bool:
        return gateway._channel_trusted(channel, chat_id, sender_id)

    @staticmethod
    def command_trusted(gateway: GatewayTurn, channel: str) -> bool:
        return gateway._command_trusted(channel)

    @staticmethod
    def autosave_trusted(gateway: GatewayTurn, channel: str) -> bool:
        return gateway._autosave_trusted(channel)

    @staticmethod
    def state_lock(gateway: GatewayTurn) -> threading.Lock:
        return gateway._lock

    @staticmethod
    def record_failed_turn(
        gateway: GatewayTurn,
        display_text: str,
        reply: str,
        channel: str,
        chat_id: str,
    ) -> None:
        gateway._record_failed_turn(display_text, reply, channel, chat_id)

    @staticmethod
    def record_turn(
        session: SessionTurnRecorder,
        text: str,
        reply: str,
        *,
        review_skills: bool,
        session_id: str | None,
    ) -> None:
        session._record_turn(
            text, reply, review_skills=review_skills, session_id=session_id
        )

    @staticmethod
    def inflight_lock(gateway: GatewayTurn) -> threading.Lock:
        return gateway._inflight_lock

    @staticmethod
    def inflight_owners(
        gateway: GatewayTurn,
    ) -> dict[ConversationKey, list[InflightOwner]]:
        return gateway._inflight

    @staticmethod
    def release_session(
        gateway: GatewayTurn, key: ConversationKey, session: AskSession | None
    ) -> None:
        gateway._claude_sessions.release(key, session)


def conversation_session_id(channel: str, chat_id: str) -> str:
    """Stable, path-safe Working Memory identity for one gateway conversation."""
    channel_value = str(channel)
    chat_value = str(chat_id)
    label = re.sub(r"[^A-Za-z0-9]+", "-", channel_value).strip("-") or "channel"
    if "\0" in channel_value or "\0" in chat_value:
        channel_bytes = channel_value.encode()
        chat_bytes = chat_value.encode()
        payload = (
            b"v2\0"
            + len(channel_bytes).to_bytes(8, "big")
            + channel_bytes
            + len(chat_bytes).to_bytes(8, "big")
            + chat_bytes
        )
    else:
        # Preserve already-shipped IDs for ordinary channel/chat values.
        payload = f"{channel_value}\0{chat_value}".encode()
    digest = hashlib.sha256(payload).hexdigest()[:20]
    return f"gateway-{label[:24]}-{digest}"


def ask_session(
    sess: AskSession,
    text: str,
    on_text: TextCallback = None,
    timeout: float | None = None,
    on_progress: ProgressCallback = None,
) -> str:
    """Call ``sess.ask`` with only the keywords its signature accepts.

    The warm pool holds two session types: CodexAppServerSession.ask takes
    ``on_progress`` (the activity feed a long turn reports through), and
    ClaudeStreamSession.ask does not. Passing it blindly would TypeError
    every claude-backed turn; dropping it silently would lose the feed the
    codex side now provides. The signature is inspected per call, which is
    nothing next to a model turn.
    """
    import inspect

    kwargs: dict[str, object] = {  # noqa: OBJECT_OK - dynamic ask signature
        "on_text": on_text
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    if on_progress is not None:
        try:
            accepts = "on_progress" in inspect.signature(sess.ask).parameters
        except (TypeError, ValueError):
            accepts = False
        if accepts:
            kwargs["on_progress"] = on_progress
    return sess.ask(text, **kwargs)


_LOCAL_TRUSTED_CHANNELS = frozenset({"http", "local", "repl", "voice"})

UNTRUSTED_CHANNEL_REPLY = "⛔ This channel sender is not authorized."

_PERSISTENT_PROVIDERS = ("claude-cli", "codex-cli")

TURN_ERROR_REPLY = (
    "⚠️ 문제가 생겨서 이번 메시지를 처리하지 못했어요. 잠시 후 다시 시도해 주세요."
)

TURN_MOIRAI_RECOVERY_ERROR_REPLY = (
    "⚠️ Moirai 자동 복구를 실행하지 못했어요. "
    "자세한 원인은 Birkin 서버 로그에 기록했습니다."
)

TURN_PARTIAL_SUFFIX = (
    "\n\n⏱️ 시간 제한에 걸려 여기까지만 받았어요. 이어서 하려면 다시 물어봐 주세요."
)

TURN_INTERRUPTED_REPLY = "(interrupted :o)"

_TELEGRAM_EXECUTION_POLICY = (
    "<gateway-execution-policy>\n"
    + WORKFLOW_POLICY
    + "Keep this foreground turn responsive: inspect only files relevant to the "
    + "request and run only targeted tests. Do not wait for a repository-wide "
    + "test suite. If broader verification is warranted, start it as a detached "
    + "background job, write its output and exit status to a receipt inside the "
    + "workspace, and tell the user the receipt path.\n"
    + "When the user explicitly asks you to send a generated file back through "
    + "Telegram, create it inside the current workspace and append one standalone "
    + "marker per file as the final line: "
    + '<telegram-attachment path="relative/path.ext" />. '
    + "Do not wrap the marker in a code fence, and never emit it before the file "
    + "exists.\n"
    + "</gateway-execution-policy>\n\n"
)

_SHORT_FOLLOWUP_RE = re.compile(
    r"(?:좀\s*)?(?:(?:더|조금)\s*)?"
    + r"(?:(?:쉽게|간단히|자세히)\s*)?"
    + r"(?:설명해|말해|알려줘|풀어줘)(?:\s*줘)?[.!?~]*"
)

LOCAL_TRUSTED_CHANNELS = _LOCAL_TRUSTED_CHANNELS
PERSISTENT_PROVIDERS = _PERSISTENT_PROVIDERS
SHORT_FOLLOWUP_RE = _SHORT_FOLLOWUP_RE
TELEGRAM_EXECUTION_POLICY = _TELEGRAM_EXECUTION_POLICY


def is_short_followup(text: str) -> bool:
    normalized = " ".join((text or "").split())
    return len(normalized) <= 60 and bool(_SHORT_FOLLOWUP_RE.fullmatch(normalized))


def anchor_short_followup(text: str, previous_request: str) -> str:
    return (
        "<conversation-followup-context>\n"
        + "The current short message refers to the previous user request below, "
        + "not to system, policy, skill, or tool instructions.\n"
        + "<previous-user-request>\n"
        + f"{previous_request}\n"
        + "</previous-user-request>\n"
        + "</conversation-followup-context>\n\n"
        + f"{text}"
    )


# Existing import surface: turn_model.py and core.py use the private spellings.
_is_short_followup = is_short_followup
_anchor_short_followup = anchor_short_followup
