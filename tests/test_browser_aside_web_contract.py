from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from birkin.web import server as web_server

_INDEX = (
    Path(__file__).parents[1]
    / "birkin"
    / "web"
    / "static"
    / "index.html"
)
_TAG = re.compile(r"<(/?)([a-z][a-z0-9-]*)([^>]*)>", re.IGNORECASE)
_ID = re.compile(r'\bid="([^"]+)"')
_VOID = frozenset({"input", "meta", "link", "br", "img"})


def _audit(
    source: str,
) -> tuple[dict[str, tuple[str | None, ...]], int]:
    stack: list[tuple[str, str | None]] = []
    parents: dict[str, tuple[str | None, ...]] = {}
    iframe_count = 0
    markup = source.split("<script>", maxsplit=1)[0]
    for match in _TAG.finditer(markup):
        closing, tag, attrs = match.groups()
        normalized = tag.lower()
        if closing:
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == normalized:
                    del stack[index:]
                    break
            continue
        id_match = _ID.search(attrs)
        element_id = id_match.group(1) if id_match else None
        if element_id is not None:
            parents[element_id] = tuple(parent for _, parent in stack)
        if normalized == "iframe":
            iframe_count += 1
        if normalized not in _VOID:
            stack.append((normalized, element_id))
    return parents, iframe_count


def test_browser_aside_reuses_shared_theme_tokens() -> None:
    source = _INDEX.read_text(encoding="utf-8")
    start = source.index(".browser-toggle")
    end = source.index(".ledger {", start)
    browser_css = source[start:end]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", browser_css)
    for token in (
        "birkin-accent",
        "birkin-border-muted",
        "birkin-focus-ring",
        "birkin-text",
        "birkin-muted",
        "birkin-surface",
        "birkin-surface-raised",
        "birkin-error",
    ):
        assert f"var(--{token})" in browser_css
    for legacy_token in (
        "surface",
        "surface-elevated",
        "text-primary",
        "text-muted",
        "accent",
        "selection",
    ):
        assert f"var(--{legacy_token})" not in browser_css


def test_browser_aside_is_nested_in_existing_workspace_shell() -> None:
    source = _INDEX.read_text(encoding="utf-8")
    parents, iframe_count = _audit(source)
    assert source.count('<div class="app">') == 1
    assert iframe_count == 0
    assert "browser-aside" not in parents["browser-aside-toggle"]
    assert "workspace-shell" in parents["browser-aside"]
    assert "browser-aside" in parents["browser-aside-canvas"]


def test_browser_aside_exposes_semantic_status_and_frame_polling() -> None:
    source = _INDEX.read_text(encoding="utf-8")
    assert 'aria-live="polite"' in source
    assert 'data-state="closed"' in source
    assert "browser-state-glyph" in source
    assert "scheduleBrowserFramePoll" in source
    assert '"/api/browser-aside/status"' in source
    assert "browser-aside-frame" in source
    assert "status.control_owner_kind" in source


def test_browser_aside_uses_unified_workspace_theme_contract() -> None:
    from birkin import workspace_theme

    contract = web_server.workspace_contract()
    exported = cast(dict[str, object], contract["workspace_theme"])
    assert set(cast(dict[str, object], exported["palettes"])) == {
        "studio_dark",
        "paper_light",
        "high_contrast",
    }
    assert exported == workspace_theme.contract()
    source = _INDEX.read_text(encoding="utf-8")
    start = source.index(".browser-toggle")
    end = source.index(".ledger {", start)
    browser_css = source[start:end]
    for role in (
        "accent",
        "border-muted",
        "text",
        "muted",
        "surface",
        "surface-raised",
        "focus-ring",
        "error",
    ):
        assert f"var(--birkin-{role})" in browser_css
