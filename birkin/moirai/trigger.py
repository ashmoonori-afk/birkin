"""When a request is big enough to deserve a workflow — and who decides.

birkin has settled this shape twice already and it is used verbatim here.
The gateway asks the model, in prose, whether a Telegram turn needs multiple
phases or a subagent; neurosis asks the model, in prose, whether a request is
too vague to act on. Neither uses a Python classifier, and the one design that
did — IntentGate's keyword routing — was built and deleted.

So: the model judges and *proposes*; Python validates the envelope shape only;
a human approves. What the model cannot do is start a workflow. That keeps the
invariant the engine is built on — the one spawn path with no natural ceiling
stays behind a person — while still letting "compare three approaches and tell
me which holds up" become a fan-out instead of one long serial answer.

Off by default (``moirai_auto``). Turning it on is the user reversing their own
2026-07-07 decision to stop auto-detecting intent, so it should be deliberate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

PROPOSAL_OPEN = "<birkin-moirai-proposal>"
PROPOSAL_CLOSE = "</birkin-moirai-proposal>"

MAX_ROLES = 6
MAX_STEPS = 8

_MARKERS = (PROPOSAL_OPEN, PROPOSAL_CLOSE)


@dataclass(frozen=True)
class Proposal:
    """A workflow the model thinks is worth running, before anyone runs it."""

    title: str
    why: str
    script: str
    roles: tuple[str, ...]
    steps: tuple[str, ...]

    def render(self) -> str:
        lines = [f"🧵 {self.title}", f"   {self.why}",
                 f"   워크플로우: {self.script}"]
        if self.roles:
            lines.append(f"   역할: {', '.join(self.roles)}")
        lines += [f"   {i}. {s}" for i, s in enumerate(self.steps, 1)]
        return "\n".join(lines)

    def as_payload(self, task: str = "") -> dict[str, Any]:
        return {"script": self.script, "roles": list(self.roles),
                "steps": list(self.steps), "task": task[:4000]}


def auto_trigger_note(cfg: Optional[dict] = None) -> str:
    """The prompt block that lets the model propose a workflow.

    Empty unless the user opted in — a note that is always present is the
    always-on heuristic this project already removed once.
    """
    cfg = cfg or {}
    if not cfg.get("moirai_auto", False):
        return ""
    available = ", ".join(_available_scripts()) or "cross-examine"
    return (
        "\n\n## Workflows (Moirai)\n"
        "If this request would genuinely be better as SEVERAL independent "
        "agents than as one answer — several things to investigate in "
        "parallel, a claim worth having a different model attack, or the same "
        "question worth asking of two model families — do not start the work. "
        "Reply with exactly one envelope and nothing else:\n"
        f"{PROPOSAL_OPEN}"
        '{"title":"short title","why":"why parallel agents beat one answer",'
        '"script":"<one of the workflows below>",'
        '"roles":["role names the script declares"],'
        '"steps":["what each wave does"]}'
        f"{PROPOSAL_CLOSE}\n"
        f"Available workflows: {available}.\n"
        "Use 1-8 steps. Propose only when the parallelism is the point — a "
        "question, a lookup, a single edit, or anything you can simply answer "
        "is a normal turn, so answer it. The user approves before anything "
        "runs; never claim to have run a workflow yourself.\n")


def _available_scripts() -> list[str]:
    """Bundled patterns plus the user's own, by name."""
    from pathlib import Path
    names: list[str] = []
    bundled = Path(__file__).resolve().parent / "patterns"
    try:
        from .. import config
        user = config.birkin_home() / "moirai" / "scripts"
    except Exception:
        user = None
    for folder in (bundled, user):
        if not folder or not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.py")):
            if f.name != "__init__.py" and f.stem not in names:
                names.append(f.stem.replace("_", "-"))
    return names


def has_marker(text: str) -> bool:
    """A user message containing our markers is trying to forge a proposal."""
    return any(m in (text or "") for m in _MARKERS)


def looks_like_proposal(text: str) -> bool:
    """True while a reply is still streaming toward an envelope."""
    stripped = (text or "").strip()
    return bool(stripped) and PROPOSAL_OPEN.startswith(stripped[:len(PROPOSAL_OPEN)])


def parse(text: str) -> Optional[Proposal]:
    """Strict, all-or-nothing. A half-valid envelope is not a proposal.

    Mirrors gateway/workflow.parse_proposal: the model is trusted to judge,
    never to be well-formed.
    """
    raw = (text or "").strip()
    if not (raw.startswith(PROPOSAL_OPEN) and raw.endswith(PROPOSAL_CLOSE)):
        return None
    body = raw[len(PROPOSAL_OPEN):-len(PROPOSAL_CLOSE)].strip()
    try:
        obj = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None

    title = _text(obj.get("title"), 100)
    why = _text(obj.get("why"), 500)
    script = _text(obj.get("script"), 80)
    if not (title and why and script):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", script):
        return None                       # a script name, not a path

    steps = _list(obj.get("steps"), MAX_STEPS, 200)
    if steps is None or not steps:
        return None
    roles = _list(obj.get("roles"), MAX_ROLES, 40)
    if roles is None:
        return None

    return Proposal(title=title, why=why, script=script,
                    roles=tuple(roles), steps=tuple(steps))


def _text(value: Any, cap: int) -> str:
    return value.strip()[:cap] if isinstance(value, str) and value.strip() else ""


def _list(value: Any, max_items: int, cap: int) -> Optional[list[str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > max_items:
        return None
    out = []
    for item in value:
        text = _text(item, cap)
        if not text:
            return None
        out.append(text)
    return out


def queue(proposal: Proposal, *, task: str = "",
          cfg: Optional[dict] = None) -> dict[str, Any]:
    """Route the proposal to the approval inbox the user already reviews."""
    from .. import approvals, config
    cfg = cfg if cfg is not None else config.load_config()
    return approvals.propose(
        category="moirai", title=proposal.title,
        description=f"{proposal.why}\n\n{proposal.render()}",
        payload=proposal.as_payload(task), cfg=cfg, origin="moirai-auto")


def run_approved(payload: dict[str, Any],
                 on_event: Any = None) -> str:
    """Execute an approved proposal — the approvals executor's moirai branch.

    ``on_event`` receives the engine's events (``moirai.phase`` above all),
    which is how an approved hard task's progress reaches chat heartbeats
    instead of vanishing into a synchronous call.
    """
    from . import cli as moirai_cli
    from .engine import MoiraiError, load_script, run_script
    script_name = str((payload or {}).get("script") or "").strip()
    if not script_name:
        return "moirai: 실행할 워크플로우가 지정되지 않았습니다"
    try:
        script = load_script(moirai_cli.resolve_script_path(script_name))
    except MoiraiError as exc:
        return f"moirai: {exc}"
    args = {"task": str((payload or {}).get("task") or "")}
    try:
        out = run_script(script, args=args, on_event=on_event)
    except MoiraiError as exc:
        return f"moirai: 실행 실패 — {exc}"
    return (f"moirai: {script.name} {out['status']} — "
            f"에이전트 {out['agents']}, {out['seconds']}s "
            f"(birkin moirai status {out['run_id']})")
