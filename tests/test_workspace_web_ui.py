"""Machine-consumed contracts for the responsive chat-first web workspace."""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
from typing import cast

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


def test_web_workspace_safely_renders_reports_and_links() -> None:
    source, _ = _document()

    assert "function renderSafeMarkdown(target, source)" in source
    assert 'document.createElement("table")' in source
    assert 'document.createElement("code")' in source
    assert 'document.createElement(`h${heading[1].length}`)' in source
    assert '["http:", "https:"].includes(url.protocol)' in source
    assert 'link.rel = "noopener noreferrer"' in source
    assert "markdownLabel || candidate" in source
    assert "target.replaceChildren()" in source
    assert "DOMParser" not in source

    start = source.index("function safeHttpURL")
    end = source.index("\n}\n", start) + 2
    script = source[start:end] + "\nconsole.log(JSON.stringify([" \
        "safeHttpURL('https://example.test/a%20b')," \
        "safeHttpURL('http://example.test/path')," \
        "safeHttpURL('javascript:alert(1)')," \
        "safeHttpURL('data:text/html,attack')]))"
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == (
        '["https://example.test/a%20b","http://example.test/path",null,null]'
    )


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
    assert "panel.inert = hidden" in source
    assert 'panel.setAttribute("aria-hidden", String(hidden))' in source
    assert 'setAttribute("aria-expanded", String(open))' in source
    assert 'streamStatus.textContent = "Birkin의 응답이 완료되었습니다."' in source


def test_web_workspace_exposes_primary_work_navigation_and_named_overflow() -> None:
    source, document = _document()

    assert {"conversation", "research", "documents", "approvals"} <= {
        attrs.get("data-work-view")
        for attrs in document.attributes
        if attrs.get("data-work-view")
    }
    assert 'aria-label="주요 업무"' in source
    assert 'id="recent-work"' in source
    assert 'id="new-work"' in source
    assert 'aria-label="부가 패널 보기"' in source
    assert "function activateWorkView(view, trigger)" in source
    assert "startBootstrap(session.session_id)" in source


def test_web_workspace_discards_stale_session_bootstrap_results() -> None:
    source, _ = _document()

    assert "const generation = ++state.bootstrapGeneration" in source
    assert source.count("generation !== state.bootstrapGeneration") >= 4
    assert "state.source.close()" in source
    assert "refreshLegacyPanels(generation)" in source
    assert "expectedGeneration === state.bootstrapGeneration" in source


def test_web_workspace_isolates_snapshots_events_and_commands_during_switch() -> None:
    source, _ = _document()

    assert "sessionId !== state.sessionId" in source
    assert "state.source !== source || generation !== state.bootstrapGeneration" in source
    assert "source.addEventListener(eventType, handleCurrentEvent)" in source
    assert "clearTimeout(state.reconnectTimer)" in source
    assert "clearInterval(state.approvalRefreshTimer)" in source
    assert "state.switchingSession = true" in source
    assert "state.switchingSession = false" in source
    assert "if (state.switchingSession)" in source
    assert "업무를 전환하는 중입니다. 입력을 유지한 채 잠시 후 다시 시도하세요." in source

    failure_start = source.index("function handleBootstrapFailure")
    failure_end = source.index("\n}", failure_start)
    assert "switchingSession = false" not in source[failure_start:failure_end]


def test_failed_session_switch_cannot_post_to_previous_session() -> None:
    source, _ = _document()
    start = source.index("async function sendCommand")
    end = source.index("async function optionalLegacyApi", start)
    send_command = source[start:end]
    script = """
const state = {switchingSession: true, sessionId: "previous", cursor: 1};
let posts = 0;
const api = async () => { posts += 1; };
""" + send_command + """
sendCommand("chat.send", {text: "keep"}).catch((error) => {
  console.log(JSON.stringify({status: error.status, posts}));
});
"""

    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == '{"status":423,"posts":0}'


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


def _function_source(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    if source[max(0, start - 6):start] == "async ":
        start -= 6
    end = source.index("\n}\n", start) + 2
    return source[start:end]


def _node_json(script: str) -> object:
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True,
    )
    return cast(object, json.loads(result.stdout))


