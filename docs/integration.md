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

Check status:

```bash
systemctl --user status hypr-canvasd.service
journalctl --user -u hypr-canvasd -f
```

## Wrappers

Three wrappers are provided in `~/.local/bin/`:

| Script | Purpose |
|--------|---------|
| `hypr-canvasd` | Launch the daemon |
| `hypr-canvas-ctl` | Control CLI (ping, status, toggle, nav, etc.) |
| `hypr-canvas-transition` | Internal wrapper for stateful transitions |

All use `uv run --directory /path/to/project python -m canvas ...` for isolation.

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
4. Resized/positioned to median geometry from original tiled snapshot
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

```lua
-- Check if Canvas is active on current workspace
local function is_canvas_active_now()
    local ws = hl.get_active_workspace()
    if not ws or ws.special then return false end
    return is_canvas_confirmed_active(ws.id)
end

-- Toggle Canvas for current workspace
local function toggle_canvas_for_current_workspace()
    local ws = hl.get_active_workspace()
    if not ws or ws.special then return end
    local ws_id = ws.id
    local currently_active = canvas_active_by_workspace[ws_id] or false
    canvas_active_by_workspace[ws_id] = not currently_active
    hl.dsp.exec_cmd("/home/youruser/.local/bin/hypr-canvas-ctl canvas-toggle")
end
```

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
