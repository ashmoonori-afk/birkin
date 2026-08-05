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
                  "items": {"type": "string", "maxLength": 200}},
    },
}

WORK_SCHEMA = {
    "type": "object",
    "required": ["result"],
    "properties": {
        "result": {"type": "string", "maxLength": 2000},
        "followups": {"type": "array",
                      "items": {"type": "string", "maxLength": 200}},
    },
}


def main(m):
    task = str(m.args.get("task") or "").strip()

    m.phase("Plan")
    plan = m.agent(
        "다음 업무를 실행 가능한 단계로 분해하라. 각 단계는 한 문장, "
        "실행 순서대로. 5개 이내를 권장하되 필요한 만큼만.\n\n"
        f"업무: {task}",
        role="planner", schema=PLAN_SCHEMA, label="plan")
    todo = todos.TodoList(plan.get("items") or [task], max_items=MAX_ITEMS)

    dropped: list[str] = []
    notes: list[str] = []
    while (index := todo.next_pending()) is not None:
        item = todo.items[index]["text"]
        todo.start(index)
        # The phase line is what the gateway shows in chat heartbeats.
        m.phase(f"할 일 {todo.done_count + 1}/{todo.total}: {item}")
        out = m.agent(
            f"전체 업무: {task}\n"
            f"지금 수행할 단계: {item}\n"
            "이 단계만 수행하고 결과를 보고하라. 수행 중 새로 발견한 후속 "
            "작업이 있으면 followups에 담아라 (없으면 빈 배열).",
            role="worker", schema=WORK_SCHEMA, label=f"step-{index + 1}")
        note = str(out.get("result") or "")
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
