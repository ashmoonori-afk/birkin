#!/usr/bin/env bash
# Drive the packaged application through its own controls in scripted QA mode.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
evidence="${1:-$repo_root/.omo/evidence/native-shell/phase16}"
dist="${2:-$evidence/dist}"
operator_home="${HOME:?HOME must identify the existing-account credential owner}"
operator_codex_home="${CODEX_HOME:-$operator_home/.codex}"
clean_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
case "$(uname -m)" in
  arm64) helper_architecture=arm64 ;;
  x86_64) helper_architecture=x86_64 ;;
  *) echo "unsupported packaged journey architecture" >&2; exit 2 ;;
esac
case "$(uname -s)" in
  Darwin) process_event_backend=kqueue ;;
  Linux) process_event_backend=pidfd ;;
  *) echo "packaged journey cleanup requires Darwin kqueue or Linux pidfd" >&2; exit 2 ;;
esac
bridge_helper="$dist/Birkin.app/Contents/Helpers/$helper_architecture/birkin-native-bridge"
unset BIRKIN_NATIVE_BRIDGE_COMMAND
unset BIRKIN_NATIVE_BRIDGE_ARGUMENTS
unset BIRKIN_NATIVE_BRIDGE_OPTIONS
# A Unix socket path is platform bounded, so the runtime root stays short.
root="$(mktemp -d /private/tmp/bk-journey-XXXXXX)"
browser_pid="" browser_started_pid="0" browser_group_id=""
app_pid="" app_started_pid="0" app_group_id=""
cleanup_started=0
bridge_pattern="$bridge_helper native-bridge serve --transport uds"

terminate_process_group() {
  local group_id="$1"
  [[ -n "$group_id" ]] || return 0
  /usr/bin/python3 - "$group_id" "$process_event_backend" <<'PY'
import errno, os, select, signal, subprocess, sys, time

process_group = int(sys.argv[1])
backend = sys.argv[2]

def subscribe(pid: int):
    if backend == "kqueue":
        watcher = select.kqueue()
        event = select.kevent(pid, filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
            fflags=select.KQ_NOTE_EXIT)
        watcher.control([event], 0, 0)
        return watcher
    descriptor = os.pidfd_open(pid)
    watcher = select.poll()
    watcher.register(descriptor, select.POLLIN)
    return descriptor, watcher


def await_exits(pending: set[int], timeout: float) -> set[int]:
    deadline, remaining = time.monotonic() + timeout, set()
    for pid in pending:
        wait = max(0.0, deadline - time.monotonic())
        watcher = watches[pid]
        observed = (bool(watcher.control(None, 1, wait)) if backend == "kqueue"
                    else bool(watcher[1].poll(max(0, int(wait * 1000)))))
        if not observed:
            remaining.add(pid)
    return remaining


if backend == "pidfd" and not hasattr(os, "pidfd_open"):
    raise RuntimeError("Linux cleanup requires os.pidfd_open")
output = subprocess.run(
    ["/bin/ps", "-axo", "pid=,pgid="], check=True, capture_output=True, text=True
).stdout
pids = {int(fields[0]) for line in output.splitlines()
        if len(fields := line.split()) == 2 and int(fields[1]) == process_group}
watches = {}
for pid in pids:
    try:
        watches[pid] = subscribe(pid)
    except OSError as error:
        if error.errno != errno.ESRCH:
            raise
pending = set(watches)
try:
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if not pending:
            break
        try:
            os.killpg(process_group, signum)
        except ProcessLookupError:
            pass
        pending = await_exits(pending, 5.0)
    raise SystemExit(1 if pending else 0)
finally:
    for watcher in watches.values():
        watcher.close() if backend == "kqueue" else os.close(watcher[0])
PY
}

stop_app() {
  terminate_process_group "$app_group_id"
  local cleanup_status=$?
  if [[ -n "$app_pid" ]]; then
    wait "$app_pid" 2>/dev/null || true
  fi
  app_pid=""
  app_group_id=""
  return "$cleanup_status"
}
stop_browser_fixture() {
  terminate_process_group "$browser_group_id"
  local cleanup_status=$?
  if [[ -n "$browser_pid" ]]; then
    wait "$browser_pid" 2>/dev/null || true
  fi
  browser_pid=""
  browser_group_id=""
  return "$cleanup_status"
}
stop_owned_bridges() {
  local pid group_id groups="" cleanup_status=0
  while IFS= read -r pid; do
    group_id="$(/bin/ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
    [[ -n "$group_id" ]] || continue
    case " $groups " in
      *" $group_id "*) continue ;;
    esac
    groups="$groups $group_id"
    terminate_process_group "$group_id" || cleanup_status=1
  done < <(pgrep -f "$bridge_pattern" 2>/dev/null || true)
  return "$cleanup_status"
}
cleanup() {
  local status=$?
  if [[ "$cleanup_started" -eq 1 ]]; then
    exit "$status"
  fi
  cleanup_started=1
  trap - EXIT HUP INT TERM
  set +e
  local cleanup_status=0
  stop_app || cleanup_status=1
  stop_owned_bridges || cleanup_status=1
  stop_browser_fixture || cleanup_status=1
  rm -rf "$root"
  if [[ "$cleanup_status" -ne 0 ]]; then
    status=1
  fi

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
    echo "process_event_backend=$process_event_backend"
    echo "bridge_overrides=absent"
    echo "home=$HOME"
    echo "home_exists=$([[ -e "$HOME" ]] && echo yes || echo no)"
    echo "search_path=$PATH"
    echo "socket_exists=$([[ -e "$root/home/native-bridge/bridge.sock" ]] && echo yes || echo no)"
    echo "exit_status=$status"
  } > "$evidence/packaged-journey-cleanup.txt"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$evidence" "$root/home" "$root/workspace" "$root/empty-home"
printf '{"provider":"codex-cli","model":"default","auto_approve":[],"self_improve":false,"checkpoints":false}' > "$root/home/config.json"
export HOME="$root/empty-home"
export CODEX_HOME="$operator_codex_home"
export PATH="$clean_path"

browser_ready="$root/browser-ready"
mkfifo "$browser_ready"
/usr/bin/python3 -u - > "$browser_ready" <<'PY' &
import http.server
import os

os.setsid()

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
browser_group_id="$browser_pid"
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
/usr/bin/python3 -c \
  'import os, sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])' \
  "$dist/Birkin.app/Contents/MacOS/BirkinNativeApp" \
  > "$evidence/packaged-journey-events.log" 2>&1 &
app_pid=$!
cd "$launch_cwd"
app_started_pid="$app_pid"
app_group_id="$app_pid"
set +e
wait "$app_pid"
status=$?
set -e
stop_app
stop_owned_bridges
stop_browser_fixture

/usr/bin/python3 "$repo_root/scripts/native/verify_packaged_journey.py" \
  "$evidence" "$bridge_helper" "$root/workspace"

echo "journey_exit=$status"
echo "bridge_processes=$(pgrep -f "$bridge_pattern" | wc -l | tr -d ' ')"
echo "socket_exists=$([[ -e "$root/home/native-bridge/bridge.sock" ]] && echo yes || echo no)"
exit "$status"
