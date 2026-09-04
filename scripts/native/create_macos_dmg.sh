#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
output_root="${1:-$repo_root/.omo/evidence/native-shell/phase13/dist}"
app="$output_root/Birkin.app"
# The package manifest is the single source of the shipped version.
package_version="$(awk -F'"' '/^version = /{print $2; exit}' "$repo_root/pyproject.toml")"
if [[ -z "$package_version" ]]; then
  echo "could not read the project version from pyproject.toml" >&2
  exit 1
fi
dmg="$output_root/Birkin-$package_version.dmg"
# Manifests describe this distribution, so they live beside it.
manifest="$output_root/artifact-manifest.sha256"
build_manifest="$output_root/build-manifest.txt"
symbols_manifest="$output_root/Birkin-$package_version-symbols-manifest.txt"
symbols_zip="$output_root/Birkin-$package_version-symbols.zip"
symbols_checksum="$output_root/Birkin-$package_version-symbols.zip.sha256"

collect_uuids() {
  /usr/bin/dwarfdump --uuid "$1" |
    awk '{
      architecture=$3
      gsub(/[()]/, "", architecture)
      print architecture "=" tolower($2)
    }' |
    LC_ALL=C sort
}

cd "$repo_root"
if [[ ! -d "$app" ]]; then
  scripts/native/package_macos_app.sh "$output_root"
