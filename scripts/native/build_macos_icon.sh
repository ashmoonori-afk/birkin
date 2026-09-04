#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_svg="${1:-$repo_root/macos/BirkinNativeApp/Resources/Birkin.svg}"
destination="${2:-$repo_root/.omo/evidence/native-shell/phase13/dist/Birkin.icns}"

[[ -f "$source_svg" ]] || {
  echo "Missing project-owned icon source: $source_svg" >&2
  exit 1
}
[[ "$destination" == *.icns ]] || {
  echo "macOS icon destination must end in .icns" >&2
  exit 1
}

work_root="$(mktemp -d "${TMPDIR:-/tmp}/birkin-icon.XXXXXX")"
trap 'rm -rf "$work_root"' EXIT
iconset="$work_root/Birkin.iconset"
master="$work_root/Birkin-1024.png"
mkdir -p "$iconset" "$(dirname "$destination")"

/usr/bin/sips -s format png -z 1024 1024 "$source_svg" \
  --out "$master" >/dev/null

while IFS=' ' read -r filename pixels; do
  /usr/bin/sips -z "$pixels" "$pixels" "$master" \
    --out "$iconset/$filename" >/dev/null
  width="$(/usr/bin/sips -g pixelWidth "$iconset/$filename" |
    awk '/pixelWidth:/{print $2}')"
  height="$(/usr/bin/sips -g pixelHeight "$iconset/$filename" |
    awk '/pixelHeight:/{print $2}')"
  [[ "$width" == "$pixels" && "$height" == "$pixels" ]] || {
    echo "Invalid icon dimensions for $filename: ${width}x${height}" >&2
    exit 1
  }
done <<'ICON_SIZES'
icon_16x16.png 16
icon_16x16@2x.png 32
icon_32x32.png 32
icon_32x32@2x.png 64
icon_128x128.png 128
icon_128x128@2x.png 256
icon_256x256.png 256
icon_256x256@2x.png 512
icon_512x512.png 512
icon_512x512@2x.png 1024
ICON_SIZES

rm -f "$destination"
/usr/bin/iconutil -c icns "$iconset" -o "$destination"
[[ -s "$destination" ]] || {
  echo "iconutil did not produce $destination" >&2
  exit 1
}
