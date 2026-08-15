"""Orchestrate deterministic server, Playwright, evidence, and cleanup."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from birkin import config

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".omo" / "evidence" / "unified-workspace"
SCREENSHOTS = {
    "web-1440-default.png": (1440, 900),
    "web-1440-approval.png": (1440, 900),
    "web-1440-question.png": (1440, 900),
    "web-1440-evidence.png": (1440, 900),
    "web-1440-checkpoint.png": (1440, 900),
    "web-1440-checkpoint-detail.png": (1440, 900),
    "web-1440-checkpoint-restored.png": (1440, 900),
    "web-1024-light.png": (1024, 800),
    "web-390-contrast-panel.png": (390, 844),
    "web-390-reconnect.png": (390, 844),
}


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path.name} is not a PNG")
    return struct.unpack(">II", data[16:24])


def _server_url(process: subprocess.Popen[str]) -> tuple[str, str]:
    if process.stdout is None:
        raise RuntimeError("fixture server stdout is unavailable")
    line = cast(str, process.stdout.readline())
    match = re.search(r"QA_WEB_URL=(\S+)", line)
    if match is None:
        raise AssertionError(f"invalid fixture server output: {line}")
    return match.group(1), line


def _run_driver(url: str, evidence: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv executable is unavailable")
    driver = subprocess.run(
        [
            uv,
            "run",
            "--with",
            "playwright",
            "python",
            "-c",
            (
                "from pathlib import Path;"
                "from script.qa.workspace_web_playwright import run;"
                "raise SystemExit(run("
                f"{url!r},Path({str(evidence)!r})))"
            ),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
        check=False,
    )
    if driver.returncode != 0:
        raise AssertionError(
            f"Playwright driver exited {driver.returncode}\n{driver.stdout}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--base-url")
    _ = parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE,
    )
    args = parser.parse_args()
    evidence = cast(Path, args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    base_value = cast(object, args.base_url)
    if base_value is not None and not isinstance(base_value, str):
        raise TypeError("base URL must be a string")
    if base_value:
        token: object = os.environ.get("BIRKIN_HTTP_TOKEN")
        if token is None:
            raw_record = cast(
                object,
                json.loads(
                    (
                        config.birkin_home() / "web_session.json"
                    ).read_text(encoding="utf-8")
                ),
            )
            if not isinstance(raw_record, dict):
                raise RuntimeError("web discovery record is invalid")
            record = cast(dict[str, object], raw_record)
            token = record.get("token")
        if not isinstance(token, str):
            raise RuntimeError("web discovery token is unavailable")
        base_url = base_value.rstrip("/")
        url = f"{base_url}/_bootstrap/{token}"
        _run_driver(url, evidence)
        for name, expected in SCREENSHOTS.items():
            actual = _png_dimensions(evidence / name)
            if actual != expected:
                raise AssertionError(
                    f"{name}: expected {expected}, got {actual}"
                )
        print(
            "Playwright workspace QA passed: "
            + "desktop/tablet/mobile/question/evidence/checkpoint/reload/interrupt"
        )
        return 0

    profile = Path(tempfile.mkdtemp(prefix="birkin-web-e2e-"))
    env = os.environ.copy()
    env["BIRKIN_HOME"] = str(profile)
    server = subprocess.Popen(
        [sys.executable, "-m", "script.qa.workspace_web_fixture"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    server_log = ""
    url = ""
    try:
        url, first_line = _server_url(server)
        server_log += first_line
        _run_driver(url, evidence)
        for name, expected in SCREENSHOTS.items():
            actual = _png_dimensions(evidence / name)
            if actual != expected:
                raise AssertionError(f"{name}: expected {expected}, got {actual}")
    finally:
        server.terminate()
        try:
            remainder, _ = server.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            remainder, _ = server.communicate(timeout=10)
        server_log += remainder
        shutil.rmtree(profile, ignore_errors=True)

    metadata_path = evidence / "browser-e2e.json"
    raw_metadata = cast(
        object,
        json.loads(metadata_path.read_text(encoding="utf-8")),
    )
    if not isinstance(raw_metadata, dict):
        raise TypeError("browser metadata must be an object")
    metadata = cast(dict[str, object], raw_metadata)
    port_match = re.search(r":(\d+)/", url)
    if port_match is None:
        raise AssertionError("browser fixture URL did not contain a port")
    metadata.update(
        {
            "server_pid": server.pid,
            "port": int(port_match.group(1)),
            "profile_path": str(profile),
            "server_exited": server.returncode == 0,
            "profile_removed": not profile.exists(),
        }
    )
    _ = metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _ = (evidence / "browser-server.log").write_text(
        server_log,
        encoding="utf-8",
    )
    print(
        "Playwright workspace QA passed: "
        + "desktop/tablet/mobile/question/evidence/checkpoint/reload/interrupt"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
