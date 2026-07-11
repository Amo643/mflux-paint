# mflux-paint

A single-screen inpaint/edit UI for the [mflux](https://github.com/filipstrand/mflux) engine — 16 FLUX/Qwen/FIBO/Z-Image/ERNIE/Ideogram models, whole-image edit, true inpainting, and text-to-image, all running fully local on Apple Silicon via MLX. No PyTorch, no cloud. Independent project, not affiliated with or based on IOPaint.

![screenshot](docs/screenshot.png)

## Requirements

- macOS, Apple Silicon
- Python 3.9+
- [mflux](https://github.com/filipstrand/mflux) CLI tools:
  ```
  uv tool install mflux
  ```
  (or `pipx install mflux`) — installs `mflux-generate`, `mflux-generate-flux2-edit`, `mflux-generate-fill`, etc. into your PATH. This app shells out to those binaries directly (default: `/opt/homebrew/bin/mflux-generate-*` — edit `BIN` in `server.py` if yours live elsewhere).

## Install

```bash
git clone https://github.com/Amo643/mflux-paint.git
cd mflux-paint
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

### Desktop app

```bash
./launch.sh
```
This is the "turn it into a desktop app" path: `desktop.py` starts `server.py` in a background thread, then opens it in a real native window via [pywebview](https://pywebview.flowrl.com/) (WKWebView on macOS — no Chrome/Electron involved). It looks and behaves like a normal Mac app: its own window, its own Dock/Cmd-Tab entry, closing the window kills the server with it. `launch.sh` first checks `:7866/alive`; if the app is already running it just refocuses that window instead of opening a second one, so it's safe to run repeatedly (e.g. bind it to a Dock icon, Spotlight, or `alias mpaint=~/Desktop/codes/mflux-paint/launch.sh`).

Want an actual double-clickable `.app` bundle (Finder/Dock/Launchpad, no terminal)? Wrap `launch.sh` with [Platypus](https://sveinbjorn.org/platypus) (`platypus -a "mflux paint" launch.sh`) or a one-file Automator "Run Shell Script" app — `desktop.py` itself doesn't need to change, it already behaves like a standalone app once launched.

### Browser mode

For remote/headless use, or if you don't want the native window:
```bash
python3 server.py
```
then open `http://localhost:7866`. In this mode the server auto-exits after 20s with no page pinging it (set `MFLUX_NO_IDLE=1` to disable).

## Features

- Brush / eraser / box-select mask painting, undo/redo, invert, hide/show
- Whole-image edit, true inpaint (fill), and text-to-image, depending on model
- Live per-step progress (parsed straight from mflux's own output), cancel mid-run
- **Multi-seed batch**: comma-separate seeds in the Seed field (e.g. `111,222,333`) to run one prompt against several seeds in a single job — mflux writes one file per seed natively, the app collects all of them and shows a thumbnail strip after the run so you click the one you want as the new base image. Leave it blank for a single random seed as usual.
- Negative prompt (hidden automatically for FLUX.2 models — they reject the flag outright), quantization (3/4/5/6/8-bit), custom resolution
- Saved/starred prompts, chain edits (each result becomes the next base image), compare-to-original (hold `C`), revert
- Copy to clipboard, save to a folder, download

Full shortcut list is in the app itself (`?` key).

## Models

| Model | Category | Tested? |
|---|---|---|
| FLUX.2 Klein-4B — fast edit | Edit | ✅ verified — real edits, multi-seed batch, cancel |
| FLUX.2 Klein-9B — quality edit | Edit | ⚠️ works, but `gen_max` (resolution cap) unverified against the real 9B weights |
| Qwen-Image-Edit | Edit | ❌ untested — wired per `--help`, not run |
| FLUX.1 Kontext — image edit | Edit | ❌ untested — wired per `--help`, not run |
| Bria FIBO Edit | Edit | ❌ untested — wired per `--help`, not run |
| FLUX.1 Fill — true inpaint | Inpaint | ❌ untested — wired per `--help`, not run |
| FLUX.1 dev — text-to-image | Text-to-image | ❌ untested — wired per `--help`, not run |
| FLUX.1 schnell — fast text-to-image | Text-to-image | 🔴 tried, failed — HF folder present but missing its VAE component; needs one more download |
| FLUX.2 Klein-4B — text-to-image | Text-to-image | ✅ verified — real run |
| Qwen-Image | Text-to-image | ❌ untested — wired per `--help`, not run |
| Bria FIBO | Text-to-image | ❌ untested — wired per `--help`, not run |
| Z-Image | Text-to-image | ❌ untested — wired per `--help`, not run |
| Z-Image Turbo | Text-to-image | ❌ untested — wired per `--help`, not run |
| ERNIE-Image | Text-to-image | ❌ untested — wired per `--help`, not run |
| ERNIE-Image Turbo | Text-to-image | ❌ untested — wired per `--help`, not run |
| Ideogram4 | Text-to-image | ❌ untested — wired per `--help`, not run |

"Untested" ones were built by matching each mflux subcommand's own `--help` output (right image-flag shape, right guidance/negative-prompt restrictions where discoverable) but never actually run — no internet was available to fetch their weights while this was built. The two bugs the testing *did* catch (FLUX.2 base rejecting any `--guidance` but 1.0, FLUX.2 rejecting `--negative-prompt` outright) suggest there are probably a couple more of these landmines hiding in the untested ones. Run one, hit an mflux argument error, and it's almost certainly a one-line fix in `MODELS` in `server.py` — the error message from mflux itself tells you exactly what's wrong.

The model picker groups these into **Edit** / **Inpaint** / **Text-to-image** and marks not-yet-downloaded ones with ⬇ (separate from the tested/untested status above — a model can be downloaded and still not run right, see schnell).

Steps/guidance defaults for anything beyond the verified models are mflux-documented values where confirmed (Fill's guidance=30 and FLUX.2's guidance=1.0-only-for-base come straight from mflux's own `--help`/error text), otherwise a generic FLUX.1-dev-family starting point (steps=20, guidance=3.5) or the standard distilled/"turbo" convention (steps=4, guidance=0) — tune in Settings once you've actually run one.

Not included: ControlNet, Depth, Redux, in-context/concept tools, upscalers, and non-generation tools (train/save/lora-library) — they need control maps, depth maps, multiple reference images, or aren't image generation at all, so they don't fit this app's single-image + prompt + optional-mask flow.

## Project layout

- `server.py` — local HTTP server + model registry + mflux subprocess orchestration
- `index.html` — the entire frontend (single file, no build step)
- `desktop.py` — native window wrapper (pywebview)
- `launch.sh` — desktop app entry point / focus-existing-window

## License

MIT — see [LICENSE](LICENSE).
