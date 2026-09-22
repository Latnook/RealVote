#!/usr/bin/env bash
# Render og.html to site/og.png (1200x630, the size link previews expect).
# Needs a headless Chromium and the Noto Sans Hebrew font installed.
set -euo pipefail
cd "$(dirname "$0")"
BROWSER=$(command -v chromium || command -v chromium-browser || command -v google-chrome)
"$BROWSER" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --window-size=1200,630 --screenshot="$PWD/../../site/og.png" "file://$PWD/og.html"
echo "wrote site/og.png"
