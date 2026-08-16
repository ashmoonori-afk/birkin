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
    assert "...(merged.get(id) || {}), ...item" in source
    assert "approval.requested_by" in source
    assert "복원 승인 요청" in source
    assert "/api/checkpoints/${encodeURIComponent(item.id)}/restore" in source
    assert "workspace-question-answer" in source
    assert 'sendCommand("question.answer"' in source
    assert "복원 범위" in source
    assert 'body: JSON.stringify({mode: mode.value})' in source
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
    assert "승인 실행" in source
    assert "submitApproval" in source
    assert "window.confirm" not in source


def test_web_workspace_prefers_workspace_approval_receipts() -> None:
    source, _ = _document()

    assert "payload.receipt" in source
    assert "recentReceipts.set(approvalId" in source