def test_agent_run_controls_follow_server_controls() -> None:
    source, _ = _document()
    script = _function_source(source, "agentRunControls") + """
console.log(JSON.stringify([
  agentRunControls({controls: ["resume"]}),
  agentRunControls({controls: ["steer", "abort", "bogus"]}),
  agentRunControls({}),
]));
"""

    assert _node_json(script) == [
        [{"action": "resume", "label": "재개"}],
        [
            {"action": "steer", "label": "조정 보내기"},
            {"action": "abort", "label": "일시 중지"},
        ],
        [],
    ]
    assert 'run.status === "blocked"' not in source
    assert "agentRunControls(run)" in source
    assert "busyRunIds.has(run.id)" in source
    assert "일시 중지" in source
    assert "보낼 조정 지시를 입력하세요." in source
    assert 'draft.setAttribute("aria-invalid", "true")' in source
    script = """
const busyRunIds = new Set();
const state = {steerDrafts: new Map([["r1", "draft"]]), selectedId: null};
const panelBody = {querySelectorAll: () => []};
const announced = [];
const calls = [];
let refreshes = 0;
let renders = 0;
let reply = null;
const announce = (text) => announced.push(text);
const api = async (path, options) => {
  calls.push(JSON.parse(options.body).action);
  await new Promise((resolve) => setTimeout(resolve, 5));
  if (reply) throw Object.assign(new Error(String(reply)), {status: reply});
  return {};
};
const refreshLegacyPanels = async () => { refreshes += 1; };
const renderPanel = () => { renders += 1; };
console.error = () => {};
""" + _function_source(source, "controlAgentRun") + """
(async () => {
  await Promise.all([
    controlAgentRun("r1", "steer", "focus"),
    controlAgentRun("r1", "steer", "focus"),
  ]);
  const drafted = state.steerDrafts.has("r1");
  reply = 409;
  await controlAgentRun("r1", "abort");
  reply = 404;
  await controlAgentRun("r1", "resume");
  reply = 500;
  await controlAgentRun("r1", "abort");
  console.log(JSON.stringify({
    calls, drafted, refreshes, renders, announced,
    busy: busyRunIds.size, selected: state.selectedId,
  }));
})();
"""

    assert _node_json(script) == {
        "calls": ["steer", "abort", "resume", "abort"],
        "drafted": False,
        "refreshes": 3,
        "renders": 1,
        "announced": [
            "조정 지시를 보냈습니다. 다음 단계에서 반영됩니다.",
            ("실행 상태가 이미 바뀌어 요청을 적용하지 않았습니다. "
             + "최신 상태를 다시 불러왔습니다."),
            "실행 기록을 찾을 수 없습니다. 목록을 새로 고쳤습니다.",
            "실행 제어 요청에 실패했습니다. 잠시 후 다시 시도하세요.",
        ],
        "busy": 0,
        "selected": "r1",
    }


def test_agent_run_rows_use_korean_summary() -> None:
    source, _ = _document()
    helpers = "".join(
        _function_source(source, name)
        for name in ("formatDuration", "agentLabel", "resultPreview",
                     "agentRunSummaryText")
    )
    script = helpers + """
console.log(JSON.stringify([
  [0, 45, 180, 3900, 7200, 172800, -1, null, "x"].map(formatDuration),
  agentLabel({agent: "my-bot", agent_title: "내 봇", agent_source: "user"}),
  agentLabel({agent: "ghost"}),
  agentLabel({}),
  agentRunSummaryText({
    agent: "researcher", agent_title: "리서처", agent_source: "builtin",
    runtime_status: "done", terminal: true, elapsed_seconds: 300,
    result: "\\n# 결론: A가 더 저렴합니다.\\n근거",
  }),
  agentRunSummaryText({
    runtime_status: "done", terminal: true, result: "(subagent returned no text)",
  }),
  agentRunSummaryText({
    runtime_status: "error", terminal: true, result: "RuntimeError: boom",
  }),
  agentRunSummaryText({
    runtime_status: "stale", terminal: true, heartbeat_age: 600,
  }),
  agentRunSummaryText({
    agent: "report-writer", agent_title: "보고서 작성가", agent_source: "builtin",
    runtime_status: "running", terminal: false, elapsed_seconds: 125,
    control_state: "blocked", pending_approvals: 1,
  }),
]));
"""

    results = _node_json(script)
    assert results == [
        ["0초", "45초", "3분", "1시간 5분", "2시간", "2일", "", "", ""],
        "내 봇 (사용자 정의)",
        "ghost",
        "",
        "리서처 · 5분 소요 · 결론: A가 더 저렴합니다.",
        "결과 텍스트가 없습니다.",
        "실행에 실패했습니다. 세부 정보에서 원인을 확인하세요.",
        "응답이 끊겼습니다 · 마지막 신호 10분 전",
        "보고서 작성가 · 시작 후 2분 · 일시 중지됨 · 승인 대기 1건",
    ]
    assert "RuntimeError" not in json.dumps(results)
    assert 'detail: run.status || ""' not in source
    assert "detail: agentRunSummaryText(run)" in source
    assert 'title: run.task || "이름 없는 백그라운드 실행"' in source


