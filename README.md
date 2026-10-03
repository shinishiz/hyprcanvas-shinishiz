# hyprcanvas-shinishiz

An independent Hyprland Canvas suite maintained by **shinishiz**, combining
and extending work derived from the `zyrophix/hyprland-canvas` daemon and the
`aaronsb/hypr-canvas` companion plugin codebase.

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

This is an independent project. It is not the official upstream for either
`zyrophix/hyprland-canvas` or Aaron Bockelie's `aaronsb/hypr-canvas`. The
daemon, Gold integration, packaging, and adapted companion plugin now live in
one source tree. See [CREDITS.md](CREDITS.md) and
[THIRD_PARTY.md](THIRD_PARTY.md) for provenance details.

**Current status:** Gold consolidation / release preparation

**Planned initial Gold suite tag:** `gold-v0.1.0` (not released)

**Integrated component versions:** Python daemon `1.5.0`; companion plugin
`0.1`

Drag the canvas with **SUPER+SHIFT+LMB**, navigate between windows, toggle canvas mode per workspace. Runs as an unprivileged user daemon — communicates directly with Hyprland via its IPC socket and Lua API.

<video src="https://github.com/user-attachments/assets/6bb06c3e-c553-481d-b726-15033ed8ac37" autoplay loop muted playsinline width="900">Demo: panning floating windows as an infinite desktop</video>

## Gold integration

The integrated Gold tree contains the following improvements over its
historical daemon base:

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

The Gold integration is currently validated against Hyprland **0.56.2**, commit
`efb50993780079460b0cbed1363e2166a2de1d9f`. The companion `hypr-canvas`
plugin uses Hyprland headers and internals and is ABI-sensitive. Build it from
the source in `plugin/` against the matching target Hyprland development
headers. A prebuilt `.so` must not be assumed to work across Hyprland versions.
The daemon requires Python 3.12+.

Runtime integration also uses `jq`, `flock` (util-linux), and
`notify-send` (libnotify).

The public repository URL is pending publication. From a local checkout of
this tree, install the Python component with **uv** (recommended):

```bash
uv tool install .
```

Install the versioned user integration wrappers and systemd unit:

```bash
./scripts/install-user
```

This default installation intentionally does **not** build or install the
ABI-sensitive companion plugin. For a full user installation using the
integrated `plugin/` source, request that build explicitly:

```bash
./scripts/install-user --with-plugin
```

The explicit plugin build validates `g++`, `make`, `pkg-config`, and the
`hyprland`, `pixman-1`, and `libdrm` pkg-config modules. It never installs
packages with sudo. The resulting plugin is installed at:

```text
$XDG_DATA_HOME/hyprcanvas-shinishiz/plugins/hypr-canvas.so
```

or, when `XDG_DATA_HOME` is unset:

```text
~/.local/share/hyprcanvas-shinishiz/plugins/hypr-canvas.so
```

`--with-plugin` only builds and installs the file. It does not load the plugin,
restart the daemon, or reload Hyprland. The Lua integration example performs
the plugin load during Hyprland startup and tolerates a missing plugin file.

**pipx:**

```bash
pipx install .
```

Then install the user integration files:

```bash
./scripts/install-user
```

**Run from source (no install):**

```bash
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
- `plugin/` — adapted companion plugin source, with its original MIT license
- `scripts/` — versioned Gold wrappers/state-machine helpers plus user installer
- `config.yml` — ready-to-copy config template
- `pyproject.toml` — package metadata, pytest/ruff/mypy config

## Gold additions relative to the historical daemon base

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

The camera/zoom integration uses the companion `hypr-canvas` plugin whose
source is now integrated under `plugin/`. That source is derived from Aaron
Bockelie's `aaronsb/hypr-canvas` codebase. The original upstream plugin was a
historical foundation; it was not compatible out of the box with the current
Gold setup. The integrated companion plugin includes later compatibility and
integration work for this suite.

The Gold plugin build was validated against Hyprland 0.56.2 commit
`efb50993780079460b0cbed1363e2166a2de1d9f` and returns
`HYPRLAND_API_VERSION` from the headers used at compile time. Releases are
source-first: rebuild the plugin against the matching development headers for
the Hyprland build that will load it. Any prebuilt `.so` is version-specific,
not universal.

The distributable Lua example expects the ABI-matched plugin installed by the
suite at:

```text
$XDG_DATA_HOME/hyprcanvas-shinishiz/plugins/hypr-canvas.so
```

with fallback to:

```text
~/.local/share/hyprcanvas-shinishiz/plugins/hypr-canvas.so
```

Use `./scripts/install-user --with-plugin` to build from `plugin/` and install
that artifact without loading it automatically.

## Known runtime limitation

The socket2 EventListener reconnects after transport failure. Events emitted
during the disconnected interval are not replayed, so lifecycle state can miss
an event until a later operation reconciles it. This is a known Gold limitation
and should remain documented unless a separate reconciler stage closes the gap.

## Maintainer / Gold integration

**shinishiz** maintains `hyprcanvas-shinishiz`.

Contact:

- GitHub: `shinishiz`
- Email: `shinishiz@outlook.com`
- Discord: `shinishi`

Responsibilities:

- Gold integration and ongoing project maintenance;
- Hyprland compatibility work for the Gold setup;
- daemon/plugin/Hyprland integration;
- packaging and integration work;
- testing and validation;
- release engineering.

These responsibilities describe the work on this independent suite; they do
not replace or reassign the original authorship and copyrights of its
historical daemon and plugin bases.

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

- **shinishiz** — project maintainer; Gold integration, compatibility and
  daemon/plugin integration work, packaging, testing/validation, and release
  engineering.
- **zyrophix** — author of the original
  [hyprland-canvas](https://github.com/zyrophix/hyprland-canvas) daemon and
  foundational Canvas implementation used as the daemon history/base.
- **Aaron Bockelie** — author of the original
  [aaronsb/hypr-canvas](https://github.com/aaronsb/hypr-canvas) companion
  plugin codebase used as the historical foundation for `plugin/`. The
  integrated Gold plugin is an adapted version with additional compatibility
  and integration work.

See [CREDITS.md](CREDITS.md) and [THIRD_PARTY.md](THIRD_PARTY.md) for the full
provenance record.

## License

MIT — see [LICENSE](LICENSE) for details.
