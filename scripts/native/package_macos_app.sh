#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
package_root="$repo_root/macos/BirkinNativeApp"
output_root="${1:-$repo_root/.omo/evidence/native-shell/phase13/dist}"
app="$output_root/Birkin.app"
binary="$package_root/.build/apple/Products/Release/BirkinNativeApp"
build="${BIRKIN_BUILD_NUMBER:-1}"

cd "$repo_root"
version="$(awk '
  /^\[project\]$/ { in_project=1; next }
  /^\[/ { in_project=0 }
  in_project && /^version = / { gsub(/[\"[:space:]]/, "", $3); print $3; exit }
' pyproject.toml)"
[[ -n "$version" ]] || { echo "Unable to read project version" >&2; exit 1; }
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

rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$app/Contents/Helpers"

swift build --package-path "$package_root" -c release --arch arm64 --arch x86_64
cp "$binary" "$app/Contents/MacOS/BirkinNativeApp"
chmod 0755 "$app/Contents/MacOS/BirkinNativeApp"
scripts/native/build_bridge_helpers.sh "$app/Contents/Helpers"
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

arm_helper="$app/Contents/Helpers/arm64/birkin-native-bridge"
x86_helper="$app/Contents/Helpers/x86_64/birkin-native-bridge"
codesign "${sign_args[@]}" "$arm_helper"
codesign "${sign_args[@]}" "$x86_helper"
arm_helper_hash="$(shasum -a 256 "$arm_helper" | awk '{print $1}')"
x86_helper_hash="$(shasum -a 256 "$x86_helper" | awk '{print $1}')"
python_version="$(plutil -extract python.version raw -o - scripts/native/bridge_helper_inputs.json)"
python_build="$(plutil -extract python.build raw -o - scripts/native/bridge_helper_inputs.json)"
dependency_lock_hash="$(shasum -a 256 uv.lock | awk '{print $1}')"
build_lock_hash="$(shasum -a 256 scripts/native/bridge_helper_build.lock | awk '{print $1}')"
inputs_hash="$(shasum -a 256 scripts/native/bridge_helper_inputs.json | awk '{print $1}')"
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
  ]
}
JSON
helper_manifest_hash="$(shasum -a 256 "$app/Contents/Resources/bridge-helper.json" | awk '{print $1}')"

# Sign nested code first, then seal its manifest with the application signature.
codesign "${sign_args[@]}" "$app/Contents/MacOS/BirkinNativeApp"
codesign "${sign_args[@]}" "$app"
codesign --verify --strict --verbose=2 "$arm_helper"
codesign --verify --strict --verbose=2 "$x86_helper"
codesign --verify --deep --strict --verbose=2 "$app"

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
