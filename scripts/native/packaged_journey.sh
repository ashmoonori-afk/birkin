#!/usr/bin/env bash
# Drive the packaged application through its own controls in scripted QA mode.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
evidence="${1:-$repo_root/.omo/evidence/native-shell/phase16}"
dist="${2:-$evidence/dist}"
# A Unix socket path is platform bounded, so the runtime root stays short.
root="$(mktemp -d /private/tmp/bk-journey-XXXXXX)"

mkdir -p "$evidence" "$root/home" "$root/bridge"
printf '{"auto_approve": ["shell"]}' > "$root/home/config.json"

export BIRKIN_HOME="$root/home"
export BIRKIN_NATIVE_BRIDGE_COMMAND="$repo_root/.venv/bin/python3"
export BIRKIN_NATIVE_BRIDGE_ARGUMENTS="-m birkin"
export BIRKIN_NATIVE_BRIDGE_OPTIONS="--root $root/bridge --session-id packaged-journey"
export BIRKIN_NATIVE_JOURNEY=1
export BIRKIN_NATIVE_JOURNEY_EVIDENCE="$evidence"
export BIRKIN_NATIVE_JOURNEY_WORKSPACE="$root/bridge"
export BIRKIN_NATIVE_SCREENSHOT="$evidence/packaged-journey-shell.png"
unset BIRKIN_NATIVE_SOCKET

set +e
"$dist/Birkin.app/Contents/MacOS/BirkinNativeApp" > "$evidence/packaged-journey-events.log" 2>&1
status=$?
set -e

"$repo_root/.venv/bin/python3" - "$evidence" <<'VERIFY'
import hashlib, json, sys
from pathlib import Path

evidence = Path(sys.argv[1])
receipts = json.loads((evidence / "packaged-journey-receipts.json").read_text())
required = {
    "connected", "session-create", "chat-send-stream", "terminal-create-lease",
    "terminal-input-output", "activity-receipts", "browser-navigate-live",
    "office-create-live", "office-open-live", "computer-use-status",
    "jailed-import-chip", "owned-bridge-restart-replay", "post-reconnect-command",
}
names = {step["name"] for step in receipts["steps"]}
missing = required - names
if missing:
    raise SystemExit(f"missing journey steps: {sorted(missing)}")
failed = [step["name"] for step in receipts["steps"] if not step["succeeded"]]
if failed:
    raise SystemExit(f"failed journey steps: {failed}")
if not any(name in names for name in ("working-memory-clear", "working-memory-gated")):
    raise SystemExit("no Working Memory step was recorded")
digests = {}
for step in receipts["steps"]:
    shot = step["screenshot"]
    if not shot:
        continue
    data = (evidence / shot).read_bytes()
    if len(data) < 4000:
        raise SystemExit(f"{shot} is not a contentful screenshot")
    digests.setdefault(hashlib.sha256(data).hexdigest(), []).append(shot)
if len(digests) < 3:
    raise SystemExit(f"journey screenshots are not distinct: {digests}")
print(f"journey_steps={len(receipts['steps'])} screenshots={sum(len(v) for v in digests.values())} distinct_screenshots={len(digests)}")
VERIFY

echo "journey_exit=$status"
echo "bridge_processes=$(pgrep -f "native-bridge serve --transport uds --root $root/bridge" | wc -l | tr -d ' ')"
echo "socket_exists=$([[ -e "$root/bridge/bridge.sock" ]] && echo yes || echo no)"
rm -rf "$root"
exit "$status"
