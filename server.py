#!/usr/bin/env python3
"""mflux-paint: single-screen inpaint/edit UI on the mflux engine.
No torch. Shells out to mflux CLIs. Model registry covers whole-image edit,
true inpaint (fill) and text-to-image, each with a different mflux CLI shape.
Saved prompts, save-to-folder, model picker, multi-seed batches.
"""
import base64, glob, http.server, io, json, os, re, shutil, subprocess, tempfile, socketserver, threading, time, urllib.parse
from PIL import Image, ImageFilter

# auto-shutdown: the open page pings /alive; no ping for IDLE_TIMEOUT -> exit.
LAST_PING = [time.time()]
IDLE_TIMEOUT = 20
def _watchdog():
    while True:
        time.sleep(5)
        if time.time() - LAST_PING[0] > IDLE_TIMEOUT:
            with JLOCK:                       # kill any in-flight mflux subprocess before exiting
                for j in JOBS.values():
                    p = j.get("_proc")
                    if p and p.poll() is None:
                        try: p.terminate()
                        except Exception: pass
            os._exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 7866
SAVE_DIR = os.path.expanduser("~/Pictures/mflux-paint")
CFG_DIR  = os.path.expanduser("~/.mflux-paint")
PROMPTS_FILE = os.path.join(CFG_DIR, "prompts.json")
CUSTOM_MODELS_FILE = os.path.join(CFG_DIR, "custom_models.json")
# auto-detect where `uv tool install mflux` / pipx put the mflux-generate-* binaries,
# falling back to the Homebrew default if they're not on PATH (e.g. launched from a
# GUI context that doesn't inherit the shell's PATH).
_mflux_bin = shutil.which("mflux-generate")
BIN = os.path.dirname(_mflux_bin) if _mflux_bin else "/opt/homebrew/bin"

