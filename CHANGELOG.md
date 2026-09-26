# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.1] — 2026-09-26

### Fixed

- README keybind examples now use Hyprland's `hl.exec_cmd()` API instead of `os.execute()`.

## [1.4.0] — 2026-09-25

### Added

- `canvas-ctl center-cursor` centers the canvas on the topmost floating window under the cursor without changing focus.

## [1.3.1] — 2026-09-24

### Fixed

- Hyprland Lua keybind examples now use the supported `hl.bind` API.
- Floating geometry restore uses Hyprland 0.55/0.56 resize arguments (`x`, `y`).
- Hyprland textual IPC errors now prevent false-success canvas/navigation results.
- Canvas toggle persists an explicit active marker and commits state around compositor actions.
- Navigation and main-loop canvas moves are serialized to avoid competing pan/edge writes.
- Edge-scroll no longer retains a stale movement direction across a fast reversal.
- Invalid non-finite config values and malformed YAML roots fail validation cleanly.

## [1.3.0] — 2026-09-18

### Added

- `canvas-ctl --help` (all 14 commands) and `--version`; `canvasd --help`.
- README T1 structure (badges, Quickstart, Repo overview, Contributing),
  video demo, `docs/` notes, `CHANGELOG.md`, governance files.

### Changed

- CLI misuse exits 2 (argparse standard); error paths unchanged.

## [1.2.0] — 2026-09-04

### Added

- Spatial 4-dir navigation with geometry-preserving toggle.
- Two-level `CANVAS_DEBUG` tracing (summary + per-window details).
- Canvas toggle preserves floating geometry; single-window toggle.

## [1.1.1] — 2026-08-24

### Fixed

- Edge-scroll: camera assist only while dragging toward the edge.

## [1.1.0] — 2026-08-18

### Added

- Structured `CANVAS_DEBUG` tracing for edge-scroll and IPC.
- Ground-truth window geometry with confirmed-drag gating.

### Fixed

- Edge-scroll disarms when the cursor leaves the dragged window; pan/edge exclusivity.
- Pan and navigation scoped to the active workspace.
- Edge-scroll fails safe without monitor geometry.

## [1.0.1] — 2026-05-20

### Fixed

- Handler map, `EdgeScrollParams` dataclass, silent recovery fix.

## [1.0.0] — 2026-05-16

### Added

- Initial release: pan, navigate, toggle, edge-scroll, IPC CLI.
