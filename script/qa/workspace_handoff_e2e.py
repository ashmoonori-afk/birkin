"""Prove terminal and browser converge through one workspace authority."""

from __future__ import annotations

import io
import re
import shutil
import socket
import tempfile
from pathlib import Path
from typing import cast

from playwright.sync_api import sync_playwright

from script.qa.workspace_handoff_support import (
    replay_duplicate_command,
    send_terminal,
    spawn_terminal,
    stop_terminal,
    workspace_snapshot,
)
from script.qa.workspace_handoff_verification import (
    BrowserDiagnostics,
    verify_handoff_convergence,
    write_handoff_report,
)

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".omo" / "evidence" / "unified-workspace"
PROMPT_READY = "\x1b[>1u"


def run(evidence: Path = EVIDENCE) -> int:
    evidence.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="birkin-handoff-e2e-"))
    terminal_log = io.StringIO()
    child, url, port = spawn_terminal(profile, terminal_log)
    terminal_pids = [child.pid]
    ports = [port]
    browser = None
    page = None
    diagnostics = BrowserDiagnostics()
    try:
        _ = child.expect_exact(PROMPT_READY)
        send_terminal(child, "handoff terminal")
        _ = child.expect_exact("Echo complete 🧵: handoff terminal")
        _ = child.expect_exact(PROMPT_READY)
        print("QA_HANDOFF_STAGE=terminal-seed", flush=True)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="chrome",
                headless=True,
            )
            context = browser.new_context(
                viewport={"width": 1024, "height": 800},
                locale="ko-KR",
            )
            _ = context.add_init_script(
                """localStorage.setItem(
                  'birkin.workspace.session',
                  'qa-terminal'
                );"""
            )
            page = context.new_page()
            diagnostics.attach(page)
            _ = page.goto(url, wait_until="domcontentloaded")
            page.locator(
                '[data-testid="workspace-connection"][data-state="connected"]'
            ).wait_for()
            initial_snapshot = workspace_snapshot(page)
            initial_texts = [
                str(message["text"])
                for message in cast(
                    list[dict[str, object]],
                    initial_snapshot["conversation"],
                )
            ]
            if not any("handoff terminal" in text for text in initial_texts):
                raise AssertionError(
                    "terminal seed was absent from the browser snapshot"
                )
            _ = cast(object, page.evaluate("refreshWorkspaceSnapshot()"))
            page.get_by_text("Echo complete 🧵: handoff terminal").wait_for()
            diagnostics.reset()
            print("QA_HANDOFF_STAGE=browser-attached", flush=True)

            input_box = page.locator("#workspace-input")
            _ = input_box.fill("handoff web")
            _ = input_box.press("Control+Enter")
            page.get_by_text("Echo complete 🧵: handoff web").wait_for()
            diagnostics.assert_clean("terminal-to-web")
            _ = stop_terminal(child)
            child, url, port = spawn_terminal(profile, terminal_log)
            terminal_pids.append(child.pid)
            ports.append(port)
            _ = child.expect_exact("handoff web")
            _ = child.expect_exact(PROMPT_READY)
            _ = page.goto(url, wait_until="domcontentloaded")
            page.locator(
                '[data-testid="workspace-connection"][data-state="connected"]'
            ).wait_for()
            page.get_by_text("Echo complete 🧵: handoff web").wait_for()
            diagnostics.reset()
            print("QA_HANDOFF_STAGE=terminal-reconnected-web", flush=True)

            send_terminal(child, "approval cross")
            _ = child.expect_exact("Approval required. Type approve to resume.")
            _ = child.expect_exact(PROMPT_READY)
            _ = page.locator('[data-panel="approvals"]').click()
            approval_item = page.locator(
                '#workspace-panel-body [data-item-id="qa-approval"]'
            )
            approval_item.wait_for()
            page.locator(
                '[data-testid="workspace-shell"][data-last-event="command.completed"]'
            ).wait_for()
            _ = approval_item.click()
            page.get_by_text(
                "fixture://approval/qa-approval",
                exact=True,
            ).wait_for()
            page.get_by_role("button", name="승인 실행").wait_for()
            _ = page.screenshot(
                path=evidence / "web-office-job-approval.png"
            )
            _ = page.get_by_role("button", name="승인 실행").click()
            _ = page.wait_for_function(
                """async () => {
                  const session = localStorage.getItem('birkin.workspace.session');
                  const response = await fetch(
                    `/api/workspace/sessions/${session}/snapshot`
                  );
                  const snapshot = await response.json();
                  const panel = snapshot.panels.find(
                    (item) => item.key === 'approvals'
                  );
                  return panel.items.some(
                    (item) => item.status === 'approved'
                      && item.ui_state === 'succeeded'
                  );
                }"""
            )
            _ = page.get_by_text("영수증 세부 정보 보기").click()
            page.get_by_text(
                "fixture approval executed",
                exact=False,
            ).wait_for()
            _ = page.screenshot(
                path=evidence / "web-office-job-approved.png"
            )
            diagnostics.assert_clean("approval")
            _ = stop_terminal(child)
            child, url, port = spawn_terminal(profile, terminal_log)
            terminal_pids.append(child.pid)
            ports.append(port)
            _ = child.expect_exact("shared continuation")
            _ = child.expect_exact(PROMPT_READY)
            _ = page.goto(url, wait_until="domcontentloaded")
            page.get_by_text("완료되었습니다 ✓ shared continuation").wait_for()
            diagnostics.reset()
            print("QA_HANDOFF_STAGE=approval-converged", flush=True)

            _ = input_box.fill("웹에서 터미널로 🧵")
            _ = input_box.press("Control+Enter")
            page.get_by_text(
                re.compile(r"Echo complete .*웹에서 터미널로")
            ).wait_for()
            diagnostics.assert_clean("web-to-terminal")
            print("QA_HANDOFF_STAGE=unicode-converged", flush=True)
            _ = stop_terminal(child)
            child, url, port = spawn_terminal(profile, terminal_log)
            terminal_pids.append(child.pid)
            ports.append(port)
            _ = child.expect_exact("웹에서 터미널로 🧵")
            _ = child.expect_exact(PROMPT_READY)
            _ = page.goto(url, wait_until="domcontentloaded")
            page.get_by_text(
                re.compile(r"Echo complete .*웹에서 터미널로")
            ).wait_for()
            diagnostics.reset()

            duplicate = replay_duplicate_command(
                page,
                "cross-surface duplicate once",
            )
            if (
                duplicate["firstStatus"] != 202
                or duplicate["secondStatus"] != 200
            ):
                raise AssertionError(
                    f"duplicate command statuses changed: {duplicate}"
                )
            second = cast(dict[str, object], duplicate["second"])
            if second.get("duplicate") is not True:
                raise AssertionError(
                    f"duplicate receipt was not idempotent: {duplicate}"
                )
            page.get_by_text(
                re.compile(r"Echo complete .*cross-surface duplicate once")
            ).wait_for()
            _ = stop_terminal(child)
            child, url, port = spawn_terminal(profile, terminal_log)
            terminal_pids.append(child.pid)
            ports.append(port)
            _ = child.expect_exact("cross-surface duplicate once")
            _ = child.expect_exact(PROMPT_READY)
            send_terminal(child, "terminal verifies duplicate")
            _ = child.expect_exact("cross-surface duplicate once")
            _ = child.expect_exact(PROMPT_READY)
            _ = page.goto(url, wait_until="domcontentloaded")
            page.locator(
                '[data-testid="workspace-connection"][data-state="connected"]'
            ).wait_for()
            diagnostics.reset()

            snapshot = workspace_snapshot(page)
            verification = verify_handoff_convergence(
                page,
                evidence,
                snapshot,
            )
            browser.close()
            browser = None

        _ = stop_terminal(child)
        if (profile / "web_session.json").exists():
            raise AssertionError("handoff web discovery file survived shutdown")
        for closed_port in ports:
            with socket.socket() as probe:
                probe.settimeout(1)
                if probe.connect_ex(("127.0.0.1", closed_port)) == 0:
                    raise AssertionError(
                        f"handoff port remained open: {closed_port}"
                    )
        diagnostics.assert_clean("final-reattach")
    finally:
        if child.isalive():
            _ = child.terminate(force=True)
        if profile.exists():
            shutil.rmtree(profile)
        if profile.exists():
            raise AssertionError(
                f"handoff profile survived cleanup: {profile}"
            )
    write_handoff_report(
        evidence=evidence,
        profile=profile,
        terminal_log=terminal_log,
        terminal_pids=terminal_pids,
        ports=ports,
        snapshot=snapshot,
        verification=verification,
        console_errors=diagnostics.console_errors,
        network_failures=diagnostics.network_failures,
    )
    print("Cross-surface QA passed: terminal ↔ web convergence")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
