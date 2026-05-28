#!/usr/bin/env bash
# Run birkin's live-LLM smoke suite.
#
# Requires one of:
#   - ANTHROPIC_API_KEY in the environment (native tool-calling loop tested)
#   - `claude` (Claude Code) on PATH and logged in
#   - `codex` on PATH and logged in
#
# Usage:  bash scripts/smoke_live.sh
set -euo pipefail

if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && ! command -v claude >/dev/null 2>&1 \
        && ! command -v codex >/dev/null 2>&1; then
    echo "FAIL: no backend available (need ANTHROPIC_API_KEY or claude/codex CLI)" >&2
    exit 2
fi

export BIRKIN_LIVE=1
echo "→ running live tests…"
if pytest -m live --no-header -q "$@"; then
    echo "PASS: live suite green"
else
    echo "FAIL: live suite failed" >&2
    exit 1
fi