def test_run_event_trail_is_presented_in_korean() -> None:
    source, _ = _document()
    script = _function_source(source, "describeRunEvent") + """
console.log(JSON.stringify([
  describeRunEvent("tool_start read_file"),
  describeRunEvent("steer "),
  describeRunEvent("custom text here"),
]));
"""

    assert _node_json(script) == [
        "도구 실행 시작 · read_file", "조정 지시 반영", "custom text here",
    ]
    detail = _function_source(source, "appendAgentRunDetail")
    assert "describeRunEvent(event.text)" in detail
    assert "formatClock(event.at)" in detail
    assert "${event.at || \"\"}" not in detail
    assert "오류 세부 정보 보기" in detail
    assert "renderSafeMarkdown(resultBody, run.result)" in detail
    assert "응답이 끊겨 결과를 확인할 수 없습니다." in detail
    assert "진행 이벤트가 아직 없습니다." in detail
    assert "백그라운드 실행 세부 정보" in detail
    assert '["시작", formatClock(run.started_at)]' in detail


def test_canonical_agent_rows_do_not_duplicate_loaded_runs() -> None:
    source, _ = _document()
    script = _function_source(source, "withoutShadowedAgentRuns") + """
const canonical = [
  {id: "9fa25663", task: "x", kind: "tasks_runs"},
  {id: "briefing:1", kind: "briefing"},
  {id: "9fa2", task: "short", kind: "tasks_runs"},
];
console.log(JSON.stringify([
  withoutShadowedAgentRuns([{kind: "agent_run", id: "9fa25663190d"}], canonical)
    .map((item) => item.id),
  withoutShadowedAgentRuns([], canonical).map((item) => item.id),
]));
"""

    assert _node_json(script) == [
        ["briefing:1", "9fa2"],
        ["9fa25663", "briefing:1", "9fa2"],
    ]
    render = _function_source(source, "renderPanel")
    assert "withoutShadowedAgentRuns(legacyItems, canonicalItems)" in render


def test_approvals_name_agent_and_link_run() -> None:
    source, _ = _document()
    script = "".join(
        _function_source(source, name)
        for name in ("agentLabel", "approvalRunContext", "buildQueue")
    ) + """
const [item] = buildQueue([{
  id: "a1", title: "", category: "shell", category_label: "Shell 명령",
  agent_run: {id: "r1", task: "시트 분석", agent: "sheet-analyst",
              agent_title: "스프레드시트 분석가", agent_source: "builtin"},
}], {jobs: []}, []);
const [plain] = buildQueue([{id: "a2", category: "memory"}], {jobs: []}, []);
console.log(JSON.stringify([item.title, item.requester, item.detail,
  item.agent_run.id, plain.title, plain.requester, plain.target]));
"""

    assert _node_json(script) == [
        "Shell 명령",
        "스프레드시트 분석가 에이전트",
        "스프레드시트 분석가 · ‘시트 분석’ 실행에서 요청",
        "r1",
        "승인 요청",
        "Birkin",
        "",
    ]
    assert "approval.agent_run" in source
    assert "approval.requested_by" in source
    assert "요청 에이전트" in source
    assert "관련 실행 보기" in source
    assert "승인 검토: " in source
    assert 'showPanelItem("approvals"' in source
    assert 'showPanelItem("tasks_runs"' in source


def test_tasks_panel_shows_summon_roster() -> None:
    source, _ = _document()

    assert 'optionalLegacyApi("/api/agents", null)' in source
    assert "소환할 수 있는 에이전트" in source
    assert "/summon <에이전트> <할 일>" in source
    assert "사용자 정의 에이전트 정의 ${rejected}개를 불러오지 못했습니다." in source
    assert "에이전트 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요." in source
    bootstrap = _function_source(source, "bootstrap")
    assert bootstrap.index("await refreshLegacyPanels(generation)") < bootstrap.index(
        "await loadAgentRoster(generation)"
    ) < bootstrap.index("startApprovalRefreshPolling()")


def test_live_agent_runs_refresh_after_approvals() -> None:
    source, _ = _document()
    start = source.index("state.approvalRefreshTimer = setInterval(")
    end = source.index("}, APPROVAL_REFRESH_INTERVAL_MS);", start)
    poller = source[start:end]

    assert "refreshLiveAgentRuns" in poller
    assert poller.index("refreshApprovals().catch") < poller.index(
        "refreshLiveAgentRuns"
    )
    live = _function_source(source, "refreshLiveAgentRuns")
    assert '["tasks_runs", "activity_logs"].includes(state.activePanel)' in live
    assert 'closest("[data-run-controls]")' in live
    assert "generation !== state.bootstrapGeneration" in live


