#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Birkin — Double-click to launch WebUI (macOS)
#
# This .command file opens in Terminal when double-clicked
# in Finder, then launches Birkin and opens the browser.
# ─────────────────────────────────────────────────────────────

# Resolve the directory this script lives in
cd "$(dirname "$0")" || exit 1

# Delegate to start.sh which handles venv, deps, and launch
exec ./start.sh
