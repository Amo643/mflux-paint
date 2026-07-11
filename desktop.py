#!/usr/bin/env python3
"""Native desktop window for mflux-paint (macOS WebKit via pywebview).
Starts the local server in a background thread, then opens a real app window —
no Chrome dependency. Closing the window exits the process (server dies with it)."""
import os, threading, time, urllib.request
# window lifetime == process lifetime; server.py's idle watchdog only starts in its
# own __main__ block, which never runs when imported as a module here, so no watchdog anyway.
import server
import webview

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, "assets", "icon.png")

def _serve():
    server.Server(("127.0.0.1", server.PORT), server.H).serve_forever()

def _wait_up():
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://localhost:{server.PORT}/alive", timeout=1); return True
        except Exception:
            time.sleep(0.1)
    return False

if __name__ == "__main__":
    threading.Thread(target=_serve, daemon=True).start()
    _wait_up()
    webview.create_window("mflux paint", f"http://localhost:{server.PORT}",
                          width=1280, height=860, min_size=(900, 600))
    # icon= sets the actual Dock icon on macOS (pywebview's Cocoa backend loads it via
    # NSImage) - undocumented in create_window, only honored by webview.start().
    webview.start(icon=ICON if os.path.exists(ICON) else None)   # blocks; returns on window close -> process exits
