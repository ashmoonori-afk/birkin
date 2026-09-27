"""Gateway command catalog, parsing, and help rendering."""

from __future__ import annotations

GATEWAY_COMMANDS: list[tuple[str, str, set[str]]] = [
    ("help", "명령 목록 보기", {"help", "commands", "start", "menu", "?"}),
    ("new", "새 대화 시작 (대화 기록 비우기)", {"new", "reset"}),
    (
        "restart",
        "가볍게 재시작 — 설정·페르소나·기억을 다시 불러오고 세션 비우기",
        {"restart", "restart-gateway", "restart_gateway", "restartgateway", "reload"},
    ),
    (
        "hard_restart",
        "완전 재시작 — 게이트웨이를 다시 실행해 코드 변경 반영",
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
        "심층 인터뷰 — 실행 전에 막연한 아이디어 구체화",
        {"neurosis", "interview"},
    ),
    (
        "models",
        "게이트웨이 모델 보기·선택 (적용 시 자동 재시작)",
        {"models", "model"},
    ),
    (
        "effort",
        "Codex 추론 강도 보기·선택 (적용 시 자동 재시작)",
        {"effort", "reasoning"},
    ),
    (
        "update",
        "원격 업데이트 — 저장소에서 새 코드를 받고 자동 재시작",
        {"update", "upgrade", "pull"},
    ),
    (
        "pending",
        "대기 중인 승인 보기 (채팅에서 승인·거부)",
        {"pending", "approvals", "review"},
    ),
    (
        "deny",
        "사유와 함께 요청 거부 — /deny <id> <이유>",
        {"deny", "refuse"},
    ),
    (
        "remind",
        "메시지 예약 — /remind 09:00 <할 일>; /remind list; /remind del <id>",
        {"remind", "cron", "schedule"},
    ),
    (
        "commitment",
        "Birkin이 챙기고 있는 약속 보기",
        {"commitment", "commitments"},
    ),
    (
        "checkin",
        "체크인 설정 — /checkin; /checkin pause; /checkin on",
        {"checkin", "check_in", "checkins"},
    ),
    ("companion", "후속 확인 완전히 끄기 — /companion off", {"companion"}),
    (
        "summon",
        "전문 에이전트 소환 — /summon <에이전트> <할 일>; 결과는 이 채팅으로 전송",
        {"summon"},
    ),
    ("omo", "로컬 OMO 세션 제어", {"omo"}),
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
    "summon",
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
