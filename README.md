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
- **Socket2 event listener** — real-time window lifecycle events via Hyprland's `.socket2.sock`, with transport reconnect recovery
- **Viewport-aware spawn geometry** — new windows use the tiled snapshot's median size and spawn at the visual Canvas viewport center
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

The complete Gold integration is versioned in
[`examples/hyprland-canvas.lua`](examples/hyprland-canvas.lua). It includes
the state helpers, `SUPER+SPACE` cycle, conditional Canvas navigation, zoom
reset, border-resize synchronization, and the validated relative workspace
movement:

| Bind | Action |
| --- | --- |
| SUPER+ALT+0 | Move the focused window to current workspace + 1 and follow it |
| SUPER+SHIFT+0 | Move the focused window to current workspace - 1 and follow it; no-op below workspace 1 |
| SUPER+SPACE | Cycle Dwindle → Canvas → Scrolling → Dwindle |
| SUPER+SHIFT+LMB | Pan Canvas |
| SUPER+LMB | Drag window with edge-scroll |
| SUPER+MMB | Center on the window under the cursor |
| SUPER+SHIFT+Arrows | Canvas spatial navigation, otherwise current layout movement |
| SUPER+SHIFT+V | Toggle focused window floating/tiled |
| SUPER+SHIFT+G | Invert pan direction |
| SUPER+0 | Reset Canvas zoom |

## Installation

The Gold integration is validated against Hyprland **0.56.2**. The companion
`hypr-canvas` plugin is ABI-sensitive and must be built against the headers
for the Hyprland version that will load it. The daemon requires Python 3.12+.

Runtime integration also uses `jq`, `flock` (util-linux), and
`notify-send` (libnotify).

**uv (recommended):**

```bash
git clone https://github.com/shinishiz/hyprland-canvas.git
cd hyprland-canvas
uv tool install .
```

Install the versioned user integration wrappers and systemd unit:

```bash
./scripts/install-user
```

**pipx:**

```bash
git clone https://github.com/shinishiz/hyprland-canvas.git
cd hyprland-canvas
pipx install .
```

Then install the user integration files:

```bash
./scripts/install-user
```

**Run from source (no install):**

```bash
git clone https://github.com/shinishiz/hyprland-canvas.git
cd hyprland-canvas
uv run canvasd
```

The source-only form above is useful for development. The Gold systemd unit
expects the installed `canvasd` and `canvas-ctl` entry points under
`~/.local/bin`.

Merge the Canvas-specific parts from
[`examples/hyprland-canvas.lua`](examples/hyprland-canvas.lua) into your
Hyprland Lua configuration and keep `general.resize_on_border = false` as the
base value. The synchronizer enables it only while the active workspace is in
Canvas mode. The example also preserves the Gold startup order: export the
Hyprland session environment to systemd, load the companion plugin, then start
`hyprland-session.target`.

After updating the daemon package, reinstall it before restarting the service:

```bash
uv tool install . --force --reinstall   # or: pipx install . --force
./scripts/install-user
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

Then merge `examples/hyprland-canvas.lua` into your Hyprland Lua config and
drag with SUPER+SHIFT+LMB.

## Control commands

The full list lives in the CLI itself — `canvas-ctl --help` is canonical:

```bash
canvas-ctl --help  # all commands with one-line descriptions
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
- `examples/hyprland-canvas.lua` — distributable Gold Hyprland integration
- `examples/hypr-canvasd.service` — portable systemd user unit
- `scripts/` — versioned Gold wrappers/state-machine helpers plus user installer
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
| SUPER+ALT+0 / SUPER+SHIFT+0 relative workspace move + follow | ✅ Gold-validated |
| Hyprland 0.56.2 compatibility | ✅ Updated |

## systemd user service

`./scripts/install-user` copies the portable unit from
[`examples/hypr-canvasd.service`](examples/hypr-canvasd.service) to
`~/.config/systemd/user/hypr-canvasd.service`. It uses the systemd `%h`
specifier instead of a hard-coded username.

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hypr-canvasd.service
```

The installer puts these versioned files in `~/.local/bin/`:

- `hypr-canvasd` — daemon launcher
- `hypr-canvas-ctl` — control CLI
- `hypr-canvas-sync-resize` — synchronizes global border resize with active Canvas state
- `hypr-cycle-mode` — Dwindle/Canvas/Scrolling state machine
- `hypr-canvas-transition` — stateful transition wrapper

## Companion plugin and ABI

The camera/zoom integration also requires the separate `hypr-canvas` plugin.
The Gold plugin build was produced for Hyprland 0.56.2 and returns
`HYPRLAND_API_VERSION` from the headers used at compile time. Treat its
`.so` as ABI-coupled to that Hyprland build; rebuild the plugin against the
target machine's matching Hyprland development headers instead of reusing a
binary across incompatible Hyprland versions.

The distributable Lua example expects the ABI-matched plugin at:

```text
~/.local/lib/hypr-canvas/hypr-canvas.so
```

After building the companion plugin, install its artifact there:

```bash
install -Dm755 hypr-canvas.so "$HOME/.local/lib/hypr-canvas/hypr-canvas.so"
```

The current Gold plugin source is still maintained separately, so a future
consolidated release must decide how that source/build is shipped before a
clean install can be called fully self-contained.

## Known runtime limitation

The socket2 EventListener reconnects after transport failure. Events emitted
during the disconnected interval are not replayed, so lifecycle state can miss
an event until a later operation reconciles it. This is a known Gold limitation
and should remain documented unless a separate reconciler stage closes the gap.

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

321 tests passing, 82.43% coverage.

## Credits

- Original: [zyrophix/hyprland-canvas](https://github.com/zyrophix/hyprland-canvas)
- Fork maintained by: shinishiz
- Companion plugin: [Aaron Bockelie / aaronsb/hypr-canvas](https://github.com/aaronsb/hypr-canvas) — MIT, maintained separately

## License

MIT — see [LICENSE](LICENSE) for details.