# --- model registry -------------------------------------------------------------
# "shape" controls how the mflux CLI command is built (see build_cmd):
#   fill        true inpaint  -> --image-path + --masked-image-path (white=fill)
#   edit_multi  whole-image edit, N reference images -> --image-paths (plural)
#   edit_single whole-image edit, 1 reference image -> --image-path (singular)
#   edit_mask   whole-image edit with a native optional mask -> --image-path [--mask-path]
#   txt2img     no input image at all, generates from scratch
# For fill/edit_* the mask (if the user painted one) is only used client-side to
# composite the result back over the untouched original ("edit_mask" is the one
# exception: fibo-edit's --mask-path is a genuine model input, not just compositing).
#
# steps/guidance marked "confirmed" come from mflux's own --help text or from
# values already field-tested in this app. Everything marked "generic default" is
# a best-effort FLUX.1-dev-family starting point (steps=20, guidance=3.5) or the
# standard distilled/"turbo" convention (steps=4, guidance=0) - mflux's own
# per-model tuned defaults are not exposed via --help, so these are NOT verified
# against real output. Override in Settings once you've actually run one.
MODELS = {
    # ---------------------------------------------------------------- edit
    "klein-4b": {
        "label": "FLUX.2 Klein-4B · fast edit", "group": "Edit",
        "bin": f"{BIN}/mflux-generate-flux2-edit",
        # NOTE: "-m" (--model) is what actually selects the preset weights.
        # "--base-model" alone is only an architecture hint for third-party HF
        # repos and silently no-ops back to the default model without it.
        "model": "flux2-klein-4b", "base": "flux2-klein-4b", "shape": "edit_multi",
        # negative-prompt tested live: FLUX.2 hard-errors on it ("--negative-prompt
        # is not supported for FLUX.2. Focus on describing what you want.") - keep
        # neg=False for every FLUX.2-family entry (klein-4b/9b, flux2-t2i below).
        "gen_max": 1024, "steps": 4, "guidance": 3.5, "needs_mask": False, "cached": True, "neg": False,
    },
    "klein-9b": {
        "label": "FLUX.2 Klein-9B · quality edit", "group": "Edit",
        "bin": f"{BIN}/mflux-generate-flux2-edit",
        "model": "flux2-klein-9b", "base": "flux2-klein-9b", "shape": "edit_multi",
        # gen_max unverified with the real 9B weights (earlier timings were
        # measured against a mistakenly-loaded 4B model - see git history).
        "gen_max": 768, "steps": 4, "guidance": 1.0, "needs_mask": False, "cached": True, "neg": False,
    },
    "qwen-edit": {
        "label": "Qwen-Image-Edit", "group": "Edit",
        "bin": f"{BIN}/mflux-generate-qwen-edit",
        "model": None, "base": None, "shape": "edit_multi",
        "gen_max": 1024, "steps": 20, "guidance": 4.0, "needs_mask": False, "cached": False,  # generic default
    },
    "kontext": {
        "label": "FLUX.1 Kontext · image edit", "group": "Edit",
        "bin": f"{BIN}/mflux-generate-kontext",
        "model": None, "base": None, "shape": "edit_single",
        "gen_max": 1024, "steps": 28, "guidance": 2.5, "needs_mask": False, "cached": False,  # BFL's published Kontext default
    },
    "fibo-edit": {
        "label": "Bria FIBO Edit", "group": "Edit",
        "bin": f"{BIN}/mflux-generate-fibo-edit",
        "model": "fibo-edit", "base": "fibo-edit", "shape": "edit_mask",
        "gen_max": 1024, "steps": 20, "guidance": 3.5, "needs_mask": False, "cached": False,  # generic default
    },
    # ---------------------------------------------------------------- inpaint
    "fill": {
        "label": "FLUX.1 Fill · inpaint", "group": "Inpaint",
        "bin": f"{BIN}/mflux-generate-fill",
        "model": "dev", "base": "dev", "shape": "fill",
        # guidance=30 confirmed by mflux-generate-fill --help ("30 for fill tools"); steps generic
        "gen_max": 1024, "steps": 25, "guidance": 30, "needs_mask": True, "cached": False,
    },
    # ---------------------------------------------------------------- text-to-image
    "dev": {
        "label": "FLUX.1 dev · text-to-image", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate", "model": "dev", "base": "dev", "shape": "txt2img",
        "gen_max": 1024, "steps": 20, "guidance": 3.5, "needs_mask": False, "cached": False,  # standard FLUX.1-dev default
    },
    "schnell": {
        "label": "FLUX.1 schnell · fast text-to-image", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate", "model": "schnell", "base": "schnell", "shape": "txt2img",
        # NOTE: tested live - the HF repo folder exists locally but is missing its VAE
        # component (FileNotFoundError from mflux's own weight loader), so despite
        # looking "cached" on disk it still needs one more download. Don't trust a
        # bare folder-exists check for this one.
        "gen_max": 1024, "steps": 4, "guidance": 0, "needs_mask": False, "cached": False,
    },
    "flux2-t2i": {
        "label": "FLUX.2 Klein-4B · text-to-image", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-flux2", "model": "flux2-klein-4b", "base": "flux2-klein-4b", "shape": "txt2img",
        # guidance=1.0 confirmed: mflux-generate-flux2 hard-errors on any other value
        # ("--guidance is only supported for FLUX.2 base models. Use --guidance 1.0.")
        # steps/cached tested live below - shares klein-4b's already-cached weights.
        "gen_max": 1024, "steps": 4, "guidance": 1.0, "needs_mask": False, "cached": True, "neg": False,
    },
    "qwen-t2i": {
        "label": "Qwen-Image", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-qwen", "model": None, "base": None, "shape": "txt2img",
        "gen_max": 1024, "steps": 20, "guidance": 4.0, "needs_mask": False, "cached": False,  # generic default
    },
    "fibo-t2i": {
        "label": "Bria FIBO", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-fibo", "model": "fibo", "base": "fibo", "shape": "txt2img",
        "gen_max": 1024, "steps": 20, "guidance": 3.5, "needs_mask": False, "cached": False,  # generic default
    },
    "z-image": {
        "label": "Z-Image", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-z-image", "model": None, "base": None, "shape": "txt2img",
        "gen_max": 1024, "steps": 20, "guidance": 3.5, "needs_mask": False, "cached": False,  # generic default
    },
    "z-image-turbo": {
        "label": "Z-Image Turbo", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-z-image-turbo", "model": None, "base": None, "shape": "txt2img",
        "gen_max": 1024, "steps": 4, "guidance": 0, "needs_mask": False, "cached": False,  # standard distilled default
    },
    "ernie-image": {
        "label": "ERNIE-Image", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-ernie-image", "model": None, "base": None, "shape": "txt2img",
        "gen_max": 1024, "steps": 20, "guidance": 3.5, "needs_mask": False, "cached": False,  # generic default
    },
    "ernie-image-turbo": {
        "label": "ERNIE-Image Turbo", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-ernie-image-turbo", "model": None, "base": None, "shape": "txt2img",
        "gen_max": 1024, "steps": 4, "guidance": 0, "needs_mask": False, "cached": False,  # standard distilled default
    },
    "ideogram4": {
        "label": "Ideogram4", "group": "Text-to-image",
        "bin": f"{BIN}/mflux-generate-ideogram4", "model": None, "base": None, "shape": "txt2img",
        "gen_max": 1024, "steps": 20, "guidance": 3.5, "needs_mask": False, "cached": False,  # generic default
    },
}
# Deliberately NOT included: controlnet / depth (need a control/depth map input),
# redux (needs separate *reference* images, not "edit this image"), in-context /
# in-context-edit / in-context-catvton / concept / concept-from-image (multi-image
# composition workflows), upscale-* (post-process, not prompt-driven), train /
# save / lora-library / completions / info (not image generation at all). None of
# these fit this app's single-image + prompt + optional-mask flow without a
# genuinely different UI, so half-wiring them in would just be a broken menu entry.

