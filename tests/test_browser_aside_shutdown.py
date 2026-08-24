from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil


def test_run_closes_owned_chromium_processes_on_normal_exit(
    tmp_path: Path,
) -> None:
    # Given: an isolated production server with fake Chromium-owning services.
    owned_processes = tmp_path / "owned-chromium-pids"
    closed_processes = tmp_path / "closed-chromium-pids"
    worker = """
import subprocess
import sys
from pathlib import Path

from birkin import browser_aside_control
from birkin.web import server

pid_path = Path(sys.argv[1])
closed_path = Path(sys.argv[2])

class FakeBrowserAsideService:
    def __init__(self, workspace_id):
        self._process = subprocess.Popen([
            sys.executable,
            "-c",
            "from time import sleep; sleep(60)",
        ])
        with pid_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{self._process.pid}\\n")

    def close(self):
        if self._process is not None:
            process = self._process
            process.terminate()
            process.wait(timeout=5)
            with closed_path.open("a", encoding="utf-8") as stream:
                stream.write(f"{process.pid}\\n")
            self._process = None
        return {"closed": True}

class StoppingServer:
    def __init__(self, address, handler):
        self.server_address = (address[0], 54321)

    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        pass

browser_aside_control.BrowserAsideService = FakeBrowserAsideService
_ = browser_aside_control.browser_workspace_registry().resolve("owned", "web")
server.HTTPServer = StoppingServer
raise SystemExit(server.run(port=0, open_browser=False))
"""
    environment = {
        **os.environ,
        "BIRKIN_HOME": str(tmp_path / "home"),
    }

    # When: the production process exits through its normal shutdown path.
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            worker,
            str(owned_processes),
            str(closed_processes),
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    pids = [
        int(raw_pid)
        for raw_pid in owned_processes.read_text(encoding="utf-8").splitlines()
    ]
    closed_pids = (
        [
            int(raw_pid)
            for raw_pid in closed_processes.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        if closed_processes.exists()
        else []
    )

    try:
        # Then: every fake Chromium process owned by the registry is gone.
        assert completed.returncode == 0, completed.stderr
        assert pids
        assert set(closed_pids) == set(pids)
        assert all(not psutil.pid_exists(pid) for pid in pids)
    finally:
        for pid in pids:
            try:
                process = psutil.Process(pid)
            except psutil.NoSuchProcess:
                continue
            process.terminate()
            process.wait(timeout=5)
