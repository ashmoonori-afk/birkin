#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
output_root="${1:-$repo_root/.omo/evidence/native-shell/phase13/dist}"
app="$output_root/Birkin.app"
# The package manifest is the single source of the shipped version.
version="$(awk -F'"' '/^version = /{print $2; exit}' "$repo_root/pyproject.toml")"
if [[ -z "$version" ]]; then
  echo "could not read the project version from pyproject.toml" >&2
  exit 1
fi
dmg="$output_root/Birkin-$version.dmg"
manifest="$repo_root/.omo/evidence/native-shell/phase13/artifact-manifest.sha256"
build_manifest="$repo_root/.omo/evidence/native-shell/phase13/build-manifest.txt"

cd "$repo_root"
if [[ ! -d "$app" ]]; then
  scripts/native/package_macos_app.sh "$output_root"
fi
rm -f "$dmg"
hdiutil create -volname Birkin -srcfolder "$app" -ov -format UDZO "$dmg"
mkdir -p "$(dirname "$manifest")"
binary_hash="$(shasum -a 256 "$app/Contents/MacOS/BirkinNativeApp" | awk '{print $1}')"
dmg_hash="$(shasum -a 256 "$dmg" | awk '{print $1}')"
{
  echo "$binary_hash  Birkin.app/Contents/MacOS/BirkinNativeApp"
  echo "$dmg_hash  $(basename "$dmg")"
} > "$manifest"
version="$(awk -F= '/^version=/{print $2}' "$output_root/packaging-report.txt")"
signing_mode="$(awk -F= '/^signing_mode=/{print $2}' "$output_root/packaging-report.txt")"
{
  echo "python_package_version=$version"
  echo "app_version=$version"
  echo "app_build=1"
  echo "local_protocol_version=1"
  echo "architectures=$(lipo -archs "$app/Contents/MacOS/BirkinNativeApp")"
  echo "signing_mode=$signing_mode"
  echo "app_binary_sha256=$binary_hash"
  echo "dmg_sha256=$dmg_hash"
} > "$build_manifest"
cat "$manifest"
cat "$build_manifest"
echo "dmg=$dmg"
echo "manifest=$manifest"
echo "build_manifest=$build_manifest"