fi
mkdir -p "$(dirname "$manifest")"
binary_hash="$(shasum -a 256 "$app/Contents/MacOS/BirkinNativeApp" | awk '{print $1}')"
arm_helper_hash="$(shasum -a 256 "$app/Contents/Helpers/arm64/birkin-native-bridge" | awk '{print $1}')"
x86_helper_hash="$(shasum -a 256 "$app/Contents/Helpers/x86_64/birkin-native-bridge" | awk '{print $1}')"
helper_manifest_hash="$(shasum -a 256 "$app/Contents/Resources/bridge-helper.json" | awk '{print $1}')"
icon_file="$(plutil -extract CFBundleIconFile raw -o - "$app/Contents/Info.plist")"
[[ "$icon_file" == "Birkin.icns" ]]
icon_hash="$(shasum -a 256 "$app/Contents/Resources/$icon_file" | awk '{print $1}')"
reported_icon_hash="$(awk -F= '/^icon_sha256=/{print $2}' "$output_root/packaging-report.txt")"
[[ "$icon_hash" == "$reported_icon_hash" ]]
[[ -f "$symbols_manifest" && -f "$symbols_zip" && -f "$symbols_checksum" ]]
(cd "$output_root" && shasum -a 256 -c "$(basename "$symbols_checksum")")
binary_uuids="$(collect_uuids "$app/Contents/MacOS/BirkinNativeApp")"
symbols_uuids="$(collect_uuids "$output_root/BirkinNativeApp.dSYM")"
cmp -s <(printf '%s\n' "$binary_uuids") <(printf '%s\n' "$symbols_uuids") || {
  echo "Refusing DMG: application and private symbol UUIDs differ" >&2
  exit 1
}
manifest_arm64_uuid="$(awk -F= '/^arm64_uuid=/{print $2}' "$symbols_manifest")"
manifest_x86_64_uuid="$(awk -F= '/^x86_64_uuid=/{print $2}' "$symbols_manifest")"
[[ "$binary_uuids" == *"arm64=$manifest_arm64_uuid"* ]]
[[ "$binary_uuids" == *"x86_64=$manifest_x86_64_uuid"* ]]
[[ -z "$(find "$app" -name '*.dSYM' -print -quit)" ]] || {
  echo "Refusing DMG: application contains a dSYM" >&2
  exit 1
}
browser_chromium="$(awk -F= '/^browser_chromium_revision=/{print $2}' "$output_root/packaging-report.txt")"
browser_ffmpeg="$(awk -F= '/^browser_ffmpeg_revision=/{print $2}' "$output_root/packaging-report.txt")"
arm_browser_root="$app/Contents/Resources/BrowserRuntimes/arm64"
x86_browser_root="$app/Contents/Resources/BrowserRuntimes/x86_64"
arm_browser_identity="$(uv run python -m birkin.bundled_browser "$arm_browser_root")"
x86_browser_identity="$(uv run python -m birkin.bundled_browser "$x86_browser_root")"
arm_browser_hash="$(printf '%s' "$arm_browser_identity" | plutil -extract sha256 raw -o - -)"
x86_browser_hash="$(printf '%s' "$x86_browser_identity" | plutil -extract sha256 raw -o - -)"
arm_browser_size="$(printf '%s' "$arm_browser_identity" | plutil -extract size_bytes raw -o - -)"
x86_browser_size="$(printf '%s' "$x86_browser_identity" | plutil -extract size_bytes raw -o - -)"
arm_browser_executable="Contents/Resources/BrowserRuntimes/arm64/chromium_headless_shell-$browser_chromium/chrome-headless-shell-mac-arm64/chrome-headless-shell"
x86_browser_executable="Contents/Resources/BrowserRuntimes/x86_64/chromium_headless_shell-$browser_chromium/chrome-headless-shell-mac-x64/chrome-headless-shell"
arm_ffmpeg_executable="Contents/Resources/BrowserRuntimes/arm64/ffmpeg-$browser_ffmpeg/ffmpeg-mac"
x86_ffmpeg_executable="Contents/Resources/BrowserRuntimes/x86_64/ffmpeg-$browser_ffmpeg/ffmpeg-mac"
app_version="$(awk -F= '/^version=/{print $2}' "$output_root/packaging-report.txt")"
helper_version="$(awk -F= '/^helper_version=/{print $2}' "$output_root/packaging-report.txt")"
helper_python_version="$(awk -F= '/^helper_python_version=/{print $2}' "$output_root/packaging-report.txt")"
helper_python_build="$(awk -F= '/^helper_python_build=/{print $2}' "$output_root/packaging-report.txt")"
helper_source_revision="$(awk -F= '/^helper_source_revision=/{print $2}' "$output_root/packaging-report.txt")"
helper_source_state="$(awk -F= '/^helper_source_state=/{print $2}' "$output_root/packaging-report.txt")"
helper_inputs_hash="$(awk -F= '/^helper_inputs_sha256=/{print $2}' "$output_root/packaging-report.txt")"
reported_arm_hash="$(awk -F= '/^helper_arm64_sha256=/{print $2}' "$output_root/packaging-report.txt")"
reported_x86_hash="$(awk -F= '/^helper_x86_64_sha256=/{print $2}' "$output_root/packaging-report.txt")"
reported_manifest_hash="$(awk -F= '/^helper_manifest_sha256=/{print $2}' "$output_root/packaging-report.txt")"
reported_arm_browser_hash="$(awk -F= '/^browser_arm64_sha256=/{print $2}' "$output_root/packaging-report.txt")"
reported_x86_browser_hash="$(awk -F= '/^browser_x86_64_sha256=/{print $2}' "$output_root/packaging-report.txt")"
reported_arm_browser_size="$(awk -F= '/^browser_arm64_size_bytes=/{print $2}' "$output_root/packaging-report.txt")"
reported_x86_browser_size="$(awk -F= '/^browser_x86_64_size_bytes=/{print $2}' "$output_root/packaging-report.txt")"
browser_playwright="$(awk -F= '/^browser_playwright_version=/{print $2}' "$output_root/packaging-report.txt")"
signing_mode="$(awk -F= '/^signing_mode=/{print $2}' "$output_root/packaging-report.txt")"
[[ "$app_version" == "$package_version" ]]
[[ "$helper_version" == "$package_version" ]]
[[ "$arm_helper_hash" == "$reported_arm_hash" ]]
[[ "$x86_helper_hash" == "$reported_x86_hash" ]]
[[ "$helper_manifest_hash" == "$reported_manifest_hash" ]]
[[ "$arm_browser_hash" == "$reported_arm_browser_hash" ]]
[[ "$x86_browser_hash" == "$reported_x86_browser_hash" ]]
[[ "$arm_browser_size" == "$reported_arm_browser_size" ]]
[[ "$x86_browser_size" == "$reported_x86_browser_size" ]]
[[ "$helper_inputs_hash" =~ ^[0-9a-f]{64}$ ]]
if [[ "$helper_source_state" != "clean" && "${BIRKIN_ALLOW_DIRTY_PACKAGE:-0}" != "1" ]]; then
  echo "Refusing a disk image from a dirty helper package" >&2
  exit 1
fi
rm -f "$dmg"
app_size_kib="$(du -sk "$app" | awk '{print $1}')"
image_size_kib="$((app_size_kib + 262144))"
hdiutil create -volname Birkin -srcfolder "$app" \
  -size "${image_size_kib}k" -fs HFS+ -ov -format UDZO "$dmg"

