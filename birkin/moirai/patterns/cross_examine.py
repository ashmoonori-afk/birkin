"""Cross-examination: one family drafts, the other family attacks.

A model asked to judge its own output grades on a curve. Splitting draft and
critique across providers is the cheapest correction available, and it is the
reason this engine routes per role instead of per run.

Every critique is structured (CRITIQUE_SCHEMA) and must carry INVERSION (how
the draft fails / what would make it wrong) and SECOND-ORDER (what adopting it
costs in 3 months) alongside the direct attack -- a draft can survive a flaw
list and still be adopted blindly, so the report always keeps both keys
(thinking-frameworks design, Item 7).

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

# The critic's contract. `inversion` and `second_order` are mandatory keys,
# not prompt suggestions: the schema validator rejects a critique that omits
# either, so the final report always has both.
CRITIQUE_SCHEMA = {
    "type": "object",
    "required": ["attack", "inversion", "second_order"],
    "properties": {
        "attack": {"type": "string", "maxLength": 1000},
        "inversion": {"type": "string", "maxLength": 1000},
        "second_order": {"type": "string", "maxLength": 1000},
    },
}

_ANGLES = ["사실관계가 틀린 곳", "숨은 전제", "반대 사례"]


def _render(critique: dict) -> str:
    """One critique as report lines: attack, then INVERSION, then SECOND-ORDER."""
    return (f"ATTACK: {critique.get('attack') or '(없음)'}\n"
            f"INVERSION: {critique.get('inversion') or '(없음)'}\n"
            f"SECOND-ORDER: {critique.get('second_order') or '(없음)'}")


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
    critiques = m.parallel([
        lambda a=a: m.agent(
            f"다음 주장을 '{a}' 관점에서 공격하세요. 스키마의 각 필드에 "
            "한국어로 답하세요:\n"
            "- attack: 가장 약한 고리 하나 (동의하는 부분은 쓰지 마세요)\n"
            "- inversion: 이 주장이 실패하는 모습 / 어떻게 하면 틀리게 되는지\n"
            "- second_order: 이 주장을 채택했을 때 3개월 뒤의 결과와 비용\n\n"
            f"---\n{draft}",
            role="critic", schema=CRITIQUE_SCHEMA, label=f"critic:{a}")
        for a in _ANGLES
    ])
    landed = [c for c in critiques if isinstance(c, dict) and c]

    m.phase("Revise")
    if not landed:
        return {"draft": draft, "critiques": [], "final": draft,
                "note": "비평이 하나도 도착하지 않아 초안을 그대로 둡니다"}

    joined = "\n\n".join(f"[비평 {i+1}]\n{_render(c)}"
                         for i, c in enumerate(landed))
    final = m.agent(
        f"당신의 초안:\n{draft}\n\n받은 비평:\n{joined}\n\n"
        "타당한 비평만 반영해 주장을 수정하세요. 어떤 비평을 왜 기각했는지도 "
        "한 줄로 밝히세요. 15줄 이내 한국어.",
        role="drafter", label="revise")

    return {"draft": draft, "critiques": landed, "final": final or draft}
