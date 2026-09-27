from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import threading
from typing import cast, final

import pytest

from birkin import approvals, goals, store, uistate, work_items
from birkin.computer_use.capability_types import (
    DisplayServer,
    PermissionState,
    PlatformProbe,
)
from birkin.computer_use.runtime import UnavailableBackend
from birkin.llm import LLMError, LLMStatus
from birkin.native.projection import public_workspace_event
from birkin.office.adapters.catalog import supported_formats
from birkin.workspace import approval_authority
from birkin.runtime import Session
from birkin.workspace import WorkspaceEvent, WorkspaceService, runtime_adapter
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.snapshot import reduce_snapshot


@final
class _RuntimeSession:
    def __init__(self) -> None:
        self.cfg: dict[str, object] = {}
        self.steers: list[str] = []
        self.ask_count: int = 0

    def steer(self, text: str) -> bool:
        self.steers.append(text)
        return True

    def ask(self, text: str, *, on_text: object, on_progress: object = None) -> str:
        del on_text, on_progress
        self.ask_count += 1
        if self.ask_count == 1:
            raise RuntimeError("provider failed")
        return f"retried: {text}"


@final
class _ActiveRuntimeSession:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.cfg: dict[str, object] = {}
        self.abort = threading.Event()
        self.steers: list[str] = []
        self._started = started
        self._release = release

    def ask(self, text: str, *, on_text: object, on_progress: object = None) -> str:
        del on_text, on_progress
        self._started.set()
        if not self._release.wait(timeout=10):
            raise AssertionError("test did not release active runtime")
        return text

    def steer(self, text: str) -> bool:
        self.steers.append(text)
        return True


@final
class _FailingRuntimeSession:
    def __init__(self, error: LLMError | ValueError) -> None:
        self.cfg: dict[str, object] = {}
        self._error = error

    def ask(self, text: str, *, on_text: object, on_progress: object = None) -> str:
        del text, on_text, on_progress
        raise self._error


@final
class _CapturingRuntimeSession:
    def __init__(self) -> None:
        self.cfg: dict[str, object] = {}
        self.abort = threading.Event()
        self.prompts: list[str] = []

    def ask(self, text: str, *, on_text: object, on_progress: object = None) -> str:
        del on_text, on_progress
        self.prompts.append(text)
        if '<approval-outcome' in text and 'outcome="approved"' in text:
            return "승인된 작업이 완료되었습니다."
        if "<approval-outcome" in text:
            return "승인된 작업을 완료하지 못했습니다."
        return f"agent saw: {text}"

    def steer(self, _text: str) -> bool:
        return False


def test_runtime_adapter_registers_product_surface_authority_and_commands(
    tmp_path: Path,
) -> None:
    adapter = RuntimeWorkspaceAdapter(
        "surface-session", _event, workspace_root=tmp_path / "workspace"
    )

    assert adapter.surface_authority.surface_names == (
        "browser_aside",
        "computer_use",
        "office",
    )
    assert {
        "browser.start",
        "browser.navigate",
        "office.create",
        "office.open",
    }.issubset(adapter.handlers())
    snapshots = adapter.surface_authority.snapshots(
        {"browser_aside": 0, "computer_use": 0, "office": 0}
    )
    assert [snapshot.surface for snapshot in snapshots] == [
        "browser_aside",
        "computer_use",
        "office",
    ]


def test_llm_retry_status_emits_korean_progress_event(tmp_path: Path) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    adapter = RuntimeWorkspaceAdapter(
        "status-session",
        emit,
        workspace_root=tmp_path / "workspace",
    )

    adapter.runtime_status(
        LLMStatus(
            kind="retrying",
            provider="anthropic",
            model="claude",
            reason="rate_limit",
            retry_in_seconds=2,
            attempt=3,
            max_attempts=4,
            http_status=429,
        )
    )

    assert emitted == [
        (
            "progress.updated",
            {
                "summary": "요청이 많아 잠시 대기 중입니다. 자동으로 다시 시도합니다.",
                "status": "retrying",
                "ui_state": "running",
                "provider": "anthropic",
                "model": "claude",
                "reason": "rate_limit",
                "retry_in_seconds": 2,
                "attempt": 3,
                "max_attempts": 4,
                "provider_status": 429,
            },
        )
    ]


