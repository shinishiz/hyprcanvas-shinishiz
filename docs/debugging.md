# Debugging

Run the daemon with structured tracing to diagnose input/camera issues:

```bash
CANVAS_DEBUG=1 canvasd 2>&1 | tee /tmp/canvas-debug.log   # summary
CANVAS_DEBUG=2 canvasd 2>&1 | tee /tmp/canvas-debug.log   # per-window details (class/title/at/size)
```

Trace lines are `<seconds> EVENT key=value …`. Useful events (level 1):

- `CMD` — every IPC command with `cmd` + `result`
- `STATE_LOAD / STATE_SAVE` — toggle snapshot counts per workspace
- `SNAPSHOT_CREATE` — `ws, count, addrs, preserve_geometry`
- `TOGGLE_ON / TOGGLE_OFF` — `ws, count, addrs` on canvas-toggle
- `TILE_START / FLOAT_START` — `ws, targets` before Lua dispatch
- `TILE_DONE / FLOAT_DONE` — after dispatch
- `EDGE_START_DECISION`, `EDGE_SESSION_TICK` (10Hz), `EDGE_CONFIRMED`, `EDGE_DISARM`

Level 2 adds per-window details: `SNAPSHOT_CREATE_DETAIL`, `TOGGLE_ON_DETAIL`, `STATE_LOAD_DETAIL`, `TILE_START_LIVE`, `TILE_WINDOW`-style live vs saved geometry with `class/title` (truncated to 30-40 chars).
