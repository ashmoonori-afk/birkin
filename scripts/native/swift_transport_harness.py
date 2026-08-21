#!/usr/bin/env python3
"""One-connection real native endpoint for Swift transport integration tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from birkin import __version__
from birkin.native.capability import BootstrapSecretStore
from birkin.native.endpoint import NativeBridgeEndpoint
from birkin.native.server import NativeBridgeServer
from birkin.workspace import TerminalAuthority, WorkspaceCommand, WorkspaceService
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("uds", "loopback"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--terminal", action="store_true")
    parser.add_argument("--j1-fixture", action="store_true")
    parser.add_argument("--connections", type=int, default=1)
    parser.add_argument("--session-id", default="session-1")
    args = parser.parse_args()
    if args.connections < 1 or args.connections > 8:
        parser.error("--connections must be between 1 and 8")

    session_id = args.session_id
    server_version = os.environ.get("BIRKIN_TEST_NATIVE_SERVER_VERSION", __version__)
    source = WorkspaceService(
        root=args.root / "workspace",
        session_id=session_id,
        handlers={},
    )
    terminal: TerminalAuthority | None = None
    adapter: RuntimeWorkspaceAdapter | None = None
    if args.j1_fixture:
        if args.terminal:
            parser.error("--j1-fixture and --terminal cannot be combined")

        def answer_first_message(payload: dict[str, object]) -> dict[str, object]:
            text = payload.get("text")
            if not isinstance(text, str):
                raise ValueError("J1 fixture requires message text")
            source.emit("message.user", {"text": text})
            source.emit(
                "message.assistant.completed",
                {"text": "The native packaged app is connected to Python authority."},
            )
            return {"fixture": "j1"}

        adapter = RuntimeWorkspaceAdapter(
            session_id, source.emit, workspace_root=args.root / "workspace-root"
        )
        handlers = dict(adapter.handlers())
        handlers["chat.send"] = answer_first_message
        source.set_handlers(handlers)
        source.submit(
            WorkspaceCommand.parse({
                "protocol_version": 1,
                "command_id": "phase13-j1",
                "expected_cursor": 0,
                "type": "chat.send",
                "payload": {"text": "Render the first native answer"},
                "client_context": {"surface": "test", "view_id": "phase13"},
            }),
            actor_id="test:phase13",
        )
    if args.terminal:
        os.environ["BIRKIN_HOME"] = str(args.root / "home")
        terminal = TerminalAuthority(
            session_id=session_id,
            workspace_root=args.root,
            emit=source.emit,
            config_loader=lambda: {"auto_approve": ["shell"]},
        )
        source.set_handlers(terminal.handlers())
    if not args.j1_fixture and not args.terminal:
        adapter = RuntimeWorkspaceAdapter(
            session_id, source.emit, workspace_root=args.root / "workspace-root"
        )
        source.set_handlers(adapter.handlers())
    capabilities = BootstrapSecretStore(args.root / "native")
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="swift-integration-instance",
        server_version=server_version,
        on_disconnect=(
            terminal.revoke_leases
            if terminal is not None
            else adapter.revoke_terminal_leases
            if adapter is not None
            else None
        ),
        surface_authority=adapter.surface_authority if adapter is not None else None,
    )
    socket_path = args.root / "bridge.sock"
    endpoint = (
        NativeBridgeEndpoint.uds(bridge, socket_path=socket_path)
        if args.transport == "uds"
        else NativeBridgeEndpoint.loopback(
            bridge,
            capabilities=capabilities,
            instance_id="swift-integration-instance",
            server_version=server_version,
        )
    )
    try:
        readiness: dict[str, object] = {
            "event": "listening",
            "transport": args.transport,
            "pid": __import__("os").getpid(),
            "root": str(args.root),
        }
        if args.transport == "uds":
            readiness["socket_path"] = str(socket_path)
        else:
            readiness["discovery_path"] = str(capabilities.endpoint_path)
        print(json.dumps(readiness, separators=(",", ":")), flush=True)
        for _ in range(args.connections):
            endpoint.serve_once()
    finally:
        endpoint.close()
        if terminal is not None:
            terminal.close_all()
        if adapter is not None:
            adapter.close()
        print(
            json.dumps(
                {
                    "event": "cleaned",
                    "socket_exists": socket_path.exists(),
                    "discovery_exists": capabilities.endpoint_path.exists(),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
