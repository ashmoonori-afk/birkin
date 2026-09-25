"""Natural-language worker request contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from . import worker_executor, worker_hooks, worker_request, worker_schema

WORKER_COMMANDS: dict[str, str] = {
    "moirai": "deterministic multi-agent workflows",
    "morpheus": "run the self-improvement routine",
    "harness": "inspect or manage the self-improvement ledger",
    "odyssey": "seed a goal-completion cycle",
    "neurosis": "seed a Socratic deep interview",
    "daedalus": "manage evidence-linked project document maps",
}

WorkerCallError = worker_request.WorkerRequestError

# Korean labels for the approval card; the schema keys stay in the payload.
_FIELD_LABELS: dict[str, str] = {
    "script": "워크플로우",
    "task": "작업",
    "limit": "개수",
    "run_id": "실행 ID",
    "dry_run": "시험 실행",
    "target": "대상",
    "scope": "범위",
    "goal": "목표",
    "idea": "아이디어",
    "resolution": "깊이",
    "slug": "문서 맵",
    "root": "루트",
    "token": "토큰",
    "text": "내용",
    "refs": "참조",
}


# Free-text fields go last and are capped so the fields an approval binds
# (workflow, scope, file) always fit in a short card preview.
_FREE_TEXT = frozenset({"task", "target", "goal", "idea", "text", "refs"})
_FREE_TEXT_CHARS = 120


def _display(value: object) -> str:
    from .tools.connections import visible_text  # local: avoids a tools cycle

    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, list):
        return ", ".join(visible_text(item) for item in value)
    return visible_text(value)


def _capped(text: str) -> str:
    if len(text) <= _FREE_TEXT_CHARS:
        return text
    return f"{text[:_FREE_TEXT_CHARS]}… ({len(text)}자)"


@dataclass(frozen=True, slots=True)
class WorkerCall:
    request: worker_request.WorkerRequest
    category: ClassVar[str] = "worker"

    @property
    def worker(self) -> str:
        return worker_request.worker_name(self.request)

    def title(self) -> str:
        action = worker_request.action_name(self.request)
        return f"워커 실행 승인: {self.worker}{f' {action}' if action else ''}"

    def description(self) -> str:
        data = worker_request.request_data(self.request)
        shown = [
            (key, value) for key, value in data.items()
            if key not in ("worker", "action") and value not in ("", [])
        ]
        fields = [
            f"- {_FIELD_LABELS.get(key, key)}: {_display(value)}"
            for key, value in shown if key not in _FREE_TEXT
        ]
        script = self.script_line()
        if script:
            fields.append(script)
        fields += [
            f"- {_FIELD_LABELS.get(key, key)}: {_capped(_display(value))}"
            for key, value in shown if key in _FREE_TEXT
        ]
        lead = "아래 내용으로 " if fields else ""
        return "\n".join([f"승인하면 {self.worker} 워커를 {lead}실행합니다.", *fields])

    def argv(self) -> tuple[str, ...]:
        return worker_executor.argv(self.request)

    def script_line(self) -> str:
        """Which file a workflow run executes, for the approval card."""
        if not isinstance(self.request, worker_request.MoiraiRun):
            return ""
        import hashlib

        from .moirai.cli import bundled_dir, resolve_trusted_script

        path = resolve_trusted_script(self.request.script)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        source = ("기본 패턴" if path.parent == bundled_dir()
                  else "사용자 워크플로우")
        return f"- 실행 파일: {source} {path} (sha256 {digest}…)"

    def payload(self) -> worker_request.JsonObject:
        return worker_request.approval_payload(self.request)


def invokable_workers() -> tuple[str, ...]:
    return tuple(name for name in worker_hooks.WORKERS if name in WORKER_COMMANDS)


def describe_workers() -> str:
    return "; ".join(
        f"{name} = {WORKER_COMMANDS[name]}" for name in invokable_workers()
    )


def resolve(request: object) -> WorkerCall:
    parsed = worker_request.parse(request)
    if worker_request.worker_name(parsed) not in invokable_workers():
        raise WorkerCallError(
            f"worker is not invokable: {worker_request.worker_name(parsed)}"
        )
    if isinstance(parsed, worker_request.MoiraiRun):
        from .moirai.cli import MoiraiError, resolve_trusted_script

        try:
            resolve_trusted_script(parsed.script)
        except MoiraiError as exc:
            # Refuse before an approval is queued for a file nobody can see.
            raise WorkerCallError(str(exc)) from exc
    return WorkerCall(parsed)


def input_schema() -> worker_request.JsonObject:
    return worker_schema.input_schema()
