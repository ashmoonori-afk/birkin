"""Issue-tree decomposition: planner tree, leaf execution, bottom-up join.

    birkin moirai run issue_tree --args '{"task": "..."}'

A planner breaks the task into a MECE tree; only the LEAVES execute, in
sibling groups through ``m.parallel`` so a parent order survives; each
worker's discovered follow-ups join the todo ledger instead of being lost;
and the judge composes the report bottom-up, so an internal node's summary
is built from its children, never from nothing.

The tree is bounded in CODE, not in the prompt: :func:`_parse_tree` rejects
a planner answer deeper than MAX_DEPTH or wider than MAX_LEAVES (per the
task's args, capped), and the follow-up cap is TodoList's own. The report
SAYS what was dropped rather than working forever or hiding the cut.
"""

from __future__ import annotations

from birkin.moirai import todos

meta = {
    "name": "issue-tree",
    "description": "이슈를 MECE 트리로 분해하고 잎만 실행해 상향식으로 취합",
    "phases": ["Plan", "Execute", "Report"],
    "roles": {
        "planner": {"default": "claude:sonnet",
                    "hint": "이슈를 겹치지 않는 하위 이슈로 쪼갠다"},
        "worker": {"default": "codex:gpt-5.6-sol",
                   "hint": "잎 이슈 하나를 실제로 수행한다"},
        "judge": {"default": "claude:haiku",
                  "hint": "자식 결과를 모아 부모 요약을 쓴다"},
    },
}

# Hard ceilings. Args can tighten them (issue_tree_max_depth / _max_leaves in
# cfg, or the run args), never widen them -- a planner told "go deep" must
# hit a wall in code, not a suggestion in a prompt.
MAX_DEPTH = 3
MAX_LEAVES = 12
# Follow-ups discovered while executing leaves get this much extra room on
# top of the leaf count; after that the run says what it dropped.
MAX_FOLLOWUPS = 12

# Loose shape only. Depth/leaf caps are structural invariants of the run, so
# they live in _parse_tree (code), not here (a hint the model can half-meet).
TREE_SCHEMA = {
    "type": "object",
    "required": ["goal", "children"],
    "properties": {
        "goal": {"type": "string", "maxLength": 200},
        "children": {"type": "array"},
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

SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "summary": {"type": "string", "maxLength": 2000},
    },
}

_FAIL_NOTE = "agent failed - see the run journal failures"


# -- the tree, as code -----------------------------------------------------

class Node:
    """One issue in the tree: a title, and children or a leaf marker."""

    __slots__ = ("title", "children", "is_leaf", "status", "note", "summary")

    def __init__(self, title: str, children: list["Node"] | None = None,
                 *, is_leaf: bool = False) -> None:
        self.title = title
        self.children = children or []
        self.is_leaf = is_leaf
        # Leaf execution state: pending -> in_progress -> done/failed.
        self.status = "pending"
        self.note = ""
        # What the judge composed for this node (leaves: the note itself).
        self.summary = ""

    def leaves(self, out: list["Node"]) -> None:
        if self.is_leaf:
            out.append(self)
            return
        for child in self.children:
            child.leaves(out)


def _caps(m) -> tuple[int, int]:
    """Effective depth/leaf limits: the tighter of the run args and the
    hard ceiling. An arg can only ever shrink the tree, never grow it."""

    def tighten(key: str, ceiling: int) -> int:
        try:
            value = int(m.args.get(key))
        except (TypeError, ValueError):
            return ceiling
        return min(ceiling, value) if value >= 1 else ceiling

    return (tighten("max_depth", MAX_DEPTH),
            tighten("max_leaves", MAX_LEAVES))


