#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Birkin — One-click launcher for macOS / Linux
#
# Double-click this file (or run ./start.sh) to:
#   1. Verify Python 3.11+ is installed
#   2. Create a virtual environment (if needed)
#   3. Install dependencies
#   4. Launch Birkin
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# Resolve the directory this script lives in (handles symlinks)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

# ── Colours (safe for terminals that don't support them) ─────
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

info()  { printf "${CYAN}[birkin]${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}[birkin]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[birkin]${NC} %s\n" "$*"; }
fail()  { printf "${RED}[birkin]${NC} %s\n" "$*"; exit 1; }

# ── Find a suitable Python ───────────────────────────────────
find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver="$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)" || continue
            local major minor
            major="${ver%%.*}"
            minor="${ver##*.}"
            if [ "$major" -ge "$MIN_PYTHON_MAJOR" ] && [ "$minor" -ge "$MIN_PYTHON_MINOR" ]; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON="$(find_python)" || fail \
    "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required but was not found.
    Install it from https://www.python.org/downloads/ and try again."

info "Using $($PYTHON --version) at $(command -v "$PYTHON")"

# ── Virtual environment ──────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment in $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created."
fi

# Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── Dependencies ─────────────────────────────────────────────
if [ ! -f "$VENV_DIR/.deps_installed" ]; then
    info "Installing dependencies (first run — this may take a minute) ..."
    pip install --upgrade pip --quiet
    pip install -e ".[all]" --quiet 2>/dev/null || pip install -e "." --quiet
    touch "$VENV_DIR/.deps_installed"
    ok "Dependencies installed."
else
    info "Dependencies already installed. To re-install, delete $VENV_DIR/.deps_installed"
fi

# ── Launch ───────────────────────────────────────────────────
HOST="${BIRKIN_HOST:-127.0.0.1}"
PORT="${BIRKIN_PORT:-8321}"
URL="http://${HOST}:${PORT}"

echo ""
printf "${BOLD}───────────────────────────────────────${NC}\n"
printf "${BOLD}  Birkin${NC} WebUI starting ...            \n"
printf "${BOLD}  ${CYAN}${URL}${NC}                      \n"
printf "${BOLD}───────────────────────────────────────${NC}\n"
echo ""

# Auto-open browser after a short delay
(sleep 2 && open "$URL" 2>/dev/null || xdg-open "$URL" 2>/dev/null) &

birkin serve --host "$HOST" --port "$PORT"