def test_unavailable_agent_runs_are_not_reported_as_empty() -> None:
    source, _ = _document()
    script = """
const unavailableLegacyPaths = new Set();
let calls = 0;
const api = async () => {
  calls += 1;
  if (calls === 1) throw new Error("503");
  return {runs: [{id: "r"}]};
};
console.warn = () => {};
""" + _function_source(source, "optionalLegacyApi") + """
(async () => {
  const first = await optionalLegacyApi("/api/agent-runs", {runs: []});
  const failed = unavailableLegacyPaths.has("/api/agent-runs");
  const second = await optionalLegacyApi("/api/agent-runs", {runs: []});
  console.log(JSON.stringify([
    first, failed, second, unavailableLegacyPaths.has("/api/agent-runs"),
  ]));
})();
"""

    assert _node_json(script) == [
        {"runs": []}, True, {"runs": [{"id": "r"}]}, False,
    ]
    assert "진행 중인 작업이나 에이전트 실행이 없습니다." in source
    assert "에이전트 실행 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요." in source
    assert "현재 표시할 항목이 없습니다." in source


def test_steer_draft_survives_panel_rerender() -> None:
    source, _ = _document()

    assert "steerDrafts: new Map()" in source
    assert "steerDrafts.get(" in source
    assert "steerDrafts.set(" in source
    assert "steerDrafts.delete(" in source


def test_panel_state_glyph_is_hidden_from_accessible_name() -> None:
    source, _ = _document()
    render = _function_source(source, "renderPanel")

    assert 'glyph.setAttribute("aria-hidden", "true")' in render
    assert "${presentation[0]} ${presentation[1]} ·" not in source
    detail = _function_source(source, "appendAgentRunDetail")
    assert 'section.setAttribute("aria-busy", "true")' in detail
    assert 'section.setAttribute("aria-busy", "false")' in detail


def test_approval_answer_announces_authority_outcome() -> None:
    source, _ = _document()
    handler = _function_source(source, "handleApprovalAnswered")
    approved = handler.index('outcome === "approved"')
    rejected = handler.index('outcome === "rejected"')

    assert "payload.result_summary" in handler
    assert approved < handler.index("작업은 실행됐지만") < rejected
    script = """
const announced = [];
const fetched = [];
const busyApprovalIds = new Set();
const recentReceipts = new Map();
const announce = (text) => announced.push(text);
const api = async (path) => { fetched.push(path); throw new Error("409"); };
const refreshWorkspaceSnapshot = async () => {};
const refreshLegacyPanels = async () => {};
console.error = () => {};
""" + handler + """
(async () => {
  await handleApprovalAnswered({
    approval_id: "a1", decision: "approve", outcome: "rejected_by_authority",
    result_summary: "승인한 작업을 실행하지 못했습니다.",
  });
  await handleApprovalAnswered({
    approval_id: "a2", decision: "reject", outcome: "answered_elsewhere",
    result_summary: "웹 대시보드에서 이미 승인되어 작업을 완료했습니다.",
  });
  await handleApprovalAnswered({
    approval_id: "a3", decision: "approve", outcome: "approved",
    result_summary: "명령이 종료 코드 2(으)로 실패했습니다.",
  });
  await handleApprovalAnswered({approval_id: "a4", decision: "approve"});
  console.log(JSON.stringify({announced, fetched}));
})();
"""

    assert _node_json(script) == {
        "announced": [
            "승인한 작업을 실행하지 못했습니다.",
            "웹 대시보드에서 이미 승인되어 작업을 완료했습니다.",
            "명령이 종료 코드 2(으)로 실패했습니다.",
            "승인 요청을 처리하지 못했습니다. 승인 목록에서 상태를 확인하세요.",
        ],
        "fetched": ["/api/actions/a3/receipt"],
    }


def test_approval_detail_uses_category_label_and_question_state() -> None:
    source, _ = _document()
    detail = _function_source(source, "appendApprovalDetail")
    queue = _function_source(source, "buildQueue")

    assert "item.category_label || record.category_label" in detail
    assert "item.needs_answers || record.needs_answers" in detail
    assert '["결과", item.result_summary || record.result_summary]' in detail
    assert "질문을 보낸 화면에서 답변하세요." in detail
    assert "approval.target || approval.category" not in queue
    assert "approval.title || approval.category_label" in queue
