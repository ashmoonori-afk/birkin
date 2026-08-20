#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
output_root="${1:-$repo_root/.omo/evidence/native-shell/phase13/dist}"
app="$output_root/Birkin.app"
dmg="$output_root/Birkin-0.4.242.dmg"
manifest="$repo_root/.omo/evidence/native-shell/phase13/artifact-manifest.sha256"

cd "$repo_root"
if [[ ! -d "$app" ]]; then
  scripts/native/package_macos_app.sh "$output_root"
fi
rm -f "$dmg"
hdiutil create -volname Birkin -srcfolder "$app" -ov -format UDZO "$dmg"
mkdir -p "$(dirname "$manifest")"
{
  shasum -a 256 "$app/Contents/MacOS/BirkinNativeApp"
  shasum -a 256 "$dmg"
} > "$manifest"
cat "$manifest"
echo "dmg=$dmg"
echo "manifest=$manifest"
