"""Cross-examination: one family drafts, the other family attacks.

A model asked to judge its own output grades on a curve. Splitting draft and
critique across providers is the cheapest correction available, and it is the
reason this engine routes per role instead of per run.

    birkin moirai run cross_examine --args '{"topic": "..."}'
    birkin moirai run cross_examine --bind critic=claude:opus
"""

meta = {
    "name": "cross-examine",
    "description": "한 계열이 초안, 다른 계열이 반박, 초안자가 수정",
    "phases": ["Draft", "Critique", "Revise"],
    "roles": {
        "drafter": {"default": "codex:gpt-5.6-sol",
                    "hint": "주장을 세우는 쪽 — 추론이 강한 모델"},
        "critic": {"default": "claude:haiku",
                   "hint": "반박하는 쪽 — 초안자와 다른 계열이어야 의미가 있다"},
    },
}


def main(m):
    topic = m.args.get("topic") or "이 저장소에서 가장 위험한 설계 결정"

    m.phase("Draft")
    draft = m.agent(
        f"주제: {topic}\n\n"
        "명확한 주장 하나와 근거 3가지를 한국어로 쓰세요. "
        "12줄 이내, 군더더기 없이.",
        role="drafter", label="draft")
    if not draft:
        return {"error": "초안 실패"}

    m.phase("Critique")
    angles = ["사실관계가 틀린 곳", "숨은 전제", "반대 사례"]
    critiques = m.parallel([
        lambda a=a: m.agent(
            f"다음 주장을 '{a}' 관점에서만 공격하세요. "
            f"동의하는 부분은 쓰지 말고, 가장 약한 고리 하나만 지적하세요. "
            f"5줄 이내 한국어.\n\n---\n{draft}",
            role="critic", label=f"critic:{a}")
        for a in angles
    ])
    landed = [c for c in critiques if c]

    m.phase("Revise")
    if not landed:
        return {"draft": draft, "critiques": [], "final": draft,
                "note": "비평이 하나도 도착하지 않아 초안을 그대로 둡니다"}

    joined = "\n\n".join(f"[비평 {i+1}]\n{c}" for i, c in enumerate(landed))
    final = m.agent(
        f"당신의 초안:\n{draft}\n\n받은 비평:\n{joined}\n\n"
        "타당한 비평만 반영해 주장을 수정하세요. 어떤 비평을 왜 기각했는지도 "
        "한 줄로 밝히세요. 15줄 이내 한국어.",
        role="drafter", label="revise")

    return {"draft": draft, "critiques": landed, "final": final or draft}
