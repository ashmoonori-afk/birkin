"""P1-6 real-browser interaction scenario."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict, cast

from playwright.sync_api import Page

PHASES = ("inspection", "comparison", "draft", "validation", "export")


class ScenarioEvidence(TypedDict):
    """Observed machine contracts from the browser scenario."""

    phases: list[str]
    external_approval_visible: bool
    unchanged_refresh_preserved_node: bool
    focused_card_preserved_on_new_approval: bool
    mobile_header_single_line: bool
    mobile_notice_clears_composer: bool


def _submit_external_approval(page: Page, text: str) -> bool:
    return cast(
        bool,
        page.evaluate(
            """async (text) => {
              const response = await fetch(
                `/api/workspace/sessions/${
                  encodeURIComponent(state.sessionId)
                }/commands`,
                {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({
                    protocol_version: 1,
                    command_id: `external-${crypto.randomUUID()}`,
                    expected_cursor: state.cursor,
                    type: 'chat.send',
                    payload: {text},
                    client_context: {
                      surface: 'web',
                      view_id: 'external-daemon'
                    }
                  })
                }
              );
              return response.ok;
            }""",
            text,
        ),
    )


def run_scenario(page: Page, evidence: Path) -> ScenarioEvidence:
    """Exercise progress reconciliation and external approval attention."""
    input_box = page.locator("#workspace-input")
    _ = page.evaluate(
        """() => {
          window.__qaOfficePhases = [];
          const seen = new Set();
          const observer = new MutationObserver(() => {
            const row = document.querySelector(
              '[data-progress-id="office:qa-progress"]'
            );
            const phase = row?.dataset.officePhase;
            if (phase && !seen.has(phase)) {
              seen.add(phase);
              window.__qaOfficePhases.push(phase);
            }
          });
          observer.observe(document.querySelector('#workspace-transcript'), {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['data-office-phase']
          });
        }"""
    )
    _ = input_box.fill("office progress")
    _ = page.locator("#workspace-send").click()
    _ = page.wait_for_function(
        """(phases) => JSON.stringify(
          window.__qaOfficePhases
        ) === JSON.stringify(phases)""",
        arg=list(PHASES),
    )
    page.locator(
        '[data-progress-id="office:qa-progress"]'
        '[data-office-phase="export"]'
        '[data-ui-state="succeeded"]'
    ).wait_for()
    _ = page.locator('[data-panel="activity_logs"]').click()
    _ = page.screenshot(path=evidence / "web-1440-office-progress.png")

    if not _submit_external_approval(page, "approval external"):
        raise AssertionError("external approval command was refused")
    _ = page.locator('[data-panel="approvals"]').click()
    first_card = page.locator('.panel-item[data-item-id="qa-approval"]')
    first_card.wait_for()
    _ = page.wait_for_function(
        """() => state.pendingAssistant.size === 0
          && document.querySelector(
            '[data-testid="workspace-shell"]'
          )?.dataset.lastEvent === 'command.completed'"""
    )
    node_stable = cast(
        bool,
        page.evaluate(
            """async () => {
              const selector = '.panel-item[data-item-id="qa-approval"]';
              const before = document.querySelector(selector);
              await refreshApprovals();
              return before === document.querySelector(selector);
            }"""
        ),
    )
    if not node_stable:
        raise AssertionError(
            "unchanged approval refresh replaced the active DOM node"
        )

    _ = first_card.focus()
    if not _submit_external_approval(page, "approval external second"):
        raise AssertionError("second external approval was refused")
    page.locator('.panel-item[data-item-id="qa-approval-2"]').wait_for()
    focused_card_preserved = cast(
        bool,
        page.evaluate(
            """() => document.activeElement?.dataset.itemId === 'qa-approval'"""
        ),
    )
    if not focused_card_preserved:
        raise AssertionError("new approval did not preserve the active card focus")

    page.set_viewport_size({"width": 390, "height": 844})
    _ = page.wait_for_function(
        """() => document.querySelector(
          '[data-testid="workspace-shell"]'
        )?.dataset.panelOpen === 'true'"""
    )
    _ = page.locator(".context-panel").evaluate(
        """(node) => new Promise((resolve) => {
          const transform = getComputedStyle(node).transform;
          if (transform === 'none' || transform.endsWith(', 0)')) {
            resolve();
            return;
          }
          node.addEventListener('transitionend', resolve, {once: true});
        })"""
    )
    first_card.wait_for()
    mobile_layout = cast(
        list[bool],
        page.evaluate(
            """() => {
              const oneLine = (node) => {
                const range = document.createRange();
                range.selectNodeContents(node);
                return range.getClientRects().length === 1;
              };
              const notice = document.querySelector(
                '#queue-notice'
              ).getBoundingClientRect();
              const composer = document.querySelector(
                '#workspace-composer'
              ).getBoundingClientRect();
              return [
                oneLine(document.querySelector(
                  '[data-testid="workspace-connection"]'
                )) && oneLine(document.querySelector(
                  '#browser-aside-toggle'
                )),
                notice.width > 0 && notice.height > 0
                  && (notice.bottom <= composer.top
                    || notice.top >= composer.bottom)
              ];
            }"""
        ),
    )
    if mobile_layout != [True, True]:
        raise AssertionError(
            "mobile approval attention wraps or covers the composer: "
            f"{mobile_layout}"
        )
    _ = page.screenshot(path=evidence / "web-390-external-approval.png")
    return {
        "phases": list(PHASES),
        "external_approval_visible": True,
        "unchanged_refresh_preserved_node": True,
        "focused_card_preserved_on_new_approval": True,
        "mobile_header_single_line": True,
        "mobile_notice_clears_composer": True,
    }
