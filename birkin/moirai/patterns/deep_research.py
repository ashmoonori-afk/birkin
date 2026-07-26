"""Saturation research: fan out, follow every lead, stop when it runs dry.

birkin already ships a `deep-research` skill (ADR-036) that says "spawn one
subagent per sub-question" — but `spawn_subagent` is not parallel-safe, so
those subagents run one after another, and the skill has no way to notice that
an answer opened three new questions. This is that skill with a runtime: the
waves are actually concurrent, and the loop keeps going until it stops finding
anything.

The algorithm is adapted from oh-my-openagent's `ulw-research` skill (MIT) —
the prompt-only orchestration contract, not code, since none exists there:
a saturation wave across orthogonal axes, an EXPAND loop that dedups leads
against every lead ever seen, and a corroboration gate that abstains rather
than guessing. What is deliberately NOT taken: its worker-count floors (birkin
caps at moirai_workers) and its HTML/PDF export (weasyprint is a dependency).

    birkin moirai run deep-research --args '{"question": "..."}'

Sources are whatever the bound model can reach. birkin's own agent has
`web_search` and `web_fetch`, but Moirai agents are text-only for now, so a
web-heavy question here leans on what the bound model already knows plus
whatever its own CLI can reach; that limit is stated in the report rather than
hidden.
"""

meta = {
    "name": "deep-research",
    "description": "포화까지 파고드는 조사 — 병렬 축 분해, 리드 추적, 교차 검증",
    "phases": ["Decompose", "Saturate", "Expand", "Corroborate", "Report"],
    "roles": {
        "planner": {"default": "claude:sonnet",
                    "hint": "질문을 직교하는 축으로 쪼갠다 — 넓게 보는 역할"},
        "worker": {"default": "claude:haiku",
                   "hint": "축 하나를 조사한다 — 여럿이 병렬로 도니 값싼 쪽이 유리"},
        "auditor": {"default": "codex:gpt-5.6-sol",
                    "hint": "주장을 반증하려 든다 — 조사자와 다른 계열이어야 의미가 있다"},
    },
}

AXES_SCHEMA = {
    "type": "object",
    "required": ["axes"],
    "properties": {
        "axes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "question"],
                "properties": {
                    "name": {"type": "string", "maxLength": 60},
                    "question": {"type": "string", "maxLength": 300},
                },
            },
        },
    },
}

FINDINGS_SCHEMA = {
    "type": "object",
    "required": ["findings", "leads"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim", "basis"],
                "properties": {
                    "claim": {"type": "string", "maxLength": 400},
                    "basis": {"type": "string", "maxLength": 400},
                    "source": {"type": "string", "maxLength": 200},
                },
            },
        },
        "leads": {"type": "array", "items": {"type": "string",
                                             "maxLength": 200}},
        "dead_ends": {"type": "array", "items": {"type": "string",
                                                 "maxLength": 200}},
    },
}

VERDICT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "reason"],
    "properties": {
        "verdict": {"type": "string",
                    "enum": ["corroborated", "refuted", "unresolved"]},
        "reason": {"type": "string", "maxLength": 400},
    },
}

MAX_WAVES = 4          # ulw-research stops at 5; birkin is stingier by default
DRY_WAVES_TO_STOP = 2  # two consecutive waves with no new lead = saturated
MAX_AXES = 6


