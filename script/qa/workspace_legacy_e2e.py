"""Exercise deprecated UI redirects and preserved APIs on a live server."""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".omo" / "evidence" / "unified-workspace"


def _request(
    port: int,
    method: str,
    path: str,
    *,
    token: str | None = None,
    cookie: str | None = None,
    host: str = "127.0.0.1",
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers = {"Host": host}
    if token is not None:
        headers["X-Birkin-Token"] = token
    if cookie is not None:
        headers["Cookie"] = cookie
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(payload))
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def run() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="birkin-legacy-e2e-"))
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
    checks: list[dict[str, object]] = []
    try:
        if server.stdout is None:
            raise RuntimeError("legacy fixture stdout is unavailable")
        first_line = cast(str, server.stdout.readline())
        server_log += first_line
        match = re.search(r"QA_WEB_URL=(\S+)", first_line)
        if match is None:
            raise AssertionError(f"invalid legacy fixture output: {first_line}")
        bootstrap_url = match.group(1)
        parsed = urlsplit(bootstrap_url)
        port = parsed.port
        if port is None:
            raise AssertionError("legacy fixture URL lacks a port")
        token = parsed.path.rsplit("/", 1)[-1]

        for path in ("/legacy-dashboard", "/dashboard", "/workbench"):
            code, headers, response_body = _request(port, "GET", path)
            expected = {
                "Location": "/",
                "Deprecation": "true",
                "Link": '</>; rel="successor-version"',
            }
            if code != 308 or response_body or any(
                headers.get(name) != value for name, value in expected.items()
            ):
                raise AssertionError(
                    f"legacy redirect changed: {path}, {code}, {headers}"
                )
            checks.append({"path": path, "status": code, **expected})

        code, _, _ = _request(
            port,
            "GET",
            "/dashboard",
            host="attacker.example",
        )
        if code != 403:
            raise AssertionError("legacy redirect bypassed Host gate")
        checks.append({"path": "/dashboard", "bad_host": code})

        code, headers, _ = _request(port, "GET", parsed.path)
        if code != 303 or headers.get("Location") != "/":
            raise AssertionError("bootstrap redirect contract changed")
        cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
        if not cookie:
            raise AssertionError("bootstrap capability cookie is missing")
        code, _, root = _request(port, "GET", "/", cookie=cookie)
        if code != 200 or b'data-testid="workspace-shell"' not in root:
            raise AssertionError("root is not the unified workspace")
        checks.append({"path": "/", "status": code, "workspace": True})

        for path in (
            "/api/status",
            "/api/jobs",
            "/api/runs",
            "/api/skills",
            "/api/contract",
        ):
            code, _, body = _request(port, "GET", path)
            if code != 200 or not body:
                raise AssertionError(f"public backend changed: {path}")
            checks.append({"path": path, "status": code})

        for path in (
            "/api/events",
            "/api/config",
            "/api/checkpoints",
            "/api/approvals",
        ):
            unauthenticated, _, _ = _request(port, "GET", path)
            code, _, body = _request(port, "GET", path, token=token)
            if unauthenticated != 403 or code != 200 or not body:
                raise AssertionError(
                    f"protected backend boundary changed: {path}"
                )
            checks.append(
                {
                    "path": path,
                    "unauthenticated": unauthenticated,
                    "authenticated": code,
                }
            )

        code, _, _ = _request(
            port,
            "POST",
            "/api/workspace/sessions",
            token="invalid",
            body={"session_id": "legacy-live"},
        )
        if code != 403:
            raise AssertionError("invalid workspace capability was accepted")
        code, _, body = _request(
            port,
            "POST",
            "/api/workspace/sessions",
            token=token,
            body={"session_id": "legacy-live"},
        )
        if code != 201:
            raise AssertionError(f"workspace session creation failed: {body!r}")
        code, _, body = _request(
            port,
            "GET",
            "/api/workspace/sessions/legacy-live/snapshot",
            token=token,
        )
        raw_snapshot = cast(object, json.loads(body))
        if not isinstance(raw_snapshot, dict):
            raise TypeError("workspace snapshot must be an object")
        snapshot = cast(dict[str, object], raw_snapshot)
        if code != 200 or snapshot["session_id"] != "legacy-live":
            raise AssertionError("workspace snapshot authority changed")
        checks.append(
            {
                "path": "/api/workspace/sessions/legacy-live/snapshot",
                "status": code,
                "cursor": snapshot["cursor"],
            }
        )
    finally:
        server.terminate()
        try:
            remainder, _ = server.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            remainder, _ = server.communicate(timeout=10)
        server_log += remainder
        shutil.rmtree(profile, ignore_errors=True)

    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise AssertionError("legacy fixture port remained open")
    metadata = {
        "server_pid": server.pid,
        "port": port,
        "checks": checks,
        "server_exited": server.returncode == 0,
        "profile_path": str(profile),
        "profile_removed": not profile.exists(),
    }
    _ = (EVIDENCE / "legacy-api-e2e.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _ = (EVIDENCE / "legacy-api-server.log").write_text(
        server_log,
        encoding="utf-8",
    )
    print("Legacy compatibility QA passed: redirects/auth/backend/workspace")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
