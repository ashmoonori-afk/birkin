#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
package_root="$repo_root/macos/BirkinNativeApp"
inputs="$repo_root/scripts/native/bridge_helper_inputs.json"
build_lock="$repo_root/scripts/native/bridge_helper_build.lock"
cache_root="${BIRKIN_HELPER_CACHE:-$package_root/.build/helper-cache}"

json_value() {
  local python=python3
  command -v "$python" >/dev/null 2>&1 || python=python
  "$python" -c \
    'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); [value := value[key] for key in sys.argv[2].split(".")]; print(str(value).lower() if isinstance(value, bool) else value)' \
    "$inputs" "$1"
}

verify_inputs() {
  local schema python_version python_build architecture url checksum
  local python locked_version package_version expected_hash actual_hash
  local project_input project_path
  schema="$(json_value schema)"
  python_version="$(json_value python.version)"
  python_build="$(json_value python.build)"
  [[ "$schema" == "1" && -n "$python_version" && -n "$python_build" ]]
  for architecture in arm64 x86_64; do
    url="$(json_value "python.artifacts.$architecture.url")"
    checksum="$(json_value "python.artifacts.$architecture.sha256")"
    [[ "$url" == https://github.com/astral-sh/python-build-standalone/releases/download/* ]]
    [[ "$checksum" =~ ^[0-9a-f]{64}$ ]]
  done
  grep -q '^pyinstaller==6\.22\.2 \\' "$build_lock"
  for project_input in pyproject uv_lock; do
    expected_hash="$(json_value "project.${project_input}_sha256")"
    case "$project_input" in
      pyproject) project_path="$repo_root/pyproject.toml" ;;
      uv_lock) project_path="$repo_root/uv.lock" ;;
    esac
    actual_hash="$(shasum -a 256 "$project_path" | awk '{print $1}')"
    [[ "$expected_hash" =~ ^[0-9a-f]{64}$ ]]
    [[ "$actual_hash" == "$expected_hash" ]]
  done
  python=python3
  command -v "$python" >/dev/null 2>&1 || python=python
  locked_version="$("$python" - "$repo_root/uv.lock" <<'PY'
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

with open(sys.argv[1], "rb") as lock_file:
    lock = tomllib.load(lock_file)
packages = lock.get("package", [])
project = next(
    package
    for package in packages
    if package.get("name") == "birkin"
    and package.get("source") == {"editable": "."}
)
print(project["version"])
PY
)"
  package_version="$(
    awk -F'"' '/^version = /{print $2; exit}' "$repo_root/pyproject.toml"
  )"
  [[ "$locked_version" == "$package_version" ]]
  printf '{"architectures":["arm64","x86_64"],'
  printf '"package_version":"%s","python_build":"%s",' \
    "$package_version" "$python_build"
  printf '"python_version":"%s","schema":%s}\n' "$python_version" "$schema"
}

if [[ "${1:-}" == "--verify-inputs" ]]; then
  verify_inputs
  exit 0
fi

if [[ "$#" -ne 1 ]]; then
  echo "usage: build_bridge_helpers.sh <Contents/Helpers>" >&2
  exit 2
fi

verify_inputs >/dev/null
destination="$1"
work="$(mktemp -d /private/tmp/bk-helper-build-XXXXXX)"
trap 'rm -rf "$work"' EXIT HUP INT TERM
mkdir -p "$cache_root" "$destination"

uv export --directory "$repo_root" --locked --no-dev \
  --extra browser --extra office --no-emit-project --no-annotate --no-header \
  --format requirements.txt --output-file "$work/runtime.lock" >/dev/null
cat > "$work/entry.py" <<'PY'
from birkin.cli import main

raise SystemExit(main())
PY

