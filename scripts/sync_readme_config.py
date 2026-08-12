"""Synchronize provider defaults in both README configuration examples."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from birkin.config import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parent.parent
READMES = (ROOT / "README.md", ROOT / "README.ko.md")
DEFAULT_KEYS = ("provider", "model", "subagent_model")


def _sync(text: str) -> str:
    pattern = re.compile(r"```json\r?\n(?P<body>.*?\r?\n)```", re.DOTALL)

    def replace(match: re.Match[str]) -> str:
        body = match.group("body")
        if not re.search(r'^\s*"provider":', body, re.MULTILINE):
            return match.group(0)
        for key in DEFAULT_KEYS:
            value = json.dumps(DEFAULT_CONFIG[key])
            body = re.sub(
                rf'^(\s*"{key}":\s*).*?(,?)$',
                rf"\g<1>{value}\2",
                body,
                count=1,
                flags=re.MULTILINE,
            )
        return f"```json\n{body}```"

    return pattern.sub(replace, text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    for path in READMES:
        original = path.read_text(encoding="utf-8")
        updated = _sync(original)
        if updated == original:
            continue
        if args.check:
            stale.append(path.name)
        else:
            path.write_text(updated, encoding="utf-8")
    if stale:
        print("README config defaults are stale: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
