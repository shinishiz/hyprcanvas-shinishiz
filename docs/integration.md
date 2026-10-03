# Hyprland Canvas — Integration Guide

This guide covers detailed integration steps for Hyprland Canvas.

## systemd service

### Unit file

```ini
# ~/.config/systemd/user/hypr-canvasd.service
[Unit]
Description=Hyprland Canvas daemon
PartOf=hyprland-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/hypr-canvasd
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

The repository ships this unit as `examples/hypr-canvasd.service`.
`./scripts/install-user` installs it and the Gold helper scripts into the
current user's home without starting or reloading anything by itself.
By default it does not build the companion plugin. Use
`./scripts/install-user --with-plugin` only when an explicit ABI-sensitive
plugin build is desired; that option still does not start or reload runtime
services.

System packages use the separate user unit
`packaging/systemd/hypr-canvasd.service`, installed under
`/usr/lib/systemd/user/`. Its `ExecStart=/usr/bin/hypr-canvasd`; package
installation must not write into `~/.config/systemd/user/`.

Check status:

```bash
systemctl --user status hypr-canvasd.service
journalctl --user -u hypr-canvasd -f
```

## Wrappers

Five integration executables are versioned in `scripts/` and installed into
`~/.local/bin/`:

| Script | Purpose |
|--------|---------|
| `hypr-canvasd` | Launch the daemon |
| `hypr-canvas-ctl` | Control CLI (ping, status, toggle, nav, etc.) |
| `hypr-canvas-sync-resize` | Keep `general:resize_on_border` aligned with active Canvas state |
| `hypr-cycle-mode` | Dwindle → Canvas → Scrolling state machine |
| `hypr-canvas-transition` | Internal wrapper for stateful transitions |

`hypr-canvasd` and `hypr-canvas-ctl` resolve the corresponding `canvasd` and
`canvas-ctl` Python entry points from `PATH`, then fall back to
`~/.local/bin/` for compatibility with the user installer. They never search
for their own wrapper names, so this resolution cannot recurse. The
transition/cycle helpers resolve their sibling scripts from the same directory,
so no username or checkout path is embedded.

## Super+Space Cycle

The `SUPER+SPACE` binding implements a 3-state cycle per workspace:

```
Dwindle (Canvas OFF)
    ↓
Canvas ON (floating, pan/edge-scroll/nav enabled)
    ↓
Scrolling (Canvas OFF, layout preserved)
    ↓
Dwindle (back to start)
```

### State machine

| Current layout | Canvas state | Next state |
|----------------|--------------|------------|
| Dwindle | OFF | Canvas ON (floating) |
| Dwindle | ON | Scrolling + Canvas OFF |
| Scrolling | OFF | Dwindle |
| Scrolling | ON | Scrolling (Canvas OFF) |

State is persisted per-workspace in `$XDG_RUNTIME_DIR/canvas/toggle-state.json`.

## Canvas pan binds

| Bind | Action |
|------|--------|
| `SUPER+SHIFT+LMB` (press) | Start panning |
| `SUPER+SHIFT+LMB` (release) | Stop panning |
| `SUPER+LMB` (press) | Edge-scroll start |
| `SUPER+LMB` (release) | Edge-scroll stop |
| `SUPER+MMB` | Center canvas on window under cursor |

## SUPER+SHIFT+Arrows navigation

| Key | Canvas ON | Canvas OFF (Dwindle) | Canvas OFF (Scrolling) |
|-----|-----------|----------------------|------------------------|
| SUPER+SHIFT+LEFT | `nav-left` | `window.move left` | `consume_or_expel prev` |
| SUPER+SHIFT+RIGHT | `nav-right` | `window.move right` | `consume_or_expel next` |
| SUPER+SHIFT+UP | `nav-up` | `window.move up` | (none) |
| SUPER+SHIFT+DOWN | `nav-down` | `window.move down` | (none) |

## Relative workspace move + follow

The Gold Lua integration also includes the manually validated relative move
helper:

```lua
local function move_focused_window_relative(delta)
    local ws = hl.get_active_workspace()
    if not ws or ws.special then return end

    local target = ws.id + delta
    if target < 1 then return end

    hl.dispatch(hl.dsp.window.move({ workspace = tostring(target) }))
end

