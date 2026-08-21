"""Nothing typed at a terminal becomes durable in the clear."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from birkin.workspace import CommandReceipt, WorkspaceCommand, WorkspaceService
from birkin.workspace.owned_terminal import TerminalAuthority


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
            "client_context": {"surface": "macos", "view_id": "main"},
        }),
        actor_id="macos:main",
    )


def _result(receipt: CommandReceipt) -> dict[str, object]:
    result = receipt.transient_result
    assert isinstance(result, dict)
    return cast(dict[str, object], result)


def _journal_events(root: Path, session_id: str) -> list[dict[str, object]]:
    text = (root / session_id / "events.jsonl").read_text(encoding="utf-8")
    return [
        cast(dict[str, object], json.loads(line))
        for line in text.splitlines()
        if line.strip()
    ]


def _payload(event: dict[str, object]) -> dict[str, object]:
    payload = event["payload"]
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def test_terminal_keystrokes_never_reach_the_durable_journal(
    tmp_path: Path,
) -> None:
    """Given text typed into an owned terminal, When the input event is
    journaled, Then the durable record keeps the sequence identity and the
    redacted sentinel but never the keystrokes themselves."""
    secret = "hunter2-never-durable"
    workspace_root = tmp_path / "terminal"
    workspace_root.mkdir()
    service = WorkspaceService(
        root=tmp_path / "workspace", session_id="session-1", handlers={}
    )
    terminal = TerminalAuthority(
        session_id="session-1",
        workspace_root=workspace_root,
        emit=service.emit,
        config_loader=lambda: {"auto_approve": ["shell"]},
    )
    service.set_handlers(terminal.handlers())
    opened = _result(_submit(
        service,
        command_id="open-terminal",
        command_type="terminal.create",
        payload={"actor_kind": "native_human", "cwd": str(workspace_root)},
    ))
    try:
        _ = _submit(
            service,
            command_id="type-secret",
            command_type="terminal.input",
            payload={
                "terminal_id": opened["terminal_id"],
                "lease": opened["lease"],
                "sequence": 1,
                "data": f"read -s ignored {secret}\n",
            },
        )
    finally:
        terminal.close_all()

    typed = [
        event
        for event in _journal_events(tmp_path / "workspace", "session-1")
        if event["type"] == "terminal.input"
    ]
    assert len(typed) == 1
    payload = _payload(typed[0])
    assert "data" not in payload
    assert payload["redacted"] is True
    assert payload["terminal_id"] == opened["terminal_id"]
    assert payload["sequence"] == 1
