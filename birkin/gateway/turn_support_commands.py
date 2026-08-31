"""Gateway command catalog, parsing, and help rendering."""

from __future__ import annotations

GATEWAY_COMMANDS: list[tuple[str, str, set[str]]] = [
    ("help", "Show these commands", {"help", "commands", "start", "menu", "?"}),
    ("new", "Start a fresh conversation (clear history)", {"new", "reset"}),
    (
        "restart",
        "Soft restart — reload config/persona/memory, clear sessions",
        {"restart", "restart-gateway", "restart_gateway", "restartgateway", "reload"},
    ),
    (
        "hard_restart",
        "Hard restart — re-exec the gateway (picks up code changes)",
        {
            "hard-restart",
            "hard_restart",
            "hardrestart",
            "restart-hard",
            "restart_hard",
            "restarthard",
        },
    ),
    (
        "neurosis",
        "Deep interview — clarify a vague idea before acting",
        {"neurosis", "interview"},
    ),
    (
        "models",
        "List or select the gateway model (auto-restarts to apply)",
        {"models", "model"},
    ),
    (
        "effort",
        "List or select Codex reasoning effort (auto-restarts to apply)",
        {"effort", "reasoning"},
    ),
    (
        "update",
        "Remote update — pull new code from the repo, then auto restart",
        {"update", "upgrade", "pull"},
    ),
    (
        "pending",
        "List pending approvals (approve/reject from chat)",
        {"pending", "approvals", "review"},
    ),
    (
        "deny",
        "Refuse a pending action with a reason — /deny <id> <why>",
        {"deny", "refuse"},
    ),
    (
        "remind",
        "Schedule a daily message — /remind 09:00 <what to do>; "
        + "/remind list; /remind del <id>",
        {"remind", "cron", "schedule"},
    ),
    (
        "commitment",
        "Show the commitment birkin is following up on",
        {"commitment", "commitments"},
    ),
    (
        "checkin",
        "Check-in settings — /checkin; /checkin pause; /checkin on",
        {"checkin", "check_in", "checkins"},
    ),
    ("companion", "Turn proactive follow-through off — /companion off", {"companion"}),
    ("omo", "Control local OMO sessions", {"omo"}),
]

PRIVILEGED_COMMANDS = {
    "update",
    "models",
    "effort",
    "restart",
    "hard_restart",
    "pending",
    "deny",
    "remind",
    "commitment",
    "checkin",
    "companion",
    "neurosis",
    "omo",
}


def match_command(text: str) -> tuple[str | None, str]:
    """Map an inbound message to (canonical command, remaining arg).

    Tolerates a leading ``/``, a ``@botname`` suffix, hyphen/underscore variants,
    and a trailing arg. ``/restart … hard`` (or ``--hard``) maps to hard_restart.
    Returns ``(None, "")`` when the text is not a recognised command.
    """
    t = (text or "").strip()
    if not t.startswith("/"):
        return None, ""
    toks = t[1:].split(maxsplit=1)
    if not toks:
        return None, ""
    name = toks[0].split("@", 1)[0].strip().lower()
    rest = toks[1].strip() if len(toks) > 1 else ""
    for canonical, _desc, triggers in GATEWAY_COMMANDS:
        if name in triggers:
            if canonical == "restart" and rest.strip().lower() in ("hard", "--hard"):
                return "hard_restart", ""  # hard_restart takes no arg
            return canonical, rest
    return None, ""


def gateway_help_text() -> str:
    """Welcome + grouped command list. Telegram auto-sends /start on first
    open, so this doubles as the onboarding message: a one-line intro and an
    example come first, then chat commands, then admin commands."""
    chat_cmds = [(c, d) for c, d, _ in GATEWAY_COMMANDS if c not in PRIVILEGED_COMMANDS]
    admin_cmds = [(c, d) for c, d, _ in GATEWAY_COMMANDS if c in PRIVILEGED_COMMANDS]
    lines = [
        "👋 안녕하세요, birkin이에요 — 당신을 기억하는 AI 에이전트입니다.",
        '그냥 평소처럼 말 걸어 주세요. 예: "내일 3시 회의 준비 도와줘"',
        "대화는 기억으로 남고, 밤사이 스스로 정리해 아침에 알려드려요.",
        "",
        "💬 명령:",
    ]
    lines += [f"/{c} — {d}" for c, d in chat_cmds]
    if admin_cmds:
        lines += ["", "🔧 관리자용 (신뢰 채널 전용):"]
        lines += [f"/{c} — {d}" for c, d in admin_cmds]
    return "\n".join(lines)