hl.bind("SUPER + ALT + 0", function() move_focused_window_relative(1) end)
hl.bind("SUPER + SHIFT + 0", function() move_focused_window_relative(-1) end)
```

There is no upper workspace limit: workspace 9 can move to 10, 10 to 11, and
so on. Moving backward from workspace 1 is a no-op.

## Canvas toggle & single window

| Bind | Action |
|------|--------|
| `SUPER+SHIFT+V` | Toggle focused window floating/tiled |
| `SUPER+SHIFT+G` | Invert pan direction |

## Notifications

Notifications use `notify-send` via `hl.exec_cmd()`. Tokens:

| Token | Meaning |
|-------|---------|
| `Canvas` | Canvas ON (Dwindle → Canvas) |
| `Scrolling` | Scrolling mode entered |
| `Dwindle` | Dwindle layout active |
| `CanvasON` | Canvas turned ON via toggle |
| `Dwindle` / `Scrolling` | Canvas OFF, returns to layout |
| `CanvasOFF` | Canvas OFF, layout unknown |
| `Error` | Fullscreen block / failure |

## New window auto-float

When Canvas is active on a workspace, newly opened tiled windows are automatically:

1. Detected via socket2 `openwindow` event
2. Queried for geometry via `j/clients`
3. Converted to floating via `window.float toggle`
4. Sized from the original tiled snapshot's median geometry and positioned at the visual Canvas viewport center
5. Registered in `_spawned_during_canvas` for proper cleanup on Canvas OFF

## State persistence

State is stored in `$XDG_RUNTIME_DIR/canvas/toggle-state.json` (daemon) and `$XDG_RUNTIME_DIR/canvas/super-space-state-<ws_id>` (wrapper cache). Format v3:

```json
{
  "_v": 3,
  "9": {
    "active": true,
    "tiled": { "0x...": {"at": [x,y], "size": [w,h]} },
    "floating": { "0x...": {"at": [x,y], "size": [w,h]} }
  }
}
```

## Hyprland Lua helpers

Use `examples/hyprland-canvas.lua` as the canonical distributable extraction
of the Gold bindings. It reads the persisted `toggle-state.json`, installs the
workspace/config resize synchronization callbacks, keeps the validated
`move_focused_window_relative(delta)` implementation, and contains the
`SUPER+SPACE`, mouse, navigation, toggle, invert, and zoom-reset binds.

Keep `general.resize_on_border = false` in the base Hyprland configuration.
The synchronizer is responsible for temporarily enabling it while the active
workspace is in Canvas mode.

The same example preserves the Gold startup ordering. On
`hyprland.start` it publishes `WAYLAND_DISPLAY`, desktop/session variables,
and `HYPRLAND_INSTANCE_SIGNATURE` to the user systemd manager. It prefers the
user plugin at
`${XDG_DATA_HOME:-$HOME/.local/share}/hyprcanvas-shinishiz/plugins/hypr-canvas.so`,
falls back to `/usr/lib/hyprcanvas-shinishiz/plugins/hypr-canvas.so` when the
user artifact is absent, and then starts
`hyprland-session.target`. This is what makes the enabled
`hypr-canvasd.service` start in the correct Hyprland session.

## Companion plugin ABI

The Canvas camera/zoom bridge depends on the `hypr-canvas` companion plugin,
whose source is integrated under `plugin/`. That source is derived from the
historical `aaronsb/hypr-canvas` codebase and has additional compatibility and
integration work for the Gold setup. The original plugin base was not
compatible out of the box with the current Gold environment.

The Gold plugin was validated against Hyprland 0.56.2 commit
`efb50993780079460b0cbed1363e2166a2de1d9f`. Because the plugin exports the
`HYPRLAND_API_VERSION` from its build headers and hooks Hyprland internals,
rebuild it against matching development headers on the target machine. Do not
assume a binary built for another Hyprland ABI is reusable.

The canonical source is the monorepo's `plugin/` directory. Install the user
integration and explicitly build/install the companion plugin with:

```bash
./scripts/install-user --with-plugin
```

The installed artifact lives at
`$XDG_DATA_HOME/hyprcanvas-shinishiz/plugins/hypr-canvas.so`, or
`~/.local/share/hyprcanvas-shinishiz/plugins/hypr-canvas.so` when
`XDG_DATA_HOME` is unset. A system package instead installs the plugin at
`/usr/lib/hyprcanvas-shinishiz/plugins/hypr-canvas.so`. The Lua example checks
the user path first and then the system path. The installer does not load the
plugin. If neither artifact exists, the Lua startup keeps going because plugin
load failure is intentionally tolerated; the Canvas camera/zoom plugin simply
remains unavailable.

## EventListener reconnect limitation

Transport recovery reconnects the socket2 EventListener after a disconnect.
Events emitted while the listener is disconnected are not replayed. This is a
known limitation of the current Gold base; a separate reconciler stage would be
needed to guarantee recovery of those missed lifecycle events.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Canvas doesn't start | Check `systemctl --user status hypr-canvasd` |
| Notifications not showing | Ensure `notify-send` is installed (`libnotify`) |
| Canvas toggle not working | Check `canvas-ctl ping` → should return `PONG` |
| Pan not working | Verify `SUPER+SHIFT+LMB` binds, check `canvas-ctl status` |
| New windows not floating | Check `canvas-ctl status`, verify daemon running |

## Hyprland 0.56.2 notes

- `hl.exec_cmd()` preferred over `os.execute()` in Lua callbacks
- `hl.dsp.window.move()` returns dispatcher, use `hl.dispatch()` to execute
- `hl.get_active_workspace()` returns workspace object with `.id`, `.name`, `.tiled_layout`
- `hl.get_workspace_windows(ws.id)` returns windows on workspace
- `hl.get_active_window()` returns focused window
