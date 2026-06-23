#!/bin/bash
DIR="$HOME/Desktop/codes/mflux-paint"; PORT=7866; URL="http://localhost:$PORT"; LOG="$DIR/server.log"
up(){ /usr/bin/curl -s -o /dev/null --max-time 2 "$URL"; }
openui(){ if [ -d "/Applications/Google Chrome.app" ]; then
  /usr/bin/open -na "Google Chrome" --args --app="$URL" --window-size=1280,860; else /usr/bin/open "$URL"; fi; }
if up; then openui; exit 0; fi
cd "$DIR" || exit 1
/usr/bin/nohup "$DIR/.venv/bin/python" "$DIR/server.py" >"$LOG" 2>&1 &
for i in $(seq 1 30); do up && { openui; exit 0; }; sleep 1; done
/usr/bin/open -t "$LOG"; exit 1
