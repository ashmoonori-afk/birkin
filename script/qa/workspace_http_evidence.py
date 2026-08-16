"""Capture raw HTTP request and response transcripts for workspace migration."""

from __future__ import annotations

import argparse
import http.client
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit


def _capture(
    base_url: str,
    method: str,
    path: str,
    headers: dict[str, str],
) -> str:
    parsed = urlsplit(base_url)
    if parsed.hostname is None or parsed.port is None:
        raise ValueError("base URL must include host and port")
    connection = http.client.HTTPConnection(
        parsed.hostname,
        parsed.port,
        timeout=5,
    )
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    body = response.read().decode("utf-8", errors="replace")
    response_headers = "\n".join(
        f"{name}: {value}" for name, value in response.getheaders()
    )
    connection.close()
    request_headers = "\n".join(
        f"{name}: {value}" for name, value in headers.items()
    )
    return (
        f"> {method} {path} HTTP/1.1\n{request_headers}\n\n"
        f"< HTTP/{response.version / 10:.1f} "
        f"{response.status} {response.reason}\n"
        f"{response_headers}\n\n{body}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--base-url", required=True)
    _ = parser.add_argument("--token", required=True)
    _ = parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
    )
    args = parser.parse_args()
    base_value = cast(object, args.base_url)
    token_value = cast(object, args.token)
    if not isinstance(base_value, str) or not isinstance(token_value, str):
        raise TypeError("base URL and token must be strings")
    base_url = base_value
    token = token_value
    evidence = cast(Path, args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)

    captures = {
        "api-contract.http.txt": _capture(
            base_url,
            "GET",
            "/api/contract",
            {
                "Host": urlsplit(base_url).netloc,
                "Authorization": f"Bearer {token}",
            },
        ),
        "legacy-dashboard.http.txt": _capture(
            base_url,
            "GET",
            "/legacy-dashboard",
            {"Host": urlsplit(base_url).netloc},
        ),
    }
    for name, capture in captures.items():
        _ = (evidence / name).write_text(
            capture + "\n",
            encoding="utf-8",
        )
    print("Raw HTTP workspace evidence captured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
