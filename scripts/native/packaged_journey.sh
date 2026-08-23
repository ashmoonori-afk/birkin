#!/usr/bin/env bash
# Drive the packaged application through its own controls in scripted QA mode.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
evidence="${1:-$repo_root/.omo/evidence/native-shell/phase16}"
dist="${2:-$evidence/dist}"
umask 077
/usr/bin/python3 - "$evidence" <<'PY'
import os
import sys

path = os.path.abspath(sys.argv[1])
flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
descriptor = os.open(os.path.sep, flags)
try:
    for component in path.split(os.path.sep)[1:]:
        try:
            os.mkdir(component, mode=0o700, dir_fd=descriptor)
        except FileExistsError:
            pass
        next_descriptor = os.open(component, flags, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = next_descriptor
    os.fchmod(descriptor, 0o700)
finally:
    os.close(descriptor)
PY

new_evidence_temp() {
  local name="$1"
  HOME=/var/empty /usr/bin/python3 - "$evidence" "$name" <<'PY'
import os
import secrets
import sys

directory, basename = sys.argv[1:]
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
directory_fd = os.open(
    directory,
    os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
)
try:
    for _ in range(32):
        name = f".{basename}.{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            continue
        os.close(descriptor)
        print(os.path.join(directory, name))
        break
    else:
        raise RuntimeError("could not allocate private evidence output")
finally:
    os.close(directory_fd)
PY
}

publish_evidence_file() {
  local temporary="$1" name="$2"
  HOME=/var/empty /usr/bin/python3 - "$evidence" "$temporary" "$name" <<'PY'
import os
import stat
import sys

directory, temporary, destination = sys.argv[1:]
if os.path.dirname(os.path.abspath(temporary)) != os.path.abspath(directory):
    raise RuntimeError("evidence temporary escaped its directory")
source = os.path.basename(temporary)
directory_fd = os.open(
    directory,
    os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
)
try:
    descriptor = os.open(
        source,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        dir_fd=directory_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("evidence temporary is not a regular file")
    finally:
        os.close(descriptor)
    os.rename(
        source,
        destination,
        src_dir_fd=directory_fd,
        dst_dir_fd=directory_fd,
    )
finally:
    os.close(directory_fd)
PY
}

operator_home="${HOME:?HOME must identify the existing-account credential owner}"
operator_codex_home="${CODEX_HOME:-$operator_home/.codex}"
clean_path="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
journey_origin="${BIRKIN_NATIVE_JOURNEY_ORIGIN:-built-app}"
case "$journey_origin" in
  built-app|mounted-dmg) ;;
  *) echo "invalid packaged journey origin: $journey_origin" >&2; exit 2 ;;
esac
ownership_token="birkin-native-journey-$$-${RANDOM}-${RANDOM}"
ownership_digest="$(
  printf '%s' "$ownership_token" |
    /usr/bin/python3 -c \
      'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
)"
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
journey_mount=""
journey_image=""
if [[ "$journey_origin" == "mounted-dmg" ]]; then
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "mounted-dmg origin requires an attached disk image" >&2
    exit 2
  fi
  if ! journey_provenance="$(
    /usr/bin/python3 - "$dist/Birkin.app" <<'PY'
import os
import plistlib
import subprocess
import sys

app = os.path.realpath(sys.argv[1])
payload = plistlib.loads(
    subprocess.check_output(["/usr/bin/hdiutil", "info", "-plist"])
)
matches = set()
writable_match = False
for image in payload.get("images", []):
    image_path = image.get("image-path")
    if not isinstance(image_path, str) or not image_path:
        continue
    for entity in image.get("system-entities", []):
        mount = entity.get("mount-point")
        if not isinstance(mount, str) or not mount:
            continue
        real_mount = os.path.realpath(mount)
        try:
            inside = os.path.commonpath((app, real_mount)) == real_mount
        except ValueError:
            inside = False
        if inside and app != real_mount:
            if image.get("writeable") is not False:
                writable_match = True
            else:
                matches.add((real_mount, os.path.realpath(image_path)))
if len(matches) != 1:
    if writable_match:
        print("__BIRKIN_WRITABLE_IMAGE__")
        raise SystemExit(0)
    raise SystemExit(1)
mount, image = matches.pop()
print(mount)
print(image)
PY
  )"; then
    echo "mounted-dmg origin requires an attached disk image" >&2
    exit 2
  fi
  if [[ "$journey_provenance" == "__BIRKIN_WRITABLE_IMAGE__" ]]; then
    echo "mounted-dmg origin requires a read-only attached disk image" >&2
    exit 2
  fi
  journey_mount="${journey_provenance%%$'\n'*}"
  journey_image="${journey_provenance#*$'\n'}"
  if [[ -z "$journey_mount" || -z "$journey_image" ||
        "$journey_mount" == "$journey_provenance" ]]; then
    echo "mounted-dmg origin requires an attached disk image" >&2
    exit 2
  fi