def available_models():
    out = [{"id": k, "label": m["label"], "group": m["group"],
            "cached": m["cached"], "shape": m["shape"], "needs_mask": m["needs_mask"],
            "steps": m["steps"], "guidance": m["guidance"], "gen_max": m["gen_max"],
            "neg": m.get("neg", True)}
           for k, m in MODELS.items()]
    for entry in load_custom_models():
        spec = custom_spec(entry)
        if spec is None: continue
        out.append({"id": f"custom:{entry['id']}", "label": spec["label"], "group": "Custom",
                     "cached": True, "shape": spec["shape"], "needs_mask": spec["needs_mask"],
                     "steps": spec["steps"], "guidance": spec["guidance"], "gen_max": spec["gen_max"],
                     "neg": spec.get("neg", True)})
    return out

# --- custom (locally-saved) models -----------------------------------------------
def load_custom_models():
    try:
        with open(CUSTOM_MODELS_FILE) as f: return json.load(f)
    except Exception:
        return []

def save_custom_models(items):
    os.makedirs(CFG_DIR, exist_ok=True)
    # only validate genuinely-new entries (id not already saved) - an existing entry
    # whose drive happens to be unmounted right now must NOT get silently dropped
    # just because someone else's remove/add action re-saved the whole list.
    old_ids = {e.get("id") for e in load_custom_models()}
    clean = []
    for it in (items or [])[:100]:
        template = str(it.get("template") or "")
        path = str(it.get("path") or "").strip()
        label = str(it.get("label") or "").strip()[:100]
        if template not in MODELS or not path or not label: continue
        eid = str(it.get("id") or os.urandom(4).hex())
        if eid not in old_ids and not os.path.isdir(path):
            raise ValueError(f"model path not found: {path}")
        clean.append({"id": eid, "label": label, "template": template, "path": path,
                       "base_model": str(it.get("base_model") or "").strip()[:100]})
    with open(CUSTOM_MODELS_FILE, "w") as f: json.dump(clean, f, indent=2)
    return clean

def custom_spec(entry):
    tmpl = MODELS.get(entry.get("template"))
    if tmpl is None: return None
    spec = {**tmpl, "label": entry["label"], "model": entry["path"], "cached": True}
    if entry.get("base_model"): spec["base"] = entry["base_model"]
    return spec

def resolve_spec(mid):
    if mid.startswith("custom:"):
        cid = mid[len("custom:"):]
        for entry in load_custom_models():
            if entry.get("id") == cid: return custom_spec(entry)
        return None
    return MODELS.get(mid)

# --- geometry helpers -----------------------------------------------------------
def snap16(v): return max(16, int(round(v / 16)) * 16)
def gen_size(w, h, gmax, gmin=256):
    long = max(w, h)
    s = gmin / long if long < gmin else gmax / long if long > gmax else 1.0
    return snap16(w * s), snap16(h * s)
def feather_px(w, h): return max(2, min(24, int(round(min(w, h) * 0.02))))

def b64_to_img(data):
    if "," in data: data = data.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data)))
def img_to_b64(img):
    buf = io.BytesIO(); img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