mount_dir="$(mktemp -d "$output_root/.dmg-mount.XXXXXX")"
cleanup_mount() {
  hdiutil detach "$mount_dir" >/dev/null 2>&1 || true
  rmdir "$mount_dir" >/dev/null 2>&1 || true
}
trap cleanup_mount EXIT
hdiutil attach -nobrowse -readonly -mountpoint "$mount_dir" "$dmg" >/dev/null
if find "$mount_dir" -name '*.dSYM' -print -quit | grep -q .; then
  echo "Customer DMG unexpectedly contains a dSYM" >&2
  exit 1
fi
mounted_binary="$mount_dir/Birkin.app/Contents/MacOS/BirkinNativeApp"
mounted_icon="$mount_dir/Birkin.app/Contents/Resources/Birkin.icns"
[[ -f "$mounted_binary" && -f "$mounted_icon" ]]
mounted_uuids="$(collect_uuids "$mounted_binary")"
cmp -s <(printf '%s\n' "$binary_uuids") <(printf '%s\n' "$mounted_uuids") || {
  echo "Mounted DMG binary UUIDs do not match the packaged application" >&2
  exit 1
}
[[ "$(shasum -a 256 "$mounted_icon" | awk '{print $1}')" == "$icon_hash" ]]
hdiutil detach "$mount_dir" >/dev/null
rmdir "$mount_dir"
trap - EXIT

dmg_hash="$(shasum -a 256 "$dmg" | awk '{print $1}')"
{
  echo "$binary_hash  Birkin.app/Contents/MacOS/BirkinNativeApp"
  echo "$arm_helper_hash  Birkin.app/Contents/Helpers/arm64/birkin-native-bridge"
  echo "$x86_helper_hash  Birkin.app/Contents/Helpers/x86_64/birkin-native-bridge"
  echo "$helper_manifest_hash  Birkin.app/Contents/Resources/bridge-helper.json"
  echo "$icon_hash  Birkin.app/Contents/Resources/Birkin.icns"
  echo "$(shasum -a 256 "$app/$arm_browser_executable" | awk '{print $1}')  Birkin.app/$arm_browser_executable"
  echo "$(shasum -a 256 "$app/$x86_browser_executable" | awk '{print $1}')  Birkin.app/$x86_browser_executable"
  echo "$(shasum -a 256 "$app/$arm_ffmpeg_executable" | awk '{print $1}')  Birkin.app/$arm_ffmpeg_executable"
  echo "$(shasum -a 256 "$app/$x86_ffmpeg_executable" | awk '{print $1}')  Birkin.app/$x86_ffmpeg_executable"
  echo "$dmg_hash  $(basename "$dmg")"
} > "$manifest"
{
  echo "python_package_version=$package_version"
  echo "app_version=$app_version"
  echo "app_build=1"
  echo "local_protocol_version=1"
  echo "architectures=$(lipo -archs "$app/Contents/MacOS/BirkinNativeApp")"
  echo "helper_version=$helper_version"
  echo "helper_architectures=arm64 x86_64"
  echo "helper_python_version=$helper_python_version"
  echo "helper_python_build=$helper_python_build"
  echo "helper_source_revision=$helper_source_revision"
  echo "helper_source_state=$helper_source_state"
  echo "helper_arm64_sha256=$arm_helper_hash"
  echo "helper_x86_64_sha256=$x86_helper_hash"
  echo "helper_manifest_sha256=$helper_manifest_hash"
  echo "helper_inputs_sha256=$helper_inputs_hash"
  echo "browser_architectures=arm64 x86_64"
  echo "browser_playwright_version=$browser_playwright"
  echo "browser_chromium_revision=$browser_chromium"
  echo "browser_ffmpeg_revision=$browser_ffmpeg"
  echo "browser_arm64_sha256=$arm_browser_hash"
  echo "browser_arm64_size_bytes=$arm_browser_size"
  echo "browser_x86_64_sha256=$x86_browser_hash"
  echo "browser_x86_64_size_bytes=$x86_browser_size"
  echo "signing_mode=$signing_mode"
  echo "app_binary_sha256=$binary_hash"
  echo "icon_sha256=$icon_hash"
  echo "app_arm64_uuid=$manifest_arm64_uuid"
  echo "app_x86_64_uuid=$manifest_x86_64_uuid"
  echo "symbols_zip_sha256=$(awk '{print $1}' "$symbols_checksum")"
  echo "dmg_sha256=$dmg_hash"
} > "$build_manifest"
cat "$manifest"
cat "$build_manifest"
echo "dmg=$dmg"
echo "manifest=$manifest"
echo "build_manifest=$build_manifest"
echo "symbols_manifest=$symbols_manifest"
echo "symbols_zip=$symbols_zip"
echo "symbols_checksum=$symbols_checksum"
