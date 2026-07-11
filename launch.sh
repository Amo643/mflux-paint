#!/bin/bash
# Launch the native desktop app (pywebview window + local server in one process).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
# already running? bring the window to front instead of starting a second instance.
if /usr/bin/curl -s -o /dev/null --max-time 2 "http://localhost:7866/alive"; then
  /usr/bin/osascript -e 'tell application "System Events" to set frontmost of (first process whose name is "Python") to true' 2>/dev/null
  exit 0
fi
exec "$DIR/.venv/bin/python" "$DIR/desktop.py"
