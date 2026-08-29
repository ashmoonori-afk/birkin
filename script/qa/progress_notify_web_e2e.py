#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "playwright",
# ]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run script/qa/progress_notify_web_e2e.py [evidence-directory]
# 3. Or make executable and run:
#      chmod +x script/qa/progress_notify_web_e2e.py
#      ./script/qa/progress_notify_web_e2e.py [evidence-directory]
# ──────────────────

"""Orchestrate real-Chrome P1-6 progress and approval QA."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
if TYPE_CHECKING:
    from script.qa.progress_notify_web_scenario import (
        ScenarioEvidence,
        run_scenario,
    )
else:
    from progress_notify_web_scenario import ScenarioEvidence, run_scenario


class BrowserEvidence(ScenarioEvidence):
    """Machine-readable P1-6 browser QA receipt."""

    browser: str
    profile_removed: bool


@dataclass(frozen=True, slots=True)
class FixtureServerError(RuntimeError):
    """Fixture server did not expose a usable browser endpoint."""

    message: str

    def __str__(self) -> str:
        return self.message


def _server_url(process: subprocess.Popen[str]) -> str:
    if process.stdout is None:
        raise FixtureServerError("fixture server stdout is unavailable")
    line = process.stdout.readline()
    match = re.search(r"QA_WEB_URL=(\S+)", line)
    if match is None:
        raise FixtureServerError(f"invalid fixture server output: {line}")
    return match.group(1)


def main() -> int:
    evidence = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / ".omo" / "evidence" / "progress-and-notify" / "web"
    ).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    network_failures: list[str] = []
    page_errors: list[str] = []
    browser_version = ""

    with tempfile.TemporaryDirectory(prefix="birkin-p16-web-") as profile:
        environment = os.environ.copy()
        environment["BIRKIN_HOME"] = profile
        server = subprocess.Popen(
            [sys.executable, "-m", "script.qa.workspace_web_fixture"],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            url = _server_url(server)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel="chrome",
                    headless=True,
                )
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    color_scheme="dark",
                    locale="ko-KR",
                )
                page = context.new_page()
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on(
                    "response",
                    lambda response: network_failures.append(
                        f"{response.status} {response.url}"
                    )
                    if response.status >= 400
                    else None,
                )
                _ = page.goto(url, wait_until="domcontentloaded")
                page.locator(
                    '[data-testid="workspace-connection"]'
                ).wait_for()
                _ = page.wait_for_function(
                    """() => document.querySelector(
                      '[data-testid="workspace-connection"]'
                    )?.dataset.state === 'connected'"""
                )
                scenario = run_scenario(page, evidence)
                browser_version = browser.version
                browser.close()
        finally:
            server.terminate()
            try:
                _, _ = server.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                _, _ = server.communicate(timeout=10)

    if console_errors or network_failures or page_errors:
        raise AssertionError(
            "browser diagnostics failed: "
            f"{console_errors}, {network_failures}, {page_errors}"
        )
    receipt: BrowserEvidence = {
        "browser": browser_version,
        "phases": scenario["phases"],
        "external_approval_visible": scenario["external_approval_visible"],
        "unchanged_refresh_preserved_node": scenario[
            "unchanged_refresh_preserved_node"
        ],
        "focused_card_preserved_on_new_approval": scenario[
            "focused_card_preserved_on_new_approval"
        ],
        "mobile_header_single_line": scenario["mobile_header_single_line"],
        "mobile_notice_clears_composer": scenario[
            "mobile_notice_clears_composer"
        ],
        "profile_removed": not Path(profile).exists(),
    }
    _ = (evidence / "browser-e2e.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("P1-6 real-Chrome progress and external-approval QA passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
