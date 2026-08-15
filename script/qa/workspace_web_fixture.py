"""Run a deterministic authenticated workspace web authority for browser QA."""

from __future__ import annotations

import os
import signal
import threading
from types import FrameType

from birkin.web import server
from script.qa.workspace_terminal_fixture import FixtureRuntimeWorkspaceAdapter


def main() -> int:
    _ = setattr(
        server,
        "RuntimeWorkspaceAdapter",
        FixtureRuntimeWorkspaceAdapter,
    )
    configured_port = os.environ.get("QA_WEB_PORT")
    port = int(configured_port) if configured_port else 0
    background = server.start_background(port)
    stopped = threading.Event()

    def stop(_signum: int, _frame: FrameType | None) -> None:
        stopped.set()

    _ = signal.signal(signal.SIGINT, stop)
    _ = signal.signal(signal.SIGTERM, stop)
    print(f"QA_WEB_URL={background.bootstrap_url}", flush=True)
    try:
        _ = stopped.wait()
    finally:
        background.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