def _parse_tree(raw, *, max_depth: int, max_leaves: int):
    """Validate the planner's tree or return a rejection string.

    Schema fit is the engine's job before this runs; what remains is the two
    invariants a prompt cannot guarantee: depth and leaf count. Rejecting
    (rather than silently pruning) keeps MECE honest -- a cut child is a
    gap the run never reports.
    """
    if not isinstance(raw, dict):
        return None, "planner did not return a tree"
    root_title = str(raw.get("goal") or "").strip()

    leaves = 0

    def build(node_raw, depth: int, path: str):
        nonlocal leaves
        if not isinstance(node_raw, dict):
            return None, f"{path}: node is not an object"
        title = str(node_raw.get("title") or "").strip()[:200]
        if not title:
            return None, f"{path}: node has no title"
        kids_raw = node_raw.get("children") or []
        if not isinstance(kids_raw, list):
            return None, f"{path}: children is not an array"
        is_leaf = bool(node_raw.get("leaf")) or not kids_raw
        if is_leaf:
            leaves += 1
            if leaves > max_leaves:
                return None, (f"{path}: leaf cap exceeded "
                              f"({max_leaves} max)")
            return Node(title, is_leaf=True), None
        if depth + 1 > max_depth:
            return None, (f"{path}: depth cap exceeded "
                          f"({max_depth} max): {title}")
        kids = []
        for index, kid_raw in enumerate(kids_raw):
            kid, err = build(kid_raw, depth + 1, f"{path}.{index}")
            if err:
                return None, err
            kids.append(kid)
        return Node(title, kids), None

    root, err = build({"title": root_title or "(task)",
                       "children": raw.get("children")}, 0, "$")
    if err:
        return None, err
    return root, None


def _sibling_groups(node: Node, groups: list[list[Node]]) -> None:
    """Leaves, grouped by parent, in parent order -- the parallel units."""
    kids = [child for child in node.children if child.is_leaf]
    if kids:
        groups.append(kids)
    for child in node.children:
        if not child.is_leaf:
            _sibling_groups(child, groups)


def _compose(root: Node, m, *, label: str) -> None:
    """Bottom-up: every internal node's summary is composed from its
    children's summaries, deepest first."""
    for child in root.children:
        if not child.is_leaf:
            _compose(child, m, label=label)
    if root.is_leaf:
        root.summary = root.note
        return
    digest = "\n".join(f"- {child.title}: {child.summary or '(no result)'}"
                       for child in root.children)
    out = m.agent(
        "아래는 한 상위 이슈의 하위 이슈 결과들이다. 상향식으로 취합해 "
        "상위 이슈에 대한 답을 summary에 한국어로 요약하라. "
        "하위에 없는 사실을 지어내지 마라.\n\n"
        f"상위 이슈: {root.title}\n하위 결과:\n{digest}",
        role="judge", schema=SUMMARY_SCHEMA, label=label) or {}
    root.summary = str(out.get("summary")
                       or "(judge failed - see the run journal failures)")


def _render(node: Node, lines: list[str], depth: int) -> None:
    """Post-order render: children first, so each node reads verdict-after-
    evidence per subtree while the document as a whole stays top-down."""
    indent = "  " * depth
    if node.is_leaf:
        lines.append(f"{indent}- [{node.status}] {node.title}"
                     f"\n{indent}  -> {node.note}")
        return
    for child in node.children:
        _render(child, lines, depth + 1)
    lines.append(f"{indent}+ {node.title}\n{indent}  => {node.summary}")


# -- the pattern -----------------------------------------------------------

