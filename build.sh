#!/bin/bash
# Build /Applications/MFLUX Paint.app as a self-contained bundle: app source and
# the venv both go inside, so the app keeps working wherever this checkout lives.
# mflux itself stays a system dependency - server.py shells out to the
# mflux-generate-* commands on PATH, and the weights are far too big to bundle.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="${1:-/Applications/MFLUX Paint.app}"
VERSION="$(cd "$DIR" && git describe --tags --always 2>/dev/null || echo 1.0.1)"

[ -d "$DIR/.venv" ] || { echo "no .venv - run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }

pkill -f "MFLUX Paint.app/Contents/Resources/desktop.py" 2>/dev/null || true

STAGE="$(mktemp -d)/MFLUX Paint.app"
trap 'rm -rf "$(dirname "$STAGE")"' EXIT
mkdir -p "$STAGE/Contents/MacOS" "$STAGE/Contents/Resources"

cp "$DIR"/server.py "$DIR"/desktop.py "$DIR"/index.html "$STAGE/Contents/Resources/"
cp -R "$DIR/assets" "$STAGE/Contents/Resources/assets"
cp "$DIR/assets/icon.icns" "$STAGE/Contents/Resources/icon.icns"
cp -R "$DIR/.venv" "$STAGE/Contents/Resources/.venv"

cat > "$STAGE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleDisplayName</key><string>MFLUX Paint</string>
  <key>CFBundleName</key><string>MFLUX Paint</string>
  <key>CFBundleExecutable</key><string>MFLUX</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundleIdentifier</key><string>com.dark0nly.mfluxpaint</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSUIElement</key><integer>0</integer>
</dict></plist>
PLIST

cat > "$STAGE/Contents/MacOS/MFLUX" <<'LAUNCH'
#!/bin/bash
RES="$(cd "$(dirname "${BASH_SOURCE[0]}")/../Resources" && pwd)"
# already running? bring that window to front instead of starting a second instance.
if /usr/bin/curl -s -o /dev/null --max-time 2 "http://localhost:7866/alive"; then
  /usr/bin/osascript -e 'tell application "System Events" to set frontmost of (first process whose name is "Python") to true' 2>/dev/null
  exit 0
fi
cd "$RES" || exit 1
exec "$RES/.venv/bin/python" "$RES/desktop.py"
LAUNCH
chmod +x "$STAGE/Contents/MacOS/MFLUX"

"$STAGE/Contents/Resources/.venv/bin/python" -c 'import PIL, webview' \
  || { echo "bundled venv is broken - aborting, $APP left untouched"; exit 1; }

rm -rf "$APP"
cp -R "$STAGE" "$APP"
xattr -cr "$APP" 2>/dev/null || true
touch "$APP"   # nudge LaunchServices to re-read the bundle
echo "built $APP ($VERSION, $(du -sh "$APP" | cut -f1))"
