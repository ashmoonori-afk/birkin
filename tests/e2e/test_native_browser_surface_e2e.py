"""Production surface authority: browser.start, navigate, revisions, cleanup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest

from birkin.workspace import CommandReceipt, WorkspaceCommand, WorkspaceService
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from tests import native_browser_aside_support as support

pytestmark = pytest.mark.browser_integration


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _submit(
    service: WorkspaceService,
    *,
    command_id: str,
    command_type: str,
    payload: dict[str, object],
) -> CommandReceipt:
    return service.submit(
        WorkspaceCommand.parse({
            "protocol_version": 1,
            "command_id": command_id,
            "expected_cursor": service.snapshot().cursor,
            "type": command_type,
            "payload": payload,
            "client_context": {"surface": "macos", "view_id": "browser"},
        }),
        actor_id="macos:browser",
    )


def test_production_browser_surface_starts_navigates_and_advances_revisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Given the production adapter's own surface authority, When browser.start
    then browser.navigate run against a local page, Then each committing
    command returns a receipt and advances the live surface by exactly one
    revision, an unchanged repeat start publishes no frame at all, and closing
    the adapter leaves no browser running."""
    if not support.browser_ready():
        pytest.skip("BIRKIN_BROWSER_INTEGRATION=1 and Playwright Chromium are mandatory")
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()

    with support.serve(support.FixtureHandler) as (_server, fixture_url):
        # The canonical egress gate refuses private addresses unless they are
        # named, exactly as the shipped browser harness names its own fixture.
        fixture = urlsplit(fixture_url)
        assert fixture.hostname is not None
        assert fixture.port is not None
        monkeypatch.setenv(
            "BIRKIN_BROWSER_PRIVATE_NETWORK_RULES",
            json.dumps([{
                "host": fixture.hostname,
                "cidr": "127.0.0.1/32",
                "port": fixture.port,
            }]),
        )
        service = WorkspaceService(
            root=tmp_path / "workspace", session_id="browser-e2e", handlers={}
        )
        adapter = RuntimeWorkspaceAdapter(
            "browser-e2e", service.emit, workspace_root=workspace_root
        )
        service.set_handlers(adapter.handlers())
        surfaces = adapter.surface_authority

        try:
            initial = surfaces.live_snapshot("browser_aside")
            assert initial is not None
            assert initial.revision == 1
            assert surfaces.live_snapshot("browser_aside") is None

            started = _submit(
                service,
                command_id="browser-start",
                command_type="browser.start",
                payload={},
            )
            assert started.state == "completed"
            live = surfaces.live_snapshot("browser_aside")
            assert live is not None
            assert live.revision == initial.revision + 1
            runtime = _object(_object(live.payload)["runtime"])
            profile = _object(_object(live.payload)["profile"])
            assert runtime["live"] is True

            # Starting again changes nothing, so it must publish nothing.
            restarted = _submit(
                service,
                command_id="browser-start-again",
                command_type="browser.start",
                payload={},
            )
            assert restarted.state == "completed"
            assert surfaces.live_snapshot("browser_aside") is None

            navigated = _submit(
                service,
                command_id="browser-navigate",
                command_type="browser.navigate",
                payload={
                    "url": fixture_url,
                    "generation": profile["generation"],
                    "revision": runtime["revision"],
                },
            )
            assert navigated.state == "completed"
            moved = surfaces.live_snapshot("browser_aside")
            assert moved is not None
            assert moved.revision == live.revision + 1
            navigation = _object(_object(moved.payload)["navigation"])
            display_url = navigation["display_url"]
            assert isinstance(display_url, str)
            assert display_url.startswith("http://127.0.0.1:")
        finally:
            adapter.close()

        closed_runtime = _object(surfaces.browser.snapshot()["runtime"])
        assert closed_runtime["live"] is False