# --- jobs (streaming progress) --------------------------------------------------
JOBS = {}
JLOCK = threading.Lock()
STEP_RE = re.compile(r'(\d+)/(\d+)')
def _jset(jid, **kw):
    with JLOCK: JOBS.setdefault(jid, {}).update(kw, t=time.time())
def _jget(jid):
    with JLOCK: return {k: v for k, v in JOBS.get(jid, {}).items() if not k.startswith("_")}

def build_cmd(spec, prompt, steps, guidance, seeds, negative_prompt, quantize, gw, gh, gout, gin=None, gmask=None):
    """Pure command-builder (no I/O) so the CLI shape per model can be unit-tested directly."""
    cmd = [spec["bin"]]
    if spec.get("model"): cmd += ["-m", spec["model"]]
    if spec.get("base"): cmd += ["--base-model", spec["base"]]
    cmd += ["--prompt", prompt]
    if negative_prompt: cmd += ["--negative-prompt", negative_prompt]
    if gh: cmd += ["--height", str(gh)]
    if gw: cmd += ["--width", str(gw)]
    if steps: cmd += ["--steps", str(steps)]
    if guidance is not None: cmd += ["--guidance", str(guidance)]
    if quantize: cmd += ["--quantize", str(quantize)]
    cmd += ["--output", gout]
    shape = spec["shape"]
    if shape == "fill":
        cmd += ["--image-path", gin, "--masked-image-path", gmask]
    elif shape == "edit_multi":
        cmd += ["--image-paths", gin]
    elif shape == "edit_single":
        cmd += ["--image-path", gin]
    elif shape == "edit_mask":
        cmd += ["--image-path", gin]
        if gmask: cmd += ["--mask-path", gmask]
    # shape == "txt2img": no image flags at all
    if seeds: cmd += ["--seed"] + [str(s) for s in seeds]
    return cmd

def _popen_stream(cmd, steps, jid):
    """Run cmd, parse mflux's live step output, push progress to JOBS[jid]."""
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "PYTHONUNBUFFERED": "1"}
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, bufsize=0)
    _jset(jid, phase="loading", step=0, total=steps, _proc=p)
    fd = p.stdout.fileno(); buf = b""; tail = b""
    while True:
        chunk = os.read(fd, 4096)
        if not chunk: break
        tail = (tail + chunk)[-3000:]
        buf += chunk
        parts = re.split(rb'[\r\n]', buf); buf = parts[-1]
        for seg in parts[:-1]:
            for mt in STEP_RE.finditer(seg.decode("utf-8", "ignore")):
                n, t = int(mt.group(1)), int(mt.group(2))
                if t == steps:   # the denoise loop (ignore unrelated x/y counters)
                    _jset(jid, phase=("decoding" if n >= t else "denoising"), step=n, total=t)
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(tail.decode("utf-8", "ignore")[-1500:] or "mflux failed")

def _collect_outputs(out):
    # multi-seed runs write one file per seed (out_seed_<N>.png); single-seed writes out.png.
    files = sorted(glob.glob(out.replace(".png", "*.png")), key=os.path.getmtime)
    if not files: raise RuntimeError("mflux produced no output")
    return files

def run_edit_or_fill(spec, base, mask, prompt, steps, guidance, seeds, gen_max, jid, negative_prompt, quantize):
    cw, ch = base.size
    gw, gh = gen_size(cw, ch, gen_max)
    with tempfile.TemporaryDirectory() as d:
        gin = os.path.join(d, "in.png"); out = os.path.join(d, "out.png")
        base.resize((gw, gh)).save(gin)
        gmask = None
        if mask is not None and spec["shape"] in ("fill", "edit_mask"):
            gmask = os.path.join(d, "mask.png")
            mask.convert("RGB").resize((gw, gh)).save(gmask)   # white = fill/edit region
        cmd = build_cmd(spec, prompt, steps, guidance, seeds, negative_prompt, quantize, gw, gh, out, gin, gmask)
        _popen_stream(cmd, steps, jid)
        return [Image.open(f).convert("RGB").resize((cw, ch)) for f in _collect_outputs(out)]

def run_txt2img(spec, prompt, steps, guidance, seeds, width, height, jid, negative_prompt, quantize):
    gw, gh = snap16(width), snap16(height)
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out.png")
        cmd = build_cmd(spec, prompt, steps, guidance, seeds, negative_prompt, quantize, gw, gh, out)
        _popen_stream(cmd, steps, jid)
        return [Image.open(f).convert("RGB") for f in _collect_outputs(out)]

