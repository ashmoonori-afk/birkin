"""Compatibility entry point for the exact cross-surface evidence scenario."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from script.qa.workspace_handoff_e2e import run


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
    )
    args = parser.parse_args()
    return run(cast(Path, args.evidence_dir).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
