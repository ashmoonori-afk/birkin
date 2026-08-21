#!/usr/bin/env bash
# Drive the packaged application through its own controls in scripted QA mode.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
evidence="${1:-$repo_root/.omo/evidence/native-shell/phase16}"
dist="${2:-$evidence/dist}"
case "$(uname -m)" in
  arm64) helper_architecture=arm64 ;;
  x86_64) helper_architecture=x86_64 ;;
  *) echo "unsupported packaged journey architecture" >&2; exit 2 ;;
esac
bridge_helper="$dist/Birkin.app/Contents/Helpers/$helper_architecture/birkin-native-bridge"
unset BIRKIN_NATIVE_BRIDGE_COMMAND
unset BIRKIN_NATIVE_BRIDGE_ARGUMENTS
unset BIRKIN_NATIVE_BRIDGE_OPTIONS
# A Unix socket path is platform bounded, so the runtime root stays short.
root="$(mktemp -d /private/tmp/bk-journey-XXXXXX)"
browser_pid=""
browser_started_pid="0"
app_pid=""
app_started_pid="0"
cleanup_started=0
bridge_pattern="$bridge_helper native-bridge serve --transport uds"

stop_app() {
  if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
    kill -TERM "$app_pid" 2>/dev/null || true
    wait "$app_pid" 2>/dev/null || true
  fi
  app_pid=""
}
stop_browser_fixture() {
  if [[ -n "$browser_pid" ]] && kill -0 "$browser_pid" 2>/dev/null; then
    kill -TERM "$browser_pid" 2>/dev/null || true
    wait "$browser_pid" 2>/dev/null || true
  fi
  browser_pid=""
}
stop_orphaned_bridge() {
  local pids
  pids="$(pgrep -f "$bridge_pattern" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    kill -TERM $pids 2>/dev/null || true
    pids="$(pgrep -f "$bridge_pattern" 2>/dev/null || true)"
    [[ -z "$pids" ]] || kill -KILL $pids 2>/dev/null || true
  fi
}
cleanup() {
  local status=$?
  if [[ "$cleanup_started" -eq 1 ]]; then
    exit "$status"
  fi
  cleanup_started=1
  trap - EXIT HUP INT TERM
  set +e
  stop_app
  stop_browser_fixture
  stop_orphaned_bridge
  rm -rf "$root"

  local app_running=no browser_running=no bridge_processes
  if [[ "$app_started_pid" != "0" ]] && kill -0 "$app_started_pid" 2>/dev/null; then
    app_running=yes
  fi
  if [[ "$browser_started_pid" != "0" ]] && kill -0 "$browser_started_pid" 2>/dev/null; then
    browser_running=yes
  fi
  bridge_processes="$(pgrep -f "$bridge_pattern" 2>/dev/null | wc -l | tr -d ' ')"
  mkdir -p "$evidence"
  {
    echo "failure_mode=${BIRKIN_NATIVE_JOURNEY_FORCE_FAILURE:-none}"
    echo "root=$root"
    echo "root_exists=$([[ -e "$root" ]] && echo yes || echo no)"
    echo "app_pid=$app_started_pid"
    echo "app_running=$app_running"
    echo "browser_pid=$browser_started_pid"
    echo "browser_running=$browser_running"
    echo "bridge_processes=$bridge_processes"
    echo "bridge_overrides=absent"
    echo "socket_exists=$([[ -e "$root/home/native-bridge/bridge.sock" ]] && echo yes || echo no)"
    echo "exit_status=$status"
  } > "$evidence/packaged-journey-cleanup.txt"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$evidence" "$root/home" "$root/workspace"
printf '{"provider":"codex-cli","model":"default","auto_approve":[],"self_improve":false,"checkpoints":false}' > "$root/home/config.json"

browser_ready="$root/browser-ready"
mkfifo "$browser_ready"
/usr/bin/python3 -u - > "$browser_ready" <<'PY' &
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
browser_started_pid="$browser_pid"
IFS= read -r browser_url < "$browser_ready"
rm -f "$browser_ready"
browser_authority="${browser_url#http://}"
browser_authority="${browser_authority%%/*}"
browser_port="${browser_authority##*:}"
[[ "$browser_port" =~ ^[0-9]+$ ]] || {
  echo "invalid Browser fixture URL: $browser_url" >&2
  exit 1
}
case "${BIRKIN_NATIVE_JOURNEY_FORCE_FAILURE:-}" in
  after-fixture) exit 97 ;;
  signal-term) kill -TERM "$$" ;;
  "") ;;
  *) echo "unknown forced failure mode" >&2; exit 96 ;;
esac

[[ -x "$bridge_helper" ]] || {
  echo "packaged bridge helper is missing: $bridge_helper" >&2
  exit 1
}
export BIRKIN_HOME="$root/home"
export BIRKIN_NATIVE_JOURNEY=1
export BIRKIN_NATIVE_JOURNEY_EVIDENCE="$evidence"
export BIRKIN_NATIVE_JOURNEY_WORKSPACE="$root/home/native-bridge"
export BIRKIN_NATIVE_JOURNEY_BROWSER_URL="$browser_url"
export BIRKIN_NATIVE_SCREENSHOT="$evidence/packaged-journey-shell.png"
export BIRKIN_BROWSER_INTEGRATION=1
export BIRKIN_BROWSER_PRIVATE_NETWORK_RULES="[{\"host\":\"127.0.0.1\",\"cidr\":\"127.0.0.1/32\",\"port\":$browser_port}]"
unset BIRKIN_NATIVE_SOCKET

(
  cd "$root/workspace"
  "$bridge_helper" native-bridge provider-probe \
    --provider codex-cli --model default \
    --output "$evidence/provider-probe.json"
) > "$evidence/provider-probe.log" 2>&1

launch_cwd="$PWD"
cd "$root/workspace"
"$dist/Birkin.app/Contents/MacOS/BirkinNativeApp" \
  > "$evidence/packaged-journey-events.log" 2>&1 &
app_pid=$!
cd "$launch_cwd"
app_started_pid="$app_pid"
set +e
wait "$app_pid"
status=$?
set -e
app_pid=""
stop_browser_fixture

/usr/bin/python3 "$repo_root/scripts/native/verify_packaged_journey.py" \
  "$evidence" "$bridge_helper" "$root/workspace"

echo "journey_exit=$status"
echo "bridge_processes=$(pgrep -f "$bridge_pattern" | wc -l | tr -d ' ')"
echo "socket_exists=$([[ -e "$root/home/native-bridge/bridge.sock" ]] && echo yes || echo no)"
exit "$status"
