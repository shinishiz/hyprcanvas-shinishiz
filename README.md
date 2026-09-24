# hyprland-canvas

Pan floating windows like an infinite desktop on Hyprland.

[![CI](https://img.shields.io/github/actions/workflow/status/zyrophix/hyprland-canvas/ci.yml)](https://github.com/zyrophix/hyprland-canvas/actions)
[![Release](https://img.shields.io/github/v/release/zyrophix/hyprland-canvas)](https://github.com/zyrophix/hyprland-canvas/releases)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Drag the canvas with **SUPER+SHIFT+LMB**, navigate between windows, toggle canvas mode per workspace. Runs as an unprivileged user daemon — communicates directly with Hyprland via its IPC socket and Lua API.

<video src="https://github.com/user-attachments/assets/6bb06c3e-c553-481d-b726-15033ed8ac37" autoplay loop muted playsinline width="900">Demo: panning floating windows as an infinite desktop</video>

## Why

Hyprland has no built-in infinite desktop. This daemon provides one by communicating with Hyprland the right way:

- **Direct Unix socket IPC** to Hyprland — no per-request subprocess startup
- **Hyprland Lua API** (`hl.dsp.window.move`) moves windows without focusing them — no cursor warp or flicker
- Runs as an unprivileged user daemon — no special permissions needed
- Has a **Unix socket IPC** for keyboard-driven commands (navigate, toggle, invert)

Honest limits: no render-level zoom (windows move, nothing scales), no touchpad gestures, no resize/move of tiled windows — pan, navigate, toggle, nothing else.

## Features

| Feature | Keybind | Description |
|---------|---------|-------------|
| Pan canvas | SUPER+SHIFT+LMB | Drag to pan all floating windows |
| Edge-scroll | SUPER+LMB | Drag a floating window toward the screen edge — camera follows (engages only for a confirmed drag of the window under the cursor) |
| Navigate | SUPER+SHIFT+Arrows | Spatial jump to nearest window in direction (up/down/left/right), auto-pan to center |
| Canvas toggle | SUPER+SHIFT+C | Toggle all windows on workspace to/from floating |
| Toggle single | SUPER+SHIFT+V | Toggle focused window floating ↔ tiled |
| Invert | SUPER+SHIFT+G | Invert pan direction |

## Install

Requires: Hyprland 0.55+ (Lua config with `hl.*` API), Python 3.12+, `uv` or `pipx`.

**uv (recommended):**
```bash
git clone https://github.com/zyrophix/hyprland-canvas.git
cd hyprland-canvas
uv tool install .
```

**pipx:**
```bash
git clone https://github.com/zyrophix/hyprland-canvas.git
cd hyprland-canvas
pipx install .
```

**Run from source (no install):**
```bash
git clone https://github.com/zyrophix/hyprland-canvas.git
cd hyprland-canvas
uv run canvasd
```

After pulling new code, reinstall and restart the daemon — an old installed copy keeps running until you do:

```bash
git pull
uv tool install . --force --reinstall   # or: pipx install . --force
```

## Quickstart

```bash
canvasd &            # 1. start the daemon
canvas-ctl ping      # 2. check it answers
```

Expected output:

```
PONG
```

```bash
canvas-ctl status    # 3. show pan direction and state
```

Then add the Hyprland keybinds from [Usage](#usage) and drag with SUPER+SHIFT+LMB.

## Usage

### 1. Start the daemon

```bash
canvasd
```

### 2. Add Hyprland keybinds

Hyprland 0.55+ uses Lua for config. Add these binds:

```lua
-- Canvas: pan (mouse binds)
hl.bind("SUPER + SHIFT + mouse:272", function()
    os.execute("canvas-ctl pan-start")
end, { mouse = true })

hl.bind("SUPER + SHIFT + mouse:272", function()
    os.execute("canvas-ctl pan-stop")
end, { mouse = true, release = true })

-- Canvas: edge-scroll (drag window to screen edge → camera follows)
hl.bind("SUPER + mouse:272", function()
    hl.dispatch(hl.dsp.window.drag())
    hl.exec_cmd("canvas-ctl edge-start")
end, { mouse = true })

hl.bind("SUPER + mouse:272", function()
    hl.exec_cmd("canvas-ctl edge-stop")
end, { mouse = true, release = true })

-- Canvas: navigation (4-dir spatial)
hl.bind("SUPER + SHIFT + left", function()
    os.execute("canvas-ctl nav-left")
end)
hl.bind("SUPER + SHIFT + right", function()
    os.execute("canvas-ctl nav-right")
end)
hl.bind("SUPER + SHIFT + up", function()
    os.execute("canvas-ctl nav-up")
end)
hl.bind("SUPER + SHIFT + down", function()
    os.execute("canvas-ctl nav-down")
end)

-- Canvas: toggle & invert
hl.bind("SUPER + SHIFT + C", function()
    os.execute("canvas-ctl canvas-toggle")
end)
hl.bind("SUPER + SHIFT + V", function()
    os.execute("canvas-ctl canvas-toggle-single")
end)
hl.bind("SUPER + SHIFT + G", function()
    os.execute("canvas-ctl toggle")
end)
```

### 3. Control commands

The full list lives in the CLI itself — `canvas-ctl --help` is canonical:

```bash
canvas-ctl --help     # all 14 commands with one-line descriptions
canvas-ctl ping       # check if daemon is running
canvas-ctl status     # show pan direction and state
```

### Configuration

All defaults are built into the daemon (`DEFAULT_CONFIG` in `canvas/config.py`) — it runs fine with no config file. The repo's `config.yml` is a ready-to-copy template; installed wheels/pipx/uv-tool packages do not include it. To customize, create `~/.config/canvas/config.yml`:

```yaml
speed: 1.6                    # pan speed multiplier
invert:
  enabled: true               # true = grab canvas (intuitive), false = follow cursor
edge_scroll:
  enabled: true               # auto-pan when dragging window past screen edge
  ramp_distance: 50            # px of overflow to reach full speed
  speed: 20.0                  # max px/frame at full overflow (~1200 px/s at 60fps)
  grab_dead_zone: 5            # px of real movement before camera engages
  # max_speed: 30             # optional: cap per-frame edge-scroll delta (pixels)
navigation:
  cooldown: 0.2               # seconds between nav commands
  protected_apps:             # these windows are skipped during navigation
    - brave-browser
    - chromium
    - firefox
canvas:
  preserve_geometry: true     # remember floating window positions/sizes on OFF,
                               # restore them on the next ON; tiled placement itself
                               # is always layout-owned
```

Invalid values (wrong type, zero/negative numbers) are rejected
at daemon startup with the exact offending keys listed on stderr.

## Repo overview

- `canvas/` — daemon source: `hypr.py` (IPC), `panning.py`,
  `navigation.py`, `ipc.py` (ctl server), `config.py`, `daemon.py`
- `tests/` — mocked pytest suite, no live compositor needed (`uv run pytest`)
- `docs/` — architecture and debugging notes beyond this README
- `config.yml` — ready-to-copy config template
- `pyproject.toml` — package metadata, pytest/ruff/mypy config

## Contributing

PRs welcome. Run `uv run pytest` and `uv run ruff check` before submitting.

## License

MIT — see [LICENSE](LICENSE) for details.