@pytest.mark.parametrize(
    ("status", "expected_summary", "expected_ui_state"),
    [
        (
            LLMStatus(
                kind="failover",
                provider="anthropic",
                model="claude",
                reason="server",
                retry_in_seconds=30,
                fallback_provider="openai",
                fallback_model="gpt",
            ),
            (
                "기본 모델을 사용할 수 없어 대체 모델로 전환했습니다. "
                "응답을 계속 기다려 주세요."
            ),
            "running",
        ),
        (
            LLMStatus(
                kind="recovered",
                provider="anthropic",
                model="claude",
                reason="primary_recovered",
            ),
            (
                "기본 모델 연결이 복구되었습니다. "
                "다음 요청부터 기본 모델을 사용합니다."
            ),
            "succeeded",
        ),
    ],
)
def test_llm_transition_status_emits_korean_progress_event(
    tmp_path: Path,
    status: LLMStatus,
    expected_summary: str,
    expected_ui_state: str,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    adapter = RuntimeWorkspaceAdapter(
        "status-transition-session",
        emit,
        workspace_root=tmp_path / "workspace",
    )

    adapter.runtime_status(status)

    assert emitted == [
        (
            "progress.updated",
            {
                "summary": expected_summary,
                "status": status.kind,
                "ui_state": expected_ui_state,
                "provider": status.provider,
                "model": status.model,
                "reason": status.reason,
                **(
                    {"retry_in_seconds": status.retry_in_seconds}
                    if status.retry_in_seconds is not None
                    else {}
                ),
                **(
                    {"fallback_provider": status.fallback_provider}
                    if status.fallback_provider is not None
                    else {}
                ),
                **(
                    {"fallback_model": status.fallback_model}
                    if status.fallback_model is not None
                    else {}
                ),
            },
        )
    ]


@final
class _GrantedBackend:
    """A platform backend that reports both permissions already granted."""

    backend_id = "test-granted"

    def probe(self) -> PlatformProbe:
        return PlatformProbe(
            platform="darwin",
            display_server=DisplayServer.QUARTZ,
            interactive=True,
            accessibility=PermissionState.GRANTED,
            screen_capture=PermissionState.GRANTED,
            responsible_process="birkin-test",
        )


def test_computer_use_surface_projects_the_selected_backend_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Given a platform backend reporting granted permissions, When the runtime
    adapter composes product surfaces, Then Computer Use projects that grant."""
    monkeypatch.setattr(runtime_adapter, "default_backend", lambda: _GrantedBackend())
    adapter = RuntimeWorkspaceAdapter(
        "capability-session", _event, workspace_root=tmp_path / "workspace"
    )

    status = cast(
        dict[str, object], adapter.surface_authority.computer_use.snapshot()["status"]
    )

    permissions = cast(dict[str, object], status["permissions"])
    assert permissions["accessibility"] == "granted"
    assert permissions["screen_capture"] == "granted"
    assert status["permission_prompted"] is False


def test_computer_use_surface_projects_an_unavailable_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Given no supported platform backend, When the runtime adapter composes
    product surfaces, Then Computer Use projects undetermined permissions."""
    monkeypatch.setattr(
        runtime_adapter, "default_backend", lambda: UnavailableBackend()
    )
    adapter = RuntimeWorkspaceAdapter(
        "capability-session", _event, workspace_root=tmp_path / "workspace"
    )

    status = cast(
        dict[str, object], adapter.surface_authority.computer_use.snapshot()["status"]
    )

    permissions = cast(dict[str, object], status["permissions"])
    assert permissions["accessibility"] == "unknown"
    assert status["permission_prompted"] is False


def test_external_agent_rows_use_task_summary_and_run_states() -> None:
    done = runtime_adapter._external_item(
        "tasks_runs", {"id": "abcd1234", "task": "분석", "status": "done"}, 0
    )
    failed = runtime_adapter._external_item(
        "tasks_runs", {"id": "abcd1235", "task": "정리", "status": "error"}, 1
    )
    titled = runtime_adapter._external_item(
        "tasks_runs",
        {"id": "abcd1236", "title": "제목", "task": "작업", "status": "running"},
        2,
    )
    summarized = runtime_adapter._external_item(
        "tasks_runs", {"id": "abcd1237", "summary": "요약", "task": "작업"}, 3
    )

    assert (done["summary"], done["ui_state"]) == ("분석", "succeeded")
    assert (failed["summary"], failed["ui_state"]) == ("정리", "failed")
    assert (titled["summary"], titled["ui_state"]) == ("제목", "running")
    assert summarized["summary"] == "요약"


def test_runtime_import_formats_follow_office_catalog() -> None:
    assert runtime_adapter._REGISTERED_IMPORT_SUFFIXES == {
        f".{format_name}" for format_name in supported_formats()
    } | {".txt"}


def test_work_item_source_handler_resolves_persisted_goal_after_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    goal = goals.set_goal("고객 보고서 제출", session_id="source-session")
    item = cast(dict[str, object], json.loads(work_items.apply_approved({
        "action": "create",
        "title": "보고서 확인",
        "session_id": "source-session",
        "source": {"goal_slug": goal.slug},
    }))["items"][0])

    restarted = RuntimeWorkspaceAdapter(
        "source-session", _event, workspace_root=tmp_path / "workspace"
    )
    result = restarted.handlers()["work_item.open_source"]({"id": item["id"]})

    assert result["source_type"] == "goal_slug"
    assert result["summary"] == "고객 보고서 제출"
    with pytest.raises(ValueError, match="올바르지"):
        restarted.handlers()["work_item.open_source"]({"id": item["id"], "target": "../secret"})


def test_creation_receipt_source_uses_canonical_approved_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "approved"
    workspace.mkdir()
    adapter = RuntimeWorkspaceAdapter(
        "receipt-session", _event, workspace_root=workspace
    )
    queued = adapter.handlers()["office.create"]({
        "format": "docx",
        "content": {"paragraphs": ["승인 영수증 검증"]},
        "output_name": "report.docx",
    })
    approved = approvals.approve(
        cast(str, queued["id"]), approved_by="human:test", approved_via="test"
    )
    assert approved["ok"] is True
    approval = cast(dict[str, object], queued["approval"])
    item = cast(dict[str, object], json.loads(work_items.apply_approved({
        "action": "create",
        "title": "생성 결과 확인",
        "source": {"job_id": approval["job_id"]},
    }))["items"][0])

    restarted = RuntimeWorkspaceAdapter(
        "receipt-session", _event, workspace_root=workspace
    )
    details = restarted.handlers()["work_item.open_source"]({"id": item["id"]})

    assert details["summary"] == "Create report.docx"
    assert details["destination"] == str(workspace / "report.docx")
    assert details["validation"] == "등록된 구조 검증 통과 · 시각 검증 미실행"
    assert "되돌리기 가능" in cast(str, details["rollback"])
    assert "새 파일 삭제로 복원" in cast(str, details["rollback"])
    assert "receipt_hmac" not in json.dumps(details)
    assert "rollback_token" not in json.dumps(details)
    snapshot = WorkspaceService(
        root=tmp_path / "fresh-workspace",
        session_id="receipt-session",
        handlers={},
    ).snapshot()
    activity = next(panel for panel in snapshot.panels if panel.key == "activity_logs")
    tasks = next(panel for panel in snapshot.panels if panel.key == "tasks_runs")
    projected = next(row for row in tasks.items if row.get("id") == item["id"])
    assert activity.items == ()
    assert projected["source_validation"] == "등록된 구조 검증 통과 · 시각 검증 미실행"


def test_runtime_adapter_advertises_and_executes_jailed_file_import(
    tmp_path: Path,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    dropped = tmp_path / "outside" / "drop.txt"
    dropped.parent.mkdir()
    _ = dropped.write_text("drop through production adapter", encoding="utf-8")
    adapter = RuntimeWorkspaceAdapter(
        "import-session", emit, workspace_root=tmp_path / "workspace"
    )

    handler = adapter.handlers()["file.import"]
    result = handler({"source_path": str(dropped)})

    reference = cast(dict[str, object], result["reference"])
    imported = tmp_path / "workspace" / "imports" / str(reference["jail_name"])
    assert imported.read_text(encoding="utf-8") == "drop through production adapter"


def test_chat_send_accepts_only_unchanged_imports_from_its_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _RuntimeSession()
    runtime.ask_count = 1

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    workspace = tmp_path / "workspace"
    source = tmp_path / "attachment.txt"
    _ = source.write_text("trusted attachment", encoding="utf-8")
    adapter = RuntimeWorkspaceAdapter(
        "attachment-session", _event, workspace_root=workspace
    )
    imported = adapter.handlers()["file.import"]({"source_path": str(source)})
    reference = cast(dict[str, object], imported["reference"])

    result = adapter.handlers()["chat.send"](
        {
            "text": "inspect this",
            "attachments": [reference],
        }
    )

    assert result["attachments"] == [reference]
    assert "attachment.txt" in cast(str, result["reply"])

    jailed = workspace / "imports" / str(reference["jail_name"])
    _ = jailed.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        _ = adapter.handlers()["chat.send"](
            {
                "text": "inspect this",
                "attachments": [reference],
            }
        )
    jailed.unlink()
    with pytest.raises(ValueError, match="deleted"):
        _ = adapter.handlers()["chat.send"](
            {
                "text": "inspect this",
                "attachments": [reference],
            }
        )


def test_chat_send_rejects_unknown_and_cross_session_imports(tmp_path: Path) -> None:
    source = tmp_path / "attachment.txt"
    _ = source.write_text("trusted attachment", encoding="utf-8")
    first = RuntimeWorkspaceAdapter(
        "first-session", _event, workspace_root=tmp_path / "workspace"
    )
    second = RuntimeWorkspaceAdapter(
        "second-session", _event, workspace_root=tmp_path / "workspace"
    )
    imported = first.handlers()["file.import"]({"source_path": str(source)})
    reference = cast(dict[str, object], imported["reference"])

    with pytest.raises(ValueError, match="unknown.*session"):
        _ = second.handlers()["chat.send"](
            {"text": "inspect", "attachments": [reference]}
        )

    unknown = dict(reference)
    unknown["import_id"] = "import-00000000000000000000000000000000"
    with pytest.raises(ValueError, match="unknown.*session"):
        _ = first.handlers()["chat.send"]({"text": "inspect", "attachments": [unknown]})


def test_steer_delegates_to_runtime_and_emits_canonical_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    runtime = _RuntimeSession()

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("steer-session", emit)

    result = adapter.handlers()["chat.steer"]({"text": "  check tests  "})

    assert result == {"steered": True}
    assert runtime.steers == ["check tests"]
    assert emitted == [("turn.steered", {"text": "check tests"})]


def test_chat_send_brackets_silent_gap_with_bounded_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    @final
    class CompletedRuntime:
        cfg: dict[str, object] = {}

        def ask(
            self, text: str, *, on_text: object, on_progress: object = None
        ) -> str:
            del text, on_text, on_progress
            return "완료"

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, CompletedRuntime()))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("progress-session", emit)

    assert adapter.handlers()["chat.send"]({"text": "진행 상황을 알려줘"}) == {
        "reply": "완료"
    }

    progress = [
        payload for event_type, payload in emitted if event_type == "progress.updated"
    ]
    assert progress == [
        {
            "progress_id": "turn:progress-session",
            "summary": "응답을 준비하고 있습니다.",
            "status": "working",
            "ui_state": "pending",
        },
        {
            "progress_id": "turn:progress-session",
            "summary": "응답을 완료했습니다.",
            "status": "succeeded",
            "ui_state": "succeeded",
        },
    ]


