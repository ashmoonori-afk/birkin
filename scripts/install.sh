#!/usr/bin/env bash
# birkin installer (macOS / Linux / WSL).
#
#   curl -fsSL https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.sh | bash
#
# Installs the `birkin` command using uv (preferred), pipx, or pip --user.
set -euo pipefail

REPO="${BIRKIN_REPO:-https://github.com/ashmoonori-afk/birkin}"
REF="${BIRKIN_REF:-main}"
SPEC="git+${REPO}@${REF}"

echo "==> Installing birkin from ${SPEC}"

if command -v uv >/dev/null 2>&1; then
  echo "    using uv"
  uv tool install --force "$SPEC"
elif command -v pipx >/dev/null 2>&1; then
  echo "    using pipx"
  pipx install --force "$SPEC"
elif command -v python3 >/dev/null 2>&1; then
  echo "    using pip (--user)"
  python3 -m pip install --user --upgrade "$SPEC"
else
  echo "!! Need one of: uv, pipx, or python3. Install Python 3.10+ first." >&2
  exit 1
fi

echo
echo "==> Done. Quick start:"
echo "    export ANTHROPIC_API_KEY=sk-ant-...   # your key"
echo "    birkin                                 # start chatting"
echo "    birkin web                             # open the dashboard"
echo "    birkin daemon                          # nightly 04:00 self-improvement"
echo
if ! command -v birkin >/dev/null 2>&1; then
  echo "Note: if 'birkin' is not found, ensure your tool bin dir is on PATH"
  echo "      (uv: ~/.local/bin, pipx: ~/.local/bin)."
fi
