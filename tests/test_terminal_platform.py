from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from birkin.config_model import Config
from birkin.workspace import owned_terminal as owned_terminal_module
from birkin.workspace.contracts import TerminalUnsupported
from birkin.workspace.owned_terminal import TerminalAuthority


def test_terminal_refuses_without_darwin_containment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=lambda _event_type, _payload: None,
        config_loader=lambda: cast(Config, {"auto_approve": ["shell"]}),
    )
    monkeypatch.setattr(owned_terminal_module, "_DARWIN", False)

    assert terminal.handlers() == {}
    with pytest.raises(TerminalUnsupported):
        _ = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
