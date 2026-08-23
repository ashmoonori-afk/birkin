#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
inputs="$repo_root/scripts/native/bridge_helper_inputs.json"
cache_root="${BIRKIN_BROWSER_CACHE:-$repo_root/macos/BirkinNativeApp/.build/browser-cache}"

json_value() {
  local python=python3
  command -v "$python" >/dev/null 2>&1 || python=python
  "$python" -c \
    'import json,sys; value=json.load(open(sys.argv[1], encoding="utf-8")); [value := value[key] for key in sys.argv[2].split(".")]; print(str(value).lower() if isinstance(value, bool) else value)' \
    "$inputs" "$1"
}

verify_inputs() {
  local architecture component url checksum size
  [[ "$(json_value browser.playwright_version)" == "1.62.0" ]] || {
    echo "invalid Playwright version" >&2
    return 1
  }
  [[ "$(json_value browser.chromium_revision)" =~ ^[0-9]+$ ]] || {
    echo "invalid Chromium revision" >&2
    return 1
  }
  [[ "$(json_value browser.ffmpeg_revision)" =~ ^[0-9]+$ ]] || {
    echo "invalid FFmpeg revision" >&2
    return 1
  }
  for architecture in arm64 x86_64; do
    for component in headless_shell ffmpeg; do
      url="$(json_value "browser.artifacts.$architecture.$component.url")"
      checksum="$(json_value "browser.artifacts.$architecture.$component.sha256")"
      size="$(json_value "browser.artifacts.$architecture.$component.size_bytes")"
      [[ "$url" == https://cdn.playwright.dev/* ]] || {
        echo "invalid $architecture $component browser URL" >&2
        return 1
      }
      [[ "$checksum" =~ ^[0-9a-f]{64}$ ]] || {
        echo "invalid $architecture $component browser checksum" >&2
        return 1
      }
      [[ "$size" =~ ^[1-9][0-9]+$ ]] || {
        echo "invalid $architecture $component browser size" >&2
        return 1
      }
    done
  done
  printf '{"architectures":["arm64","x86_64"],'
  printf '"chromium_revision":"%s","ffmpeg_revision":"%s",' \
    "$(json_value browser.chromium_revision)" \
    "$(json_value browser.ffmpeg_revision)"
  printf '"playwright_version":"%s"}\n' \
    "$(json_value browser.playwright_version)"
}

fetch_artifact() {
  local architecture="$1" component="$2" url checksum size archive
  url="$(json_value "browser.artifacts.$architecture.$component.url")"
  checksum="$(json_value "browser.artifacts.$architecture.$component.sha256")"
  size="$(json_value "browser.artifacts.$architecture.$component.size_bytes")"
  archive="$cache_root/$architecture-$component.zip"
  if [[ -f "$archive" ]] && {
    [[ "$(stat -f %z "$archive")" != "$size" ]] ||
      ! printf '%s  %s\n' "$checksum" "$archive" | shasum -a 256 -c - >/dev/null 2>&1
  }; then
    rm -f "$archive"
  fi
  if [[ ! -f "$archive" ]]; then
    [[ "${BIRKIN_HELPER_OFFLINE:-0}" != "1" ]] || {
      echo "missing cached $architecture $component browser runtime" >&2
      exit 1
    }
    curl --fail --location --retry 3 --output "$archive.partial" "$url"
    [[ "$(stat -f %z "$archive.partial")" == "$size" ]]
    printf '%s  %s\n' "$checksum" "$archive.partial" | shasum -a 256 -c -
    mv "$archive.partial" "$archive"
  fi
  printf '%s  %s\n' "$checksum" "$archive" | shasum -a 256 -c - >/dev/null
}

extract_architecture() {
  local architecture="$1" chromium_revision ffmpeg_revision root shell_directory
  chromium_revision="$(json_value browser.chromium_revision)"
  ffmpeg_revision="$(json_value browser.ffmpeg_revision)"
  root="$work/output/$architecture"
  shell_directory=chrome-headless-shell-mac-arm64
  [[ "$architecture" == x86_64 ]] && shell_directory=chrome-headless-shell-mac-x64
  mkdir -p \
    "$root/chromium_headless_shell-$chromium_revision" \
    "$root/ffmpeg-$ffmpeg_revision"
  unzip -q "$cache_root/$architecture-headless_shell.zip" \
    -d "$root/chromium_headless_shell-$chromium_revision"
  unzip -q "$cache_root/$architecture-ffmpeg.zip" \
    -d "$root/ffmpeg-$ffmpeg_revision"
  for directory in \
    "$root/chromium_headless_shell-$chromium_revision" \
    "$root/ffmpeg-$ffmpeg_revision"; do
    : > "$directory/INSTALLATION_COMPLETE"
    : > "$directory/DEPENDENCIES_VALIDATED"
  done
  chmod 0755 \
    "$root/chromium_headless_shell-$chromium_revision/$shell_directory/chrome-headless-shell" \
    "$root/ffmpeg-$ffmpeg_revision/ffmpeg-mac"
  [[ -z "$(find "$root" -type l -print -quit)" ]]
  [[ "$(lipo -archs "$root/chromium_headless_shell-$chromium_revision/$shell_directory/chrome-headless-shell")" == "$architecture" ]]
  [[ "$(lipo -archs "$root/ffmpeg-$ffmpeg_revision/ffmpeg-mac")" == "$architecture" ]]
}

if [[ "${1:-}" == "--verify-inputs" ]]; then
  verify_inputs || exit $?
  exit 0
fi
if [[ "$#" -ne 1 ]]; then
  echo "usage: build_browser_runtimes.sh <Contents/Resources/BrowserRuntimes>" >&2
  exit 2
fi
verify_inputs >/dev/null || exit $?
destination="$1"
work="$(mktemp -d /private/tmp/bk-browser-build-XXXXXX)"
trap 'rm -rf "$work"' EXIT HUP INT TERM
mkdir -p "$cache_root" "$work/output"
for architecture in arm64 x86_64; do
  fetch_artifact "$architecture" headless_shell
  fetch_artifact "$architecture" ffmpeg
  extract_architecture "$architecture"
done
rm -rf "$destination"
mkdir -p "$destination"
cp -R "$work/output/." "$destination/"
