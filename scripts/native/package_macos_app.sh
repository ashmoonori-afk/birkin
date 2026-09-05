#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
package_root="$repo_root/macos/BirkinNativeApp"
output_root="${1:-$repo_root/.omo/evidence/native-shell/phase13/dist}"
app="$output_root/Birkin.app"
binary="$package_root/.build/apple/Products/Release/BirkinNativeApp"
app_binary="$app/Contents/MacOS/BirkinNativeApp"
icon_source="$repo_root/macos/BirkinNativeApp/Resources/Birkin.svg"
icon="$app/Contents/Resources/Birkin.icns"
dsym="$output_root/BirkinNativeApp.dSYM"
build="${BIRKIN_BUILD_NUMBER:-1}"

cd "$repo_root"
version="$(awk '
  /^\[project\]$/ { in_project=1; next }
  /^\[/ { in_project=0 }
  in_project && /^version = / { gsub(/[\"[:space:]]/, "", $3); print $3; exit }
' pyproject.toml)"
[[ -n "$version" ]] || { echo "Unable to read project version" >&2; exit 1; }
symbols_manifest="$output_root/Birkin-$version-symbols-manifest.txt"
symbols_zip="$output_root/Birkin-$version-symbols.zip"
symbols_checksum="$output_root/Birkin-$version-symbols.zip.sha256"

collect_uuids() {
  /usr/bin/dwarfdump --uuid "$1" |
    awk '{
      architecture=$3
      gsub(/[()]/, "", architecture)
      print architecture "=" tolower($2)
    }' |
    LC_ALL=C sort
}

source_revision="$(git rev-parse HEAD)"
source_state=clean
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  source_state=dirty
fi
if [[ "$source_state" != "clean" && "${BIRKIN_ALLOW_DIRTY_PACKAGE:-0}" != "1" ]]; then
  echo "Refusing to package a dirty source tree; commit the app and helper first" >&2
  exit 1
fi

identity="${BIRKIN_SIGN_IDENTITY:-}"
if [[ -z "$identity" ]]; then
  identity="$(security find-identity -v -p codesigning 2>/dev/null | sed -n 's/.*"\(Developer ID Application:[^"]*\)"/\1/p' | head -1)"
fi
if [[ -n "$identity" ]]; then
  sign_args=(--force --sign "$identity" --options runtime --timestamp)
  signing_mode="developer-id-hardened-runtime"
else
  sign_args=(--force --sign -)
  signing_mode="ad-hoc-no-hardened-runtime"
fi
export BIRKIN_SIGN_IDENTITY="$identity"

rm -rf "$app" "$dsym"
rm -f "$symbols_manifest" "$symbols_zip" "$symbols_checksum"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$app/Contents/Helpers"

swift build --package-path "$package_root" -c release \
  --arch arm64 --arch x86_64 -Xswiftc -g
cp "$binary" "$app_binary"
chmod 0755 "$app_binary"
localization_bundle="$package_root/.build/apple/Products/Release/BirkinNativeApp_BirkinNativeShell.bundle"
[[ -d "$localization_bundle" ]] || {
  echo "Swift localization resource bundle is missing" >&2
  exit 1
}
localization_resources="$localization_bundle/Contents/Resources"
cp -R "$localization_bundle" "$app/Contents/Resources/"
for localization in en ko; do
  cp -R \
    "$localization_resources/$localization.lproj" \
    "$app/Contents/Resources/"
done
scripts/native/build_bridge_helpers.sh "$app/Contents/Helpers"
scripts/native/build_browser_runtimes.sh \
  "$app/Contents/Resources/BrowserRuntimes"
bash scripts/native/build_macos_icon.sh "$icon_source" "$icon"
icon_source_hash="$(shasum -a 256 "$icon_source" | awk '{print $1}')"
icon_hash="$(shasum -a 256 "$icon" | awk '{print $1}')"
printf 'APPL????' > "$app/Contents/PkgInfo"
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleDisplayName</key><string>Birkin</string>
  <key>CFBundleExecutable</key><string>BirkinNativeApp</string>
  <key>CFBundleIdentifier</key><string>com.birkin.native</string>
  <key>CFBundleIconFile</key><string>Birkin.icns</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>Birkin</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$version</string>
  <key>CFBundleVersion</key><string>$build</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
plutil -lint "$app/Contents/Info.plist"
[[ "$(plutil -extract CFBundleIconFile raw -o - "$app/Contents/Info.plist")" == "Birkin.icns" ]]
cat > "$app/Contents/Resources/app-resources.json" <<JSON
{
  "schema": 1,
  "icon": {
    "file": "Birkin.icns",
    "source": "macos/BirkinNativeApp/Resources/Birkin.svg",
    "source_sha256": "$icon_source_hash",
    "sha256": "$icon_hash"
  }
}
JSON
resource_manifest_hash="$(shasum -a 256 "$app/Contents/Resources/app-resources.json" | awk '{print $1}')"

arm_helper="$app/Contents/Helpers/arm64/birkin-native-bridge"
x86_helper="$app/Contents/Helpers/x86_64/birkin-native-bridge"
browser_code_paths=()
while IFS= read -r candidate; do
  if file "$candidate" | grep -q 'Mach-O'; then
    codesign "${sign_args[@]}" "$candidate"
    browser_code_paths+=("$candidate")
  fi
done < <(find "$app/Contents/Resources/BrowserRuntimes" -type f | LC_ALL=C sort)
codesign "${sign_args[@]}" "$arm_helper"
codesign "${sign_args[@]}" "$x86_helper"
arm_helper_hash="$(shasum -a 256 "$arm_helper" | awk '{print $1}')"
x86_helper_hash="$(shasum -a 256 "$x86_helper" | awk '{print $1}')"
python_version="$(plutil -extract python.version raw -o - scripts/native/bridge_helper_inputs.json)"
python_build="$(plutil -extract python.build raw -o - scripts/native/bridge_helper_inputs.json)"
dependency_lock_hash="$(shasum -a 256 uv.lock | awk '{print $1}')"
build_lock_hash="$(shasum -a 256 scripts/native/bridge_helper_build.lock | awk '{print $1}')"
inputs_hash="$(shasum -a 256 scripts/native/bridge_helper_inputs.json | awk '{print $1}')"
browser_playwright="$(plutil -extract browser.playwright_version raw -o - scripts/native/bridge_helper_inputs.json)"
browser_chromium="$(plutil -extract browser.chromium_revision raw -o - scripts/native/bridge_helper_inputs.json)"
browser_ffmpeg="$(plutil -extract browser.ffmpeg_revision raw -o - scripts/native/bridge_helper_inputs.json)"
arm_browser_root="$app/Contents/Resources/BrowserRuntimes/arm64"
x86_browser_root="$app/Contents/Resources/BrowserRuntimes/x86_64"
arm_browser_identity="$(uv run python -m birkin.bundled_browser "$arm_browser_root")"
x86_browser_identity="$(uv run python -m birkin.bundled_browser "$x86_browser_root")"
arm_browser_hash="$(printf '%s' "$arm_browser_identity" | plutil -extract sha256 raw -o - -)"
x86_browser_hash="$(printf '%s' "$x86_browser_identity" | plutil -extract sha256 raw -o - -)"
arm_browser_size="$(printf '%s' "$arm_browser_identity" | plutil -extract size_bytes raw -o - -)"
x86_browser_size="$(printf '%s' "$x86_browser_identity" | plutil -extract size_bytes raw -o - -)"
cat > "$app/Contents/Resources/bridge-helper.json" <<JSON
{
  "schema": 1,
  "package_version": "$version",
  "source_revision": "$source_revision",
  "source_state": "$source_state",
  "python_version": "$python_version",
  "python_build": "$python_build",
  "dependency_lock_sha256": "$dependency_lock_hash",
  "build_lock_sha256": "$build_lock_hash",
  "inputs_sha256": "$inputs_hash",
  "helpers": [
    {"architecture":"arm64","path":"arm64/birkin-native-bridge","sha256":"$arm_helper_hash"},
    {"architecture":"x86_64","path":"x86_64/birkin-native-bridge","sha256":"$x86_helper_hash"}
  ],
  "browser_runtimes": [
    {"architecture":"arm64","path":"BrowserRuntimes/arm64","sha256":"$arm_browser_hash","size_bytes":$arm_browser_size,"playwright_version":"$browser_playwright","chromium_revision":"$browser_chromium","ffmpeg_revision":"$browser_ffmpeg","headless_executable":"chromium_headless_shell-$browser_chromium/chrome-headless-shell-mac-arm64/chrome-headless-shell","ffmpeg_executable":"ffmpeg-$browser_ffmpeg/ffmpeg-mac"},
    {"architecture":"x86_64","path":"BrowserRuntimes/x86_64","sha256":"$x86_browser_hash","size_bytes":$x86_browser_size,"playwright_version":"$browser_playwright","chromium_revision":"$browser_chromium","ffmpeg_revision":"$browser_ffmpeg","headless_executable":"chromium_headless_shell-$browser_chromium/chrome-headless-shell-mac-x64/chrome-headless-shell","ffmpeg_executable":"ffmpeg-$browser_ffmpeg/ffmpeg-mac"}
  ]
}
JSON
helper_manifest_hash="$(shasum -a 256 "$app/Contents/Resources/bridge-helper.json" | awk '{print $1}')"

# Sign nested code first, then seal its manifest with the application signature.
codesign "${sign_args[@]}" "$app_binary"
codesign "${sign_args[@]}" "$app"
codesign --verify --strict --verbose=2 "$arm_helper"
codesign --verify --strict --verbose=2 "$x86_helper"
for candidate in "${browser_code_paths[@]}"; do
  codesign --verify --strict --verbose=2 "$candidate"
done
codesign --verify --deep --strict --verbose=2 "$app"

# Generate and validate private symbols only after the shipped binary is final.
# The dSYM and its archive remain beside the app, never inside it.
/usr/bin/dsymutil "$app_binary" -o "$dsym"
binary_uuids="$(collect_uuids "$app_binary")"
dsym_uuids="$(collect_uuids "$dsym")"
grep -q "^arm64=" <<<"$binary_uuids"
grep -q "^x86_64=" <<<"$binary_uuids"
[[ "$(wc -l <<<"$binary_uuids" | tr -d ' ')" == "2" ]]
cmp -s <(printf '%s\n' "$binary_uuids") <(printf '%s\n' "$dsym_uuids") || {
  echo "Application and dSYM UUIDs do not match" >&2
  diff -u <(printf '%s\n' "$binary_uuids") <(printf '%s\n' "$dsym_uuids") >&2 || true
  exit 1
}
app_binary_hash="$(shasum -a 256 "$app_binary" | awk '{print $1}')"
arm64_uuid="$(awk -F= '/^arm64=/{print $2}' <<<"$binary_uuids")"
x86_64_uuid="$(awk -F= '/^x86_64=/{print $2}' <<<"$binary_uuids")"
cat > "$symbols_manifest" <<SYMBOLS
schema=1
package_version=$version
source_revision=$source_revision
app_binary_sha256=$app_binary_hash
arm64_uuid=$arm64_uuid
x86_64_uuid=$x86_64_uuid
SYMBOLS
symbol_stage="$(mktemp -d "${TMPDIR:-/tmp}/birkin-symbols.XXXXXX")"
trap 'rm -rf "$symbol_stage"' EXIT
/usr/bin/ditto "$dsym" "$symbol_stage/BirkinNativeApp.dSYM"
cp "$symbols_manifest" "$symbol_stage/$(basename "$symbols_manifest")"
/usr/bin/ditto -c -k --sequesterRsrc "$symbol_stage/" "$symbols_zip"
/usr/bin/unzip -t "$symbols_zip" >/dev/null
symbols_zip_hash="$(shasum -a 256 "$symbols_zip" | awk '{print $1}')"
printf '%s  %s\n' "$symbols_zip_hash" "$(basename "$symbols_zip")" \
  > "$symbols_checksum"
rm -rf "$symbol_stage"
trap - EXIT
[[ -z "$(find "$app" -name '*.dSYM' -print -quit)" ]] || {
  echo "Customer application unexpectedly contains a dSYM" >&2
  exit 1
}

{
  echo "app=$app"
  echo "version=$version"
  echo "build=$build"
  echo "architectures=$(lipo -archs "$app/Contents/MacOS/BirkinNativeApp")"
  echo "helper_version=$version"
  echo "helper_architectures=arm64 x86_64"
  echo "helper_arm64_sha256=$arm_helper_hash"
  echo "helper_x86_64_sha256=$x86_helper_hash"
  echo "helper_manifest_sha256=$helper_manifest_hash"
  echo "helper_python_version=$python_version"
  echo "helper_python_build=$python_build"
  echo "helper_source_revision=$source_revision"
  echo "helper_source_state=$source_state"
  echo "helper_dependency_lock_sha256=$dependency_lock_hash"
  echo "helper_build_lock_sha256=$build_lock_hash"
  echo "helper_inputs_sha256=$inputs_hash"
  echo "browser_architectures=arm64 x86_64"
  echo "browser_playwright_version=$browser_playwright"
  echo "browser_chromium_revision=$browser_chromium"
  echo "browser_ffmpeg_revision=$browser_ffmpeg"
  echo "browser_arm64_sha256=$arm_browser_hash"
  echo "browser_arm64_size_bytes=$arm_browser_size"
  echo "browser_x86_64_sha256=$x86_browser_hash"
  echo "browser_x86_64_size_bytes=$x86_browser_size"
  echo "icon_file=Birkin.icns"
  echo "icon_source_sha256=$icon_source_hash"
  echo "icon_sha256=$icon_hash"
  echo "resource_manifest_sha256=$resource_manifest_hash"
  echo "app_binary_sha256=$app_binary_hash"
  echo "app_arm64_uuid=$arm64_uuid"
  echo "app_x86_64_uuid=$x86_64_uuid"
  echo "symbols_manifest=$(basename "$symbols_manifest")"
  echo "symbols_zip=$(basename "$symbols_zip")"
  echo "symbols_zip_sha256=$symbols_zip_hash"
  echo "signing_mode=$signing_mode"
  echo "identity=${identity:--}"
  echo "app_sandbox=disabled"
  echo "entitlements=none"
  echo "sandbox_rationale=PTY, local sockets, Accessibility, and Screen Recording require capabilities outside the initial sandbox profile."
  if [[ "$signing_mode" == "developer-id-hardened-runtime" ]]; then
    echo "hardened_runtime=enabled"
  else
    echo "hardened_runtime=deferred-developer-id"
    echo "notarization=deferred-credentials"
  fi
} | tee "$output_root/packaging-report.txt"