def main(m):
    task = str(m.args.get("task") or "").strip()
    max_depth, max_leaves = _caps(m)

    m.phase("Plan")
    tree_raw = m.agent(
        "다음 과제를 MECE(겹치지 않고 빠짐없이) 이슈 트리로 분해하라. "
        f"깊이는 최대 {max_depth}단계, 잎(실행 단위)은 최대 {max_leaves}개. "
        "각 노드는 {title, children} 또는 잎이면 {title, leaf: true}. "
        "잎 하나는 한 subagent가 짧게 끝낼 수 있는 실행 단위여야 한다.\n\n"
        f"과제: {task}",
        role="planner", schema=TREE_SCHEMA, label="plan")
    root, err = _parse_tree(tree_raw, max_depth=max_depth,
                            max_leaves=max_leaves)
    if err:
        return {"error": f"tree rejected: {err}"}

    leaves: list[Node] = []
    root.leaves(leaves)
    if not leaves:
        return {"error": "tree rejected: no executable leaves"}

    # The leaf ledger. Follow-ups discovered at runtime join here; the cap is
    # leaves + follow-up allowance, and what does not fit is SAID, not hidden.
    todo = todos.TodoList([leaf.title for leaf in leaves],
                          max_items=len(leaves) + MAX_FOLLOWUPS)
    dropped: list[str] = []

    m.phase("Execute")
    groups: list[list[Node]] = []
    _sibling_groups(root, groups)
    for group_index, group in enumerate(groups):
        m.phase(f"잎 그룹 {group_index + 1}/{len(groups)}: "
                + ", ".join(node.title for node in group))

        def run_leaf(node: Node):
            node.status = "in_progress"
            index = next((i for i, item in enumerate(todo.items)
                          if item["text"] == node.title
                          and item["status"] == "pending"), None)
            if index is not None:
                todo.start(index)
            out = m.agent(
                f"전체 과제: {task}\n"
                f"지금 수행할 잎 이슈: {node.title}\n"
                "이 잎 이슈 하나만 수행하고 결과를 result에 보고하라. "
                "수행 중 새로 발견한 후속 작업은 원자 단위로 followups에 "
                "담아라 (없으면 빈 배열).",
                role="worker", schema=WORK_SCHEMA,
                label=f"leaf:{node.title}") or {}
            note = str(out.get("result") or _FAIL_NOTE)
            node.note = note
            node.status = "done" if out.get("result") else "failed"
            if index is not None:
                todo.done(index, note=note)
            for followup in out.get("followups") or []:
                if not todo.append(followup):
                    dropped.append(str(followup))
            return node

        m.parallel([lambda node=node: run_leaf(node) for node in group])

    # Follow-ups join the same ledger and run after the planned leaves, in
    # discovery order. They are leaves without a parent, so they report
    # straight into the verdict, not into a subtree.
    extra_notes: list[str] = []
    while (index := todo.next_pending()) is not None:
        title = todo.items[index]["text"]
        todo.start(index)
        m.phase(f"후속 {todo.done_count + 1}/{todo.total}: {title}")
        out = m.agent(
            f"전체 과제: {task}\n"
            f"후속으로 발견된 잎 이슈: {title}\n"
            "이 항목만 수행하고 결과를 result에 보고하라. "
            "추가 후속은 followups에 담아라 (없으면 빈 배열).",
            role="worker", schema=WORK_SCHEMA,
            label=f"followup:{title}") or {}
        note = str(out.get("result") or _FAIL_NOTE)
        todo.done(index, note=note)
        extra_notes.append(f"- [{'done' if out.get('result') else 'failed'}] "
                           f"{title}\n  -> {note}")
        for followup in out.get("followups") or []:
            if not todo.append(followup):
                dropped.append(str(followup))

    m.phase("Report")
    _compose(root, m, label="judge")

    # Minto pyramid (design Item 8): verdict first, then the ledger state,
    # then the per-leaf evidence, then what the caps cut.
    failed = sum(1 for leaf in leaves if leaf.status == "failed")
    verdict = ("완료" if todo.is_complete and not failed
               else f"부분 완료 - 잎 {len(leaves)}개 중 실패 {failed}개")
    lines = [f"VERDICT: {verdict} - {task}", "",
             f"GOAL: {root.summary or '(없음)'}", "", todo.render(), ""]
    _render(root, lines, 0)
    if extra_notes:
        lines.append("")
        lines.append("후속으로 실행된 잎:")
        lines.extend(extra_notes)
    if dropped:
        lines.append("")
        lines.append(f"한도(cap)에 걸려 수행하지 못한 후속 작업 "
                     f"{len(dropped)}건: " + ", ".join(dropped[:10]))
    return "\n".join(lines)