fi
bridge_helper="$dist/Birkin.app/Contents/Helpers/$helper_architecture/birkin-native-bridge"
unset BIRKIN_NATIVE_BRIDGE_COMMAND
unset BIRKIN_NATIVE_BRIDGE_ARGUMENTS
unset BIRKIN_NATIVE_BRIDGE_OPTIONS
# A Unix socket path is platform bounded, so the runtime root stays short.
root="$(mktemp -d /private/tmp/bk-journey-XXXXXX)"
browser_pid="" browser_started_pid="0" browser_group_id=""
app_pid="" app_started_pid="0" app_group_id=""
provider_log_tmp="" events_log_tmp=""
cleanup_started=0

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
owned_bridge_pids() {
  local line remainder pid event_log
  event_log="${events_log_tmp:-$evidence/packaged-journey-events.log}"
  [[ -f "$event_log" && ! -L "$event_log" ]] || return 0
  while IFS= read -r line; do
    case "$line" in
      *" owner_sha256=$ownership_digest"*) ;;
      *) continue ;;
    esac
    case "$line" in
      *"bridge-started kind=owned pid="*|*"bridge-restarted kind=owned pid="*)
        remainder="${line#*kind=owned pid=}"
        pid="${remainder%% *}"
        [[ "$pid" =~ ^[0-9]+$ ]] && printf '%s\n' "$pid"
        ;;
    esac
  done < "$event_log"
}
terminate_owned_bridge() {
  local pid="$1"
  /usr/bin/python3 - "$pid" "$process_event_backend" "$bridge_helper" <<'PY'
import os
import select
import shlex
import signal
import subprocess
import sys

pid = int(sys.argv[1])
backend = sys.argv[2]
helper = sys.argv[3]

try:
    if backend == "kqueue":
        watcher = select.kqueue()
        watcher.control(
            [select.kevent(
                pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                fflags=select.KQ_NOTE_EXIT,
            )],
            0,
            0,
        )
    else:
        watcher = os.pidfd_open(pid)
except (OSError, ProcessLookupError):
    raise SystemExit(0)

def close_watcher() -> None:
    watcher.close() if backend == "kqueue" else os.close(watcher)

try:
    command = subprocess.run(
        ["/bin/ps", "-o", "command=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    parts = shlex.split(command)
    if parts[:5] == [helper, "native-bridge", "serve", "--transport", "uds"]:
        pass
    elif len(parts) >= 6 and parts[1:6] == [
        helper, "native-bridge", "serve", "--transport", "uds",
    ]:
        pass
    else:
        print(f"owned bridge command mismatch for pid {pid}: {command}", file=sys.stderr)
        raise SystemExit(1)
    group = os.getpgid(pid)
    processes = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    members = {
        int(fields[0])
        for line in processes
        if len(fields := line.split()) == 2 and int(fields[1]) == group
    }
    watches = {}
    for member in members:
        try:
            if backend == "kqueue":
                member_watcher = select.kqueue()
                member_watcher.control(
                    [select.kevent(
                        member,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                        fflags=select.KQ_NOTE_EXIT,
                    )],
                    0,
                    0,
                )
            else:
                member_watcher = os.pidfd_open(member)
            watches[member] = member_watcher
        except (OSError, ProcessLookupError):
            continue
    def signal_and_wait(targets, signum):
        for member in targets:
            try:
                os.kill(member, signum)
            except ProcessLookupError:
                pass
        for member in list(targets):
            member_watcher = watches.get(member)
            if member_watcher is None:
                continue
            if backend == "kqueue":
                exited = bool(member_watcher.control(None, 1, 5.0))
            else:
                exited = bool(select.select([member_watcher], [], [], 5.0)[0])
            if exited:
                member_watcher.close() if backend == "kqueue" else os.close(member_watcher)
                del watches[member]

    children = set(watches) - {pid}
    signal_and_wait(children, signal.SIGTERM)
    signal_and_wait(set(watches) - {pid}, signal.SIGKILL)
    signal_and_wait({pid} & set(watches), signal.SIGTERM)
    signal_and_wait({pid} & set(watches), signal.SIGKILL)
    raise SystemExit(1 if watches else 0)
finally:
    close_watcher()
PY
}
stop_owned_bridges() {
  local pid cleanup_status=0
  while IFS= read -r pid; do
    terminate_owned_bridge "$pid" || cleanup_status=1
  done < <(owned_bridge_pids)
  return "$cleanup_status"
}
count_owned_bridges() {
  local pid process count=0
  while IFS= read -r pid; do
    process="$(/bin/ps eww -o command= -p "$pid" 2>/dev/null || true)"
    case "$process" in
      *"BIRKIN_NATIVE_OWNER_TOKEN=$ownership_token"*) count=$((count + 1)) ;;
    esac
  done < <(owned_bridge_pids)
  printf '%s\n' "$count"
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
  if [[ -n "$provider_log_tmp" && -f "$provider_log_tmp" ]]; then
    publish_evidence_file "$provider_log_tmp" "provider-probe.log" \
      || cleanup_status=1
    provider_log_tmp=""
  fi
  if [[ -n "$events_log_tmp" && -f "$events_log_tmp" ]]; then
    publish_evidence_file "$events_log_tmp" "packaged-journey-events.log" \
      || cleanup_status=1
    events_log_tmp=""
  fi
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
  bridge_processes="$(count_owned_bridges)"
  mkdir -p "$evidence"
  local cleanup_report_tmp
  cleanup_report_tmp="$(new_evidence_temp "packaged-journey-cleanup.txt")" || exit 1
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
  } > "$cleanup_report_tmp"
  publish_evidence_file "$cleanup_report_tmp" "packaged-journey-cleanup.txt" \
    || status=1
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
/usr/bin/env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  TMPDIR="${TMPDIR:-/tmp}" \
  /usr/bin/python3 -u - > "$browser_ready" <<'PY' &
import http.server
import os

os.setsid()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<h1>BIRKIN PACKAGED JOURNEY</h1>"
            "<p>패키지 브라우저 · 日本語 · 漢字</p>"
        ).encode("utf-8")
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
export BIRKIN_BROWSER_INTEGRATION=1
export BIRKIN_BROWSER_PRIVATE_NETWORK_RULES="[{\"host\":\"127.0.0.1\",\"cidr\":\"127.0.0.1/32\",\"port\":$browser_port}]"
unset BIRKIN_NATIVE_SOCKET

