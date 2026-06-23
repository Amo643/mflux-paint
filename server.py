#!/usr/bin/env python3
"""mflux-paint: IOPaint-style single-screen inpaint/edit UI on the mflux engine.
No torch. Shells out to mflux-generate-flux2-edit (flux2-klein-4b, already cached).
Masked run -> edit whole image, composite only the masked region back (feathered).
No mask -> edit the whole image by prompt.
"""
import base64, glob, http.server, io, json, os, subprocess, tempfile, socketserver, threading, time
from PIL import Image, ImageFilter

# auto-shutdown: the open page pings /alive; no ping for IDLE_TIMEOUT -> exit.
# So the server lives only while the app window is open (no idle process).
LAST_PING = [time.time()]
IDLE_TIMEOUT = 20
def _watchdog():
    while True:
        time.sleep(5)
        if time.time() - LAST_PING[0] > IDLE_TIMEOUT:
            os._exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
MFLUX = "/opt/homebrew/bin/mflux-generate-flux2-edit"
BASE_MODEL = "flux2-klein-4b"
GEN_MIN, GEN_MAX = 512, 1024          # resolution band (speed/quality), from localfill benchmarks
PORT = 7866

def snap16(v): return max(16, int(round(v / 16)) * 16)

def gen_size(w, h):
    long = max(w, h)
    s = GEN_MIN / long if long < GEN_MIN else GEN_MAX / long if long > GEN_MAX else 1.0
    return snap16(w * s), snap16(h * s)

def feather_px(w, h): return max(2, min(24, int(round(min(w, h) * 0.02))))

def b64_to_img(data):
    if "," in data: data = data.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data)))

def img_to_b64(img):
    buf = io.BytesIO(); img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

def run_edit(base, prompt, steps, guidance, seed):
    """Run flux2-edit on the whole image at gen-res, return result at base size."""
    cw, ch = base.size
    gw, gh = gen_size(cw, ch)
    with tempfile.TemporaryDirectory() as d:
        gin = os.path.join(d, "in.png")
        base.resize((gw, gh)).save(gin)
        out = os.path.join(d, "out.png")
        cmd = [MFLUX, "--base-model", BASE_MODEL, "--image-paths", gin,
               "--prompt", prompt, "--height", str(gh), "--width", str(gw),
               "--steps", str(steps), "--guidance", str(guidance), "--output", out]
        if seed not in (None, ""): cmd += ["--seed", str(seed)]
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if p.returncode != 0:
            raise RuntimeError(p.stderr[-1500:] or p.stdout[-1500:])
        files = sorted(glob.glob(out.replace(".png", "*.png")), key=os.path.getmtime)
        if not files: raise RuntimeError("mflux produced no output")
        return Image.open(files[-1]).convert("RGB").resize((cw, ch))

def handle_run(payload):
    base = b64_to_img(payload["image"]).convert("RGB")
    prompt = (payload.get("prompt") or "").strip()
    steps = int(payload.get("steps") or 4)
    guidance = float(payload.get("guidance") or 3.5)
    seed = payload.get("seed")
    if not prompt: raise ValueError("prompt is empty")
    edited = run_edit(base, prompt, steps, guidance, seed)
    mask_data = payload.get("mask")
    if mask_data:                      # masked: keep edit only inside the mask
        mask = b64_to_img(mask_data).convert("L").resize(base.size)
        if mask.getbbox():             # any white at all
            f = feather_px(*base.size)
            # dilate first so the region is FULLY covered to its edges (no leftover
            # original pixels at the boundary, e.g. text edges), then a gentle blend.
            dil = min(25, f * 2 + 1)
            mask = mask.filter(ImageFilter.MaxFilter(dil if dil % 2 else dil + 1))
            soft = mask.filter(ImageFilter.GaussianBlur(max(1, f // 2)))
            edited = Image.composite(edited, base, soft)
    return {"image": img_to_b64(edited)}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if self.path == "/alive":
            LAST_PING[0] = time.time()
            self._send(200, b"ok", "text/plain")
        elif self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")
    def do_POST(self):
        if self.path != "/run":
            return self._send(404, b"not found", "text/plain")
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n))
            self._send(200, json.dumps(handle_run(payload)))
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    print(f"mflux-paint on http://localhost:{PORT}")
    threading.Thread(target=_watchdog, daemon=True).start()
    Server(("127.0.0.1", PORT), H).serve_forever()
