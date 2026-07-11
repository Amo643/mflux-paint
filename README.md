# mflux-paint

An IOPaint-style single-screen inpaint/edit UI for the [mflux](https://github.com/filipstrand/mflux) engine — 16 FLUX/Qwen/FIBO/Z-Image/ERNIE/Ideogram models, whole-image edit, true inpainting, and text-to-image, all running fully local on Apple Silicon via MLX. No PyTorch, no cloud.

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

**Desktop app** (native window, no browser):
```bash
./launch.sh
```
Opens a WebKit window backed by a local server on `:7866`. Closing the window kills the server. Running `launch.sh` again while it's already open just refocuses the window instead of starting a second instance.

**Browser mode** (e.g. for remote/headless use):
```bash
python3 server.py
```
then open `http://localhost:7866`. In this mode the server auto-exits after 20s with no page pinging it (set `MFLUX_NO_IDLE=1` to disable).

## Features

- Brush / eraser / box-select mask painting, undo/redo, invert, hide/show
- Whole-image edit, true inpaint (fill), and text-to-image, depending on model
- Live per-step progress (parsed straight from mflux's own output), cancel mid-run
- Multi-seed batch: comma-separate seeds (`111,222,333`) to generate several variations in one run and pick the best
- Negative prompt, quantization (3/4/5/6/8-bit), custom resolution
- Saved/starred prompts, chain edits (each result becomes the next base image), compare-to-original (hold `C`), revert
- Copy to clipboard, save to a folder, download

Full shortcut list is in the app itself (`?` key).

## Models

| Model | Category | Downloaded already? |
|---|---|---|
| FLUX.2 Klein-4B — fast edit | Edit | yes |
| FLUX.2 Klein-9B — quality edit | Edit | yes |
| Qwen-Image-Edit | Edit | no |
| FLUX.1 Kontext — image edit | Edit | no |
| Bria FIBO Edit | Edit | no |
| FLUX.1 Fill — true inpaint | Inpaint | no |
| FLUX.1 dev — text-to-image | Text-to-image | no |
| FLUX.1 schnell — fast text-to-image | Text-to-image | no* |
| FLUX.2 Klein-4B — text-to-image | Text-to-image | yes |
| Qwen-Image | Text-to-image | no |
| Bria FIBO | Text-to-image | no |
| Z-Image | Text-to-image | no |
| Z-Image Turbo | Text-to-image | no |
| ERNIE-Image | Text-to-image | no |
| ERNIE-Image Turbo | Text-to-image | no |
| Ideogram4 | Text-to-image | no |

"No" means mflux fetches the weights (several GB) on first use — needs internet, only happens once per model. The model picker groups these into **Edit** / **Inpaint** / **Text-to-image** and marks undownloaded ones with ⬇.

\* FLUX.1 schnell showed up as locally present but was missing its VAE component in testing — mflux still had to fetch that piece on first run. A repo folder existing in your HF cache doesn't guarantee every component is there.

Steps/guidance defaults for anything beyond the original two Klein models are mflux-documented values where confirmed (Fill's guidance=30 and FLUX.2's guidance=1.0-only-for-base come straight from mflux's own `--help`/error text), otherwise a generic FLUX.1-dev-family starting point (steps=20, guidance=3.5) or the standard distilled/"turbo" convention (steps=4, guidance=0) — tune in Settings once you've actually run one.

Not included: ControlNet, Depth, Redux, in-context/concept tools, upscalers, and non-generation tools (train/save/lora-library) — they need control maps, depth maps, multiple reference images, or aren't image generation at all, so they don't fit this app's single-image + prompt + optional-mask flow.

## Project layout

- `server.py` — local HTTP server + model registry + mflux subprocess orchestration
- `index.html` — the entire frontend (single file, no build step)
- `desktop.py` — native window wrapper (pywebview)
- `launch.sh` — desktop app entry point / focus-existing-window

## License

MIT — see [LICENSE](LICENSE).