def main(m):
    question = (m.args.get("question") or m.args.get("task") or "").strip()
    if not question:
        return {"error": "질문이 필요합니다 — --args '{\"question\": \"…\"}'"}

    # -- Decompose ---------------------------------------------------------
    m.phase("Decompose")
    plan = m.agent(
        f"조사 질문: {question}\n\n"
        f"이 질문을 서로 겹치지 않는 조사 축 3~{MAX_AXES}개로 쪼개세요. "
        "각 축은 독립적으로 조사 가능해야 하고, 축끼리 답이 겹치면 잘못 쪼갠 "
        "것입니다.",
        role="planner", label="decompose", schema=AXES_SCHEMA)
    if not plan or not plan.get("axes"):
        return {"error": "축 분해 실패", "question": question}
    axes = plan["axes"][:MAX_AXES]
    m.log(f"축 {len(axes)}개: " + ", ".join(a["name"] for a in axes))

    # -- Saturate + Expand -------------------------------------------------
    findings: list[dict] = []
    seen_leads: set[str] = set()     # every lead ever seen, not just followed
    dead_ends: list[str] = []
    pending = [(a["name"], a["question"]) for a in axes]
    dry = 0

    for wave in range(1, MAX_WAVES + 1):
        if not pending:
            break
        m.phase("Saturate" if wave == 1 else "Expand")
        m.log(f"wave {wave}: 워커 {len(pending)}")

        results = m.parallel([
            (lambda n=name, q=q: m.agent(
                f"조사 축: {n}\n질문: {q}\n\n"
                "확인 가능한 사실만 쓰세요. 각 발견에 근거를 붙이고, 출처가 "
                "있으면 함께. 확실하지 않으면 findings에 넣지 말고 leads로 "
                "남기세요. 조사하다 새로 생긴 의문은 leads에, 막다른 길로 "
                "판명된 것은 dead_ends에 적으세요.",
                role="worker", label=f"w{wave}:{n}"[:40],
                schema=FINDINGS_SCHEMA))
            for name, q in pending
        ])

        fresh: list[str] = []
        for got in results:
            if not got:
                continue
            findings.extend(got.get("findings") or [])
            dead_ends.extend(got.get("dead_ends") or [])
            for lead in got.get("leads") or []:
                key = lead.strip().lower()
                # dedup against everything ever seen, or a rejected lead
                # resurfaces every wave and the loop never converges
                if key and key not in seen_leads:
                    seen_leads.add(key)
                    fresh.append(lead)

        if not fresh:
            dry += 1
            m.log(f"wave {wave}: 새 리드 없음 ({dry}/{DRY_WAVES_TO_STOP})")
            if dry >= DRY_WAVES_TO_STOP:
                m.log("포화 — 조사를 멈춥니다")
                break
            pending = []
            continue
        dry = 0
        pending = [(f"lead{i}", lead) for i, lead in enumerate(fresh, 1)]

    if not findings:
        return {"question": question, "findings": [], "corroborated": [],
                "unresolved": [], "note": "확인된 발견이 없습니다"}

    # -- Corroborate -------------------------------------------------------
    # A different model family tries to refute each claim. Anything it cannot
    # settle is reported as unresolved rather than quietly promoted.
    m.phase("Corroborate")
    checked = m.parallel([
        (lambda f=f: m.agent(
            f"주장: {f.get('claim')}\n근거: {f.get('basis')}\n"
            f"출처: {f.get('source') or '없음'}\n\n"
            "이 주장을 반증해 보세요. 반증되면 refuted, 독립적으로 뒷받침되면 "
            "corroborated, 어느 쪽도 확정할 수 없으면 unresolved입니다. "
            "모르면 unresolved가 정답이며, 추측으로 corroborated를 주지 마세요.",
            role="auditor", label=f"audit:{(f.get('claim') or '')[:20]}",
            schema=VERDICT_SCHEMA))
        for f in findings[:12]
    ])

    corroborated, refuted, unresolved = [], [], []
    for finding, verdict in zip(findings, checked):
        bucket = {"corroborated": corroborated, "refuted": refuted}.get(
            (verdict or {}).get("verdict"), unresolved)
        bucket.append({**finding, "verdict": (verdict or {}).get("verdict",
                                                                "unresolved"),
                       "audit": (verdict or {}).get("reason", "판정 없음")})

    # -- Report ------------------------------------------------------------
    m.phase("Report")
    summary = m.agent(
        f"질문: {question}\n\n"
        f"교차 검증을 통과한 발견:\n{_bullets(corroborated)}\n\n"
        f"미해결(확정 못 함):\n{_bullets(unresolved)}\n\n"
        f"반증된 것:\n{_bullets(refuted)}\n\n"
        "이걸로 답을 쓰세요. 검증된 것만 단정하고, 미해결은 미해결이라고 "
        "밝히세요. 모르는 부분을 메우지 마세요 — 빈칸으로 남기는 게 맞습니다.",
        role="planner", label="synthesize")

    return {"question": question, "axes": [a["name"] for a in axes],
            "waves": wave, "leads_seen": len(seen_leads),
            "corroborated": corroborated, "unresolved": unresolved,
            "refuted": refuted, "dead_ends": dead_ends[:20],
            "answer": summary}


def _bullets(items: list[dict]) -> str:
    if not items:
        return "  (없음)"
    return "\n".join(f"  - {i.get('claim')} — {i.get('audit', '')}"
                     for i in items[:12])
