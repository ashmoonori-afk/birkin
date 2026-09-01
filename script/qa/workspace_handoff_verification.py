"""Post-scenario convergence checks for cross-surface workspace QA."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast, final

from playwright.sync_api import Page, Response

from script.qa.workspace_handoff_support import (
    history_hash,
    png_dimensions,
    workspace_events,
    workspace_snapshot,
)


@final
@dataclass(frozen=True)
class HandoffVerification:
    conversation_messages: int
    terminal_history_hash: str
    web_history_hash: str


@final
class BrowserDiagnostics:
    def __init__(self) -> None:
        self.console_errors: list[str] = []
        self.network_failures: list[dict[str, object]] = []

    def attach(self, page: Page) -> None:
        page.on(
            "console",
            lambda message: (
                self.console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )

        def record_response(response: Response) -> None:
            if response.status >= 400:
                self.network_failures.append(
                    {"url": response.url, "status": response.status}
                )

        page.on("response", record_response)

    def reset(self) -> None:
        self.console_errors.clear()
        self.network_failures.clear()

    def assert_clean(self, stage: str) -> None:
        if self.console_errors or self.network_failures:
            raise AssertionError(
                f"{stage} browser errors: "
                f"{self.console_errors}, {self.network_failures}"
            )


def verify_handoff_convergence(
    page: Page,
    evidence: Path,
    snapshot: dict[str, object],
) -> HandoffVerification:
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

    _ = page.screenshot(path=evidence / "cross-surface-handoff.png")
    _ = page.reload(wait_until="domcontentloaded")
    page.get_by_text(
        re.compile(r"Echo complete .*웹에서 터미널로")
    ).wait_for()
    reloaded_snapshot = workspace_snapshot(page)
    terminal_hash = history_hash(snapshot)
    web_hash = history_hash(reloaded_snapshot)
    if terminal_hash != web_hash:
        raise AssertionError("terminal/web history hashes diverged")

    answered = [
        event
        for event in workspace_events(page)
        if event.get("type") == "approval.answered"
    ]
    if len(answered) != 1 or answered[0].get("actor_id") != "web:browser-1":
        raise AssertionError(f"approval actor is ambiguous: {answered}")
    duplicates = [
        message
        for message in cast(
            list[dict[str, object]],
            reloaded_snapshot["conversation"],
        )
        if message.get("text") == "cross-surface duplicate once"
    ]
    if len(duplicates) != 1:
        raise AssertionError(
            f"duplicate command executed more than once: {duplicates}"
        )
    for screenshot in (
        "web-office-job-approval.png",
        "web-office-job-approved.png",
        "cross-surface-handoff.png",
    ):
        if png_dimensions(evidence / screenshot) != (1024, 800):
            raise AssertionError(f"{screenshot} dimensions changed")
    return HandoffVerification(
        conversation_messages=len(conversation),
        terminal_history_hash=terminal_hash,
        web_history_hash=web_hash,
    )


def write_handoff_report(
    *,
    evidence: Path,
    profile: Path,
    terminal_log: io.StringIO,
    terminal_pids: list[int | None],
    ports: list[int],
    snapshot: dict[str, object],
    verification: HandoffVerification,
    console_errors: list[str],
    network_failures: list[dict[str, object]],
) -> None:
    metadata = {
        "terminal_pids": terminal_pids,
        "ports": ports,
        "session_id": snapshot["session_id"],
        "cursor": snapshot["cursor"],
        "conversation_messages": verification.conversation_messages,
        "terminal_to_web": True,
        "web_to_terminal": True,
        "approval_continuation": True,
        "approval_actor": "web:browser-1",
        "duplicate_command_single_execution": True,
        "terminal_history_hash": verification.terminal_history_hash,
        "web_history_hash": verification.web_history_hash,
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