def test_turn_controls_mutate_the_active_runtime_without_waiting_for_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    runtime = _ActiveRuntimeSession(started, release)

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    adapter = RuntimeWorkspaceAdapter("control-session", emit)
    handlers = adapter.handlers()
    errors: list[BaseException] = []

    def send() -> None:
        try:
            _ = handlers["chat.send"]({"text": "work"})
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert started.wait(timeout=1)
        assert handlers["chat.interrupt"]({}) == {"interrupted": True}
        assert runtime.abort.is_set()
        assert handlers["chat.steer"]({"text": "redirect"}) == {"steered": True}
        assert runtime.steers == ["redirect"]
        assert handlers["chat.resume"]({}) == {"resumed": True}
        assert not runtime.abort.is_set()
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert errors == []
    assert (
        "progress.updated",
        {
            "summary": "응답 생성을 중단했습니다.",
            "status": "interrupted",
            "ui_state": "paused",
        },
    ) in emitted


def test_retry_replays_failed_text_as_a_new_handler_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    runtime = _RuntimeSession()

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("retry-session", emit)
    handlers = adapter.handlers()

    with pytest.raises(RuntimeError, match="provider failed"):
        _ = handlers["chat.send"]({"text": "original intent"})
    result = handlers["chat.retry"]({})

    assert runtime.ask_count == 2
    assert result == {"reply": "retried: original intent"}
    assert emitted == [
        ("message.user", {"text": "original intent"}),
        (
            "progress.updated",
            {
                "progress_id": "turn:retry-session",
                "summary": "응답을 준비하고 있습니다.",
                "status": "working",
                "ui_state": "pending",
            },
        ),
        (
            "progress.updated",
            {
                "progress_id": "turn:retry-session",
                "summary": "응답을 완료하지 못했습니다. 잠시 후 다시 시도하세요.",
                "status": "failed",
                "ui_state": "failed",
                "refusal_code": "E_RUNTIME",
                "retryable": True,
            },
        ),
        ("message.user", {"text": "original intent"}),
        (
            "progress.updated",
            {
                "progress_id": "turn:retry-session",
                "summary": "응답을 준비하고 있습니다.",
                "status": "working",
                "ui_state": "pending",
            },
        ),
        (
            "progress.updated",
            {
                "progress_id": "turn:retry-session",
                "summary": "응답을 완료했습니다.",
                "status": "succeeded",
                "ui_state": "succeeded",
            },
        ),
        ("message.assistant.completed", {"text": "retried: original intent"}),
        ("workspace.refreshed", {"approval_requests": [], "work_items": []}),
    ]


