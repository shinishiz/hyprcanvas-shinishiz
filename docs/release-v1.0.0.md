# v1.0.0 — First public release of the Canvas fork

> Historical document: this release note describes the legacy
> `shinishiz/hyprland-canvas` fork and its historical publication URLs. It is
> retained for provenance and does not identify the current
> `hyprcanvas-shinishiz` publication target.

## Summary

First public release of the `shinishiz/hyprland-canvas` fork.

Based on [zyrophix/hyprland-canvas](https://github.com/zyrophix/hyprland-canvas) at commit `0b81a9a`.

Tested with:
- Hyprland 0.56.2
- Fedora Linux 44 (Workstation Edition)
- Python 3.12 / uv 0.12.9

## New features (vs upstream)

| Feature | Description |
|---------|-------------|
| Auto-float on openwindow | New tiled windows opened while Canvas is active automatically become floating and join the Canvas |
| Socket2 event listener | Listens to Hyprland's `.socket2.sock` for `openwindow`/`closewindow` events |
| Sensible spawn geometry | New windows use median geometry from original tiled snapshot |
| Canvas state persistence | State persisted in `toggle-state.json` + local cache |
| Spawned window tracking | Windows spawned during Canvas ON are tracked and restored on OFF |
| Hyprland 0.56.2 compatibility | API updates for 0.56.2 |

## Workspace workflow

```
Dwindle → Canvas ON → Scrolling → Dwindle
```

Triggered by `Super+Space`.

## Keybinds

| Bind | Action |
|------|---------|
| Super+Space | Cycle: Dwindle → Canvas → Scrolling → Dwindle |
| Super+Shift+LMB | Pan canvas |
| Super+LMB | Edge-scroll |
| Super+MMB | Center on cursor |
| Super+Shift+Arrows | Conditional nav (Canvas: nav-*, OFF: layout action) |
| Super+Shift+V | Toggle single window |
| Super+Shift+G | Invert pan direction |

## Installation

```bash
git clone https://github.com/shinishiz/hyprland-canvas.git
cd hyprland-canvas
uv tool install .
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

- Original: zyrophix/hyprland-canvas
- Fork maintained by: shinishiz

## License

MIT
