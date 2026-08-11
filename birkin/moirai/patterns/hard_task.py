"""Hard-task runtime: decompose, execute step by step, follow up, report.

    birkin moirai run hard_task --args '{"task": "..."}'

A planner turns the task into an internal todo list. A worker executes one
item at a time, and may report follow-ups it discovered -- those JOIN the list
instead of being lost. Every step announces itself through ``m.phase()``,
which is the same channel the gateway forwards into chat heartbeats, so the
user watching Telegram sees "할 일 3/7 · 진행 중: ..." instead of silence.

The list is bounded (MAX_ITEMS): a worker that keeps discovering follow-ups
runs out of room, and the report SAYS what was dropped rather than working
forever or hiding the cut.
"""

from birkin.moirai import todos

meta = {
    "name": "hard-task",
    "description": "어려운 업무를 내부 TODO로 분해하고 단계별로 실행·후속 추적",
    "phases": ["Plan", "Execute", "Report"],
    "roles": {
        "planner": {"default": "claude:sonnet",
                    "hint": "업무를 실행 가능한 단계로 쪼갠다"},
        "decomposer": {"default": "claude:haiku",
                       "hint": "업무 흐름을 원자 단위 작업으로 세분화한다"},
        "worker": {"default": "codex:gpt-5.6-sol",
                   "hint": "단계 하나를 실제로 수행한다"},
    },
}

MAX_ITEMS = todos.DEFAULT_MAX_ITEMS

PLAN_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {"type": "array",
                  "maxItems": 6,
                  "items": {"type": "string", "maxLength": 200}},
    },
}

ATOMIC_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {"type": "array",
                  "maxItems": 8,
                  "items": {"type": "string", "maxLength": 200}},
    },
}

WORK_SCHEMA = {
    "type": "object",
    "required": ["result"],
    "properties": {
        "result": {"type": "string", "maxLength": 2000},
        "followups": {"type": "array",
                      "maxItems": 5,
                      "items": {"type": "string", "maxLength": 200}},
    },
}


def main(m):
    task = str(m.args.get("task") or "").strip()

    m.phase("Plan")
    plan = m.agent(
        "다음 업무를 실행 순서가 있는 상위 작업 흐름으로 분해하라. "
        "서로 독립적으로 세분화할 수 있는 흐름만, 최대 5개.\n\n"
        f"업무: {task}",
        role="planner", schema=PLAN_SCHEMA, label="plan") or {}

    dropped: list[str] = []
    atomic_items: list[str] = []
    workstreams = plan.get("items") or [task]
    for index, item in enumerate(workstreams):
        m.phase(f"세분화 {index + 1}/{len(workstreams)}: {item}")
        split = m.agent(
            "다음 작업 흐름을 한 subagent가 짧게 끝낼 수 있는 원자 단위로 "
            "세분화하라. 각 항목은 산출물 하나와 그 검증 하나를 함께 명시하고, "
            "독립 실행 가능한 순서로 작성하라.\n\n"
            f"전체 업무: {task}\n작업 흐름: {item}",
            role="decomposer", schema=ATOMIC_SCHEMA,
            label=f"decompose-{index + 1}") or {}
        for atomic in split.get("items") or [item]:
            if len(atomic_items) >= MAX_ITEMS:
                dropped.append(str(atomic))
            elif str(atomic).strip():
                atomic_items.append(str(atomic).strip())

    todo = todos.TodoList(atomic_items or [task], max_items=MAX_ITEMS)
    notes: list[str] = []
    while (index := todo.next_pending()) is not None:
        item = todo.items[index]["text"]
        todo.start(index)
        # The phase line is what the gateway shows in chat heartbeats.
        m.phase(f"할 일 {todo.done_count + 1}/{todo.total}: {item}")
        out = m.agent(
            f"전체 업무: {task}\n"
            f"지금 수행할 단계: {item}\n"
            "이 원자 단계만 수행하고 명시된 검증까지 실행해 결과를 보고하라. "
            "수행 중 새로 발견한 후속 작업은 산출물 하나와 검증 하나를 갖춘 "
            "원자 단위로 followups에 담아라 (없으면 빈 배열).",
            role="worker", schema=WORK_SCHEMA,
            label=f"step-{index + 1}") or {}
        note = str(
            out.get("result")
            or "에이전트 실패 — 실행 저널의 failures를 확인하세요")
        todo.done(index, note=note)
        notes.append(f"[{todo.done_count}/{todo.total}] {item}\n  → {note}")
        for followup in out.get("followups") or []:
            if not todo.append(followup):
                dropped.append(str(followup))

    m.phase("Report")
    lines = [f"# {task}", "", todo.render(), ""]
    lines.extend(notes)
    if dropped:
        lines.append("")
        lines.append("한도(cap)에 걸려 수행하지 못한 후속 작업 "
                     f"{len(dropped)}건: " + ", ".join(dropped[:10]))
    return "\n".join(lines)
