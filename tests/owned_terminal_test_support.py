from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from birkin.workspace.owned_terminal import TerminalAuthority

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="owned terminal behavior requires Darwin containment",
)
windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="owned Windows terminal behavior requires ConPTY containment",
)


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def __call__(self, kind: str, payload: dict[str, object]) -> Any:
        self.events.append((kind, payload))
        return payload


def authority(tmp_path: Path, recorder: EventRecorder, cfg: dict[str, Any]) -> TerminalAuthority:
    return TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=recorder,
        config_loader=lambda: cfg,
    )
