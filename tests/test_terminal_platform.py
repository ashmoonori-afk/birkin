from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import psutil
import pytest

from birkin.config_model import Config
from birkin.workspace import owned_terminal as owned_terminal_module
from birkin.workspace.contracts import TerminalUnsupported
from birkin.workspace.owned_terminal import TerminalAuthority


@pytest.mark.skipif(sys.platform != "win32", reason="Windows capability advertisement")
def test_terminal_handlers_are_advertised_when_conpty_is_supported(
    tmp_path: Path,
) -> None:
    from birkin.workspace.windows_conpty import conpty_supported

    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=lambda _event_type, _payload: None,
        config_loader=lambda: cast(Config, {"auto_approve": ["shell"]}),
    )

    assert conpty_supported()
    assert set(terminal.handlers()) == {
        "terminal.create",
        "terminal.input",
        "terminal.resize",
        "terminal.signal",
        "terminal.close",
        "terminal.snapshot",
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ConPTY lifecycle")
def test_windows_natural_exit_emits_exactly_one_terminal_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a real Windows authority subscribed before terminal creation
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    events: list[tuple[str, dict[str, object]]] = []
    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=tmp_path,
        emit=lambda kind, payload: events.append((kind, payload)),
        config_loader=lambda: cast(Config, {"auto_approve": ["shell"]}),
    )
    opened = terminal.create({"actor_kind": "native_human", "cwd": str(tmp_path)})
    raw_pid = opened["pid"]
    assert isinstance(raw_pid, int) and not isinstance(raw_pid, bool)
    process = psutil.Process(raw_pid)
    try:
        # When the shell exits naturally
        _ = terminal.input({
            "terminal_id": opened["terminal_id"],
            "lease": opened["lease"],
            "sequence": 1,
            "data": "exit\r\n",
        })
        # Then process EOF is bounded and one canonical exit is emitted
        _ = process.wait(timeout=10)
        assert sum(kind == "terminal.exited" for kind, _ in events) == 1
    finally:
        terminal.close_all()


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
    monkeypatch.setattr(owned_terminal_module, "_WINDOWS", False)

    assert terminal.handlers() == {}
    with pytest.raises(TerminalUnsupported):
        _ = terminal.create({
            "actor_kind": "native_human",
            "cwd": str(tmp_path),
        })
