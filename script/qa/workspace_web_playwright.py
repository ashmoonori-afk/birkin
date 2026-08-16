"""Real-Chrome interaction driver for workspace browser QA."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from script.qa.workspace_web_driver_support import (
    CONNECTED,
    assert_closed_mobile_drawer,
    assert_layout,
    assert_open_mobile_drawer,
    assert_tablet_overflow,
)


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
        _ = page.locator("#workspace-send").click()
        page.get_by_text("Approval required. Type approve to resume.").wait_for()
        page.locator(
            '[data-testid="workspace-shell"][data-last-event="command.completed"]'
        ).wait_for()
        _ = page.locator('[data-panel="approvals"]').click()
        page.get_by_text("Approve deterministic workspace action").wait_for()
        _ = page.get_by_text("Approve deterministic workspace action").click()
        page.get_by_role("button", name="승인 실행").wait_for()
        _ = page.screenshot(path=evidence / "web-1440-approval.png")
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
        page.get_by_text("완료되었습니다 ✓ shared continuation").wait_for()

        _ = input_box.fill("inspect question evidence checkpoint")
        _ = input_box.press("Control+Enter")
        page.get_by_text(
            "Question ready with file evidence and checkpoint."
        ).wait_for()
        _ = page.locator('[data-panel="approvals"]').click()
        page.get_by_text(
            re.compile(r"Continue with the inspected evidence")
        ).wait_for()
        _ = page.locator("#workspace-panel-body").get_by_text(
            re.compile(r"Continue with the inspected evidence")
        ).click()
        _ = page.screenshot(path=evidence / "web-1440-question.png")
        _ = page.locator(
            '[data-testid="workspace-question-answer"]'
        ).fill("continue")
        _ = page.get_by_text("답변 보내기").click()
        page.get_by_text("Question answered: continue").wait_for()
        _ = page.locator('[data-panel="files_evidence"]').click()
        page.get_by_text("workspace-report.txt").wait_for()
        _ = page.screenshot(path=evidence / "web-1440-evidence.png")
        _ = page.locator('[data-panel="checkpoints_restore"]').click()
        page.get_by_text("Before workspace inspection").wait_for()
        _ = page.locator("#workspace-panel-body").get_by_text(
            "Before workspace inspection"
        ).first.click()
        _ = page.screenshot(
            path=evidence / "web-1440-checkpoint-detail.png"
        )
        _ = page.get_by_text("복원 승인 요청").click()
        page.locator("#workspace-panel-body").get_by_text(
            re.compile(r"복원 승인 대기:")
        ).wait_for()
        _ = page.screenshot(path=evidence / "web-1440-checkpoint.png")
        _ = page.locator('[data-panel="approvals"]').click()
        _ = page.get_by_text(
            re.compile(r"Restore checkpoint")
        ).click()
        _ = page.get_by_text("승인 실행").click()
        _ = page.locator('[data-panel="checkpoints_restore"]').click()
        page.get_by_text(
            re.compile(r"✓ 완료 · a1b2c3d4")
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
        _ = input_box.press("Control+Enter")
        page.get_by_text(
            re.compile(r"Echo complete .*브라우저 붙여넣기 한글")
        ).wait_for()

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
        _ = input_box.press("Control+Enter")
        page.get_by_text("interrupt-ready").wait_for()
        _ = input_box.press("Escape")
        page.get_by_text("Interrupted safely").wait_for()
        _ = page.reload(wait_until="domcontentloaded")
        _ = page.wait_for_function(CONNECTED)
        page.get_by_text("Interrupted safely").wait_for()
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

    failures: list[dict[str, object]] = []
    for entry in network:
        status = entry.get("status")
        if isinstance(status, int) and status >= 400:
            failures.append(entry)
    console_failures = [
        entry for entry in console if entry["type"] == "error"
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