def test_chat_send_projects_parent_mcp_start_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    @final
    class McpRuntime:
        cfg: dict[str, object] = {}

        def ask(
            self, text: str, *, on_text: object, on_progress: object = None
        ) -> str:
            del text, on_text
            progress = cast(Callable[[dict], None], on_progress)
            identity = {"item_id": "item-7", "server": "birkin",
                        "name": "office_job_request"}
            progress({"mcp_tool_call": {
                **identity, "event": "item/started", "status": "inProgress"}})
            progress({"mcp_tool_call": {
                **identity, "event": "item/completed", "status": "failed",
                "diagnostic": {
                    "operation_count": 2,
                    "locator_shapes": ["public_docx_positive_index",
                                       "native_or_extra_locator"],
                    "error_code": "PRECONDITION_FAILED",
                    "error_stage": "preview",
                }}})
            progress({"mcp_tool_call": {
                **identity, "event": "item/completed", "status": "unknown"}})
            return "완료"

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, McpRuntime()))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("mcp-progress-session", emit)

    adapter.handlers()["chat.send"]({"text": "업무를 만들어 줘"})

    tools = [(event_type, payload) for event_type, payload in emitted
             if event_type.startswith("tool.")]
    assert [event_type for event_type, _payload in tools] == [
        "tool.started", "tool.failed"]
    assert tools[0][1]["runtime_name"] == "office_job_request"
    assert tools[0][1]["runtime_server"] == "birkin"
    assert tools[0][1]["runtime_item_id"] == "item-7"
    assert tools[0][1]["runtime_tool_status"] == "inProgress"
    assert tools[1][1]["runtime_tool_status"] == "failed"
    assert tools[1][1]["runtime_diagnostic"] == {
        "operation_count": 2,
        "locator_shapes": ["public_docx_positive_index",
                           "native_or_extra_locator"],
        "error_code": "PRECONDITION_FAILED",
        "error_stage": "preview",
    }


def test_chat_send_drops_untrusted_or_non_office_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    @final
    class DiagnosticRuntime:
        cfg: dict[str, object] = {}

        def ask(
            self, text: str, *, on_text: object, on_progress: object = None
        ) -> str:
            del text, on_text
            progress = cast(Callable[[dict], None], on_progress)
            for name, diagnostic in (
                ("office_job_request", {
                    "operation_count": 1,
                    "locator_shapes": [{"SECRET_MARKER": True}],
                    "error_code": ["PRECONDITION_FAILED"],
                }),
                ("work_item_request", {
                    "operation_count": 1,
                    "locator_shapes": ["native_or_extra_locator"],
                    "SECRET_MARKER": "SECRET_MARKER",
                }),
            ):
                progress({"mcp_tool_call": {
                    "item_id": f"item-{name}", "server": "birkin",
                    "name": name, "event": "item/completed",
                    "status": "failed", "diagnostic": diagnostic,
                }})
            return "완료"

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, DiagnosticRuntime()))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("diagnostic-session", emit)

    result = adapter.handlers()["chat.send"]({"text": "진단"})

    assert result["reply"] == "완료"
    assert "runtime_diagnostic" not in str(emitted)
    assert "SECRET_MARKER" not in str(emitted)


def test_non_provider_runtime_failure_emits_bounded_korean_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    runtime = _FailingRuntimeSession(
        ValueError("raw parser detail must remain diagnostic")
    )

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("unexpected-failure-session", emit)

    with pytest.raises(ValueError, match="raw parser detail"):
        _ = adapter.handlers()["chat.send"]({"text": "요청"})

    assert emitted[-1] == (
        "progress.updated",
        {
            "progress_id": "turn:unexpected-failure-session",
            "summary": "응답을 완료하지 못했습니다. 잠시 후 다시 시도하세요.",
            "status": "failed",
            "ui_state": "failed",
            "refusal_code": "E_RUNTIME",
            "retryable": True,
        },
    )
    assert "raw parser detail" not in str(emitted)