fetch_runtime() {
  local architecture="$1" url="$2" checksum="$3"
  local archive="$cache_root/cpython-$architecture.tar.gz"
  if [[ -f "$archive" ]] && ! printf '%s  %s\n' "$checksum" "$archive" \
      | shasum -a 256 -c - >/dev/null 2>&1; then
    rm -f "$archive"
  fi
  if [[ ! -f "$archive" ]]; then
    [[ "${BIRKIN_HELPER_OFFLINE:-0}" != "1" ]] || {
      echo "missing cached $architecture Python runtime in offline build" >&2
      exit 1
    }
    curl --fail --location --retry 3 --output "$archive.partial" "$url"
    printf '%s  %s\n' "$checksum" "$archive.partial" | shasum -a 256 -c -
    mv "$archive.partial" "$archive"
  fi
  printf '%s  %s\n' "$checksum" "$archive" | shasum -a 256 -c -
}

build_architecture() {
  local architecture="$1" url="$2" checksum="$3"
  local stage="$work/$architecture" runtime python site_packages arch_flag helper
  local binary
  local -a pyinstaller_args
  fetch_runtime "$architecture" "$url" "$checksum"
  stage="$work/$architecture"
  runtime="$stage/runtime"
  mkdir -p "$runtime" "$stage/dist" "$stage/spec" "$stage/work"
  tar -xzf "$cache_root/cpython-$architecture.tar.gz" \
    -C "$runtime" --strip-components=1
  python="$runtime/bin/python3"
  while IFS= read -r -d '' binary; do
    case "$(/usr/bin/file -b "$binary")" in
      Mach-O*) /usr/bin/codesign --force --sign - "$binary" ;;
    esac
  done < <(/usr/bin/find "$runtime" -type f -perm -111 -print0)
  /usr/bin/codesign --verify "$python"
  uv pip install --python "$python" --require-hashes --only-binary :all: \
    --requirements "$build_lock"
  uv pip install --python "$python" --only-binary :all: \
    --requirements "$work/runtime.lock"
  site_packages="$runtime/lib/python3.13/site-packages"
  cp -R "$repo_root/birkin" "$site_packages/birkin"
  find "$site_packages/birkin" -type d -name __pycache__ -prune -exec rm -rf {} +
  find "$site_packages/birkin" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
  mkdir -p "$site_packages/birkin/_bundled_skills"
  cp -R "$repo_root/skills/." "$site_packages/birkin/_bundled_skills/"
  case "$architecture" in
    arm64) arch_flag=-arm64 ;;
    x86_64) arch_flag=-x86_64 ;;
    *) echo "unsupported helper architecture: $architecture" >&2; exit 2 ;;
  esac
  pyinstaller_args=(
    --clean --noconfirm --onefile
    --name birkin-native-bridge
    --distpath "$stage/dist" --workpath "$stage/work" --specpath "$stage/spec"
    --collect-submodules birkin --collect-data birkin --collect-all playwright
    --collect-all docx --collect-all hwpx --collect-all openpyxl --collect-all pptx
  )
  if [[ -n "${BIRKIN_SIGN_IDENTITY:-}" ]]; then
    pyinstaller_args+=(--codesign-identity "$BIRKIN_SIGN_IDENTITY")
  fi
  (
    cd "$stage"
    SOURCE_DATE_EPOCH="$(git -C "$repo_root" show -s --format=%ct HEAD)" \
      PYTHONHASHSEED=0 arch "$arch_flag" "$python" -m PyInstaller \
      "${pyinstaller_args[@]}" "$work/entry.py"
  )
  helper="$stage/dist/birkin-native-bridge"
  mkdir -p "$destination/$architecture"
  cp "$helper" "$destination/$architecture/birkin-native-bridge"
  chmod 0755 "$destination/$architecture/birkin-native-bridge"
  [[ "$(lipo -archs "$destination/$architecture/birkin-native-bridge")" \
      == "$architecture" ]]
}

for architecture in arm64 x86_64; do
  build_architecture \
    "$architecture" \
    "$(json_value "python.artifacts.$architecture.url")" \
    "$(json_value "python.artifacts.$architecture.sha256")"
done
