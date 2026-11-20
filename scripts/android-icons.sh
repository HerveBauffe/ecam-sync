#!/usr/bin/env bash
# Regenerate every app icon from assets/. Run after changing the logo or after `tauri android init`.
# `tauri icon` writes desktop icons and legacy Android mipmaps. We then replace the
# adaptive-icon foreground (Android 8+, which is every supported device) with a transparent,
# safe-zone version, and set its background to the app colour.
set -euo pipefail
cd "$(dirname "$0")/.."
npx tauri icon assets/icon.svg
rm -rf src-tauri/icons/ios
RES=src-tauri/gen/android/app/src/main/res
if [ -d "$RES" ]; then
  for d in mdpi:108 hdpi:162 xhdpi:216 xxhdpi:324 xxxhdpi:432; do
    magick -background none -density 300 assets/icon-foreground.svg -resize "${d#*:}x${d#*:}" \
      -depth 8 "$RES/mipmap-${d%%:*}/ic_launcher_foreground.png"
  done
  sed -i 's|<color name="ic_launcher_background">#[0-9A-Fa-f]*</color>|<color name="ic_launcher_background">#16181D</color>|' \
    "$RES/values/ic_launcher_background.xml"
fi
echo "icons regenerated"
