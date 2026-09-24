# Architecture

```
canvasd (daemon)
├── hypr.py        Direct Unix socket IPC to Hyprland
├── panning.py     Cursor polling, pan state, edge-scroll state
├── navigation.py  Window navigation, canvas toggle
├── ipc.py         Unix socket server for canvas-ctl
├── config.py      YAML config with deep merge
└── daemon.py      Main loop, wires modules together
```

Key design decisions:

- **Cursor polling** — reads cursor position from Hyprland IPC, works on any Wayland setup
- **`hl.dsp.window.move({window=w})` without focus** — passing a window object bypasses auto-focus, so no cursor warp or feedback loop
- **Direct socket IPC** — one short-lived Unix-socket request per Hyprland command, avoiding subprocess startup on every frame
- **Workspace-scoped** — pan, edge-scroll and navigation only move floating windows on the current workspace; other workspaces are never touched
- **Ground-truth, direction-aware edge pan** — modeled after compositor-level implementations (driftwm, hevel): the camera assists only while a *confirmed* drag (window under cursor + focus match + moved past `grab_dead_zone`) pushes the window *toward* an edge or holds it there; pulling the window away from a boundary stops that side's assist immediately. The dragged window's real geometry is polled from Hyprland every frame — no cursor-derived guessing, so clicks on borders/gaps or holds without movement never move the camera on their own
- **Idle timeout** (500ms) — auto-stops panning if Hyprland drops a mouse release event during active drag