def _run_job(jid, payload, spec):
    try:
        shape = spec["shape"]
        prompt = payload["prompt"].strip()
        negative_prompt = (payload.get("negative_prompt") or "").strip() or None
        if not spec.get("neg", True): negative_prompt = None   # FLUX.2 rejects this flag entirely
        steps = int(payload.get("steps") or spec["steps"] or 0) or None
        g = payload.get("guidance")
        guidance = float(g) if g not in (None, "") else spec["guidance"]
        quantize = payload.get("quantize") or None
        seed_raw = str(payload.get("seed") or "").strip()
        seeds = [s.strip() for s in seed_raw.split(",") if s.strip()] or None

        # optional local weights override: mflux's own -m/--model accepts a HF repo
        # name, org/model, OR a local filesystem path - if the user points us at a
        # folder they already downloaded, pass it straight through instead of the
        # preset name. --base-model stays as the architecture hint mflux needs.
        model_path = (payload.get("model_path") or "").strip()
        if model_path:
            if not os.path.isdir(model_path):
                raise ValueError(f"model path not found: {model_path}")
            spec = {**spec, "model": model_path}

        if shape == "txt2img":
            width = int(payload.get("width") or 1024)
            height = int(payload.get("height") or 1024)
            results = run_txt2img(spec, prompt, steps, guidance, seeds, width, height, jid, negative_prompt, quantize)
        else:
            base = b64_to_img(payload["image"]).convert("RGB")
            gen_max = int(payload.get("size") or spec["gen_max"])
            mask_data = payload.get("mask"); mask = None
            if mask_data:
                mm = b64_to_img(mask_data)
                mask = (mm.split()[-1] if mm.mode in ("RGBA", "LA") else mm.convert("L")).resize(base.size)
            if mask is None or not mask.getbbox():
                mask = Image.new("L", base.size, 255) if shape == "fill" else None
            results = run_edit_or_fill(spec, base, mask, prompt, steps, guidance, seeds, gen_max, jid, negative_prompt, quantize)
            if mask is not None:   # keep everything outside the mask pixel-exact (feathered seam)
                f = feather_px(*base.size); dil = min(25, f * 2 + 1)
                soft = mask.filter(ImageFilter.MaxFilter(dil if dil % 2 else dil + 1))
                soft = soft.filter(ImageFilter.GaussianBlur(max(1, f // 2)))
                results = [Image.composite(r, base, soft) for r in results]
        images = [img_to_b64(r) for r in results]
        _jset(jid, status="done", phase="done", step=steps or 0, total=steps or 0, images=images)
    except Exception as e:
        with JLOCK: cancelled = JOBS.get(jid, {}).get("_cancel")
        _jset(jid, status="error", error="cancelled" if cancelled else str(e)[-1500:])

def handle_run(payload):
    """Start a job, return its id immediately. Client polls /progress?job=ID."""
    prompt = (payload.get("prompt") or "").strip()
    if not prompt: raise ValueError("prompt is empty")
    mid = payload.get("model") or next(iter(MODELS))
    spec = resolve_spec(mid)
    if not spec: raise ValueError(f"unknown model {mid}")
    if spec["shape"] != "txt2img" and not payload.get("image"):
        raise ValueError("this model needs an input image")
    if len(JOBS) > 40:                       # drop oldest finished jobs
        with JLOCK:
            for k in sorted(JOBS, key=lambda k: JOBS[k].get("t", 0))[:20]: JOBS.pop(k, None)
    jid = os.urandom(6).hex()
    _jset(jid, status="running", phase="starting", step=0, total=int(payload.get("steps") or spec["steps"] or 1))
    threading.Thread(target=_run_job, args=(jid, payload, spec), daemon=True).start()
    return {"job": jid}

def handle_progress(query):
    jid = urllib.parse.parse_qs(query).get("job", [""])[0]
    j = _jget(jid)
    if not j: return {"status": "unknown"}
    return j

def handle_cancel(query):
    jid = urllib.parse.parse_qs(query).get("job", [""])[0]
    with JLOCK:
        j = JOBS.get(jid); p = j.get("_proc") if j else None
        if j: j["_cancel"] = True
    if p and p.poll() is None:
        try: p.terminate()
        except Exception: pass
    return {"ok": True}

# --- saved prompts --------------------------------------------------------------
def load_prompts():
    try:
        with open(PROMPTS_FILE) as f: d = json.load(f)
        return {"default": d.get("default", ""), "presets": d.get("presets", [])}
    except Exception:
        return {"default": "", "presets": []}
def save_prompts(d):
    os.makedirs(CFG_DIR, exist_ok=True)
    data = {"default": (d.get("default") or "")[:2000],
            "presets": [str(p)[:2000] for p in (d.get("presets") or [])][:200]}
    with open(PROMPTS_FILE, "w") as f: json.dump(data, f, indent=2)
    return data

# --- save / open folder ---------------------------------------------------------
def handle_save(payload):
    os.makedirs(SAVE_DIR, exist_ok=True)
    img = b64_to_img(payload["image"]).convert("RGB")
    name = payload.get("name") or f"mflux-{time.strftime('%Y%m%d-%H%M%S')}.png"
    if not name.lower().endswith(".png"): name += ".png"
    name = os.path.basename(name)
    path = os.path.join(SAVE_DIR, name)
    img.save(path)
    return {"path": path, "dir": SAVE_DIR, "name": name}
def open_folder():
    os.makedirs(SAVE_DIR, exist_ok=True)
    subprocess.Popen(["open", SAVE_DIR])
    return {"dir": SAVE_DIR}
def handle_copy(payload):
    # pywebview's WKWebView often refuses navigator.clipboard.write() for images
    # (silent NotAllowedError). Go through the system pasteboard instead via osascript,
    # which works regardless of WebView clipboard permissions.
    img = b64_to_img(payload["image"]).convert("RGB")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img.save(f.name)
        path = f.name
    try:
        subprocess.run(
            ["osascript", "-e", f'set the clipboard to (read (POSIX file "{path}") as «class PNGf»)'],
            check=True, capture_output=True, text=True)
    finally:
        os.remove(path)
    return {"ok": True}

# --- http -----------------------------------------------------------------------
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)
    def _json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}
    def do_GET(self):
        try:
            if self.path == "/alive":
                LAST_PING[0] = time.time(); self._send(200, b"ok", "text/plain")
            elif self.path == "/models":
                self._send(200, json.dumps({"models": available_models(), "save_dir": SAVE_DIR}))
            elif self.path.startswith("/progress"):
                q = self.path.split("?", 1)[1] if "?" in self.path else ""
                self._send(200, json.dumps(handle_progress(q)))
            elif self.path == "/prompts":
                self._send(200, json.dumps(load_prompts()))
            elif self.path == "/custom-models":
                self._send(200, json.dumps({"models": load_custom_models(), "templates": list(MODELS)}))
            elif self.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif self.path.startswith("/assets/"):
                name = os.path.basename(self.path[len("/assets/"):])
                path = os.path.join(HERE, "assets", name)
                if not os.path.isfile(path):
                    return self._send(404, b"not found", "text/plain")
                ctype = "image/png" if name.endswith(".png") else "image/x-icns" if name.endswith(".icns") else "application/octet-stream"
                with open(path, "rb") as f:
                    self._send(200, f.read(), ctype)
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))
    def do_POST(self):
        try:
            if self.path == "/run":       return self._send(200, json.dumps(handle_run(self._json())))
            if self.path.startswith("/cancel"):
                return self._send(200, json.dumps(handle_cancel(self.path.split("?",1)[1] if "?" in self.path else "")))
            if self.path == "/save":      return self._send(200, json.dumps(handle_save(self._json())))
            if self.path == "/copy":      return self._send(200, json.dumps(handle_copy(self._json())))
            if self.path == "/open":      return self._send(200, json.dumps(open_folder()))
            if self.path == "/prompts":   return self._send(200, json.dumps(save_prompts(self._json())))
            if self.path == "/custom-models":
                return self._send(200, json.dumps({"models": save_custom_models(self._json().get("models"))}))
            self._send(404, b"not found", "text/plain")
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}))

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    print(f"mflux-paint on http://localhost:{PORT}   (saves -> {SAVE_DIR})")
    if not os.environ.get("MFLUX_NO_IDLE"):   # set MFLUX_NO_IDLE=1 to keep running with no page open
        threading.Thread(target=_watchdog, daemon=True).start()
    Server(("127.0.0.1", PORT), H).serve_forever()
