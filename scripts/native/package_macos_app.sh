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
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

swift build --package-path "$package_root" -c release --arch arm64 --arch x86_64
cp "$binary" "$app/Contents/MacOS/BirkinNativeApp"
chmod 0755 "$app/Contents/MacOS/BirkinNativeApp"
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

# There are no nested frameworks or helpers in this SwiftPM bundle. Sign the
# Mach-O first, then the enclosing bundle to preserve inside-out ordering.
codesign "${sign_args[@]}" "$app/Contents/MacOS/BirkinNativeApp"
codesign "${sign_args[@]}" "$app"
codesign --verify --deep --strict --verbose=2 "$app"

{
  echo "app=$app"
  echo "version=$version"
  echo "build=$build"
  echo "architectures=$(lipo -archs "$app/Contents/MacOS/BirkinNativeApp")"
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
