"""The web hub must list durable workspace sessions left by an earlier process.

The native bridge already calls ``restore_existing()``; the web factory did
not, so a browser without the old session id in localStorage saw an empty
workspace and started a new conversation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.web import server as web_server
from birkin.workspace.hub import WorkspaceHub


def test_web_hub_restores_durable_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    handlers = {"chat.send": lambda _payload: {}}
    earlier = WorkspaceHub(root=tmp_path, handlers=handlers)
    earlier.create("saved")
    earlier.close()

    monkeypatch.setattr(web_server, "_workspace_root", tmp_path, raising=False)
    monkeypatch.setattr(web_server, "_workspace_handlers", handlers, raising=False)
    monkeypatch.setattr(web_server, "_workspace_hub", None, raising=False)
    hub = web_server._get_workspace_hub()
    try:
        assert [s["session_id"] for s in hub.summaries()] == ["saved"]
    finally:
        hub.close()