provider_log_tmp="$(new_evidence_temp "provider-probe.log")"
(
  cd "$root/workspace"
  /usr/bin/env -i \
    HOME="$HOME" \
    CODEX_HOME="$CODEX_HOME" \
    PATH="$PATH" \
    TMPDIR="${TMPDIR:-/tmp}" \
    BIRKIN_HOME="$BIRKIN_HOME" \
    "$bridge_helper" native-bridge provider-probe \
    --provider codex-cli --model default \
    --output "$evidence/provider-probe.json"
) > "$provider_log_tmp" 2>&1
publish_evidence_file "$provider_log_tmp" "provider-probe.log"
provider_log_tmp=""

launch_cwd="$PWD"
cd "$root/workspace"
events_log_tmp="$(new_evidence_temp "packaged-journey-events.log")"
/usr/bin/env -i \
  HOME="$HOME" \
  CODEX_HOME="$CODEX_HOME" \
  PATH="$PATH" \
  TMPDIR="${TMPDIR:-/tmp}" \
  BIRKIN_HOME="$BIRKIN_HOME" \
  BIRKIN_NATIVE_JOURNEY="$BIRKIN_NATIVE_JOURNEY" \
  BIRKIN_NATIVE_JOURNEY_ORIGIN="$journey_origin" \
  BIRKIN_NATIVE_JOURNEY_MOUNT="$journey_mount" \
  BIRKIN_NATIVE_JOURNEY_IMAGE="$journey_image" \
  BIRKIN_NATIVE_JOURNEY_EVIDENCE="$BIRKIN_NATIVE_JOURNEY_EVIDENCE" \
  BIRKIN_NATIVE_JOURNEY_WORKSPACE="$BIRKIN_NATIVE_JOURNEY_WORKSPACE" \
  BIRKIN_NATIVE_JOURNEY_BROWSER_URL="$BIRKIN_NATIVE_JOURNEY_BROWSER_URL" \
  BIRKIN_NATIVE_OWNER_TOKEN="$ownership_token" \
  BIRKIN_BROWSER_INTEGRATION="$BIRKIN_BROWSER_INTEGRATION" \
  BIRKIN_BROWSER_PRIVATE_NETWORK_RULES="$BIRKIN_BROWSER_PRIVATE_NETWORK_RULES" \
  /usr/bin/python3 -c \
  'import os, sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])' \
  "$dist/Birkin.app/Contents/MacOS/BirkinNativeApp" \
  -ApplePersistenceIgnoreState YES \
  > "$events_log_tmp" 2>&1 &
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
publish_evidence_file "$events_log_tmp" "packaged-journey-events.log"
events_log_tmp=""

/usr/bin/python3 "$repo_root/scripts/native/verify_packaged_journey.py" \
  "$evidence" "$bridge_helper" "$root/workspace"

echo "journey_exit=$status"
echo "bridge_processes=$(count_owned_bridges)"
echo "socket_exists=$([[ -e "$root/home/native-bridge/bridge.sock" ]] && echo yes || echo no)"
exit "$status"
