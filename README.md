# Hyprland Canvas

Pan floating windows like an infinite desktop on Hyprland.

[![CI](https://img.shields.io/github/actions/workflow/status/shinishiz/hyprland-canvas/ci.yml)](https://github.com/shinishiz/hyprland-canvas/actions)
[![Release](https://img.shields.io/github/v/release/shinishiz/hyprland-canvas)](https://github.com/shinishiz/hyprland-canvas/releases)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Fork of [zyrophix/hyprland-canvas](https://github.com/zyrophix/hyprland-canvas) with additional window integration and workspace workflow improvements.

Drag the canvas with **SUPER+SHIFT+LMB**, navigate between windows, toggle canvas mode per workspace. Runs as an unprivileged user daemon — communicates directly with Hyprland via its IPC socket and Lua API.

<video src="https://github.com/user-attachments/assets/6bb06c3e-c553-481d-b726-15033ed8ac37" autoplay loop muted playsinline width="900">Demo: panning floating windows as an infinite desktop</video>

## What this fork adds

This fork adds the following improvements over the upstream:

- **Automatic handling of windows opened while Canvas is active** — newly opened tiled windows automatically become part of the Canvas (become floating with sensible geometry)
- **Socket2 event listener** — real-time window creation events via Hyprland's `.socket2.sock`
- **Sensible spawn geometry** — new windows use median geometry from original tiled snapshot
- **Restoration to tiled state** — when leaving Canvas, windows return to their tiled positions correctly
- **Safer address normalization** — robust window address handling between socket2 events and j/clients
- **Hyprland 0.56.2 compatibility** — updated for API changes in 0.56.2

## Workspace workflow

Dwindle → Canvas → Scrolling → Dwindle

via **Super + Space**:

- **Dwindle + Canvas OFF** → Canvas ON (floating, pan/edge-scroll/nav enabled)
- **Canvas ON (on Dwindle)** → Scrolling + Canvas OFF
- **Scrolling + Canvas OFF** → Dwindle
- **Scrolling + Canvas ON** → Canvas OFF, stays in Scrolling

### Canvas Mode (while active)

| Feature | Keybind | Description |
| --- | --- | --- |
| Pan canvas | SUPER+SHIFT+LMB | Drag to pan all floating windows |
| Edge-scroll | SUPER+LMB | Drag a floating window toward screen edge — camera follows |
| Navigate | SUPER+SHIFT+Arrows | Spatial jump to nearest window (up/down/left/right), auto-pan to center |
| Center under cursor | SUPER+MMB | Center canvas on topmost floating window under cursor |
| Toggle single window | SUPER+SHIFT+V | Toggle focused window floating ↔ tiled |
| Invert pan direction | SUPER+SHIFT+G | Invert pan direction |

## Keybinds

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

-- Canvas: center view on the floating window under the cursor
hl.bind("SUPER + mouse:274", function()
    hl.exec_cmd("canvas-ctl center-cursor")
end, { mouse = true })

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
hl.bind("SUPER + SHIFT + V", function()
    os.execute("canvas-ctl canvas-toggle-single")
end)
hl.bind("SUPER + SHIFT + G", function()
    os.execute("canvas-ctl toggle")
end)

-- Super+Space: Cycle workspace mode (Dwindle → Canvas → Scrolling → Dwindle)
hl.bind("SUPER + SPACE", cycle_mode)
```

Note: `SUPER+SHIFT+C` (canvas toggle) is intentionally omitted — the `SUPER+SPACE` cycle replaces it for a more intuitive workflow.

## Installation

Requires: Hyprland 0.55+ (Lua config with `hl.*` API), Python 3.12+, `uv`, `pipx`, or Arch `makepkg`.

**uv (recommended):**

```bash
git clone https://github.com/shinishiz/hyprland-canvas.git
cd hyprland-canvas
uv tool install .
```

**pipx:**

```bash
git clone https://github.com/shinishiz/hyprland-canvas.git
cd hyprland-canvas
pipx install .
```

**Run from source (no install):**

```bash
git clone https://github.com/shinishiz/hyprland-canvas.git
cd hyprland-canvas
uv run canvasd
```

After pulling new code, reinstall and restart the daemon:

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

```text
PONG
```

```bash
canvas-ctl status    # show pan direction and state
```

Then add the Hyprland keybinds from above and drag with SUPER+SHIFT+LMB.

## Control commands

The full list lives in the CLI itself — `canvas-ctl --help` is canonical:

```bash
canvas-ctl --help  # all 15 commands with one-line descriptions
canvas-ctl ping    # check if daemon is running
canvas-ctl status  # show pan direction and state
```

### Configuration

All defaults are built into the daemon (`DEFAULT_CONFIG` in `canvas/config.py`) — it runs fine with no config file. To customize, create `~/.config/canvas/config.yml`:

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

## Repository structure

- `canvas/` — daemon source: `hypr.py` (IPC), `panning.py`,
  `navigation.py`, `ipc.py` (ctl server), `config.py`, `daemon.py`
- `tests/` — mocked pytest suite, no live compositor needed (`uv run pytest`)
- `docs/` — [architecture.md](docs/architecture.md): process model, IPC, config load
- `docs/` — [debugging.md](docs/debugging.md): logs, tracing, common failures
- `config.yml` — ready-to-copy config template
- `pyproject.toml` — package metadata, pytest/ruff/mypy config

## What this fork adds (vs upstream)

| Feature | Status |
|---------|--------|
| Auto-float new windows during Canvas ON | ✅ Implemented |
| Socket2 event listener (.socket2.sock) | ✅ Implemented |
| Sensible spawn geometry | ✅ Implemented |
| Restoration to tiled on Canvas OFF | ✅ Implemented |
| Canvas state persistence (toggle-state.json) | ✅ Implemented |
| Spawned window tracking & restoration | ✅ Implemented |
| Super+Space cycle: Dwindle → Canvas → Scrolling → Dwindle | ✅ Implemented |
| SUPER+SHIFT+Arrows navigation (conditional) | ✅ Implemented |
| SUPER+SHIFT+V (single window toggle) | ✅ Implemented |
| SUPER+SHIFT+G (invert pan) | ✅ Implemented |
| Hyprland 0.56.2 compatibility | ✅ Updated |

## systemd user service

```ini
# ~/.config/systemd/user/hypr-canvasd.service
[Unit]
Description=Hyprland Canvas daemon
PartOf=hyprland-session.target

[Service]
Type=simple
ExecStart=/home/youruser/.local/bin/hypr-canvasd
Restart=on-failure
RestartSec=1

[Install]
WantedBy=hyprland-session.target
```

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hypr-canvasd.service
```

Wrappers (included in repo, install to `~/.local/bin/`):

- `hypr-canvasd` — daemon launcher
- `hypr-canvas-ctl` — control CLI
- `hypr-canvas-transition` — stateful transition wrapper

## Updating from upstream

Remotes:
- `origin` → your fork (push access)
- `upstream` → zyrophix/hyprland-canvas (read-only)

```bash
# Sync upstream changes
git fetch upstream
git rebase upstream/main

# Push to your fork
git push origin main
```

## Tested on

- Hyprland 0.56.2
- Fedora Linux 44 (Workstation Edition)
- Python 3.12 / uv 0.12.9

## Tests

```bash
uv run pytest
uv run ruff check .
uv run mypy canvas
```

247 tests passing, 80.17% coverage.

## Credits

- Original: [zyrophix/hyprland-canvas](https://github.com/zyrophix/hyprland-canvas)
- Fork maintained by: shinishiz

## License

MIT — see [LICENSE](LICENSE) for details.
