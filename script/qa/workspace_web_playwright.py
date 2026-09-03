"""Real-Chrome interaction driver for workspace browser QA."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from script.qa.workspace_web_driver_support import (
    CONNECTED,
    assert_closed_mobile_drawer,
    assert_layout,
    assert_open_mobile_drawer,
    assert_tablet_overflow,
)


def trigger_and_wait_for_new_text(
    locator: Locator,
    trigger: Callable[[], object],
) -> None:
    next_index = locator.count()
    _ = trigger()
    locator.nth(next_index).wait_for()


def run(url: str, evidence: Path) -> int:
    console: list[dict[str, str]] = []
    network: list[dict[str, object]] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            color_scheme="dark",
            locale="ko-KR",
        )
        page = context.new_page()
        page.on(
            "console",
            lambda message: console.append(
                {"type": message.type, "text": message.text}
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "response",
            lambda response: network.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "method": response.request.method,
                }
            ),
        )
        page.on("dialog", lambda dialog: dialog.accept())

        _ = page.goto(url, wait_until="domcontentloaded")
        page.locator('[data-testid="workspace-connection"]').wait_for(
            state="visible"
        )
        try:
            _ = page.wait_for_function(
                CONNECTED
            )
        except PlaywrightTimeoutError as exc:
            message = (
                f"workspace connection timeout; console={console}; "
                + f"network={network}; errors={page_errors}"
            )
            raise AssertionError(message) from exc
        assert_layout(page)
        _ = page.screenshot(path=evidence / "web-1440-default.png")

        input_box = page.locator("#workspace-input")
        _ = input_box.fill("approval web")
        trigger_and_wait_for_new_text(
            page.get_by_text("Approval required. Type approve to resume."),
            page.locator("#workspace-send").click,
        )
        page.locator(
            '[data-testid="workspace-shell"][data-last-event="command.completed"]'
        ).wait_for()
        _ = page.locator('[data-panel="approvals"]').click()
        approval_item = page.locator(
            '#workspace-panel-body [data-item-id="qa-approval"]'
        )
        approval_item.get_by_text(
            re.compile(r"Approve deterministic workspace action")
        ).first.wait_for()
        _ = approval_item.click()
        page.get_by_role("button", name="승인 실행").wait_for()
        _ = page.screenshot(path=evidence / "web-1440-approval.png")
        completed = page.get_by_text("완료되었습니다 ✓ shared continuation")
        completed_index = completed.count()
        _ = page.get_by_role("button", name="승인 실행").click()
        _ = page.wait_for_function(
            """async () => {
              const session = localStorage.getItem('birkin.workspace.session');
              const response = await fetch(
                `/api/workspace/sessions/${session}/snapshot`
              );
              const snapshot = await response.json();
              const panel = snapshot.panels.find((item) => item.key === 'approvals');
              return panel.items.some((item) => item.status === 'approve');
            }"""
        )
        completed.nth(completed_index).wait_for()
        page.locator(
            '[data-testid="workspace-shell"][data-last-event="command.completed"]'
        ).wait_for()
        page.get_by_text(
            "승인한 작업을 실행했습니다. 영수증 세부 정보에서 결과를 확인하세요.",
            exact=True,
        ).wait_for()
        receipt_summary = page.get_by_text(
            "영수증 세부 정보 보기",
            exact=True,
        )
        receipt_summary.wait_for()
        receipt_details = receipt_summary.locator("xpath=..")
        if receipt_details.get_attribute("open") is not None:
            raise AssertionError("receipt details opened without user action")
        if receipt_details.locator("pre").is_visible():
            raise AssertionError("raw receipt is visible before disclosure")
        receipt_details.scroll_into_view_if_needed()
        _ = page.screenshot(path=evidence / "web-1440-receipt-closed.png")
        _ = receipt_summary.click()
        receipt_pre = receipt_details.locator("pre")
        receipt_pre.wait_for(state="visible")
        receipt_pre.scroll_into_view_if_needed()
        _ = page.screenshot(path=evidence / "web-1440-receipt-open.png")
        _ = receipt_summary.click()

        _ = input_box.fill("inspect question evidence checkpoint")
        _ = input_box.press("Control+Enter")
        _ = page.locator('[data-panel="approvals"]').click()
        question_item = page.locator(
            '#workspace-panel-body [data-item-id="qa-question"]'
        )
        question_item.get_by_text(
            re.compile(
                r"◆ 조치 필요 · Continue with the inspected evidence"
            ),
        ).wait_for()
        page.locator(
            '[data-testid="workspace-shell"][data-last-event="command.completed"]'
        ).wait_for()
        _ = question_item.click()
        _ = page.screenshot(path=evidence / "web-1440-question.png")
        _ = page.locator(
            '[data-testid="workspace-question-answer"]'
        ).fill("continue")
        _ = page.get_by_text("답변 보내기").click()
        question_item.get_by_text(
            re.compile(r"✓ 완료 · Continue with the inspected evidence"),
        ).wait_for()
        page.locator(
            '[data-testid="workspace-shell"][data-last-event="command.completed"]'
        ).wait_for()
        _ = page.locator('[data-panel="files_evidence"]').click()
        page.locator(
            '#workspace-panel-body [data-item-id="qa-evidence"]'
        ).wait_for()
        _ = page.screenshot(path=evidence / "web-1440-evidence.png")
        _ = page.locator('[data-panel="checkpoints_restore"]').click()
        checkpoint_item = page.locator(
            '#workspace-panel-body [data-item-id="a1b2c3d4"]'
        )
        checkpoint_item.wait_for()
        _ = checkpoint_item.click()
        _ = page.screenshot(
            path=evidence / "web-1440-checkpoint-detail.png"
        )
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/restore")
            )
        ) as restore_response_info:
            _ = page.get_by_text("복원 승인 요청").click()
        restore_response = restore_response_info.value
        if restore_response.status != 202:
            raise AssertionError(
                f"restore approval request returned {restore_response.status}"
            )
        restore_payload = cast(object, restore_response.json())
        if not isinstance(restore_payload, dict):
            raise TypeError("restore approval response must be an object")
        restore_approval_id = str(
            cast(dict[str, object], restore_payload)["approval_id"]
        )
        _ = page.locator('[data-panel="approvals"]').click()
        restore_item = page.locator(
            f'#workspace-panel-body [data-item-id="{restore_approval_id}"]'
        )
        restore_item.get_by_text(
            re.compile(r"체크포인트 복원:")
        ).wait_for()
        _ = page.screenshot(path=evidence / "web-1440-checkpoint.png")
        _ = restore_item.click()
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/commands")
            )
        ) as approval_response_info:
            _ = page.get_by_text("승인 실행").click()
        if approval_response_info.value.status != 202:
            raise AssertionError(
                "restore approval command was not accepted"
            )
        _ = page.locator('[data-panel="checkpoints_restore"]').click()
        page.locator(
            '#workspace-panel-body [data-item-id="a1b2c3d4"]'
        ).get_by_text(
            re.compile(r"✓ 완료 · Before workspace inspection")
        ).wait_for()
        _ = page.screenshot(
            path=evidence / "web-1440-checkpoint-restored.png"
        )

        page.set_viewport_size({"width": 1024, "height": 800})
        _ = page.locator("#workspace-theme").select_option("paper_light")
        _ = page.reload(wait_until="domcontentloaded")
        _ = page.wait_for_function(CONNECTED)
        page.get_by_text(
            "완료되었습니다 ✓ shared continuation"
        ).last.wait_for()
        if page.locator("html").get_attribute("data-theme") != "paper_light":
            raise AssertionError("light theme did not survive reload")
        if page.locator('[data-testid="workspace-mobile-back"]').is_visible():
            raise AssertionError("mobile back is visible at tablet width")
        assert_layout(page)
        _ = page.screenshot(path=evidence / "web-1024-light.png")
        assert_tablet_overflow(page)

        _ = input_box.fill("draft survives reload")
        _ = page.reload(wait_until="domcontentloaded")
        _ = page.wait_for_function(CONNECTED)
        if input_box.input_value() != "draft survives reload":
            raise AssertionError("composer draft did not survive reload")
        _ = input_box.fill("브라우저 붙여넣기 한글")
        trigger_and_wait_for_new_text(
            page.get_by_text(
                re.compile(r"Echo complete .*브라우저 붙여넣기 한글")
            ),
            lambda: input_box.press("Control+Enter"),
        )

        page.set_viewport_size({"width": 390, "height": 844})
        _ = page.locator("#workspace-theme").select_option("high_contrast")
        _ = page.locator("#lens-toggle").click()
        assert_open_mobile_drawer(page)
        _ = page.screenshot(path=evidence / "web-390-contrast-panel.png")
        _ = page.locator('[data-testid="workspace-mobile-back"]').click()
        if page.locator("#lens-toggle").evaluate(
            "(node) => document.activeElement === node"
        ) is not True:
            raise AssertionError("mobile back did not restore focus")

        _ = input_box.fill("interrupt")
        trigger_and_wait_for_new_text(
            page.get_by_text("interrupt-ready"),
            lambda: input_box.press("Control+Enter"),
        )
        trigger_and_wait_for_new_text(
            page.get_by_text("Interrupted safely"),
            lambda: input_box.press("Escape"),
        )
        _ = page.reload(wait_until="domcontentloaded")
        _ = page.wait_for_function(CONNECTED)
        page.get_by_text("Interrupted safely").last.wait_for()
        if page.locator("html").get_attribute("data-theme") != "high_contrast":
            raise AssertionError("high-contrast theme did not survive reload")
        assert_closed_mobile_drawer(page, 844)
        _ = page.screenshot(path=evidence / "web-390-reconnect.png")

        session_id = cast(
            str | None,
            page.evaluate(
                "() => localStorage.getItem('birkin.workspace.session')"
            ),
        )
        metadata: dict[str, object] = {
            "browser": browser.version,
            "channel": "chrome",
            "viewports": [[1440, 900], [1024, 800], [390, 844]],
            "session_id": session_id,
            "theme": page.locator("html").get_attribute("data-theme"),
            "draft_persisted": True,
            "interrupt_resumed": True,
            "reconnect_history": True,
        }
        browser.close()

    optional_legacy_paths = {"/api/runs", "/api/agent-runs"}
    optional_failures: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for entry in network:
        status = entry.get("status")
        if isinstance(status, int) and status >= 400:
            path = urlparse(str(entry.get("url") or "")).path
            if status == 503 and path in optional_legacy_paths:
                optional_failures.append(entry)
            else:
                failures.append(entry)
    console_failures = [
        entry
        for entry in console
        if entry["type"] == "error"
        and not (
            optional_failures
            and entry["text"].startswith(
                "Failed to load resource: the server responded with a status of 503"
            )
        )
    ]
    if failures or console_failures or page_errors:
        message = (
            f"browser diagnostics failed: {failures}, "
            + f"{console_failures}, {page_errors}"
        )
        raise AssertionError(message)
    for filename, payload in (
        ("browser-console.json", console),
        ("browser-network.json", network),
        ("browser-e2e.json", metadata),
    ):
        _ = (evidence / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0
