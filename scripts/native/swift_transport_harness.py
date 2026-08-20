#!/usr/bin/env python3
"""One-connection real native endpoint for Swift transport integration tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from birkin.native.capability import BootstrapSecretStore
from birkin.native.endpoint import NativeBridgeEndpoint
from birkin.native.server import NativeBridgeServer
from birkin.workspace import WorkspaceService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("uds", "loopback"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    source = WorkspaceService(
        root=args.root / "workspace",
        session_id="session-1",
        handlers={},
    )
    capabilities = BootstrapSecretStore(args.root / "native")
    bridge = NativeBridgeServer(
        source,
        capabilities=capabilities,
        instance_id="swift-integration-instance",
        server_version="1.0.0",
    )
    socket_path = args.root / "bridge.sock"
    endpoint = (
        NativeBridgeEndpoint.uds(bridge, socket_path=socket_path)
        if args.transport == "uds"
        else NativeBridgeEndpoint.loopback(
            bridge,
            capabilities=capabilities,
            instance_id="swift-integration-instance",
            server_version="1.0.0",
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
        endpoint.serve_once()
    finally:
        endpoint.close()
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
