#!/usr/bin/env bash
# Drive the packaged application through its own controls in scripted QA mode.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
evidence="${1:-$repo_root/.omo/evidence/native-shell/phase16}"
dist="${2:-$evidence/dist}"
# A Unix socket path is platform bounded, so the runtime root stays short.
root="$(mktemp -d /private/tmp/bk-journey-XXXXXX)"
browser_pid=""

stop_browser_fixture() {
  if [[ -n "$browser_pid" ]] && kill -0 "$browser_pid" 2>/dev/null; then
    kill "$browser_pid"
    wait "$browser_pid" 2>/dev/null || true
  fi
  browser_pid=""
}
cleanup() {
  stop_browser_fixture
  rm -rf "$root"
}
trap cleanup EXIT

mkdir -p "$evidence" "$root/home" "$root/bridge"
printf '{}' > "$root/home/config.json"

browser_ready="$root/browser-ready"
mkfifo "$browser_ready"
"$repo_root/.venv/bin/python3" -u - > "$browser_ready" <<'PY' &
import http.server

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><h1>BIRKIN PACKAGED JOURNEY</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass

server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(f"http://127.0.0.1:{server.server_port}/packaged-journey", flush=True)
server.serve_forever()
PY
browser_pid=$!
IFS= read -r browser_url < "$browser_ready"
rm -f "$browser_ready"
browser_authority="${browser_url#http://}"
browser_authority="${browser_authority%%/*}"
browser_port="${browser_authority##*:}"
[[ "$browser_port" =~ ^[0-9]+$ ]] || {
  echo "invalid Browser fixture URL: $browser_url" >&2
  exit 1
}

export BIRKIN_HOME="$root/home"
export BIRKIN_NATIVE_BRIDGE_COMMAND="$repo_root/.venv/bin/python3"
export BIRKIN_NATIVE_BRIDGE_ARGUMENTS="-m birkin"
export BIRKIN_NATIVE_BRIDGE_OPTIONS="--root $root/bridge --session-id packaged-journey"
export BIRKIN_NATIVE_JOURNEY=1
export BIRKIN_NATIVE_JOURNEY_EVIDENCE="$evidence"
export BIRKIN_NATIVE_JOURNEY_WORKSPACE="$root/bridge"
export BIRKIN_NATIVE_JOURNEY_BROWSER_URL="$browser_url"
export BIRKIN_NATIVE_SCREENSHOT="$evidence/packaged-journey-shell.png"
export BIRKIN_BROWSER_INTEGRATION=1
export BIRKIN_BROWSER_PRIVATE_NETWORK_RULES="[{\"host\":\"127.0.0.1\",\"cidr\":\"127.0.0.1/32\",\"port\":$browser_port}]"
unset BIRKIN_NATIVE_SOCKET

set +e
"$dist/Birkin.app/Contents/MacOS/BirkinNativeApp" > "$evidence/packaged-journey-events.log" 2>&1
status=$?
set -e
stop_browser_fixture

"$repo_root/.venv/bin/python3" - "$evidence" <<'VERIFY'
import hashlib, json, sys
from pathlib import Path

evidence = Path(sys.argv[1])
receipts = json.loads((evidence / "packaged-journey-receipts.json").read_text())
required = {
    "connected", "session-create", "chat-send-stream",
    "terminal-approval-requested", "terminal-approval-approved",
    "terminal-create-lease", "terminal-input-output", "activity-receipts",
    "terminal-replay-refusal", "browser-start-live",
    "browser-navigate-live",
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
critical_names = {"chat-send-stream", "terminal-input-output", "jailed-import-chip"}
critical_digests = {}
for step in receipts["steps"]:
    shot = step["screenshot"]
    if not shot:
        if step["name"] in critical_names:
            raise SystemExit(f"critical step has no screenshot: {step['name']}")
        continue
    data = (evidence / shot).read_bytes()
    if len(data) < 4000:
        raise SystemExit(f"{shot} is not a contentful screenshot")
    digest = hashlib.sha256(data).hexdigest()
    digests.setdefault(digest, []).append(shot)
    if step["name"] in critical_names:
        critical_digests[step["name"]] = digest
if set(critical_digests) != critical_names:
    raise SystemExit(f"missing critical screenshot digests: {critical_digests}")
if len(set(critical_digests.values())) != len(critical_names):
    raise SystemExit(f"critical screenshots are not distinct: {critical_digests}")
if len(digests) < 3:
    raise SystemExit(f"journey screenshots are not distinct: {digests}")
print(f"journey_steps={len(receipts['steps'])} screenshots={sum(len(v) for v in digests.values())} distinct_screenshots={len(digests)}")
VERIFY

echo "journey_exit=$status"
echo "bridge_processes=$(pgrep -f "native-bridge serve --transport uds --root $root/bridge" | wc -l | tr -d ' ')"
echo "socket_exists=$([[ -e "$root/bridge/bridge.sock" ]] && echo yes || echo no)"
exit "$status"
