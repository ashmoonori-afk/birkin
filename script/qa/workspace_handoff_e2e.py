"""Prove terminal and browser converge through one workspace authority."""

from __future__ import annotations

import io
import json
import re
import shutil
import socket
import tempfile
from pathlib import Path
from typing import cast

from playwright.sync_api import Response, sync_playwright

from script.qa.workspace_handoff_support import (
    history_hash,
    png_dimensions,
    replay_duplicate_command,
    send_terminal,
    spawn_terminal,
    stop_terminal,
    workspace_events,
    workspace_snapshot,
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
    console_errors: list[str] = []
    network_failures: list[dict[str, object]] = []

    def assert_browser_clean(stage: str) -> None:
        if console_errors or network_failures:
            raise AssertionError(
                f"{stage} browser errors: {console_errors}, {network_failures}"
            )

    def reset_planned_restart_errors() -> None:
        console_errors.clear()
        network_failures.clear()
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
            page.on(
                "console",
                lambda message: (
                    console_errors.append(message.text)
                    if message.type == "error"
                    else None
                ),
            )

            def record_response(response: Response) -> None:
                if response.status >= 400:
                    network_failures.append(
                        {"url": response.url, "status": response.status}
                    )

            page.on("response", record_response)
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
            reset_planned_restart_errors()
            print("QA_HANDOFF_STAGE=browser-attached", flush=True)

            input_box = page.locator("#workspace-input")
            _ = input_box.fill("handoff web")
            _ = input_box.press("Control+Enter")
            page.get_by_text("Echo complete 🧵: handoff web").wait_for()
            assert_browser_clean("terminal-to-web")
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
            reset_planned_restart_errors()
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
            assert_browser_clean("approval")
            _ = stop_terminal(child)
            child, url, port = spawn_terminal(profile, terminal_log)
            terminal_pids.append(child.pid)
            ports.append(port)
            _ = child.expect_exact("shared continuation")
            _ = child.expect_exact(PROMPT_READY)
            _ = page.goto(url, wait_until="domcontentloaded")
            page.get_by_text("완료되었습니다 ✓ shared continuation").wait_for()
            reset_planned_restart_errors()
            print("QA_HANDOFF_STAGE=approval-converged", flush=True)

            _ = input_box.fill("웹에서 터미널로 🧵")
            _ = input_box.press("Control+Enter")
            page.get_by_text(
                re.compile(r"Echo complete .*웹에서 터미널로")
            ).wait_for()
            assert_browser_clean("web-to-terminal")
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
            reset_planned_restart_errors()

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
            reset_planned_restart_errors()

            snapshot = workspace_snapshot(page)
            conversation = cast(
                list[dict[str, object]],
                snapshot["conversation"],
            )
            texts = [str(message["text"]) for message in conversation]
            for marker in (
                "handoff terminal",
                "handoff web",
                "완료되었습니다 ✓ shared continuation",
                "웹에서 터미널로 🧵",
            ):
                if not any(marker in text for text in texts):
                    raise AssertionError(f"missing converged marker: {marker}")
            _ = page.screenshot(
                path=evidence / "cross-surface-handoff.png"
            )
            _ = page.reload(wait_until="domcontentloaded")
            page.get_by_text(
                re.compile(r"Echo complete .*웹에서 터미널로")
            ).wait_for()
            reloaded_snapshot = workspace_snapshot(page)
            terminal_history_hash = history_hash(snapshot)
            web_history_hash = history_hash(reloaded_snapshot)
            if terminal_history_hash != web_history_hash:
                raise AssertionError("terminal/web history hashes diverged")
            events = workspace_events(page)
            answered = [
                event
                for event in events
                if event.get("type") == "approval.answered"
            ]
            if len(answered) != 1 or answered[0].get("actor_id") != "web:browser-1":
                raise AssertionError(
                    f"approval actor is ambiguous: {answered}"
                )
            duplicate_messages = [
                message
                for message in cast(
                    list[dict[str, object]],
                    reloaded_snapshot["conversation"],
                )
                if message.get("text") == "cross-surface duplicate once"
            ]
            if len(duplicate_messages) != 1:
                raise AssertionError(
                    f"duplicate command executed more than once: {duplicate_messages}"
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
        assert_browser_clean("final-reattach")
        for screenshot in (
            "web-office-job-approval.png",
            "web-office-job-approved.png",
            "cross-surface-handoff.png",
        ):
            if png_dimensions(evidence / screenshot) != (1024, 800):
                raise AssertionError(f"{screenshot} dimensions changed")

        metadata = {
            "terminal_pids": terminal_pids,
            "ports": ports,
            "session_id": snapshot["session_id"],
            "cursor": snapshot["cursor"],
            "conversation_messages": len(conversation),
            "terminal_to_web": True,
            "web_to_terminal": True,
            "approval_continuation": True,
            "approval_actor": "web:browser-1",
            "duplicate_command_single_execution": True,
            "terminal_history_hash": terminal_history_hash,
            "web_history_hash": web_history_hash,
            "reload_convergence": True,
            "console_errors": console_errors,
            "network_failures": network_failures,
            "profile_path": str(profile),
            "profile_removed": True,
        }
        _ = (evidence / "cross-surface-terminal.raw.txt").write_text(
            terminal_log.getvalue(),
            encoding="utf-8",
        )
        _ = (evidence / "cross-surface-handoff.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        if child.isalive():
            _ = child.terminate(force=True)
        shutil.rmtree(profile, ignore_errors=True)
    print("Cross-surface QA passed: terminal ↔ web convergence")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