@pytest.mark.parametrize(
    (
        "error",
        "expected_summary",
        "expected_code",
        "expected_retryable",
    ),
    [
        (
            LLMError("missing API key", status=401, kind="auth"),
            "API 인증에 실패했습니다. API 키 또는 로그인을 확인한 뒤 다시 시도하세요.",
            "E_PROVIDER_AUTH",
            False,
        ),
        (
            LLMError("payment required", status=402, kind="billing"),
            "결제 상태 때문에 요청을 처리할 수 없습니다. 제공자 결제 설정을 확인하세요.",
            "E_PROVIDER_BILLING",
            False,
        ),
        (
            LLMError("too many requests", status=429, kind="rate_limit"),
            "요청이 너무 많아 잠시 대기해야 합니다. 잠시 후 다시 시도하세요.",
            "E_PROVIDER_RATE_LIMIT",
            True,
        ),
        (
            LLMError("no route", kind="network"),
            "네트워크에 연결할 수 없습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
            "E_PROVIDER_NETWORK",
            True,
        ),
    ],
)
def test_provider_failure_emits_distinct_korean_guidance_and_retryability(
    monkeypatch: pytest.MonkeyPatch,
    error: LLMError,
    expected_summary: str,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    runtime = _FailingRuntimeSession(error)

    def build(
        _cfg: dict[str, object],
        on_event: Callable[[str, dict[str, object]], None] | None = None,
        on_status: Callable[[LLMStatus], None] | None = None,
    ) -> Session:
        del on_event, on_status
        return cast(Session, cast(object, runtime))

    monkeypatch.setattr("birkin.workspace.runtime_adapter.build_session", build)
    adapter = RuntimeWorkspaceAdapter("provider-failure-session", emit)

    with pytest.raises(LLMError):
        _ = adapter.handlers()["chat.send"]({"text": "요청"})

    failure = emitted[-1]
    assert failure == (
        "progress.updated",
        {
            "summary": expected_summary,
            "status": "failed",
            "ui_state": "failed",
            "refusal_code": expected_code,
            "retryable": expected_retryable,
            "provider_kind": error.kind,
            **(
                {"provider_status": error.status}
                if error.status is not None
                else {}
            ),
        },
    )


def _event(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
    return WorkspaceEvent(
        protocol_version=1,
        session_id="test-session",
        cursor=1,
        event_id="event-1",
        type=event_type,
        timestamp="2026-08-20T00:00:00Z",
        actor_id="test:runtime",
        command_id="command-1",
        payload=payload,
    )


def test_approval_answer_event_carries_execution_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return WorkspaceEvent(
            protocol_version=1,
            session_id="receipt-session",
            cursor=1,
            event_id="event-1",
            type=event_type,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="web:test",
            command_id="command-1",
            payload=payload,
        )

    def decide(
        approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        assert on_event is not None
        assert decision == "approve"
        assert reason == ""
        return {
            "outcome": "approved",
            "approval_id": approval_id,
            "receipt": "exit 0: approved",
        }

    monkeypatch.setattr(approval_authority, "decide", decide)
    adapter = RuntimeWorkspaceAdapter("receipt-session", emit)

    result = adapter.handlers()["approval.answer"](
        {"approval_id": "abc123def456", "decision": "approve"}
    )

    assert result == {
        "outcome": "approved",
        "approval_id": "abc123def456",
        "receipt": "exit 0: approved",
    }
    assert emitted == [
        (
            "approval.answered",
            {
                "approval_id": "abc123def456",
                "decision": "approve",
                "outcome": "approved",
                "receipt": "exit 0: approved",
                "result_summary": "승인한 작업을 완료했습니다.",
                "result_code": "approved",
                "ui_state": "succeeded",
            },
        ),
        ("workspace.refreshed", {"approval_requests": [], "work_items": []}),
    ]


def _answering_adapter() -> tuple[
    RuntimeWorkspaceAdapter, list[tuple[str, dict[str, object]]]
]:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return _event(event_type, payload)

    return RuntimeWorkspaceAdapter("answer-session", emit), emitted


def _approval_context(adapter: RuntimeWorkspaceAdapter) -> str:
    return cast(str, getattr(adapter, "_pending_approval_context"))


def _answered_payload(
    emitted: list[tuple[str, dict[str, object]]],
) -> dict[str, object]:
    return next(payload for kind, payload in emitted if kind == "approval.answered")


@pytest.mark.parametrize(
    ("resolution", "status", "ui_state"),
    [
        ("approve", "approved", "succeeded"),
        ("reject", "rejected", "blocked"),
        ("error", "error", "failed"),
    ],
)
def test_an_approval_answered_on_another_surface_reports_what_happened(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    resolution: str,
    status: str,
    ui_state: str,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))

    def execute_action(
        _category: str,
        _payload: dict[str, object],
        cfg: object = None,
        on_event: object = None,
    ) -> str:
        del cfg, on_event
        return "executed"

    monkeypatch.setattr(approvals, "execute_action", execute_action)
    record = store.add_pending(
        category="memory", title="note", description="", payload={}, origin="test"
    )
    approval_id = cast(str, record["id"])
    if resolution == "approve":
        assert approvals.approve(
            approval_id, approved_by="human:telegram:1", approved_via="gateway:telegram"
        )["ok"] is True
    elif resolution == "reject":
        assert approvals.reject(
            approval_id, rejected_by="human:telegram:1", rejected_via="gateway:telegram"
        )["ok"] is True
    else:
        _ = store.resolve_pending(approval_id, "error")
    adapter, emitted = _answering_adapter()

    result = adapter.handlers()["approval.answer"](
        {"approval_id": approval_id, "decision": "approve"}
    )

    assert result == {"outcome": "answered_elsewhere", "approval_id": approval_id}
    context = _approval_context(adapter)
    assert 'outcome="answered_elsewhere"' in context
    if resolution != "error":
        assert "완료하지 못했습니다" not in context
        assert "텔레그램" in context
    answered = _answered_payload(emitted)
    assert answered["result_code"] == "answered_elsewhere"
    assert answered["resolved_status"] == status
    assert answered["ui_state"] == ui_state


def test_an_overwrite_follow_up_is_not_reported_as_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin import approval_text

    def decide(
        approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        del decision, reason, on_event
        return {
            "outcome": "follow_up_required",
            "approval_id": approval_id,
            "follow_up_approval_id": "fedcba987654",
            "question": "overwrite?",
        }

    monkeypatch.setattr(approval_authority, "decide", decide)
    adapter, emitted = _answering_adapter()

    _ = adapter.handlers()["approval.answer"](
        {"approval_id": "abc123def456", "decision": "approve"}
    )

    assert approval_text.FOLLOW_UP in _approval_context(adapter)
    answered = _answered_payload(emitted)
    assert answered["result_code"] == "follow_up_required"
    # The follow-up card is what still needs the user, so the card it
    # replaced ends as a failure, as its canonical projection says.
    assert answered["ui_state"] == "failed"


def test_a_waiting_workflow_card_leaves_the_attention_to_its_question(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from birkin.moirai import outcome as moirai_outcome
    from birkin.workspace.approval_projection import approval_item

    # Given: an approved workflow that stopped at a question of its own.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    record = store.add_pending(
        category="moirai", title="워크플로", description="", payload={}, origin="test",
    )
    waiting = moirai_outcome.render({"status": "waiting_input", "run_id": "r8"}, name="hard")

    def decide(
        approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        del decision, reason, on_event
        _ = store.resolve_pending(approval_id, "approved", details={"action_receipt": waiting})
        return {"outcome": "approved", "approval_id": approval_id, "receipt": waiting}

    monkeypatch.setattr(approval_authority, "decide", decide)
    adapter, emitted = _answering_adapter()

    # When: the approval is answered.
    _ = adapter.handlers()["approval.answer"](
        {"approval_id": cast(str, record["id"]), "decision": "approve"}
    )

    # Then: the live card and its canonical projection agree that it is
    # paused, not a second card asking for the user.
    answered = _answered_payload(emitted)
    resolved = store.get_pending(cast(str, record["id"]))
    assert resolved is not None
    assert answered["result_code"] == "workflow_waiting"
    assert answered["ui_state"] == approval_item(resolved)["ui_state"] == "paused"
    assert "질문에 대한 답을 기다리고" in _approval_context(adapter)


def test_an_approved_command_that_failed_is_not_reported_as_completed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    record = store.add_pending(
        category="shell", title="run", description="",
        payload={"command": "false"}, origin="test",
    )

    def decide(
        approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        del decision, reason, on_event
        return {"outcome": "approved", "approval_id": approval_id, "receipt": "[exit 2] boom"}

    monkeypatch.setattr(approval_authority, "decide", decide)
    adapter, emitted = _answering_adapter()

    _ = adapter.handlers()["approval.answer"](
        {"approval_id": cast(str, record["id"]), "decision": "approve"}
    )

    context = _approval_context(adapter)
    assert "완료되었습니다" not in context
    assert "종료 코드 2" in context
    answered = _answered_payload(emitted)
    assert answered["result_code"] == "command_failed"
    assert answered["ui_state"] == "failed"
    events = (
        _event("approval.requested", {"approval_id": record["id"]}),
        _event("approval.answered", answered),
    )
    (item,) = next(
        panel.items
        for panel in reduce_snapshot("test-session", events).panels
        if panel.key == "approvals"
    )
    assert item["ui_state"] == "failed"


def test_only_a_moirai_worker_failure_is_answered_as_its_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from birkin.moirai import outcome as moirai_outcome
    from birkin.worker_request import DaedalusShow, approval_payload

    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    record = store.add_pending(
        category="worker", title="show", description="",
        payload=approval_payload(DaedalusShow("notes")), origin="test",
    )
    waiting = moirai_outcome.render({"status": "waiting_input", "run_id": "r9"})

    def decide(
        approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        del decision, reason, on_event
        return {
            "outcome": "rejected_by_authority",
            "approval_id": approval_id,
            "error": f"action failed: worker exited with status 1: {waiting}",
        }

    monkeypatch.setattr(approval_authority, "decide", decide)
    adapter, emitted = _answering_adapter()

    _ = adapter.handlers()["approval.answer"](
        {"approval_id": cast(str, record["id"]), "decision": "approve"}
    )

    assert _answered_payload(emitted)["result_code"] == "E_APPROVAL_ACTION_FAILED"


def test_chat_completion_refreshes_provider_created_work_item_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    emitted: list[tuple[str, dict[str, object]]] = []
    runtime = _CapturingRuntimeSession()
    adapter = RuntimeWorkspaceAdapter(
        "refresh-session",
        lambda event_type, payload: (
            emitted.append((event_type, payload)) or _event(event_type, payload)
        ),
        workspace_root=tmp_path / "workspace",
    )
    setattr(adapter, "_session", cast(Session, cast(object, runtime)))
    pending = store.add_pending(
        category="work_item",
        title="후속 업무 생성 확인",
        description="업무: 새 검증 업무 · 담당자: 담당자 · 기한: 미정 · 원본: 없음",
        payload={"action": "create", "title": "새 검증 업무"},
        origin="conversation",
    )

    adapter.handlers()["chat.send"]({"text": "후속 업무를 제안해 줘"})

    refresh = next(payload for event_type, payload in emitted if event_type == "workspace.refreshed")
    approval = next(
        item for item in cast("list[dict[str, object]]", refresh["approval_requests"])
        if item["id"] == pending["id"]
    )
    assert approval["description"] == pending["description"]
    assert approval["action"] == "create"


def test_native_complete_request_projects_canonical_action(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    item = cast(dict[str, object], json.loads(work_items.apply_approved({
        "action": "create", "title": "키보드 완료 확인",
    }))["items"][0])
    emitted: list[tuple[str, dict[str, object]]] = []
    adapter = RuntimeWorkspaceAdapter(
        "complete-session",
        lambda event_type, payload: (
            emitted.append((event_type, payload)) or _event(event_type, payload)
        ),
        workspace_root=tmp_path / "workspace",
    )

    adapter.handlers()["work_item.request"]({
        "action": "complete", "id": item["id"],
    })

    requested = next(payload for event_type, payload in emitted if event_type == "approval.requested")
    assert requested["action"] == "complete"
    snapshot = WorkspaceService(
        root=tmp_path / "bridge",
        session_id="complete-session",
        handlers={},
    ).snapshot()
    approvals_panel = next(panel for panel in snapshot.panels if panel.key == "approvals")
    canonical = next(
        item
        for item in approvals_panel.items
        if item["id"] == requested["approval_id"]
    )
    assert requested["sealed"] is canonical["sealed"] is False


def test_approval_answer_summary_is_injected_into_next_agent_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _CapturingRuntimeSession()
    adapter = RuntimeWorkspaceAdapter(
        "approval-context-session",
        _event,
        workspace_root=tmp_path / "workspace",
    )
    setattr(adapter, "_session", cast(Session, cast(object, runtime)))

    def approved_decide(
        _approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        assert on_event is not None
        assert decision == "approve"
        assert reason == ""
        return {
            "outcome": "approved",
            "receipt": '{"job_id":"job-context","outcome":"saved"}',
        }

    monkeypatch.setattr(
        approval_authority,
        "decide",
        approved_decide,
    )

    _ = adapter.handlers()["approval.answer"](
        {"approval_id": "approval-context", "decision": "approve"}
    )
    first = adapter.handlers()["chat.send"]({"text": "결과를 알려줘"})
    second = adapter.handlers()["chat.send"]({"text": "다음 질문"})

    assert "<approval-outcome" in runtime.prompts[0]
    assert 'lang="ko"' in runtime.prompts[0]
    assert 'approval_id="approval-context"' in runtime.prompts[0]
    assert 'outcome="approved"' in runtime.prompts[0]
    assert "결과를 알려줘" in runtime.prompts[0]
    assert "<approval-outcome" not in runtime.prompts[1]
    assert first["reply"] == "승인된 작업이 완료되었습니다."
    assert second["reply"] == "agent saw: 다음 질문"


def test_failed_approval_summary_is_injected_into_next_agent_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _CapturingRuntimeSession()
    adapter = RuntimeWorkspaceAdapter(
        "approval-failure-context-session",
        _event,
        workspace_root=tmp_path / "workspace",
    )
    setattr(adapter, "_session", cast(Session, cast(object, runtime)))

    def failed_decide(
        _approval_id: str,
        *,
        decision: str,
        reason: str = "",
        on_event: object = None,
    ) -> dict[str, object]:
        assert on_event is not None
        assert decision == "approve"
        assert reason == ""
        return {
            "outcome": "execution_failed",
            "error": "export denied",
        }

    monkeypatch.setattr(
        approval_authority,
        "decide",
        failed_decide,
    )

    _ = adapter.handlers()["approval.answer"](
        {"approval_id": "approval-failed", "decision": "approve"}
    )
    response = adapter.handlers()["chat.send"]({"text": "실패 원인을 알려줘"})

    assert 'approval_id="approval-failed"' in runtime.prompts[0]
    assert 'outcome="execution_failed"' in runtime.prompts[0]
    assert 'lang="ko"' in runtime.prompts[0]
    assert "export denied" in runtime.prompts[0]
    assert response["reply"] == "승인된 작업을 완료하지 못했습니다."


def _runtime_adapter() -> tuple[
    RuntimeWorkspaceAdapter,
    list[tuple[str, dict[str, object]]],
]:
    emitted: list[tuple[str, dict[str, object]]] = []

    def emit(
        event_type: str,
        payload: dict[str, object],
    ) -> WorkspaceEvent:
        emitted.append((event_type, payload))
        return WorkspaceEvent(
            protocol_version=1,
            session_id="receipt-session",
            cursor=1,
            event_id="event-1",
            type=event_type,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="web:test",
            command_id="command-1",
            payload=payload,
        )

    return RuntimeWorkspaceAdapter("receipt-session", emit), emitted


def test_tool_end_error_distinguishable_from_success() -> None:
    adapter, emitted = _runtime_adapter()

    adapter.runtime_event(
        "tool_end",
        {"name": "grep", "is_error": False, "content": "ok"},
    )
    adapter.runtime_event(
        "tool_end",
        {"name": "grep", "is_error": True, "content": "boom"},
    )

    assert [event_type for event_type, _payload in emitted] == [
        "tool.completed",
        "tool.failed",
    ]
    assert emitted[0][1]["state"] == "completed"
    assert emitted[1][1]["state"] == "failed"
    assert emitted[0][1] != emitted[1][1]


def test_aborted_tool_maps_failed() -> None:
    adapter, emitted = _runtime_adapter()

    adapter.runtime_event(
        "tool_end",
        {"content": "aborted", "is_error": True},
    )

    assert emitted[0][0] == "tool.failed"
    assert emitted[0][1]["state"] == "failed"


def test_all_emitted_states_in_uistate_vocabulary() -> None:
    adapter, emitted = _runtime_adapter()
    events = (
        "tool_start",
        "tool_end",
        "subagent.start",
        "subagent.done",
        "compact",
        "steer",
    )

    for event in events:
        adapter.runtime_event(event, {})
        adapter.runtime_event(event, {"is_error": True})
    adapter.runtime_event("no_such_event", {})

    for _event_type, payload in emitted:
        assert payload["state"] in uistate.UI_STATES


@pytest.mark.parametrize(
    ("payload", "expected_event_type", "expected_state"),
    [
        ({}, "tool.completed", "completed"),
        ({"is_error": None}, "tool.completed", "completed"),
        ({"is_error": 0}, "tool.completed", "completed"),
        ({"is_error": ""}, "tool.completed", "completed"),
        ({"is_error": False}, "tool.completed", "completed"),
        ({"is_error": True}, "tool.failed", "failed"),
        ({"is_error": 1}, "tool.failed", "failed"),
        ({"is_error": "false"}, "tool.failed", "failed"),
        ({"is_error": ["error"]}, "tool.failed", "failed"),
    ],
)
def test_tool_end_is_error_uses_truthiness(
    payload: dict[str, object],
    expected_event_type: str,
    expected_state: str,
) -> None:
    adapter, emitted = _runtime_adapter()

    adapter.runtime_event("tool_end", payload)

    assert emitted[0][0] == expected_event_type
    assert emitted[0][1]["state"] == expected_state


def test_runtime_event_hides_tool_identifier_behind_korean_summary() -> None:
    adapter, emitted = _runtime_adapter()

    adapter.runtime_event("tool_start", {"name": "shell_exec"})

    payload = emitted[0][1]
    assert payload["summary"] == "도구 실행을 시작했습니다."
    assert payload["runtime_name"] == "shell_exec"
    assert "shell_exec" not in str(payload["summary"])


def test_event_type_table_pin() -> None:
    """Reverse the earlier pin after tool.failed consumer support was verified.

    Support exists in snapshot.py, workspace_terminal.py, and index.html.
    """
    adapter, emitted = _runtime_adapter()
    runtime_events: tuple[tuple[str, dict[str, object]], ...] = (
        ("tool_start", {}),
        ("tool_end", {}),
        ("tool_end", {"is_error": True}),
        ("subagent.start", {}),
        ("subagent.done", {}),
        ("compact", {}),
        ("steer", {}),
        ("no_such_event", {}),
    )

    for event, payload in runtime_events:
        adapter.runtime_event(event, payload)

    assert [event_type for event_type, _payload in emitted] == [
        "tool.started",
        "tool.completed",
        "tool.failed",
        "progress.updated",
        "progress.updated",
        "progress.updated",
        "progress.updated",
        "progress.updated",
    ]


_AGENT_RUN_ID = "abc123def456"


def _agent_lifecycle(adapter: RuntimeWorkspaceAdapter) -> None:
    adapter.runtime_event(
        "subagent.start",
        {
            "task": "분기 매출 시트 분석",
            "id": _AGENT_RUN_ID,
            "agent": "sheet-analyst",
            "agent_title": "스프레드시트 분석가",
        },
    )
    adapter.runtime_event(
        "subagent.done",
        {
            "chars": 12,
            "id": _AGENT_RUN_ID,
            "agent": "sheet-analyst",
            "agent_title": "스프레드시트 분석가",
        },
    )


def test_summoned_agent_lifecycle_is_named_korean_activity() -> None:
    adapter, emitted = _runtime_adapter()

    _agent_lifecycle(adapter)

    assert [event_type for event_type, _payload in emitted] == [
        "progress.updated",
        "progress.updated",
    ]
    (_start_type, start), (_done_type, done) = emitted
    assert start["summary"] == "스프레드시트 분석가 에이전트가 작업을 시작했습니다."
    assert done["summary"] == "스프레드시트 분석가 에이전트가 작업을 마쳤습니다."
    assert [start["ui_state"], done["ui_state"]] == ["running", "succeeded"]
    for payload in (start, done):
        assert payload["progress_id"] == f"agent-run:{_AGENT_RUN_ID}"
        assert payload["agent_run_id"] == _AGENT_RUN_ID
        assert payload["state"] in uistate.UI_STATES
        assert payload["status"] == payload["state"]
        assert "sheet-analyst" not in str(payload)
        assert "분기 매출" not in str(payload)


def test_failed_agent_run_and_research_step_report_failure() -> None:
    adapter, emitted = _runtime_adapter()

    adapter.runtime_event(
        "subagent.done",
        {"chars": 0, "id": _AGENT_RUN_ID, "is_error": True},
    )
    adapter.runtime_event("subagent.start", {"task": "[collect] 시장 조사"})
    adapter.runtime_event("subagent.done", {"error": "Traceback boom"})
    # A step that raised TimeoutError() carries an empty error text.
    adapter.runtime_event("subagent.done", {"error": ""})

    (_agent_type, agent), (_start_type, start), (_step_type, step), (
        _silent_type, silent) = emitted
    assert agent["summary"] == "하위 에이전트가 작업을 마치지 못했습니다."
    assert agent["ui_state"] == agent["state"] == "failed"
    assert start["summary"] == "하위 작업을 시작했습니다."
    assert start["progress_id"] == "runtime:subagent.start:operation"
    assert "agent_run_id" not in start
    assert "시장 조사" not in str(start)
    assert step["summary"] == "하위 작업을 완료하지 못했습니다."
    assert step["ui_state"] == step["state"] == "failed"
    assert "boom" not in str(step)
    assert silent["summary"] == "하위 작업을 완료하지 못했습니다."
    assert silent["ui_state"] == silent["state"] == "failed"


def test_child_internal_events_are_not_journaled() -> None:
    adapter, emitted = _runtime_adapter()

    adapter.runtime_event(
        "subagent.tool_start",
        {"name": "analyze_workbook", "input": {"path": "/Users/me/a.xlsx"}},
    )
    adapter.runtime_event(
        "subagent.tool_end",
        {"name": "analyze_workbook", "is_error": False},
    )
    adapter.runtime_event("subagent.subagent.start", {"id": _AGENT_RUN_ID})

    assert emitted == []


def test_agent_activity_reduces_into_activity_not_work_items() -> None:
    events: list[WorkspaceEvent] = []

    def emit(event_type: str, payload: dict[str, object]) -> WorkspaceEvent:
        event = WorkspaceEvent(
            protocol_version=1,
            session_id="agent-session",
            cursor=len(events) + 1,
            event_id=f"event-{len(events) + 1}",
            type=event_type,
            timestamp="2026-09-26T00:00:00Z",
            actor_id="native:test",
            command_id="command-1",
            payload=payload,
        )
        events.append(event)
        return event

    adapter = RuntimeWorkspaceAdapter("agent-session", emit)
    _agent_lifecycle(adapter)

    panels = {
        panel.key: panel.items
        for panel in reduce_snapshot("agent-session", tuple(events)).panels
    }
    assert panels["tasks_runs"] == ()
    assert [
        (item["summary"], item["ui_state"]) for item in panels["activity_logs"]
    ] == [
        ("스프레드시트 분석가 에이전트가 작업을 시작했습니다.", "running"),
        ("스프레드시트 분석가 에이전트가 작업을 마쳤습니다.", "succeeded"),
    ]
    for event in events:
        public = public_workspace_event(event)["payload"]
        assert isinstance(public, dict)
        assert cast(dict[str, object], public)["summary"] == event.payload["summary"]


def test_runtime_adapter_registers_the_working_memory_command(tmp_path: Path) -> None:
    """Given the production runtime adapter, When its handlers are read, Then
    Working Memory mutation is registered so the shell can advertise it."""
    adapter = RuntimeWorkspaceAdapter(
        "memory-session", _event, workspace_root=tmp_path / "workspace"
    )

    assert "memory.write" in adapter.handlers()
