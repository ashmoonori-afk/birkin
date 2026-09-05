"""Machine-consumed contracts for the responsive chat-first web workspace."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parents[1]
    / "birkin"
    / "web"
    / "static"
    / "index.html"
)

PANEL_KEYS = {
    "tasks_runs",
    "approvals",
    "files_evidence",
    "sessions_history",
    "activity_logs",
    "cron",
    "memory_skills",
    "checkpoints_restore",
    "computer_use",
    "settings_status",
}


class _WorkspaceHTML:
    def __init__(self) -> None:
        self.test_ids: set[str] = set()
        self.panel_keys: set[str] = set()
        self.ids: set[str] = set()
        self.attributes: list[dict[str, str | None]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del tag
        values = dict(attrs)
        self.attributes.append(values)
        test_id = values.get("data-testid")
        if test_id:
            self.test_ids.add(test_id)
        panel = values.get("data-panel")
        if panel:
            self.panel_keys.add(panel)
        element_id = values.get("id")
        if element_id:
            self.ids.add(element_id)


def _document() -> tuple[str, _WorkspaceHTML]:
    source = HTML_PATH.read_text(encoding="utf-8")
    document = _WorkspaceHTML()
    parser = HTMLParser()
    parser.handle_starttag = document.handle_starttag
    parser.feed(source)
    return source, document


def test_web_workspace_has_chat_primary_landmarks_and_all_panels() -> None:
    _, document = _document()

    assert {
        "workspace-shell",
        "workspace-transcript",
        "workspace-composer",
        "workspace-send",
        "workspace-interrupt",
        "workspace-resume",
        "workspace-panel-tabs",
        "workspace-panel",
        "workspace-connection",
    } <= document.test_ids
    assert document.panel_keys == PANEL_KEYS


def test_web_workspace_consumes_shared_session_event_command_routes() -> None:
    source, _ = _document()

    assert "/api/workspace/sessions" in source
    assert "/snapshot" in source
    assert "/events" in source
    assert "/commands" in source
    assert "EventSource" in source
    assert "command_id" in source
    assert "expected_cursor" in source
    assert "chat.send" in source
    assert "chat.interrupt" in source
    assert '"computer.updated"' in source
    assert "refreshWorkspaceSnapshot" in source
    assert "queueMicrotask(connectEvents)" not in source
    assert "reconnectAttempts" in source
    assert "setTimeout(connectEvents" in source
    assert "followsOutput" in source
    assert "if (followsOutput) transcript.scrollTop" in source
    assert "legacyItems.map" in source
    assert "const combined = {...previous, ...item};" in source
    assert "approval.requested_by" in source
    assert "복원 승인 요청" in source
    assert "/api/checkpoints/${encodeURIComponent(item.id)}/restore" in source
    assert "workspace-question-answer" in source
    assert 'sendCommand("question.answer"' in source
    assert "복원 범위" in source
    assert "mode: mode.value" in source
    assert "session_id: state.sessionId" in source
    assert "chat.resume" in source


def test_web_workspace_exposes_accessible_live_and_focus_contracts() -> None:
    _, document = _document()

    assert any(attrs.get("aria-live") == "polite" for attrs in document.attributes)
    assert any(attrs.get("role") == "log" for attrs in document.attributes)
    assert any(attrs.get("role") == "tablist" for attrs in document.attributes)
    assert any(attrs.get("aria-controls") for attrs in document.attributes)
    assert any(attrs.get("aria-label") for attrs in document.attributes)


def test_web_workspace_does_not_inject_event_text_as_html() -> None:
    source, _ = _document()

    assert ".textContent" in source
    assert "insertAdjacentHTML" not in source
    assert ".innerHTML =" not in source


def test_web_workspace_restores_durable_conversation_and_panel_items() -> None:
    source, _ = _document()

    assert "snapshot.conversation || []" in source
    assert "message.kind" in source
    assert "panel?.items || []" in source
    assert "refreshWorkspaceSnapshot" in source
    assert "response.accepted_cursor" not in source


def test_web_workspace_renders_state_and_explicit_approval_actions() -> None:
    source, _ = _document()

    assert "statePresentations" in source
    assert 'unknown: ["?", "불명"]' in source
    assert "statePresentations.unknown" in source
    assert "attentionRanks" in source
    assert "expected_impact" in source
    assert "item.category || record.category" in source
    assert "승인 실행" in source
    assert "submitApproval" in source
    assert "window.confirm" not in source


def test_web_workspace_prefers_workspace_approval_receipts() -> None:
    source, _ = _document()

    assert "payload.receipt" in source
    assert "recentReceipts.set(approvalId" in source


def test_web_workspace_reconciles_progress_by_machine_identity() -> None:
    source, _ = _document()

    assert '"progress.updated"' in source
    assert "function renderProgress(payload, eventId)" in source
    assert "article.dataset.progressId = progressId" in source
    assert "article.dataset.officePhase = String(payload.office_phase)" in source
    assert "article.dataset.uiState = uiState" in source


def test_web_workspace_refreshes_external_approvals_without_duplicate_pollers() -> None:
    source, _ = _document()

    assert "const APPROVAL_REFRESH_INTERVAL_MS = 30_000;" in source
    assert "approvalRefreshTimer: null" in source
    assert "clearInterval(state.approvalRefreshTimer)" in source
    assert "state.approvalRefreshTimer = setInterval(" in source
    assert "}, APPROVAL_REFRESH_INTERVAL_MS);" in source
    assert "startApprovalRefreshPolling();" in source
    assert "async function refreshApprovals()" in source
    assert "refreshApprovals().catch" in source
    assert '"approval.requested"' in source
    assert "refreshWorkspaceSnapshot(), refreshApprovals()" in source


def test_web_workspace_counts_merged_approvals_and_announces_increases() -> None:
    source, _ = _document()

    assert "approvalCount: null" in source
    assert "const approvalItems = mergePanelItems(" in source
    assert "state.approvalCount = waiting;" in source
    assert "waiting > previousWaiting" in source


def test_web_workspace_folds_raw_receipt_behind_korean_summary() -> None:
    source, _ = _document()

    assert 'document.createElement("details")' in source
    assert "영수증 세부 정보 보기" in source
    assert "승인한 작업을 실행했습니다." in source
    assert 'receiptText.className = "detail-output"' in source
    assert "JSON.stringify(receipt, null, 2)" in source
    assert "Action executed:" not in source


def test_web_workspace_uses_korean_decision_and_progress_copy() -> None:
    source, _ = _document()

    for removed in (
        "The requested action will not run.",
        "View diff",
        "No diff available:",
        "Preview diff",
        "Alternate command (JSON string array)",
        "Run alternate branch",
        "Diff preview failed:",
        "Background run detail",
        "Run detail loading…",
        "No progress events yet.",
        "Run detail unavailable:",
        "요청 payload 보기",
        "Python authority",
        "item.title || item.key || item.id",
        "item.summary || item.detail || item.id",
        "run.task || run.id",
        "대체 분기 실행 완료: ${result.stdout",
        "오류: ${String(payload.error || event.type)}",
        "announce(error.message)",
        "${error.message}",
        "status.textContent = error.message",
    ):
        assert removed not in source
    for shipped in (
        "요청한 동작은 실행되지 않습니다.",
        "변경 내용 보기",
        "차이 미리보기",
        "대체 명령(JSON 문자열 배열)",
        "격리된 대체 분기 실행",
        "백그라운드 실행 세부 정보",
        "진행 이벤트가 아직 없습니다.",
        "요청 데이터 보기",
        "권한 실행 계층",
        "표시 이름 없는 항목",
        "질문 내용을 확인할 수 없습니다.",
        "이름 없는 백그라운드 실행",
        "도구 실행을 시작했습니다.",
        "대체 분기 실행을 완료했습니다.",
        "대체 분기 출력 보기",
        "승인 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요.",
        "요청을 완료하지 못했습니다. 잠시 후 다시 시도하세요.",
        "승인 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.",
        "메시지를 전송하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.",
        "응답 중단 요청에 실패했습니다. 잠시 후 다시 시도하세요.",
    ):
        assert shipped in source


def test_web_workspace_keeps_localized_controls_accessible() -> None:
    source, _ = _document()

    assert "textarea::placeholder" in source
    assert "summary:focus-visible" in source
    assert ".panel-more {\n    display: grid;" in source
    assert "input:focus-visible, select:focus-visible" in source
    assert "animation-iteration-count: 1" in source
    assert "!event.isComposing && event.keyCode !== 229" in source
    assert 'panelTabs.addEventListener("keydown"' in source
    assert 'entry.tabIndex = selected ? 0 : -1' in source


def test_checkpoint_restore_success_is_not_reclassified_by_panel_refresh() -> None:
    source, _ = _document()

    assert 'optionalLegacyApi("/api/status", {})' in source
    assert 'optionalLegacyApi("/api/jobs", [])' in source
    assert 'optionalLegacyApi("/api/runs", [])' in source
    assert 'optionalLegacyApi("/api/agent-runs", {runs: []})' in source
    assert "console.warn(`optional legacy panel unavailable: ${path}`" in source
    assert "await Promise.all([" in source
    assert "refreshWorkspaceSnapshot()," in source
    assert "refreshLegacyPanels()," in source
    assert "catch (refreshError)" in source
    assert "checkpoint panels failed after restore approval request" in source


def test_web_workspace_releases_failed_approval_for_retry() -> None:
    source, _ = _document()
    failed_start = source.index('event.type === "command.failed"')
    answered_start = source.index(
        'event.type === "approval.answered"',
        failed_start,
    )
    failed_branch = source[failed_start:answered_start]

    assert ".get(commandId)" in failed_branch
    assert "busyApprovalIds.delete(approvalId)" in failed_branch
    assert "renderPanel()" in failed_branch


def test_web_workspace_refresh_stays_within_server_worker_budget() -> None:
    source, _ = _document()

    assert "const [status, jobs, runs] = await Promise.all([" in source
    assert "const [status, jobs, runs, agentRuns] = await Promise.all([" not in source


def test_web_workspace_bounds_long_approval_receipts() -> None:
    source, _ = _document()
    style_start = source.index(".detail-output {")
    style_end = source.index("}", style_start)
    detail_output_style = source[style_start:style_end]

    assert 'const receiptDetails = document.createElement("details")' in source
    assert "receiptDetails.append(receiptSummary, receiptText)" in source
    assert 'receiptText.className = "detail-output"' in source
    assert "overflow-wrap: anywhere" in detail_output_style


def test_web_workspace_counts_only_pending_approvals() -> None:
    source, _ = _document()
    start = source.index("function approvalIsActionable")
    end = source.index("}", start)
    actionable = source[start:end]

    assert 'return status === "pending";' in actionable
    assert "attentionFor(item.ui_state)" not in actionable


def test_web_workspace_keeps_selected_completed_approval() -> None:
    source, _ = _document()

    assert "canonicalSelectionExists" in source
    assert "&& !canonicalSelectionExists" in source
